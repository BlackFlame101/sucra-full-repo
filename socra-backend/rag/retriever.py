"""Similarity search against the existing pgvector ``match_embeddings`` RPC.

The function lives in Supabase since Phase 7.5 of the V1 scope and has the
following signature::

    match_embeddings(query_embedding vector, match_count integer, filter_course_id uuid)
        RETURNS TABLE(id uuid, content text, document_id uuid,
                      page_number integer, chunk_index integer,
                      filename text, similarity double precision)
"""
from __future__ import annotations

import asyncio
import logging
from typing import TypedDict

from db.supabase_client import get_supabase
from rag.embeddings import embed_query


logger = logging.getLogger(__name__)


class RetrievedChunk(TypedDict):
    id: str
    content: str
    document_id: str
    page_number: int | None
    chunk_index: int | None
    filename: str | None
    similarity: float


def _call_rpc(
    embedding: list[float], course_id: str, match_count: int
) -> list[RetrievedChunk]:
    res = get_supabase().rpc(
        "match_embeddings",
        {
            "query_embedding": embedding,
            "match_count": match_count,
            "filter_course_id": course_id,
        },
    ).execute()
    return res.data or []


async def retrieve_chunks(
    query: str,
    course_id: str,
    *,
    k: int = 5,
) -> list[RetrievedChunk]:
    """Return the top-``k`` most similar chunks for ``query`` within ``course_id``."""
    if not query.strip():
        return []
    try:
        embedding = await embed_query(query)
    except Exception as exc:
        logger.exception("Embedding failed for query %r: %s", query[:60], exc)
        return []
    try:
        return await asyncio.to_thread(_call_rpc, embedding, course_id, k)
    except Exception as exc:
        logger.exception("match_embeddings RPC failed: %s", exc)
        return []


def format_chunks_for_prompt(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks into a compact, citation-friendly block."""
    if not chunks:
        return "(no relevant excerpts found in the course material)"
    lines: list[str] = []
    for i, c in enumerate(chunks, start=1):
        page = c.get("page_number")
        fname = c.get("filename") or "document"
        cite = f"{fname}, p.{page}" if page is not None else fname
        lines.append(f"[{i}] ({cite})\n{c['content'].strip()}")
    return "\n\n".join(lines)
