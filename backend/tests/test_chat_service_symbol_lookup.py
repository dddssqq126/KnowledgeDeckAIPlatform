import pytest

from app.db.models import ChatMessage, ChatRole
from app.features.chat.services import chat_service
from app.features.chat.services.chat_service import (
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


@pytest.mark.asyncio
async def test_rewrite_for_retrieval_builds_symbol_query() -> None:
    query = await rewrite_for_retrieval([], "找到 `parse_token` 在哪裡用")

    assert query == (
        "Find the definition, signature, implementation, usages, call sites, "
        "and related function for symbol: parse_token"
    )


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
