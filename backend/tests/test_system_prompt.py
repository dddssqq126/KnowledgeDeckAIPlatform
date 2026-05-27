from app.features.chat.services.chat_service import SYSTEM_PROMPT


def test_prompt_has_answer_discipline_rules() -> None:
    p = SYSTEM_PROMPT.lower()
    # only answer from context for doc Q&A
    assert "only" in p and "context" in p
    # admit insufficient context
    assert "insufficient" in p or "not enough" in p
    # ask one clarifying question when ambiguous
    assert "clarif" in p
    # citation behavior must remain referenced (unchanged block)
    assert "citation" in p
