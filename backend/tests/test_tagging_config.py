from app.core.config import Settings


def test_tagging_settings_defaults() -> None:
    s = Settings()
    assert s.rag_tagging_enabled is True
    assert s.rag_tag_max_chars == 4000
