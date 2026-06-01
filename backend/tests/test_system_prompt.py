from app.features.chat.services.chat_service import SYSTEM_PROMPT


def test_prompt_has_answer_discipline_rules() -> None:
    p = SYSTEM_PROMPT.lower()
    assert "primary evidence" in p and "context" in p
    assert "teradyne" in p and "advantest" in p
    assert "ultraflex" in p and "v93000" in p
    assert "evidence priority" in p
    assert "conflict handling" in p
    assert "insufficient evidence" in p
    assert "traditional chinese" in p
    assert "結論" in SYSTEM_PROMPT
    assert "文件不足" in SYSTEM_PROMPT
    assert "clarifying question" in p
    assert "citation" in p
    assert "programming language" in p
    assert "do not generate new code" in p
    assert "explicitly asks" in p
    assert "functions" in p
    assert "signatures" in p
    assert "code blocks" in p
    assert "step-by-step" in p
    assert "do not fabricate" in p
