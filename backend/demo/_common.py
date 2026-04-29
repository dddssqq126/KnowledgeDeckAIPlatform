"""Shared demo configuration + cleanup helper.

Only configuration + a single cleanup helper live here. RAG / chat /
slide algorithms are intentionally NOT abstracted out — each demo
script repeats them inline so a reader can understand the full
pipeline by reading one file top-to-bottom.

Mirrors production env defaults from backend/app/core/config.py and
the docker-compose service hostnames. Override via environment
variables when running the demo outside the compose network.
"""
from __future__ import annotations

import os

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

# Demo identity. Production rows live under real user/KB ids; these
# constants give the demo a parallel namespace inside the same Qdrant
# collection without colliding with real data.
DEMO_USER_ID = 999
DEMO_KB_ID = 999

# --- Service endpoints ---------------------------------------------------
# Defaults match docker-compose service hostnames so
# `docker exec -it knowledgedeck_backend python demo/01_kb_ingest.py ...`
# Just Works. Override via env vars when running outside compose.

QDRANT_URL = os.getenv("QDRANT_URL", "http://knowledgedeck_qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "knowledgedeck")

EMBED_URL = os.getenv("EMBEDDING_BASE_URL", "http://knowledgedeck_vllm_embedding:8000/v1")
EMBED_API_KEY = os.getenv("EMBEDDING_API_KEY", "local-dev-key")
EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
EMBED_DIM = 1024  # BAAI/bge-m3 output dimensionality

LLM_URL = os.getenv("LLM_BASE_URL", "http://knowledgedeck_vllm_chat:8000/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "local-dev-key")
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemma-4-E4B-it")

RERANK_URL = os.getenv("RERANK_BASE_URL", "http://knowledgedeck_vllm_rerank:8000/v1")
RERANK_API_KEY = os.getenv("RERANK_API_KEY", "local-dev-key")
RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

PRESENTON_URL = os.getenv("PRESENTON_URL", "http://knowledgedeck_presenton:80")
PRESENTON_USERNAME = os.getenv("PRESENTON_USERNAME", "admin")
PRESENTON_PASSWORD = os.getenv("PRESENTON_PASSWORD", "change-me-please")
PRESENTON_DATA_ROOT = os.getenv("PRESENTON_DATA_ROOT", "/presenton_data")

# Named-vector schema constants — must match production qdrant_store.py.
DENSE_VEC = "dense"
SPARSE_VEC = "sparse"


def cleanup_demo_vectors() -> int:
    """Wipe every Qdrant point owned by DEMO_USER_ID. Returns the count
    of points deleted. Run between demo iterations to start fresh."""
    client = QdrantClient(url=QDRANT_URL)
    if not client.collection_exists(QDRANT_COLLECTION):
        return 0
    flt = qm.Filter(
        must=[qm.FieldCondition(key="user_id", match=qm.MatchValue(value=DEMO_USER_ID))]
    )
    # Cheap probe so we can report a count — qdrant-client's delete()
    # response is opaque about how many points actually went away.
    points, _ = client.scroll(
        collection_name=QDRANT_COLLECTION, scroll_filter=flt, limit=10000
    )
    n = len(points)
    if n:
        client.delete(
            collection_name=QDRANT_COLLECTION,
            points_selector=qm.FilterSelector(filter=flt),
        )
    return n
