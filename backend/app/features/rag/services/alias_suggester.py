"""Offline alias suggestion helpers for tag vocabulary maintenance.

The tagger intentionally accepts flexible tags, but over time the corpus may
contain variants such as ``PCI-SIG`` / ``PCI SIG`` or ``UltraFlex`` /
``Ultra Flex``. This module scans observed tags, filenames, and document text
and groups likely variants under a deterministic canonical slug that can be
reviewed before adding aliases to ``tagger.py``.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.features.rag.services import tagger

_ALIAS_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+/#-]{1,63}")
_PROPER_PHRASE_RE = re.compile(
    r"(?:[A-Z][A-Za-z0-9._+/#-]*|[A-Z0-9]{2,}|\d+(?:\.\w+)+)"
    r"(?:\s+(?:[A-Z][A-Za-z0-9._+/#-]*|[A-Z0-9]{2,}|\d+(?:\.\w+)+)){0,3}"
)
_LEGAL_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "limited",
    "llc",
    "ltd",
}
_ALIAS_STOPWORDS = {
    "all",
    "and",
    "confidential",
    "copyright",
    "document",
    "figure",
    "file",
    "page",
    "reserved",
    "right",
    "rights",
    "section",
    "table",
    "the",
    "version",
}
_BOILERPLATE_PHRASES = {
    "all rights reserved",
    "all right reserved",
    "copyright all rights reserved",
}


@dataclass(frozen=True)
class AliasObservation:
    field: str
    value: str
    source: str


@dataclass
class AliasSuggestion:
    field: str
    canonical: str
    aliases: list[str]
    count: int
    examples: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "canonical": self.canonical,
            "aliases": self.aliases,
            "count": self.count,
            "examples": self.examples,
        }


def _clean_alias(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().strip("'\"“”‘’.,;:!?()[]{}").split())
    if not cleaned:
        return None
    normalized = cleaned.casefold()
    if normalized in _BOILERPLATE_PHRASES:
        return None
    words = re.findall(r"[a-z0-9]+", normalized)
    if not words or all(word in _ALIAS_STOPWORDS for word in words):
        return None
    return cleaned[:64]


def canonicalize_alias(value: object, field_name: str = "") -> str:
    cleaned = _clean_alias(value)
    if cleaned is None:
        return "unknown"
    words = [w for w in re.findall(r"[a-z0-9]+", cleaned.casefold()) if w]
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    if not words:
        return "unknown"
    value_slug = "_".join(words)
    if field_name == "vendor":
        return tagger.normalize_vendor(value_slug)
    if field_name == "knowledge_type":
        return tagger.normalize_knowledge_type(value_slug)
    return tagger.normalize_platform(value_slug)


def observations_from_file(
    *,
    filename: str,
    text: str = "",
    vendor: str | None = None,
    platform: str | None = None,
    knowledge_type: str | None = None,
    max_text_chars: int = 6000,
) -> list[AliasObservation]:
    """Extract alias observations from one file's metadata and text sample."""
    observations: list[AliasObservation] = []
    source = filename
    for field_name, value in (
        ("vendor", vendor),
        ("platform", platform),
        ("knowledge_type", knowledge_type),
    ):
        cleaned = _clean_alias(value)
        if cleaned and cleaned.casefold() != "unknown":
            observations.append(AliasObservation(field_name, cleaned, source))

    filename_base = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    for token in _ALIAS_TOKEN_RE.finditer(filename_base.replace("-", " ")):
        cleaned = _clean_alias(token.group(0))
        if cleaned:
            observations.append(AliasObservation("filename", cleaned, source))

    for match in _PROPER_PHRASE_RE.finditer(text[:max_text_chars]):
        cleaned = _clean_alias(match.group(0))
        if cleaned:
            observations.append(AliasObservation("proper_noun", cleaned, source))
    return observations


def suggest_aliases(
    observations: list[AliasObservation], *, min_count: int = 2
) -> list[AliasSuggestion]:
    """Group observations by field + canonical slug for human review."""
    grouped: dict[tuple[str, str], list[AliasObservation]] = defaultdict(list)
    for obs in observations:
        canonical = canonicalize_alias(obs.value, obs.field)
        if canonical == "unknown":
            continue
        grouped[(obs.field, canonical)].append(obs)

    suggestions: list[AliasSuggestion] = []
    for (field_name, canonical), rows in grouped.items():
        if len(rows) < min_count:
            continue
        alias_counts = Counter(row.value for row in rows)
        aliases = [alias for alias, _count in alias_counts.most_common()]
        # A canonical seen only once under a single spelling is not an alias
        # decision; keep repeated or variant spellings for review.
        if len(aliases) < 2 and len(rows) < max(min_count, 3):
            continue
        examples = []
        seen_sources: set[str] = set()
        for row in rows:
            if row.source in seen_sources:
                continue
            seen_sources.add(row.source)
            examples.append(row.source)
            if len(examples) >= 5:
                break
        suggestions.append(
            AliasSuggestion(
                field=field_name,
                canonical=canonical,
                aliases=aliases,
                count=len(rows),
                examples=examples,
            )
        )

    suggestions.sort(key=lambda item: (-item.count, item.field, item.canonical))
    return suggestions
