from app.features.rag.services.tagger import (
    DocTags,
    _TAGGER_SYSTEM,
    _parse_tags,
    enrich_text_for_embedding,
)


def test_parse_well_formed_json() -> None:
    raw = (
        '{"topic": ["billing", "api-auth"], "doc_type": "faq",'
        ' "intent": "how_to", "language": "en", "vendor": "Teradyne ATE",'
        ' "platform": "UltraFlex", "knowledge_type": "vendor doc"}'
    )
    tags = _parse_tags(raw)
    assert tags.topic == ["billing", "api-auth"]
    assert tags.doc_type == "faq"
    assert tags.intent == "how_to"
    assert tags.language == "en"
    assert tags.vendor == "teradyne"
    assert tags.platform == "ultraflex"
    assert tags.knowledge_type == "vendor_doc"


def test_parse_strips_code_fence() -> None:
    raw = '```json\n{"topic": ["x"], "doc_type": "guide", "intent": "conceptual"}\n```'
    tags = _parse_tags(raw)
    assert tags.topic == ["x"]
    assert tags.doc_type == "guide"


def test_parse_rejects_unknown_doc_type_and_intent_but_keeps_flexible_tags() -> None:
    raw = (
        '{"topic": ["x"], "doc_type": "newspaper", "intent": "vibes",'
        ' "vendor": "Initech", "platform": "big-iron",'
        ' "knowledge_type": "memo"}'
    )
    tags = _parse_tags(raw)
    assert tags.doc_type is None
    assert tags.intent is None
    assert tags.vendor == "initech"
    assert tags.platform == "big_iron"
    assert tags.knowledge_type == "memo"


def test_parse_keeps_standards_and_protocol_tags() -> None:
    raw = (
        '{"topic": ["radio access", "wifi"], "vendor": "IEEE",'
        ' "platform": "802.11ax", "knowledge_type": "Wireless Standard"}'
    )
    tags = _parse_tags(raw)
    assert tags.vendor == "ieee"
    assert tags.platform == "802.11ax"
    assert tags.knowledge_type == "wireless_standard"


def test_parse_can_tag_5g_documents() -> None:
    raw = (
        '{"topic": ["5g", "nr"], "vendor": "3GPP",'
        ' "platform": "5G NR", "knowledge_type": "specification"}'
    )
    tags = _parse_tags(raw)
    assert tags.vendor == "3gpp"
    assert tags.platform == "5g_nr"
    assert tags.knowledge_type == "specification"


def test_parse_caps_topics_at_ten() -> None:
    raw = '{"topic": ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"]}'
    tags = _parse_tags(raw)
    assert tags.topic == ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]


def test_tagger_system_encourages_broad_topic_inference() -> None:
    assert "Do not limit tags to ATE vendors" in _TAGGER_SYSTEM
    assert "any source organization" in _TAGGER_SYSTEM
    assert "up to the 10-topic limit" in _TAGGER_SYSTEM


def test_parse_garbage_returns_empty() -> None:
    assert _parse_tags("not json at all") == DocTags.empty()


def test_enrich_prepends_tag_line() -> None:
    tags = DocTags(
        topic=["billing"],
        doc_type="faq",
        intent="how_to",
        language="en",
        vendor="advantest",
        platform="v93000",
        knowledge_type="internal_bkm",
    )
    out = enrich_text_for_embedding("How do I pay?", tags)
    assert out == (
        "[topics: billing | type: faq | intent: how_to | vendor: advantest | "
        "platform: v93000 | knowledge_type: internal_bkm]\nHow do I pay?"
    )


def test_enrich_empty_tags_returns_text_unchanged() -> None:
    assert enrich_text_for_embedding("hello", DocTags.empty()) == "hello"


def test_parse_drops_non_string_topics() -> None:
    raw = '{"topic": ["ok", null, 42, "  ", "good"]}'
    tags = _parse_tags(raw)
    assert tags.topic == ["ok", "good"]


def test_parse_non_dict_json_returns_empty() -> None:
    assert _parse_tags("[]") == DocTags.empty()
    assert _parse_tags("null") == DocTags.empty()
    assert _parse_tags("") == DocTags.empty()


def test_enrich_language_only_returns_text_unchanged() -> None:
    out = enrich_text_for_embedding("hello", DocTags(language="en"))
    assert out == "hello"


def test_parse_normalizes_platform_aliases() -> None:
    tags = _parse_tags(
        '{"topic": [], "vendor": "Advantest V93000", '
        '"platform": "Sm93000", "knowledge_type": "BKM"}'
    )
    assert tags.vendor == "advantest"
    assert tags.platform == "v93000"
    assert tags.knowledge_type == "internal_bkm"


import pytest

from app.features.rag.services import tagger as tagger_mod


@pytest.mark.asyncio
async def test_generate_doc_tags_returns_empty_on_llm_error(monkeypatch) -> None:
    class _BoomLLM:
        async def ainvoke(self, _messages):
            raise RuntimeError("vllm down")

    monkeypatch.setattr(tagger_mod, "_build_tagger_llm", lambda: _BoomLLM())

    tags = await tagger_mod.generate_doc_tags("some document text", "doc.txt")
    assert tags == DocTags.empty()


@pytest.mark.asyncio
async def test_generate_doc_tags_parses_llm_output(monkeypatch) -> None:
    class _FakeResult:
        content = (
            '{"topic": ["k8s"], "doc_type": "guide", "intent": "how_to",'
            ' "language": "en", "vendor": "internal", "platform": "generic",'
            ' "knowledge_type": "code"}'
        )

    class _FakeLLM:
        def __init__(self):
            self.seen = None

        async def ainvoke(self, messages):
            self.seen = messages
            return _FakeResult()

    fake = _FakeLLM()
    monkeypatch.setattr(tagger_mod, "_build_tagger_llm", lambda: fake)

    tags = await tagger_mod.generate_doc_tags("kubernetes setup guide ...", "setup.md")
    assert tags.topic == ["k8s"]
    assert tags.doc_type == "guide"
    assert tags.vendor == "internal"
    assert tags.platform == "generic"
    assert tags.knowledge_type == "code"
    assert any("kubernetes setup guide" in str(m.content) for m in fake.seen)
