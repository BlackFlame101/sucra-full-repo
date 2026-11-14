"""Embed text with Gemini ``gemini-embedding-001``.

The DB stores 768-dim vectors (created originally with the now-retired
``text-embedding-004``). We use Matryoshka truncation to produce 768-dim
vectors with the current GA model so cosine similarity stays meaningful
once the existing chunks are re-embedded with the same model.
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from math import isfinite
from time import monotonic

from google import genai
from google.genai import types

from config import get_settings


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    settings = get_settings()
    return genai.Client(api_key=settings.gemini_api_key)


def _embed_sync(text: str, *, task_type: str) -> list[float]:
    settings = get_settings()
    client = _client()
    res = client.models.embed_content(
        model=settings.embedding_model,
        contents=text,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=settings.embedding_dim,
        ),
    )
    if not res.embeddings:
        raise RuntimeError("Gemini returned no embeddings")
    values = res.embeddings[0].values
    if not values or len(values) != settings.embedding_dim or not all(isfinite(value) for value in values):
        raise ValueError("Embedding provider returned an invalid vector")
    return list(values)


async def embed_query(text: str) -> list[float]:
    """Embed a search query (asymmetric task type for retrieval)."""
    if not text.strip():
        raise ValueError("Cannot embed empty text")
    return await asyncio.to_thread(_embed_sync, text, task_type="RETRIEVAL_QUERY")


async def embed_document(text: str) -> list[float]:
    """Embed a chunk of a course document (kept for parity / re-embed scripts)."""
    if not text.strip():
        raise ValueError("Cannot embed empty text")
    return await asyncio.to_thread(_embed_sync, text, task_type="RETRIEVAL_DOCUMENT")


async def embed_documents(texts: list[str], *, api_key=None, on_batch=None, job_id=None) -> list[list[float]]:
    settings = get_settings()
    vectors: list[list[float]] = []
    client = genai.Client(
        api_key=api_key or settings.gemini_api_key,
        http_options=types.HttpOptions(timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1)),
    ).aio
    try:
        for start in range(0, len(texts), 32):
            batch = texts[start:start + 32]
            started = monotonic()
            response = await client.models.embed_content(
                model=settings.embedding_model, contents=batch,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT", output_dimensionality=settings.embedding_dim,
                ),
            )
            rows = [list(embedding.values or []) for embedding in response.embeddings or []]
            if len(rows) != len(batch) or any(
                len(row) != settings.embedding_dim or not all(isfinite(value) for value in row) for row in rows
            ):
                raise ValueError("Embedding provider returned an incomplete batch")
            vectors.extend(rows)
            logger.info("pdf_embedding_batch job_id=%s batch=%d count=%d duration_ms=%d provider_status=ok",
                        job_id, start // 32 + 1, len(batch), (monotonic() - started) * 1000)
            if on_batch:
                await on_batch(len(vectors), len(texts))
    finally:
        await client.aclose()
    return vectors
