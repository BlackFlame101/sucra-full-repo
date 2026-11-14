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
import re
from contextlib import asynccontextmanager
from contextvars import ContextVar
from time import monotonic
from typing import TypedDict

from db.supabase_client import get_supabase
from rag.embeddings import embed_query


logger = logging.getLogger(__name__)
request_id: ContextVar[str | None] = ContextVar("retrieval_request_id", default=None)


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
        return await _cached(("sections", course_id), lambda: asyncio.to_thread(
            lambda: get_supabase().rpc("current_course_sections", {"course": course_id}).execute().data or [],
        ))
    except Exception as exc:
        logger.info("Course section summaries unavailable; using broad vector retrieval error_type=%s", type(exc).__name__)
        return []


class RetrievedChunk(TypedDict):
    id: str
    content: str
    document_id: str
    page_number: int | None
    chunk_index: int | None
    filename: str | None
    similarity: float


_search_cache: ContextVar[dict | None] = ContextVar("search_cache", default=None)


@asynccontextmanager
async def retrieval_scope():
    cache: dict = {}
    token = _search_cache.set(cache)
    try:
        yield
    finally:
        pending = [task for task in cache.values() if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        _search_cache.reset(token)


async def _cached(key, factory):
    cache = _search_cache.get()
    if cache is None:
        return await factory()
    task = cache.get(key)
    if task is None:
        # A request/short exam may contain multiple distinct candidate queries.
        if len(cache) >= 64:
            return await factory()
        task = cache[key] = asyncio.create_task(factory())
    try:
        return await asyncio.shield(task)
    except Exception:
        if cache.get(key) is task:
            cache.pop(key)
        raise


async def _query_vector(query: str) -> list[float]:
    return await _cached(("query", query), lambda: embed_query(query))


def _term_query(query: str) -> str:
    common = {"about", "could", "would", "please", "explain", "course", "question", "create",
              "dans", "pour", "avec", "cette", "comment", "explique", "cest", "quelle"}
    tokens = dict.fromkeys(token for token in re.findall(r"[^\W\d_][\w-]{2,}", query.casefold())
                           if token not in common and len(token) <= 40)
    return " OR ".join(list(tokens)[:10])


def _match_terms(course_id: str, terms: str, count: int) -> list[RetrievedChunk]:
    return get_supabase().rpc("match_course_terms", {
        "course": course_id, "search_text": terms, "match_count": count,
    }).execute().data or []


def fuse_rankings(vector: list[RetrievedChunk], lexical: list[RetrievedChunk], k: int) -> list[RetrievedChunk]:
    """Blend ranks while keeping original vector similarity for semantic matches."""
    rows: dict[str, RetrievedChunk] = {}
    scores: dict[str, float] = {}
    for weight, candidates in ((1.0, vector), (0.75, lexical)):
        for rank, item in enumerate(candidates, start=1):
            key = item["id"]
            rows.setdefault(key, item)
            scores[key] = scores.get(key, 0.0) + weight / (20 + rank)
    return [rows[key] for key in sorted(rows, key=lambda key: -scores[key])[:k]]


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


async def retrieve_chunks(query: str, course_id: str, *, k: int = 5, hybrid: bool = False) -> list[RetrievedChunk]:
    """Return course-scoped chunks with optional full-text rank fusion."""
    query = query.strip()
    if not query:
        return []
    started = monotonic()
    terms = _term_query(query) if hybrid else ""
    limit = min(60, max(k, 12)) if terms else k

    async def semantic():
        try:
            vector = await _query_vector(query)
            return await _cached(("semantic", course_id, query, limit),
                                 lambda: asyncio.to_thread(_call_rpc, vector, course_id, limit))
        except Exception as exc:
            logger.warning("vector_search_failed error_type=%s", type(exc).__name__)
            return []

    async def lexical():
        try:
            return await _cached(("lexical", course_id, terms, limit),
                                 lambda: asyncio.to_thread(_match_terms, course_id, terms, limit))
        except Exception as exc:
            logger.warning("lexical_search_failed error_type=%s", type(exc).__name__)
            return []

    if terms:
        semantic_rows, lexical_rows = await asyncio.gather(semantic(), lexical())
        rows = fuse_rankings(semantic_rows, lexical_rows, k)
    else:
        rows = await semantic()
    logger.info("retrieval_timing request_id=%s duration_ms=%d chunks=%d mode=%s",
                request_id.get(), (monotonic() - started) * 1000, len(rows), "hybrid" if terms else "semantic")
    return rows


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
    ).eq("index_status", "ready").execute().data or []
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
        return await _cached(("code_candidates", course_id, limit),
                             lambda: asyncio.to_thread(_load_course_code_candidates, course_id, limit))
    except Exception as exc:
        logger.info("Course-wide code candidate search unavailable error_type=%s", type(exc).__name__)
        return []


async def retrieve_summary_guided_chunks(
    query: str, course_id: str, *, k: int = 10
) -> list[RetrievedChunk]:
    """Use current-version section summaries to select source documents/pages.

    Summary lookup is deliberately best-effort: older deployments or missing
    summaries fall back to normal vector search. Returned content is always a
    real page-level embedding, never generated summary text.
    """
    query = query.strip()
    if not query:
        return []
    started = monotonic()
    rows, sections = await asyncio.gather(
        retrieve_chunks(query, course_id, k=min(60, max(24, k * 3)), hybrid=True),
        get_current_course_sections(course_id),
    )
    terms = {term.casefold() for term in _term_query(query).split(" OR ") if term}
    ranked = []
    for section in sections:
        section_terms = set(re.findall(r"[^\W_]{3,}", f"{section.get('title', '')} {section.get('summary', '')}".casefold()))
        score = len(terms & section_terms)
        if score:
            ranked.append((score, section))
    ranked.sort(key=lambda item: -item[0])
    selected = constrain_chunks_to_sections(rows, [section for _, section in ranked[:8]])
    # Keep ordinary retrieval candidates when the Course Map covers only part of the query.
    selected_ids = {row["id"] for row in selected}
    result = selected + [row for row in rows if row["id"] not in selected_ids]
    logger.info("retrieval_timing request_id=%s duration_ms=%d chunks=%d mode=summary_guided",
                request_id.get(), (monotonic() - started) * 1000, min(k, len(result)))
    return result[:k]


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
