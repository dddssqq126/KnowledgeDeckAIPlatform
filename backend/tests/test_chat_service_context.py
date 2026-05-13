from app.features.chat.services.chat_service import _context_message_content


def test_context_message_content_uses_default_header_without_code_intent() -> None:
    assert _context_message_content("doc snippet", None) == "Context:\ndoc snippet"


def test_context_message_content_uses_code_header_with_code_intent() -> None:
    content = _context_message_content("def helper(): pass", "explain")

    assert content.startswith("Retrieved project/library code context:\n")
    assert "Use these snippets to identify existing functions" in content
    assert "signatures, usages, expected behavior, and related variables" in content
    assert content.endswith("\ndef helper(): pass")
