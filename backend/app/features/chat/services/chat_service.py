"""Chat-only orchestration: history + (optional) RAG context → vLLM streaming.

RAG retrieval lives in `app.services.rag` and is shared with the slide
maker. This module contains:
  - the chat SYSTEM_PROMPT
  - `rewrite_for_retrieval` — chat-specific follow-up rewriter, used so
    multi-turn pronouns ("and Python?", "what about that one?") embed
    against a self-contained query rather than the literal user message
  - `detect_code_assist_intent` / `rewrite_for_code_retrieval` — deterministic
    code-aware retrieval query helpers that preserve identifiers and errors
  - `stream_answer` — token-streaming reply assembly
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.db.models import ChatMessage, ChatRole
from app.features.rag.services import tagger

logger = logging.getLogger(__name__)

_IDENTIFIER_RE = r"[A-Za-z_][A-Za-z0-9_]*"
_SYMBOL_RE = re.compile(rf"^{_IDENTIFIER_RE}(?:\.{_IDENTIFIER_RE})*$")
_SYMBOL_TOKEN_RE = re.compile(
    rf"(?<![A-Za-z0-9_.]){_IDENTIFIER_RE}(?:\.{_IDENTIFIER_RE})*(?![A-Za-z0-9_.])"
)
_CODE_SPAN_RE = re.compile(r"`+([^`]+?)`+")
_SYMBOL_QUERY_TEMPLATE = (
    "Find the definition, signature, implementation, usages, call sites, "
    "and related function for symbol: {symbol}"
)
_SYMBOL_LOOKUP_STOPWORDS = {
    "a",
    "an",
    "and",
    "call",
    "calls",
    "callsite",
    "callsites",
    "class",
    "define",
    "definition",
    "find",
    "function",
    "implementation",
    "in",
    "is",
    "method",
    "of",
    "reference",
    "references",
    "related",
    "signature",
    "symbol",
    "the",
    "to",
    "usage",
    "usages",
    "used",
    "variable",
    "where",
}
_SYMBOL_LOOKUP_HINT_RE = re.compile(
    r"("
    r"\b(find|where|used|usage|usages|definition|define|signature|"
    r"implementation|call\s+sites?|calls?|references?|related|function|"
    r"method|class|variable|symbol)\b"
    r"|相關|函式|函數|方法|類別|變數|定義|簽名|實作|實現|使用|用到|在哪|找到|呼叫|引用"
    r")",
    re.IGNORECASE,
)


SYSTEM_PROMPT = """
You are KnowledgeDeck, an internal engineering knowledge assistant for
semiconductor test knowledge, company BKM, vendor documents, and source code.

Primary goal:
Help users understand and apply internal knowledge clearly, accurately, and
practically. The user may ask about Teradyne, Advantest, specific tester
platforms, internal BKM, troubleshooting procedures, or project code.

Conversation:
Focus on the user's latest message. Use prior turns only to resolve explicit
follow-up references, pronouns, or user preferences. Do not copy, summarize, or
continue the previous assistant answer unless the latest user message clearly
asks you to do so.

Grounding policy:
When a `Context:` section is provided, treat it as the primary evidence for
questions about the user's documents, company BKM, vendor platforms, or
codebase. Do not invent internal facts, procedures, APIs, platform behavior,
limits, or BKM that are not supported by the Context. If Context is absent or
irrelevant, answer from general engineering knowledge without adding a separate
boilerplate disclaimer. If Context is partial, answer the supported parts
directly and avoid a standalone "missing information" section unless the user
explicitly asks for gaps.

Vendor/platform discipline:
Pay close attention to source metadata such as vendor, platform,
knowledge_type, doc_type, filename, page, and topic. Do not mix Teradyne and
Advantest guidance unless the user asks for comparison or the Context
explicitly supports a shared conclusion. Do not treat UltraFLEX, J750, V93000,
and T2000 as interchangeable. If retrieved sources are from a different vendor
or platform than the user's question, warn the user before applying them.

Evidence priority:
Prefer sources in this order:
1. Same vendor and same platform internal BKM.
2. Same vendor and same platform vendor documentation.
3. Same vendor but generic platform documentation.
4. Internal code or implementation details when the question is about code
   behavior.
5. Other vendor/platform material only for comparison or clearly labeled
   reference.

Answer style:
Answer in Traditional Chinese by default unless the user asks for another
language. Provide detailed, practical engineering explanations with enough
context, reasoning, examples, and next actions for the user to apply the answer.
Do not be overly terse. Make the answer easy to understand for an engineer who
may not know the document set.

For document/BKM questions, use this structure when useful:
- 結論
- 適用範圍：vendor / platform / knowledge type
- 依據：briefly mention the relevant source files or source numbers
- 詳細說明：explain the mechanism, rule, or procedure
- 操作步驟：if the question asks how to do something
- 注意事項 / 風險
- 建議下一步

For code questions:
Inspect retrieved code context first. Keep the original programming language
used by the retrieved code. Do not translate, rewrite, or convert code into
another programming language unless the user explicitly asks for that
conversion. When relevant functions, classes, or modules are found in Context,
identify them first by name, file/module path if available, signatures if
available, and explain their existing behavior or usage. Do not generate new code,
replacement implementations, pseudocode, or invented APIs unless the user
explicitly asks to create, implement, rewrite, refactor, or provide an example.
This restriction does not prevent quoting or explaining code that is present in
Context. If retrieved procedures, steps, or methods include code blocks and the
user asks how to use or perform them, present the relevant Context code in its
original language, either step-by-step with explanation or as the complete
referenced code block when needed. If the source is a plot image, screenshot,
scan, OCR text, or other image-derived document that contains code (for example
VBA), and the user asks to print, extract, or show that code, transcribe the
retrieved code exactly as Context provides it. Preserve the source language and
formatting as much as possible, cite the source, and explicitly mark any
uncertain OCR/image characters instead of guessing. Clearly distinguish Context
code from any optional new example, and do not fabricate missing steps, code, or
APIs. If the user asks where a behavior is implemented, answer by pointing to
the existing function, class, or call site rather than inventing a fresh
implementation. Prefer existing functions, classes, modules, signatures, call
sites, and tests from the Context. Do not invent project APIs. If no relevant
function is found, clearly state that the retrieved Context does not contain the
needed function. If code context is insufficient, say what code artifact is
missing and provide best-effort general guidance separately from
project-specific facts.

Conflict handling:
If sources disagree, do not hide the conflict. State the conflicting sources,
explain the difference, and say which one appears more applicable based on
vendor/platform/knowledge_type. If applicability cannot be determined, ask one
clarifying question.

Citation behavior:
When using Context, cite source numbers or filenames naturally in the answer.
Do not cite sources that were not used. When making an inference, label it as
an inference.

Evidence boundaries:
Do not overstate uncertain conclusions or fabricate details. When evidence is
limited, keep the answer scoped to what can be supported, phrase inferences as
engineering judgment, and continue with practical guidance. Avoid adding a
repetitive standalone section named "文件不足", "不確定處", or similar unless the
user explicitly asks you to list gaps.

Do not:
- Pretend unsupported information came from the documents.
- Merge different vendors/platforms without warning.
- Give a single definitive procedure when the evidence only supports a partial
  answer.
- Over-focus on citations at the expense of a clear explanation.
""".strip()
CODE_INTENT_UNIT_TEST = "unit_test"
CODE_INTENT_DEBUG = "debug"
CODE_INTENT_IMPLEMENTATION = "implementation"
CODE_INTENT_SNIPPET = "code_snippet"

_CODE_INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        CODE_INTENT_UNIT_TEST,
        ("unit test", "pytest", "unittest", "test case", "測試", "單元測試"),
    ),
    (
        CODE_INTENT_DEBUG,
        (
            "debug",
            "bug",
            "error",
            "exception",
            "traceback",
            "stack trace",
            "除錯",
            "錯誤",
        ),
    ),
    (
        CODE_INTENT_IMPLEMENTATION,
        ("write function", "implement", "refactor", "寫函式", "實作"),
    ),
)

_CODE_SNIPPET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"```"),
    re.compile(r"\bdef\s+"),
    re.compile(r"\bclass\s+"),
    re.compile(r"\bfunction\s+"),
    re.compile(r"^\s*import\s+[A-Za-z_][\w.]*", re.MULTILINE),
    re.compile(r"^\s*from\s+[A-Za-z_][\w.]*\s+import\s+", re.MULTILINE),
    re.compile(r"\b(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=?"),
)

_CODE_RETRIEVAL_TARGETS = {
    CODE_INTENT_UNIT_TEST: (
        "Find related function definitions, signatures, usages, expected behavior, "
        "and existing tests for writing unit tests."
    ),
    CODE_INTENT_DEBUG: (
        "Find related implementation, call sites, error handling, and variables "
        "connected to this error."
    ),
    CODE_INTENT_IMPLEMENTATION: (
        "Find existing reusable library functions, classes, APIs, signatures, "
        "examples, and patterns."
    ),
    CODE_INTENT_SNIPPET: (
        "Find related implementation, function definitions, class definitions, "
        "signatures, usages, imports, examples, and patterns."
    ),
}


@dataclass(frozen=True)
class QueryTags:
    vendor: str = "unknown"
    platform: str = "unknown"
    knowledge_type: str = "unknown"

    def has_signal(self) -> bool:
        return any(
            value != "unknown"
            for value in (self.vendor, self.platform, self.knowledge_type)
        )

    def as_prompt_text(self) -> str:
        return (
            "Query intent tags detected from the user request and retrieval "
            f"query: vendor={self.vendor}, platform={self.platform}, "
            f"knowledge_type={self.knowledge_type}. These tags are soft "
            "guidance only; do not hard-filter evidence, but prefer matching "
            "source metadata and warn about mismatches."
        )


def detect_query_tags(*texts: str | None) -> QueryTags:
    """Detect soft metadata hints from user and rewritten retrieval queries."""
    haystack = " ".join(t for t in texts if t).casefold()

    vendor = "unknown"
    for canonical, aliases in (
        ("teradyne", ("teradyne", "泰瑞達", "泰瑞达")),
        ("advantest", ("advantest", "艾德萬", "爱德万")),
        ("3gpp", ("3gpp", "third generation partnership project")),
        ("ieee", ("ieee", "institute of electrical and electronics engineers")),
        ("pcisig", ("pci-sig", "pci sig", "pcisig")),
    ):
        if any(alias in haystack for alias in aliases):
            vendor = canonical
            break

    platform = "unknown"
    for canonical, aliases in (
        ("ultraflex", ("ultraflex", "ultra flex")),
        ("j750", ("j750", "j 750")),
        ("v93000", ("v93000", "v93k", "sm93000", "sm 93000")),
        ("t2000", ("t2000", "t 2000")),
        ("5g_nr", ("5g nr", "5gnr", "new radio")),
        ("5g", ("5g",)),
        ("802.11", ("802.11", "wi-fi", "wifi")),
        ("pcie", ("pcie", "pci express")),
    ):
        if any(alias in haystack for alias in aliases):
            platform = canonical
            break

    knowledge_type = "unknown"
    if any(term in haystack for term in ("bkm", "best known method")):
        knowledge_type = "internal_bkm"
    elif any(
        term in haystack
        for term in ("code", "source code", "function", "class", "api", "程式", "代碼")
    ):
        knowledge_type = "code"
    elif any(term in haystack for term in ("standard", "specification", "spec", "rfc")):
        knowledge_type = "standard"
    elif any(
        term in haystack
        for term in ("vendor doc", "vendor document", "manual", "datasheet")
    ):
        knowledge_type = "vendor_doc"

    return QueryTags(
        vendor=tagger.normalize_vendor(vendor),
        platform=tagger.normalize_platform(platform),
        knowledge_type=tagger.normalize_knowledge_type(knowledge_type),
    )


def detect_code_assist_intent(user_message: str) -> str | None:
    """Return the code-assistance intent detected in a user message, if any."""
    normalized = user_message.casefold()
    for intent, keywords in _CODE_INTENT_KEYWORDS:
        if any(keyword.casefold() in normalized for keyword in keywords):
            return intent

    if any(pattern.search(user_message) for pattern in _CODE_SNIPPET_PATTERNS):
        return CODE_INTENT_SNIPPET

    return None


def rewrite_for_code_retrieval(
    history: list[ChatMessage], user_message: str, intent: str
) -> str:
    """Build a code-aware retrieval query while preserving exact identifiers.

    This rewrite is deterministic on purpose: code retrieval quality depends on
    exact function names, class names, variable names, error text, and import
    paths surviving unchanged. The raw user message is therefore embedded
    verbatim and augmented only with code-search target terms.
    """
    target = _CODE_RETRIEVAL_TARGETS.get(
        intent, _CODE_RETRIEVAL_TARGETS[CODE_INTENT_SNIPPET]
    )
    parts = [
        target,
        "Preserve exact function names, class names, variable names, error "
        "messages, and import paths from the request.",
    ]

    if history:
        recent_user_turns = [
            m.content.strip()
            for m in history[-6:]
            if m.role is ChatRole.USER and m.content.strip()
        ]
        if recent_user_turns:
            recent_context = " | ".join(
                turn if len(turn) <= 240 else turn[:240] + "..."
                for turn in recent_user_turns[-2:]
            )
            parts.append(f"Recent user context: {recent_context}")

    parts.append(f"User request: {user_message}")
    return "\n".join(parts)


_REWRITE_SYSTEM = (
    "You rewrite user questions into standalone search queries optimized "
    "for retrieval against a knowledge base, where a cross-encoder "
    "reranker scores (query, passage) pairs. Cross-encoders work best on "
    "natural-language queries with full canonical terms, not bare tokens "
    "or abbreviations, except when the user is looking up a code symbol.\n\n"
    "Identifier preservation rules:\n"
    "- Never paraphrase code identifiers.\n"
    "- Preserve exact function names, class names, variable names, method "
    "names, module paths, and error strings.\n"
    "- For symbol-only queries, search for definition, signature, usage, "
    "and call sites.\n\n"
    "You may receive:\n"
    "- A first-turn question (no conversation history above).\n"
    "- A follow-up question that uses pronouns ('that', 'it', 'this "
    "one') or elliptical references ('and Python?') that only make sense "
    "relative to recent user turns.\n\n"
    "Apply these rules in order:\n"
    "1. Use history only when the latest question explicitly depends on it; "
    "otherwise ignore history and keep the query focused on the latest question.\n"
    "2. Resolve pronouns / references / ellipsis against recent history only "
    "when needed.\n"
    "3. Replace technical abbreviations with their full canonical form. "
    "Drop the abbreviation entirely — do NOT keep it in parentheses, "
    "because parenthetical noise lowers cross-encoder rerank scores. "
    "Examples:\n"
    "   k8s -> Kubernetes\n"
    "   aws -> Amazon Web Services\n"
    "   gpu -> graphics processing unit\n"
    "   ml  -> machine learning\n"
    "   db  -> database\n"
    "4. If the question is a single bare term (one word or one acronym), "
    "reformulate it into a natural question. Examples:\n"
    "   'Kubernetes'  -> 'What is Kubernetes?'\n"
    "   'embeddings'  -> 'What are embeddings?'\n"
    "   'k8s'         -> 'What is Kubernetes?'\n"
    "5. If the question is already a complete natural-language question "
    "with no abbreviations and no references to resolve, output it "
    "unchanged.\n\n"
    "Output: ONE LINE. The rewritten query only. No quotation marks. No "
    "'Query:' prefix. No explanation."
)


def detect_symbol_lookup(user_message: str) -> str | None:
    """Return the exact code symbol requested by a symbol lookup, if any.

    Supports Python/JavaScript identifiers and dotted paths, including
    camelCase, PascalCase, snake_case, and module/class method references.
    Natural-language questions without code-lookup intent are ignored so
    the normal LLM rewrite path can handle documentation-style queries.
    """
    message = user_message.strip()
    if not message:
        return None

    def normalize(candidate: str) -> str | None:
        symbol = candidate.strip().strip("`'\"“”‘’.,;:!?()[]{}<>，。！？；：")
        if symbol.endswith("()"):
            symbol = symbol[:-2]
        if _SYMBOL_RE.fullmatch(symbol):
            return symbol
        return None

    code_span_symbols = [
        symbol
        for match in _CODE_SPAN_RE.finditer(message)
        if (symbol := normalize(match.group(1)))
    ]
    if code_span_symbols:
        return code_span_symbols[0]

    symbol_only = normalize(message)
    if symbol_only:
        return symbol_only

    if not _SYMBOL_LOOKUP_HINT_RE.search(message):
        return None

    candidates = [
        symbol
        for match in _SYMBOL_TOKEN_RE.finditer(message)
        if (symbol := normalize(match.group(0)))
        and symbol.lower() not in _SYMBOL_LOOKUP_STOPWORDS
    ]
    if not candidates:
        return None

    dotted = [symbol for symbol in candidates if "." in symbol]
    snake_case = [symbol for symbol in candidates if "_" in symbol]
    camel_or_pascal = [
        symbol
        for symbol in candidates
        if re.search(r"[a-z][A-Z]|[A-Z][a-z]+[A-Z]", symbol)
    ]

    for preferred in (dotted, snake_case, camel_or_pascal):
        if preferred:
            return preferred[0]
    return candidates[0]


def _symbol_lookup_query(symbol: str) -> str:
    return _SYMBOL_QUERY_TEMPLATE.format(symbol=symbol)


async def rewrite_for_retrieval(history: list[ChatMessage], user_message: str) -> str:
    """Rewrite the user's question into a standalone, abbreviation-expanded
    query for the retrieval pipeline.

    Always runs when called (chat path gates this on `use_rag=true`).
    First-turn queries pay one extra LLM call for the chance to expand
    abbreviations like "k8s" / "aws" — without it, cross-encoder rerank
    scores those tokens far below threshold and citations vanish.

    On any LLM error or off-rails output, falls back to the raw user
    message so retrieval still runs.
    """
    symbol = detect_symbol_lookup(user_message)
    if symbol:
        return _symbol_lookup_query(symbol)

    if history:
        # Multi-turn: feed only a very small recent window so the rewriter can
        # resolve short follow-ups without dragging in old answer content.
        s = get_settings()
        recent = history[-max(0, s.chat_rewrite_history_messages) :]
        max_chars = max(40, s.chat_rewrite_history_chars)
        transcript_lines: list[str] = []
        for m in recent:
            role = "User" if m.role is ChatRole.USER else "Assistant"
            body = (
                m.content
                if len(m.content) <= max_chars
                else m.content[:max_chars] + "..."
            )
            transcript_lines.append(f"{role}: {body}")
        prompt = (
            "Conversation history:\n"
            + "\n".join(transcript_lines)
            + f"\n\nMost recent question:\n{user_message}\n\nStandalone query:"
        )
    else:
        # First turn: no history to resolve against; rewriter still
        # handles abbreviation expansion + bare-term reformulation.
        prompt = f"Question:\n{user_message}\n\nStandalone search query:"

    s = get_settings()
    try:
        rewriter = ChatOpenAI(
            model=s.llm_model,
            base_url=s.llm_base_url,
            api_key=s.llm_api_key,
            streaming=False,
            temperature=0,
            max_tokens=128,
        )
        result = await rewriter.ainvoke(
            [SystemMessage(content=_REWRITE_SYSTEM), HumanMessage(content=prompt)]
        )
        rewritten = (result.content or "").strip()
        # Defensive: bail if model went off the rails (returned nothing,
        # multiline explanation, or something far longer than expected).
        if not rewritten or len(rewritten) > 500 or "\n" in rewritten:
            return user_message
        return rewritten
    except Exception:
        logger.exception("query_rewrite_failed; falling back to raw user message")
        return user_message


def _build_llm() -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(
        model=s.llm_model,
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        streaming=True,
        temperature=0.3,
    )


def _history_window(rows: list[ChatMessage], max_messages: int) -> list[ChatMessage]:
    return rows[-max(0, max_messages) :] if max_messages else []


def _history_to_messages(rows: list[ChatMessage]) -> list[HumanMessage | AIMessage]:
    s = get_settings()
    max_messages = max(0, s.chat_answer_history_messages)
    msgs: list[HumanMessage | AIMessage] = []
    for r in _history_window(rows, max_messages):
        if r.role is ChatRole.USER:
            msgs.append(HumanMessage(content=r.content))
        else:
            msgs.append(AIMessage(content=r.content))
    return msgs


async def stream_answer(
    *,
    history: list[ChatMessage],
    user_message: str,
    context: str,
    rag_query: str | None = None,
    code_assist_intent: str | None = None,
    query_tags: QueryTags | None = None,
    retrieval_note: str | None = None,
) -> AsyncIterator[str]:
    """Yields LLM token chunks as plain strings."""
    messages: list[Any] = [SystemMessage(content=SYSTEM_PROMPT)]
    messages.extend(_history_to_messages(history))
    if context:
        messages.append(SystemMessage(content=f"Context:\n{context}"))
    if rag_query:
        messages.append(
            SystemMessage(
                content=f"Retrieval query used to select context: {rag_query}"
            )
        )
    if query_tags and query_tags.has_signal():
        messages.append(SystemMessage(content=query_tags.as_prompt_text()))
    if retrieval_note:
        messages.append(SystemMessage(content=retrieval_note))
    if code_assist_intent:
        messages.append(
            SystemMessage(
                content=(
                    "This is a code-assistance request: "
                    f"{code_assist_intent}. Map the user's request to "
                    "retrieved code context before answering."
                )
            )
        )
    messages.append(HumanMessage(content=user_message))

    llm = _build_llm()
    async for chunk in llm.astream(messages):
        if chunk.content:
            yield chunk.content
