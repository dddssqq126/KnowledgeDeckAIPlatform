from app.core.config import Settings


def test_settings_defaults_match_local_development() -> None:
    settings = Settings()

    assert settings.app_name == "KnowledgeDeck"
    assert settings.environment == "local"
    assert settings.llm_base_url == "http://knowledgedeck_vllm_chat:8000/v1"
    assert settings.llm_model == "google/gemma-4-E4B-it"
    assert settings.embedding_base_url == "http://knowledgedeck_vllm_embedding:8001/v1"
    assert settings.embedding_model == "BAAI/bge-m3"
    assert settings.gpu_device == "0"
    assert settings.database_url == (
        "sqlite+aiosqlite:///./knowledgedeck.db"
    )
    assert settings.initial_user_username == ""
    assert settings.initial_user_password == ""


def test_settings_accept_endpoint_overrides() -> None:
    settings = Settings(
        llm_base_url="https://models.example.test/v1",
        llm_api_key="test-key",
        llm_model="custom-chat",
        embedding_base_url="https://embeddings.example.test/v1",
        embedding_api_key="embedding-key",
        embedding_model="custom-embedding",
    )

    assert settings.llm_base_url == "https://models.example.test/v1"
    assert settings.llm_api_key == "test-key"
    assert settings.llm_model == "custom-chat"
    assert settings.embedding_base_url == "https://embeddings.example.test/v1"
    assert settings.embedding_api_key == "embedding-key"
    assert settings.embedding_model == "custom-embedding"


def test_settings_accept_initial_user_overrides() -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///./test.db",
        initial_user_username="admin",
        initial_user_password="admin-password",
    )

    assert settings.database_url == "sqlite+aiosqlite:///./test.db"
    assert settings.initial_user_username == "admin"
    assert settings.initial_user_password == "admin-password"


def test_settings_expose_storage_fields(monkeypatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("LOCAL_STORAGE_ROOT", "/tmp/kd-storage")
    monkeypatch.setenv("STORAGE_BUCKET", "kd-test")
    s = Settings()
    assert s.local_storage_root == "/tmp/kd-storage"
    assert s.storage_bucket == "kd-test"
    assert s.max_upload_bytes == 52_428_800


def test_max_upload_bytes_overridable_by_env(monkeypatch) -> None:
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1024")
    assert Settings().max_upload_bytes == 1024
