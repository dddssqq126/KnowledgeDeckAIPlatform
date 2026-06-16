import pytest

from app.db.models import ChatMessage, ChatRole
from app.features.chat.services import chat_service
from app.features.chat.services.chat_service import (
    build_rag_query_with_attachment,
    detect_query_tags,
    detect_symbol_lookup,
    rewrite_for_retrieval,
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("user_id", "user_id"),
        ("parseToken", "parseToken"),
        ("ClassName.method_name", "ClassName.method_name"),
        ("module.function_name", "module.function_name"),
        ("user_id 相關的函式", "user_id"),
        ("找到 `parse_token` 在哪裡用", "parse_token"),
        ("Find parse_token where used", "parse_token"),
        ("什麼是 Kubernetes？", None),
    ],
)
def test_detect_symbol_lookup(message: str, expected: str | None) -> None:
    assert detect_symbol_lookup(message) == expected


def test_build_rag_query_with_attachment_combines_question_and_input() -> None:
    query = build_rag_query_with_attachment(
        "How should I fix this alarm?",
        "Filename: alarms.csv\nUltraFLEX ALM-42 vector load failure",
    )

    assert query.startswith("How should I fix this alarm?")
    assert "Uploaded input data for RAG search:" in query
    assert "Filename: alarms.csv" in query
    assert "ALM-42" in query


@pytest.mark.asyncio
async def test_rewrite_for_retrieval_builds_symbol_query() -> None:
    query = await rewrite_for_retrieval([], "找到 `parse_token` 在哪裡用")

    assert query == (
        "Find the definition, signature, implementation, usages, call sites, "
        "and related function for symbol: parse_token"
    )


@pytest.mark.asyncio
async def test_rewrite_for_retrieval_includes_attachment_hints(monkeypatch) -> None:
    captured = {}

    class _FakeRewriter:
        def __init__(self, **_kwargs):
            pass

        async def ainvoke(self, messages):
            captured["prompt"] = messages[-1].content
            return type(
                "Result",
                (),
                {"content": "Find ALM-42 UltraFLEX alarm documentation"},
            )()

    monkeypatch.setattr(chat_service, "ChatOpenAI", _FakeRewriter)

    query = await rewrite_for_retrieval(
        [],
        "請找相關文件",
        attachment_retrieval_text="Filename: alarm.txt\nUltraFLEX ALM-42 vector load failure",
    )

    assert query == "Find ALM-42 UltraFLEX alarm documentation"
    assert "Uploaded file text for retrieval hints" in captured["prompt"]
    assert "Filename: alarm.txt" in captured["prompt"]
    assert "ALM-42" in captured["prompt"]




@pytest.mark.asyncio
async def test_rewrite_for_retrieval_fallback_keeps_attachment_hints(monkeypatch) -> None:
    class _FailingRewriter:
        def __init__(self, **_kwargs):
            pass

        async def ainvoke(self, _messages):
            raise RuntimeError("rewriter unavailable")

    monkeypatch.setattr(chat_service, "ChatOpenAI", _FailingRewriter)

    query = await rewrite_for_retrieval(
        [],
        "",
        attachment_retrieval_text="Filename: alarms.csv\nUltraFLEX ALM-42 vector load failure",
    )

    assert "Filename: alarms.csv" in query
    assert "ALM-42" in query

@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "請說明 Teradyne UltraFLEX 的 BKM",
            ("teradyne", "ultraflex", "internal_bkm"),
        ),
        (
            "艾德萬 V93000 code 哪裡處理 error?",
            ("advantest", "v93000", "code"),
        ),
        (
            "V93K vendor document",
            ("unknown", "v93000", "unknown"),
        ),
        (
            "J750 troubleshooting",
            ("unknown", "j750", "unknown"),
        ),
        (
            "3GPP 5G NR specification",
            ("3gpp", "5g_nr", "standard"),
        ),
        (
            "IEEE 802.11ax standard",
            ("ieee", "802.11", "standard"),
        ),
    ],
)
def test_detect_query_tags(message: str, expected: tuple[str, str, str]) -> None:
    tags = detect_query_tags(message)
    assert (tags.vendor, tags.platform, tags.knowledge_type) == expected


def _message(role: ChatRole, content: str) -> ChatMessage:
    return ChatMessage(session_id=1, role=role, content=content, citations=None)


def test_history_to_messages_uses_configured_recent_window(monkeypatch) -> None:
    from app.core.config import Settings

    history = [
        _message(ChatRole.USER, "old user"),
        _message(ChatRole.ASSISTANT, "old assistant"),
        _message(ChatRole.USER, "recent user"),
        _message(ChatRole.ASSISTANT, "recent assistant"),
    ]
    monkeypatch.setattr(
        chat_service,
        "get_settings",
        lambda: Settings(chat_answer_history_messages=2),
    )

    messages = chat_service._history_to_messages(history)

    assert [m.content for m in messages] == ["recent user", "recent assistant"]


def test_history_to_messages_can_disable_history(monkeypatch) -> None:
    from app.core.config import Settings

    monkeypatch.setattr(
        chat_service,
        "get_settings",
        lambda: Settings(chat_answer_history_messages=0),
    )

    assert chat_service._history_to_messages([_message(ChatRole.USER, "old")]) == []


def test_rewrite_for_code_retrieval_trims_long_request(monkeypatch) -> None:
    from app.core.config import Settings

    monkeypatch.setattr(
        chat_service,
        "get_settings",
        lambda: Settings(chat_rewrite_user_message_chars=100),
    )

    query = chat_service.rewrite_for_code_retrieval(
        [], "HEAD" + ("x" * 200) + "TAIL", chat_service.CODE_INTENT_SNIPPET
    )

    assert "User request: HEAD" in query
    assert query.endswith("TAIL")
    assert "truncated before answer generation" in query


def test_trim_answer_input_leaves_short_input_unchanged() -> None:
    assert (
        chat_service._trim_answer_input("  short prompt  ", max_chars=100)
        == "  short prompt  "
    )


def test_trim_answer_input_preserves_head_and_tail() -> None:
    text = "HEAD" + ("x" * 200) + "TAIL"

    trimmed = chat_service._trim_answer_input(text, max_chars=100)

    assert len(trimmed) == 100
    assert trimmed.startswith("HEAD")
    assert trimmed.endswith("TAIL")
    assert "truncated before answer generation" in trimmed


def test_history_to_messages_trims_each_message(monkeypatch) -> None:
    from app.core.config import Settings

    monkeypatch.setattr(
        chat_service,
        "get_settings",
        lambda: Settings(
            chat_answer_history_messages=2,
            chat_answer_history_message_max_chars=100,
        ),
    )
    history = [
        _message(ChatRole.USER, "HEAD" + ("x" * 200) + "TAIL"),
        _message(ChatRole.ASSISTANT, "short answer"),
    ]

    messages = chat_service._history_to_messages(history)

    assert len(messages[0].content) == 100
    assert messages[0].content.startswith("HEAD")
    assert messages[0].content.endswith("TAIL")
    assert messages[1].content == "short answer"


@pytest.mark.asyncio
async def test_stream_answer_trims_context_query_and_user_message(monkeypatch) -> None:
    from app.core.config import Settings

    captured = {}

    class _FakeLLM:
        async def astream(self, messages):
            captured["messages"] = messages
            yield type("Chunk", (), {"content": "ok"})()

    monkeypatch.setattr(
        chat_service,
        "get_settings",
        lambda: Settings(
            chat_answer_context_max_chars=100,
            chat_answer_user_message_max_chars=80,
            chat_answer_metadata_max_chars=60,
        ),
    )
    monkeypatch.setattr(chat_service, "_build_llm", lambda: _FakeLLM())

    chunks = [
        chunk
        async for chunk in chat_service.stream_answer(
            history=[],
            user_message="USER" + ("u" * 200) + "TAIL",
            context="CTX" + ("c" * 200) + "TAIL",
            rag_query="QUERY" + ("q" * 200) + "TAIL",
        )
    ]

    assert chunks == ["ok"]
    messages = captured["messages"]
    context_message = next(m for m in messages if str(m.content).startswith("Context:"))
    query_message = next(
        m
        for m in messages
        if str(m.content).startswith("Retrieval query used to select context:")
    )
    user_message = messages[-1]
    assert len(context_message.content.removeprefix("Context:\n")) == 100
    assert len(
        query_message.content.removeprefix(
            "Retrieval query used to select context: "
        )
    ) == 60
    assert len(user_message.content) == 80
    assert "truncated before answer generation" in context_message.content
    assert "truncated before answer generation" in query_message.content
    assert "truncated before answer generation" in user_message.content
