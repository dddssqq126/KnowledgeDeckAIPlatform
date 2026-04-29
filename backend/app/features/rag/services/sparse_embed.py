"""Dependency-light BM25-style sparse embeddings.

Why this exists:
- `fastembed` can be difficult to install in some environments.
- We still want hybrid retrieval (dense + sparse) for keyword recall.

Implementation:
- Tokenize text into lowercase word-like terms.
- Map each token to a stable hashed index.
- Use BM25 TF saturation as sparse values for passages.
- Let Qdrant apply collection-level IDF (`modifier=IDF`) at query time.

This keeps install friction low (no extra third-party runtime dependency)
while preserving a useful lexical channel for Qdrant hybrid search.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Sequence
from collections import Counter
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
# Large fixed hashing space; deterministic across processes.
_SPARSE_DIM = 1 << 20
_K1 = 1.5
_B = 0.75
# Fallback average chunk length in tokens. This keeps BM25 TF saturation
# useful without requiring a persisted corpus-stat table.
_AVGDL = 180.0


@dataclass(frozen=True)
class SparseVec:
    indices: list[int]
    values: list[float]


def _stable_hash_index(token: str) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=False) % _SPARSE_DIM


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _bm25_tf_weight(*, tf: int, dl: int, avgdl: float = _AVGDL) -> float:
    denom = tf + _K1 * (1.0 - _B + _B * (dl / max(avgdl, 1.0)))
    return ((tf * (_K1 + 1.0)) / denom) if denom > 0 else 0.0


def _embed_passage_one(text: str) -> SparseVec:
    tokens = _tokenize(text)
    if not tokens:
        return SparseVec(indices=[], values=[])
    counts = Counter(tokens)
    dl = len(tokens)
    by_index: dict[int, float] = {}
    for token, tf in counts.items():
        idx = _stable_hash_index(token)
        weight = _bm25_tf_weight(tf=tf, dl=dl)
        by_index[idx] = by_index.get(idx, 0.0) + weight
    items = sorted(by_index.items(), key=lambda x: x[0])
    return SparseVec(indices=[i for i, _ in items], values=[v for _, v in items])


def _embed_query_one(text: str) -> SparseVec:
    tokens = _tokenize(text)
    if not tokens:
        return SparseVec(indices=[], values=[])
    counts = Counter(tokens)
    by_index: dict[int, float] = {}
    for token, tf in counts.items():
        idx = _stable_hash_index(token)
        # Query-side BM25 typically has light tf influence; this keeps
        # repeated query terms from exploding.
        by_index[idx] = by_index.get(idx, 0.0) + (1.0 + 0.5 * float(tf - 1))
    items = sorted(by_index.items(), key=lambda x: x[0])
    return SparseVec(indices=[i for i, _ in items], values=[v for _, v in items])


async def embed_passages(texts: Sequence[str]) -> list[SparseVec]:
    """Used at ingestion time. Pass the exact chunk text we'll store."""
    if not texts:
        return []

    return await asyncio.to_thread(lambda: [_embed_passage_one(t) for t in texts])


async def embed_query(text: str) -> SparseVec:
    """Used at retrieval time. Uses the same hashing vocabulary."""
    return await asyncio.to_thread(lambda: _embed_query_one(text))
