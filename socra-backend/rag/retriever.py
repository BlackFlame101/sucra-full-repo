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


def current_version_summaries(summaries: list[dict], documents: list[dict]) -> list[dict]:
    """Discard summaries whose source PDF has since changed."""
    versions = {str(doc["id"]): doc.get("content_hash") for doc in documents}
    return [summary for summary in summaries
            if summary.get("level") == "section"
            and versions.get(str(summary.get("document_id"))) == summary.get("document_version")]


def constrain_chunks_to_sections(chunks: list[RetrievedChunk], sections: list[dict]) -> list[RetrievedChunk]:
    """Keep only detailed chunks inside selected section ranges."""
    return [chunk for chunk in chunks if any(
        str(chunk.get("document_id")) == str(section.get("document_id"))
        and int(section.get("page_start", 0)) <= int(chunk.get("page_number") or 0) <= int(section.get("page_end", 0))
        for section in sections
    )]


async def get_current_course_sections(course_id: str) -> list[dict]:
    """Return current-version section summaries for broad course-wide planning."""
    try:
        client = get_supabase()
        summaries, documents = await asyncio.gather(
            asyncio.to_thread(lambda: client.table("document_summaries")
                .select("document_id,document_version,level,title,summary,page_start,page_end")
                .eq("course_id", course_id).eq("level", "section").limit(200).execute().data or []),
            asyncio.to_thread(lambda: client.table("documents")
                .select("id,content_hash").eq("course_id", course_id).execute().data or []),
        )
        return current_version_summaries(summaries, documents)
    except Exception as exc:
        logger.info("Course section summaries unavailable; using broad vector retrieval: %s", exc)
        return []


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


def _load_course_code_candidates(course_id: str, limit: int) -> list[RetrievedChunk]:
    """Read page chunks for this course so code search isn't limited by semantic ranking.

    Code examples in PDF text extraction are often flattened into one line and
    score poorly for natural-language vector queries. The course's document IDs
    provide a strict boundary; the caller still filters these rows to pages that
    contain recognizable source code before exposing them to the model.
    """
    client = get_supabase()
    documents = client.table("documents").select("id,filename").eq(
        "course_id", course_id
    ).execute().data or []
    document_names = {str(row["id"]): row.get("filename") for row in documents}
    document_ids = list(document_names)
    if not document_ids:
        return []

    rows = client.table("embeddings").select(
        "id,content,document_id,page_number,chunk_index"
    ).in_("document_id", document_ids).order("page_number").limit(limit).execute().data or []
    return [
        {
            **row,
            "document_id": str(row["document_id"]),
            "filename": document_names.get(str(row["document_id"])),
            "similarity": 0.0,
        }
        for row in rows
    ]


async def retrieve_course_code_candidates(
    course_id: str, *, limit: int = 1000
) -> list[RetrievedChunk]:
    """Fetch bounded page-level candidates for code-aware filtering."""
    try:
        return await asyncio.to_thread(_load_course_code_candidates, course_id, limit)
    except Exception as exc:
        logger.info("Course-wide code candidate search unavailable: %s", exc)
        return []


async def retrieve_summary_guided_chunks(
    query: str, course_id: str, *, k: int = 10
) -> list[RetrievedChunk]:
    """Use current-version section summaries to select source documents/pages.

    Summary lookup is deliberately best-effort: older deployments or missing
    summaries fall back to normal vector search. Returned content is always a
    real page-level embedding, never generated summary text.
    """
    if not query.strip():
        return []
    try:
        current = await get_current_course_sections(course_id)
        if current:
            query_terms = {w.casefold() for w in query.split() if len(w) > 2}
            ranked = sorted(current, key=lambda s: sum(
                term in f"{s.get('title', '')} {s.get('summary', '')}".casefold()
                for term in query_terms
            ), reverse=True)
            relevant = [s for s in ranked if any(
                term in f"{s.get('title', '')} {s.get('summary', '')}".casefold()
                for term in query_terms
            )][:8]
            if relevant:
                embedding = await embed_query(query)
                chunks = await asyncio.to_thread(_call_rpc, embedding, course_id, min(60, k * 6))
                selected = constrain_chunks_to_sections(chunks, relevant)
                if selected:
                    return selected[:k]
    except Exception as exc:
        logger.info("Summary-guided retrieval unavailable; using chunk search: %s", exc)
    return await retrieve_chunks(query, course_id, k=k)


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
