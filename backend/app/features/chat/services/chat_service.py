"""Chat-only orchestration: history + (optional) RAG context → vLLM streaming.

RAG retrieval lives in `app.services.rag` and is shared with the slide
maker. This module contains:
  - the chat SYSTEM_PROMPT
  - `rewrite_for_retrieval` — chat-specific follow-up rewriter, used so
    multi-turn pronouns ("and Python?", "what about that one?") embed
    against a self-contained query rather than the literal user message
  - `stream_answer` — token-streaming reply assembly
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.db.models import ChatMessage, ChatRole

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are KnowledgeDeck, a helpful conversational assistant.\n\n"
    "This is a multi-turn conversation. The messages above (if any) are the "
    "prior turns — treat them as the running context. Refer back to facts, "
    "preferences, and details the user has shared earlier in the conversation, "
    "and maintain continuity across turns.\n\n"
    "When a `Context:` section is included by the system, prefer it as the "
    "source for factual claims about the user's documents. When `Context:` is "
    "absent or irrelevant to the question, answer from your general knowledge.\n\n"
    "Be concise. Do not refuse to recall information the user has shared "
    "earlier in this conversation — the conversation history above is yours "
    "to use."
)
# 20 = up to ~10 user/assistant pairs. Conversational chat tends to have
# short turns, so this is plenty before older turns fall off the window.
HISTORY_MAX_MESSAGES = 20


_REWRITE_SYSTEM = (
    "You rewrite user questions into standalone search queries optimized "
    "for retrieval against a knowledge base, where a cross-encoder "
    "reranker scores (query, passage) pairs. Cross-encoders work best on "
    "natural-language queries with full canonical terms, not bare tokens "
    "or abbreviations.\n\n"
    "You may receive:\n"
    "- A first-turn question (no conversation history above).\n"
    "- A follow-up question that uses pronouns ('that', 'it', 'this "
    "one'), elliptical references ('and Python?'), or implicit context "
    "that only makes sense relative to the prior turns.\n\n"
    "Apply these rules in order:\n"
    "1. Resolve all pronouns / references / ellipsis against the history.\n"
    "2. Replace technical abbreviations with their full canonical form. "
    "Drop the abbreviation entirely — do NOT keep it in parentheses, "
    "because parenthetical noise lowers cross-encoder rerank scores. "
    "Examples:\n"
    "   k8s -> Kubernetes\n"
    "   aws -> Amazon Web Services\n"
    "   gpu -> graphics processing unit\n"
    "   ml  -> machine learning\n"
    "   db  -> database\n"
    "3. If the question is a single bare term (one word or one acronym), "
    "reformulate it into a natural question. Examples:\n"
    "   'Kubernetes'  -> 'What is Kubernetes?'\n"
    "   'embeddings'  -> 'What are embeddings?'\n"
    "   'k8s'         -> 'What is Kubernetes?'\n"
    "4. If the question is already a complete natural-language question "
    "with no abbreviations and no references to resolve, output it "
    "unchanged.\n\n"
    "Output: ONE LINE. The rewritten query only. No quotation marks. No "
    "'Query:' prefix. No explanation."
)


async def rewrite_for_retrieval(
    history: list[ChatMessage], user_message: str
) -> str:
    """Rewrite the user's question into a standalone, abbreviation-expanded
    query for the retrieval pipeline.

    Always runs when called (chat path gates this on `use_rag=true`).
    First-turn queries pay one extra LLM call for the chance to expand
    abbreviations like "k8s" / "aws" — without it, cross-encoder rerank
    scores those tokens far below threshold and citations vanish.

    On any LLM error or off-rails output, falls back to the raw user
    message so retrieval still runs.
    """
    if history:
        # Multi-turn: feed the rewriter the recent history so it can
        # resolve pronouns/ellipsis. Long assistant turns are clipped
        # because only the gist matters for reference resolution.
        recent = history[-6:]
        transcript_lines: list[str] = []
        for m in recent:
            role = "User" if m.role is ChatRole.USER else "Assistant"
            body = m.content if len(m.content) <= 400 else m.content[:400] + "..."
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


def _history_to_messages(rows: list[ChatMessage]) -> list[HumanMessage | AIMessage]:
    msgs: list[HumanMessage | AIMessage] = []
    for r in rows[-HISTORY_MAX_MESSAGES:]:
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
) -> AsyncIterator[str]:
    """Yields LLM token chunks as plain strings."""
    messages: list[Any] = [SystemMessage(content=SYSTEM_PROMPT)]
    messages.extend(_history_to_messages(history))
    if context:
        messages.append(SystemMessage(content=f"Context:\n{context}"))
    if rag_query:
        messages.append(
            SystemMessage(content=f"Retrieval query used to select context: {rag_query}")
        )
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
