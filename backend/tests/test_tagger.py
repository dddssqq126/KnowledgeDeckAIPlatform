from app.features.rag.services.tagger import (
    DocTags,
    _parse_tags,
    enrich_text_for_embedding,
)


def test_parse_well_formed_json() -> None:
    raw = '{"topic": ["billing", "api-auth"], "doc_type": "faq", "intent": "how_to", "language": "en"}'
    tags = _parse_tags(raw)
    assert tags.topic == ["billing", "api-auth"]
    assert tags.doc_type == "faq"
    assert tags.intent == "how_to"
    assert tags.language == "en"


def test_parse_strips_code_fence() -> None:
    raw = '```json\n{"topic": ["x"], "doc_type": "guide", "intent": "conceptual"}\n```'
    tags = _parse_tags(raw)
    assert tags.topic == ["x"]
    assert tags.doc_type == "guide"


def test_parse_rejects_unknown_enum() -> None:
    raw = '{"topic": ["x"], "doc_type": "newspaper", "intent": "vibes"}'
    tags = _parse_tags(raw)
    assert tags.doc_type is None
    assert tags.intent is None


def test_parse_caps_topics_at_five() -> None:
    raw = '{"topic": ["a", "b", "c", "d", "e", "f", "g"]}'
    tags = _parse_tags(raw)
    assert tags.topic == ["a", "b", "c", "d", "e"]


def test_parse_garbage_returns_empty() -> None:
    assert _parse_tags("not json at all") == DocTags.empty()


def test_enrich_prepends_tag_line() -> None:
    tags = DocTags(topic=["billing"], doc_type="faq", intent="how_to", language="en")
    out = enrich_text_for_embedding("How do I pay?", tags)
    assert out == "[topics: billing | type: faq | intent: how_to]\nHow do I pay?"


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
        content = '{"topic": ["k8s"], "doc_type": "guide", "intent": "how_to", "language": "en"}'

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
    assert any("kubernetes setup guide" in str(m.content) for m in fake.seen)
