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
    if values is None:
        raise RuntimeError("Gemini returned an embedding with no values")
    if len(values) != settings.embedding_dim:
        logger.warning(
            "Unexpected embedding dim %d (expected %d)",
            len(values),
            settings.embedding_dim,
        )
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
