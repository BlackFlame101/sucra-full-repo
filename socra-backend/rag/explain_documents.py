"""Read-only, authenticated source resolution for the Explain inventory."""
from __future__ import annotations

import asyncio
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

from db.supabase_client import get_supabase
from rag.unit_map import unit_pipeline_enabled

_MAX_CHUNKS = 500
_MAX_DOCUMENTS = 256


@dataclass(frozen=True)
class DocumentSelection:
    document: dict[str, Any] | None
    reason: str
    document_ids: tuple[str, ...] = ()


async def course_documents(course_id: str, owner_id: str, *, versioned: bool = False) -> list[dict]:
    if not course_id or not owner_id:
        raise ValueError("An authenticated course is required to select an Explain document.")

    def read():
        fields = "id,filename,page_count,index_chunk_count,content_hash,index_config,courses!inner(user_id)"
        if unit_pipeline_enabled() or versioned:
            fields += ",index_generation,index_stage"
        if versioned:
            fields += ",course_id,storage_path,file_size"
        response = (get_supabase().table("documents")
                    .select(fields, count="exact")
                    .eq("course_id", course_id).eq("courses.user_id", owner_id)
                    .eq("index_status", "ready").order("id").limit(_MAX_DOCUMENTS).execute())
        if response.count != len(response.data or []):
            raise RuntimeError("Incomplete course document catalog")
        return response.data or []

    return await asyncio.to_thread(read)


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in value if not unicodedata.combining(char))


def requests_whole_document(topic: str) -> bool:
    text = _fold(topic)
    breadth = r"\b(?:entire|whole|complete|full|everything|all pages|tout|integralite|complet|كل|كامل|بالكامل|جميع الصفحات)\b"
    source = r"\b(?:pdfs?|documents?|handout|manual|fichiers?|polycopie|documentos|الملف|ملف|المستند|مستند|الوثيقة)\b"
    return bool(re.search(breadth, text) and re.search(source, text))


def select_document(documents: list[dict], topic: str, chunks: list[dict], explicit_id: str | None, threshold: float) -> DocumentSelection:
    by_id = {str(doc["id"]): doc for doc in documents}
    if explicit_id is not None:
        if explicit_id not in by_id:
            raise ValueError("That PDF is unavailable in this inquiry's course.")
        return DocumentSelection(by_id[explicit_id], "explicit_id", (explicit_id,))

    text = _fold(topic)
    mentions: dict[str, set[str]] = {}
    for document_id, doc in by_id.items():
        filename = _fold(doc.get("filename") or "")
        stem = filename.removesuffix(".pdf")
        exact = filename and re.search(r"(?<![\w.-])" + re.escape(filename) + r"(?![\w-]|\.[\w-])", text)
        quoted = len(stem) >= 3 and re.search(r"[\x22“]" + re.escape(stem) + r"[\x22”]", text)
        if exact or quoted:
            mentions.setdefault(filename, set()).add(document_id)
    # Identical filenames are ambiguous even when one dominates retrieval.
    if any(len(matches) > 1 for matches in mentions.values()):
        raise ValueError("Several PDFs match that name. Specify a unique PDF in this course.")
    named = tuple(sorted(set().union(*mentions.values()))) if mentions else ()
    if len(named) == 1:
        return DocumentSelection(by_id[named[0]], "filename", named)
    if named:
        return DocumentSelection(None, "multiple_named", named)
    if re.search(
        r"\b(?:from|using|explain|analyze|analyse|dans|depuis|explique|fichier)\s+"
        r"(?:(?:the|le|la|this|ce)\s+)?(?:[\x22“][^\x22”]+[.]pdf[\x22”]|[\w.-]+[.]pdf)(?![\w-]|\.[\w-])",
        text,
    ):
        raise ValueError("That PDF is unavailable in this inquiry's course.")
    if len(by_id) == 1:
        document_id, doc = next(iter(by_id.items()))
        return DocumentSelection(doc, "sole_pdf", (document_id,))
    if len(by_id) <= 1:
        return DocumentSelection(None, "no_indexed_documents")
    if re.search(r"\b(?:(?:all|both) (?:the )?(?:pdfs|documents|sources)|across (?:the )?(?:pdfs|documents|sources)"
                 r"|compare (?:these |the )?(?:pdfs|documents|sources)|tous les documents|comparer les documents"
                 r"|جميع المستندات|كل الملفات)\b", text):
        return DocumentSelection(None, "multi_document_request")

    counts = Counter(str(chunk["document_id"]) for chunk in {
        chunk["id"]: chunk for chunk in chunks if chunk.get("id") and str(chunk.get("document_id")) in by_id
    }.values())
    if counts:
        document_id, count = counts.most_common(1)[0]
        if count / counts.total() >= threshold:
            return DocumentSelection(by_id[document_id], "dominant_retrieval", (document_id,))
    raise ValueError("Which PDF should Explain use? Name a file in this course or ask to compare the documents.")


def complete_index(chunks: list[dict], document: dict, expected_count: int | None = None, *,
                   paged: bool = False) -> bool:
    count = expected_count if expected_count is not None else document.get("index_chunk_count")
    pages = document.get("page_count")
    if type(count) is not int or count < 1 or (not paged and count > _MAX_CHUNKS) or len(chunks) != count:
        return False
    if type(pages) is not int or not 1 <= pages <= count:
        return False
    return (all(str(chunk.get("document_id")) == str(document["id"]) and chunk.get("id")
                and isinstance(chunk.get("content"), str) and chunk["content"].strip() for chunk in chunks)
            and len({chunk["id"] for chunk in chunks}) == count
            and {chunk.get("chunk_index") for chunk in chunks} == set(range(count))
            and {chunk.get("page_number") for chunk in chunks} == set(range(1, pages + 1)))


async def document_inventory_chunks(
    course_id: str, owner_id: str, document: dict, retrieved: list[dict],
    *, versioned: bool = False,
) -> tuple[list[dict], str]:
    """Verify a full index snapshot or return only the already retrieved excerpts."""
    if not course_id or not owner_id:
        raise ValueError("An authenticated course is required to read Explain source material.")
    document_id = str(document["id"])
    selected = [chunk for chunk in retrieved if str(chunk.get("document_id")) == document_id]
    if (unit_pipeline_enabled() or versioned) and "index_generation" in document:
        if document.get("index_stage") is not None:
            return selected, "retrieved_only"
        rows = await asyncio.to_thread(_read_paged_index, course_id, owner_id, document)
        return (rows, "full_document") if rows is not None else (selected, "retrieved_only")
    if complete_index(selected, document):
        return selected, "full_document"
    if (document.get("index_chunk_count") or 0) > _MAX_CHUNKS:
        return selected, "retrieved_only"

    def read():
        query = (get_supabase().table("embeddings")
                 .select("id,document_id,content,page_number,chunk_index,documents!inner(courses!inner(user_id))", count="exact")
                 .eq("document_id", document_id).eq("documents.course_id", course_id)
                 .eq("documents.courses.user_id", owner_id).eq("documents.index_status", "ready"))
        for field in ("content_hash", "index_config", "index_chunk_count", "page_count"):
            version = document.get(field)
            query = query.is_("documents." + field, "null") if version is None else query.eq("documents." + field, version)
        response = query.order("page_number").order("chunk_index").order("id").limit(_MAX_CHUNKS).execute()
        rows = response.data or []
        if response.count is None or not complete_index(rows, document, response.count):
            return selected, "retrieved_only"
        if document.get("index_chunk_count") not in (None, response.count):
            return selected, "retrieved_only"
        return [
            {key: value for key, value in row.items() if key != "documents"}
            | {"filename": document.get("filename"), "similarity": 0.0}
            for row in rows
        ], "full_document"

    return await asyncio.to_thread(read)


def _read_paged_index(course_id: str, owner_id: str, document: dict) -> list[dict] | None:
    expected = document.get("index_chunk_count")
    if expected is not None and (type(expected) is not int or expected < 1):
        return None
    client = get_supabase()
    rows = []
    cursor = -1
    while expected is None or len(rows) < expected:
        query = (client.table("embeddings")
                 .select("id,document_id,content,page_number,chunk_index,documents!inner(courses!inner(user_id))",
                         count="exact" if cursor == -1 else None)
                 .eq("document_id", str(document["id"])).eq("documents.course_id", course_id)
                 .eq("documents.courses.user_id", owner_id).eq("documents.index_status", "ready")
                 .is_("documents.index_stage", "null"))
        for field in ("content_hash", "index_config", "index_chunk_count", "page_count", "index_generation"):
            version = document.get(field)
            query = query.is_("documents." + field, "null") if version is None else query.eq("documents." + field, version)
        batch = query.order("chunk_index").order("id").limit(_MAX_CHUNKS)
        if cursor >= 0:
            batch = batch.gt("chunk_index", cursor)
        response = batch.execute()
        if cursor == -1:
            if expected is not None and response.count != expected:
                return None
            expected = response.count
            if type(expected) is not int or expected < 1:
                return None
        batch_rows = response.data or []
        if not batch_rows or any(row.get("chunk_index") != len(rows) + offset
                                 for offset, row in enumerate(batch_rows)):
            return None
        rows.extend(batch_rows)
        cursor = rows[-1]["chunk_index"]
    if not complete_index(rows, document, expected, paged=True):
        return None
    return [{key: value for key, value in row.items() if key != "documents"}
            | {"filename": document.get("filename"), "similarity": 0.0} for row in rows]
