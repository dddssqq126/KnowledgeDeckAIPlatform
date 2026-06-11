from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "KnowledgeDeck"
    environment: str = "local"
    api_prefix: str = "/api"

    database_url: str = "sqlite+aiosqlite:///./knowledgedeck.db"

    initial_user_username: str = ""
    initial_user_password: str = ""

    # Comma-separated list of allowed CORS origins (e.g.
    # "http://localhost:3000,http://192.168.1.102:3000"). Empty = no CORS
    # middleware attached. Used by the browser when the frontend host
    # differs from the backend host (cross-origin requests).
    cors_origins: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    storage_bucket: str = "knowledgedeck"
    local_storage_root: str = "/var/lib/knowledgedeck-storage"

    # 50 MiB hard cap on a single file upload.
    max_upload_bytes: int = 52_428_800

    llm_base_url: str = "http://knowledgedeck_vllm_chat:8000/v1"
    llm_api_key: str = "local-dev-key"
    llm_model: str = "google/gemma-4-E4B-it"
    # Display name shown in the UI header. Decoupled from llm_model so the
    # internal model id (sent to vLLM) and the user-facing label can change
    # independently.
    llm_model_label: str = "Gemma 4 E4B"
    # Keep answer generation focused on the latest turn. Older turns still
    # exist in DB, but only this many recent messages are sent to the LLM.
    chat_answer_history_messages: int = 6
    # GPT-OSS 120B supports a large context window, but pasted files/code can
    # still produce 500K+ character prompts. Cap only the answer-generation
    # prompt inputs; short strings pass through unchanged.
    chat_answer_history_message_max_chars: int = 4_000
    chat_answer_user_message_max_chars: int = 20_000
    chat_answer_context_max_chars: int = 60_000
    chat_answer_metadata_max_chars: int = 4_000
    # Query rewrite only needs enough history to resolve short follow-ups.
    chat_rewrite_history_messages: int = 4
    chat_rewrite_history_chars: int = 180
    chat_rewrite_user_message_chars: int = 4_000

    embedding_base_url: str = "http://knowledgedeck_vllm_embedding:8001/v1"
    embedding_api_key: str = "local-dev-key"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024  # BAAI/bge-m3 outputs 1024-dim vectors
    # Batch large document embedding requests so one huge file does not create
    # a single long-running HTTP call that is likely to time out.
    embedding_batch_size: int = 32
    # Also cap the total characters per embedding request. This is a *batch*
    # budget for document ingestion: up to embedding_batch_size already-split
    # chunks can be sent together, and ingestion bisects the batch if a
    # provider still rejects/times out.
    embedding_batch_max_chars: int = 24_000
    # Chat/RAG retrieval embeds the user's query as one input item. Pasted code
    # can exceed bge-m3/vLLM's 8K-token item context, so cap only that single
    # query string before calling /embeddings. Short queries return unchanged.
    embedding_query_max_chars: int = 6_000

    # Local disk mode (no Qdrant server process): set qdrant_path and leave
    # qdrant_url empty. If qdrant_path is empty, url mode is used.
    qdrant_url: str = ""
    qdrant_path: str = "./qdrant_data"
    qdrant_collection: str = "knowledgedeck"
    # Cap each Qdrant upsert request so large files do not exceed
    # HTTP/JSON payload limits.
    qdrant_upsert_batch_size: int = 64

    # RAG retrieval knobs.
    # rag_dense_top_k: how many candidates Qdrant returns before rerank.
    # rag_final_top_k: how many chunks survive after rerank → into prompt.
    # rag_min_score: cosine threshold below which dense hits are dropped
    #   (post-rerank rerank score is also thresholded by rag_rerank_min_score).
    # rag_rerank_min_score: cross-encoder score threshold; below this the
    #   rerank result is treated as "no relevant context".
    rag_dense_top_k: int = 20
    # Retrieve a wider candidate set before reranking so the cross-encoder can
    # recover relevant chunks that were not at the very top of vector fusion.
    rag_rerank_candidate_k: int = 40
    rag_hybrid_prefetch_limit: int = 80
    rag_final_top_k: int = 7
    # Limit repeated chunks from one file so final context covers more likely
    # documents instead of filling the prompt with near-duplicates.
    rag_per_file_context_limit: int = 3
    # Soft boost per matching query metadata tag (vendor/platform/knowledge_type).
    # This improves ranking without hard-filtering away potentially useful hits.
    rag_tag_match_boost: float = 0.05
    rag_min_score: float = 0.30
    rag_rerank_min_score: float = 0.10
    # BAAI/bge-reranker-base is a 512-token cross-encoder. These are
    # character budgets (not token budgets) that keep each (query, passage)
    # pair safely below that small window while preserving one /score call for
    # the normal 40-candidate rerank set. Longer chunks are trimmed only for
    # rerank scoring; final answer context still uses the selected chunk text.
    rag_rerank_query_max_chars: int = 256
    rag_rerank_passage_max_chars: int = 1_000
    rag_rerank_batch_max_chars: int = 64_000
    # Deep retrieval's coverage judge is also an LLM call; bound its prompt so
    # pasted code or oversized selected chunks cannot exceed chat model context.
    rag_coverage_user_message_max_chars: int = 8_000
    rag_coverage_query_max_chars: int = 4_000
    rag_coverage_context_max_chars: int = 60_000

    # Reranker (cross-encoder) — separate vLLM service running in score mode.
    rerank_base_url: str = "http://knowledgedeck_vllm_rerank:8000/v1"
    rerank_api_key: str = "local-dev-key"
    rerank_model: str = "BAAI/bge-reranker-base"

    # Presenton (PPTX rendering) — runs as a separate compose service. The
    # shared volume mounted at presenton_data_root lets backend read PPTX
    # files Presenton wrote without proxying via HTTP.
    presenton_url: str = "http://knowledgedeck_presenton:80"
    presenton_username: str = "admin"
    presenton_password: str = "change-me-please"
    presenton_data_root: str = "/presenton_data"

    # Chunking knobs (character-based, simple). Bigger overlap reduces
    # mid-sentence cuts at the cost of more vectors per file.
    chunk_chars: int = 1200
    chunk_overlap: int = 150

    # LLM document tagging (see docs/superpowers/specs/2026-05-27-tag-aware-rag-design.md).
    # When enabled, ingestion makes one LLM call per document to produce
    # topic/doc_type/intent tags and folds them into the embedded text.
    rag_tagging_enabled: bool = True
    rag_tag_max_chars: int = 4000  # head of the doc sent to the tagger LLM

    gpu_device: str = "0"
    vllm_chat_gpu_memory_utilization: float = 0.70
    vllm_chat_max_model_len: int = 16384
    vllm_embedding_gpu_memory_utilization: float = 0.22
    vllm_embedding_max_model_len: int = 8192


@lru_cache
def get_settings() -> Settings:
    return Settings()
