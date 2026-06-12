import pytest

from app.features.chat.services.chat_service import (
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
