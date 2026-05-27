"""LLM document tagging for RAG enrichment.

One LLM call per document produces topic/doc_type/intent/language tags. The
tags are folded into the text that gets embedded + sparse-encoded (soft
enrichment) so tiny documents carry more semantic signal. See
docs/superpowers/specs/2026-05-27-tag-aware-rag-design.md.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_DOC_TYPES = {"guide", "faq", "api", "reference", "code", "release_note"}
_INTENTS = {"how_to", "troubleshooting", "conceptual", "policy"}
_MAX_TOPICS = 5


@dataclass
class DocTags:
    topic: list[str] = field(default_factory=list)
    doc_type: str | None = None
    intent: str | None = None
    language: str | None = None

    @classmethod
    def empty(cls) -> "DocTags":
        return cls()


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
    topic = [str(t).strip() for t in topic_raw if str(t).strip()][:_MAX_TOPICS] \
        if isinstance(topic_raw, list) else []

    doc_type = obj.get("doc_type")
    doc_type = doc_type if doc_type in _DOC_TYPES else None

    intent = obj.get("intent")
    intent = intent if intent in _INTENTS else None

    language = obj.get("language")
    language = str(language).strip() if isinstance(language, str) and language.strip() else None

    return DocTags(topic=topic, doc_type=doc_type, intent=intent, language=language)


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
    if not parts:
        return text
    return "[" + " | ".join(parts) + "]\n" + text
