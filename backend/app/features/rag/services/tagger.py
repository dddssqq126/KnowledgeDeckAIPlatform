"""LLM document tagging for RAG enrichment.

One LLM call per document produces topic/doc_type/intent/language plus
vendor/platform/knowledge_type tags. The tags are folded into the text that
gets embedded + sparse-encoded (soft enrichment) so tiny documents carry more
semantic signal. See
docs/superpowers/specs/2026-05-27-tag-aware-rag-design.md.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_DOC_TYPES = {"guide", "faq", "api", "reference", "code", "release_note"}
_INTENTS = {"how_to", "troubleshooting", "conceptual", "policy"}
VENDORS = {"teradyne", "advantest", "internal", "unknown"}
PLATFORMS = {"ultraflex", "j750", "v93000", "t2000", "generic", "unknown"}
KNOWLEDGE_TYPES = {"vendor_doc", "internal_bkm", "code", "mixed", "unknown"}
_MAX_TOPICS = 10
_MAX_TAG_VALUE_CHARS = 64
_TAG_VALUE_RE = re.compile(r"[^a-z0-9._+/#]+")
_TOPIC_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+/#-]{1,63}")
_TOPIC_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORD_TOPICS = {
    "about",
    "all",
    "and",
    "are",
    "bridge",
    "com",
    "commissioning",
    "confidential",
    "copyright",
    "corp",
    "corporation",
    "disclaimer",
    "doc",
    "docs",
    "document",
    "file",
    "figure",
    "for",
    "from",
    "good",
    "guide",
    "http",
    "https",
    "inc",
    "incorporated",
    "into",
    "ltd",
    "llc",
    "manual",
    "ok",
    "page",
    "pdf",
    "pptx",
    "proprietary",
    "reference",
    "reserved",
    "right",
    "rights",
    "runbook",
    "section",
    "setup",
    "spec",
    "table",
    "the",
    "this",
    "troubleshooting",
    "txt",
    "version",
    "with",
    "www",
}
_TOPIC_BOILERPLATE_PHRASES = {
    "all rights reserved",
    "all right reserved",
    "copyright all rights reserved",
}
_CODE_EXTENSIONS = {"cs", "css", "go", "html", "java", "js", "py", "rs", "ts"}

_VENDOR_ALIASES = {
    "teradyne ate": "teradyne",
    "teradyne": "teradyne",
    "ter": "teradyne",
    "advantest v93000": "advantest",
    "advantest": "advantest",
    "adv": "advantest",
    "internal": "internal",
    "company internal": "internal",
}
_PLATFORM_ALIASES = {
    "ultraflex": "ultraflex",
    "ultra flex": "ultraflex",
    "j750": "j750",
    "j 750": "j750",
    "v93000": "v93000",
    "v93k": "v93000",
    "sm93000": "v93000",
    "sm 93000": "v93000",
    "t2000": "t2000",
    "t 2000": "t2000",
    "generic": "generic",
}
_KNOWLEDGE_TYPE_ALIASES = {
    "vendor doc": "vendor_doc",
    "vendor_doc": "vendor_doc",
    "vendor document": "vendor_doc",
    "internal bkm": "internal_bkm",
    "internal_bkm": "internal_bkm",
    "bkm": "internal_bkm",
    "best known method": "internal_bkm",
    "code": "code",
    "source code": "code",
    "mixed": "mixed",
}


@dataclass
class DocTags:
    topic: list[str] = field(default_factory=list)
    doc_type: str | None = None
    intent: str | None = None
    language: str | None = None
    vendor: str = "unknown"
    platform: str = "unknown"
    knowledge_type: str = "unknown"

    @classmethod
    def empty(cls) -> "DocTags":
        return cls()

    def with_overrides(
        self,
        *,
        vendor: str | None = None,
        platform: str | None = None,
        knowledge_type: str | None = None,
    ) -> "DocTags":
        return DocTags(
            topic=list(self.topic),
            doc_type=self.doc_type,
            intent=self.intent,
            language=self.language,
            vendor=normalize_vendor(vendor) if vendor else self.vendor,
            platform=normalize_platform(platform) if platform else self.platform,
            knowledge_type=(
                normalize_knowledge_type(knowledge_type)
                if knowledge_type
                else self.knowledge_type
            ),
        )


def _normalize_key(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    key = " ".join(value.strip().lower().replace("-", "_").split())
    return key or None


def _normalize_flexible_tag(value: object, aliases: dict[str, str]) -> str:
    """Normalize a user/LLM supplied tag while preserving useful new labels.

    The original tagger only accepted a small ATE-focused vocabulary. That made
    standards/protocol documents (for example 5G or IEEE 802.x material) fall
    back to ``unknown`` even when the LLM had enough context to suggest a useful
    tag. We still canonicalize known aliases, but otherwise keep a compact slug
    so future domains can be tagged without a code deploy.
    """
    key = _normalize_key(value)
    if key is None or key == "unknown":
        return "unknown"
    if key in aliases:
        return aliases[key]

    slug = _TAG_VALUE_RE.sub("_", key).strip("_")
    slug = re.sub(r"_+", "_", slug)[:_MAX_TAG_VALUE_CHARS].strip("_")
    return slug or "unknown"


def normalize_vendor(value: object) -> str:
    key = _normalize_key(value)
    if key in VENDORS:
        return key
    return _normalize_flexible_tag(value, _VENDOR_ALIASES)


def normalize_platform(value: object) -> str:
    key = _normalize_key(value)
    if key in PLATFORMS:
        return key
    return _normalize_flexible_tag(value, _PLATFORM_ALIASES)


def normalize_knowledge_type(value: object) -> str:
    key = _normalize_key(value)
    if key in KNOWLEDGE_TYPES:
        return key
    return _normalize_flexible_tag(value, _KNOWLEDGE_TYPE_ALIASES)


def _topic_words(value: str) -> list[str]:
    return _TOPIC_WORD_RE.findall(value.lower())


def _normalize_topic(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    topic = " ".join(value.strip().lower().split())[:_MAX_TAG_VALUE_CHARS].strip()
    if not topic:
        return None
    words = _topic_words(topic)
    if not words:
        return None
    if topic in _TOPIC_BOILERPLATE_PHRASES:
        return None
    if all(len(word) < 2 for word in words) and not any(ch.isdigit() for ch in topic):
        return None
    if all(word in _STOPWORD_TOPICS for word in words):
        return None
    return topic


def _is_proper_topic_candidate(value: str, *, from_filename: bool) -> bool:
    topic = _normalize_topic(value)
    if topic is None:
        return False
    # Standards, protocols, model numbers, file formats, and product IDs often
    # contain digits or separators even when lowercased (5g, 802.11ax, api/v1).
    if any(ch.isdigit() for ch in value) or any(ch in value for ch in "._+/#"):
        return True
    # Acronyms and mixed-case identifiers are common proper technical nouns
    # (PCIe, OpenAPI, Qdrant, iOS). Avoid plain sentence-case text tokens unless
    # they came from the filename, where title-cased words are more likely labels.
    letters = [ch for ch in value if ch.isalpha()]
    has_upper = any(ch.isupper() for ch in letters)
    has_lower = any(ch.islower() for ch in letters)
    if (
        has_upper
        and has_lower
        and (value[:1].islower() or any(ch.isupper() for ch in value[1:]))
    ):
        return True
    if len(letters) > 1 and all(ch.isupper() for ch in letters):
        return True
    return from_filename and value[:1].isupper()


def _append_topic(topics: list[str], seen: set[str], value: object) -> None:
    topic = _normalize_topic(value)
    if topic is None:
        return
    key = _normalize_flexible_tag(topic, {})
    if key == "unknown" or key in seen:
        return
    seen.add(key)
    topics.append(topic)


def _filename_extension(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1].strip().lower()
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1]


def _infer_doc_type(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1].strip().lower()
    ext = _filename_extension(filename)
    if ext in _CODE_EXTENSIONS:
        return "code"
    if any(marker in name for marker in ("release", "changelog", "change_log")):
        return "release_note"
    if "faq" in name:
        return "faq"
    if "api" in name:
        return "api"
    if any(
        marker in name for marker in ("guide", "tutorial", "how_to", "setup", "install")
    ):
        return "guide"
    return "reference"


def _infer_knowledge_type(filename: str, text: str) -> str:
    ext = _filename_extension(filename)
    haystack = f"{filename}\n{text[:1000]}".lower()
    if ext in _CODE_EXTENSIONS:
        return "code"
    if any(marker in haystack for marker in ("standard", "specification", " rfc ")):
        return "standard"
    if any(marker in haystack for marker in ("bkm", "best known method")):
        return "internal_bkm"
    if any(marker in haystack for marker in ("vendor", "datasheet", "manual")):
        return "vendor_doc"
    return "document"


def _fallback_topics(text: str, filename: str) -> list[str]:
    """Derive deterministic proper-noun topics for indexed documents."""
    filename_base = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    topics: list[str] = []
    seen: set[str] = set()

    filename_slug = _normalize_flexible_tag(filename_base, {})
    filename_words = _topic_words(filename_slug)
    if filename_words and not all(word in _STOPWORD_TOPICS for word in filename_words):
        _append_topic(topics, seen, filename_slug)

    for source, from_filename in ((filename_base, True), (text[:2000], False)):
        for match in _TOPIC_TOKEN_RE.finditer(source.replace("-", " ")):
            candidate = match.group(0)
            if not _is_proper_topic_candidate(candidate, from_filename=from_filename):
                continue
            _append_topic(topics, seen, candidate)
            if len(topics) >= _MAX_TOPICS:
                return topics
    return topics or ["document"]


def ensure_document_tags(tags: DocTags, text: str, filename: str) -> DocTags:
    """Fill safe fallback tags so every successfully indexed document is tagged.

    LLM tagging is best-effort, but retrieval still benefits from deterministic
    tag signal when the LLM is unavailable or omits optional fields.
    """
    return DocTags(
        topic=tags.topic or _fallback_topics(text, filename),
        doc_type=tags.doc_type or _infer_doc_type(filename),
        intent=tags.intent,
        language=tags.language,
        vendor=tags.vendor,
        platform=tags.platform,
        knowledge_type=(
            tags.knowledge_type
            if tags.knowledge_type != "unknown"
            else _infer_knowledge_type(filename, text)
        ),
    )


def _parse_tags(raw: str) -> DocTags:
    """Parse the tagger LLM output into validated DocTags. Any malformed or
    out-of-vocabulary content degrades to empty/None rather than raising."""
    text = raw.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return DocTags.empty()
    if not isinstance(obj, dict):
        return DocTags.empty()

    topic_raw = obj.get("topic")
    topic: list[str] = []
    if isinstance(topic_raw, list):
        seen_topics: set[str] = set()
        for raw_topic in topic_raw:
            _append_topic(topic, seen_topics, raw_topic)
            if len(topic) >= _MAX_TOPICS:
                break

    doc_type = obj.get("doc_type")
    doc_type = doc_type if doc_type in _DOC_TYPES else None

    intent = obj.get("intent")
    intent = intent if intent in _INTENTS else None

    language = obj.get("language")
    language = (
        str(language).strip()
        if isinstance(language, str) and language.strip()
        else None
    )

    return DocTags(
        topic=topic,
        doc_type=doc_type,
        intent=intent,
        language=language,
        vendor=normalize_vendor(obj.get("vendor")),
        platform=normalize_platform(obj.get("platform")),
        knowledge_type=normalize_knowledge_type(obj.get("knowledge_type")),
    )


def enrich_text_for_embedding(text: str, tags: DocTags) -> str:
    """Prepend a compact tag line to the text that will be embedded. Returns
    the text unchanged when there are no usable tags."""
    parts: list[str] = []
    if tags.topic:
        parts.append("topics: " + ", ".join(tags.topic))
    if tags.doc_type:
        parts.append("type: " + tags.doc_type)
    if tags.intent:
        parts.append("intent: " + tags.intent)
    if tags.vendor != "unknown":
        parts.append("vendor: " + tags.vendor)
    if tags.platform != "unknown":
        parts.append("platform: " + tags.platform)
    if tags.knowledge_type != "unknown":
        parts.append("knowledge_type: " + tags.knowledge_type)
    if not parts:
        return text
    return "[" + " | ".join(parts) + "]\n" + text


_TAGGER_SYSTEM = (
    "You label a document for a retrieval system. Read the document and reply "
    "with ONLY a JSON object, no prose, no code fence, with keys:\n"
    '  "topic": array of 3-10 short lowercase proper-noun topic keywords,\n'
    f'  "doc_type": one of {sorted(_DOC_TYPES)},\n'
    f'  "intent": one of {sorted(_INTENTS)},\n'
    '  "vendor": a concise lowercase source/organization/domain tag,\n'
    '  "platform": a concise lowercase product/platform/standard tag,\n'
    '  "knowledge_type": a concise lowercase document-category tag,\n'
    '  "language": ISO language code of the document (e.g. "en", "zh").\n'
    "Prefer known ATE values when they fit: "
    f"vendor={sorted(VENDORS)}, platform={sorted(PLATFORMS)}, "
    f"knowledge_type={sorted(KNOWLEDGE_TYPES)}. "
    "Do not limit tags to ATE vendors, instruments, 5G, or any predefined "
    "domain. When the document gives enough evidence, infer useful tags for "
    "any source organization, standard body, product, platform, protocol, "
    "technology, API, workflow, business process, feature, file format, or "
    "document category. Every document must receive tags: always provide at "
    "least one topic, and choose the closest doc_type and knowledge_type even "
    "when the document is short. Topic values must be proper nouns or specific "
    "technical identifiers, such as company names, standards, protocols, product "
    "names, API names, model numbers, file formats, and domain-specific named "
    "technologies. Never use boilerplate/legal/footer words as topics, such as "
    "all, inc, rights, reserved, copyright, confidential, page, table, or figure. "
    "Put as many meaningful, retrieval-helpful subjects as possible in topic, up "
    "to the 10-topic limit; prefer specific terms over generic ones and avoid "
    "duplicates. Use vendor_doc for vendor manuals, "
    "internal_bkm for company BKM, code for source code, mixed when multiple "
    "categories are central, or a concise inferred category such as standard, "
    "specification, test_plan, architecture, tutorial, policy, report, or "
    "datasheet when that is more accurate. Use unknown only for vendor or "
    "platform when no reliable source or platform can be inferred. If unsure "
    "about intent, omit that key. Output JSON only."
)


def _build_tagger_llm() -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(
        model=s.llm_model,
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        streaming=False,
        temperature=0,
        max_tokens=384,
    )


async def generate_doc_tags(text: str, filename: str) -> DocTags:
    """One LLM call -> validated DocTags plus deterministic fallbacks.

    Never raises: LLM failures, timeouts, malformed output, or missing optional
    fields still return retrieval-helpful tags so ingestion can proceed.
    """
    s = get_settings()
    snippet = text[: s.rag_tag_max_chars]
    prompt = f"Filename: {filename}\n\nDocument:\n{snippet}"
    try:
        result = await _build_tagger_llm().ainvoke(
            [SystemMessage(content=_TAGGER_SYSTEM), HumanMessage(content=prompt)]
        )
        return ensure_document_tags(
            _parse_tags(result.content or ""), snippet, filename
        )
    except Exception:
        logger.exception("doc_tagging_failed filename=%s", filename)
        return ensure_document_tags(DocTags.empty(), snippet, filename)
