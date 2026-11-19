"""Read-only, authenticated source resolution for the Explain inventory."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

from db.supabase_client import get_supabase
from rag.qcm_inventory import QcmInventory, build_qcm_inventory

_MAX_CHUNKS = 500
_MAX_DOCUMENTS = 256
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentSelection:
    document: dict[str, Any] | None
    reason: str
    document_ids: tuple[str, ...] = ()


class ExplainSourceError(ValueError):
    """The selected indexed PDF cannot establish the requested source."""


@dataclass(frozen=True)
class ExplainSources:
    task_source: dict
    reference_sources: tuple[dict, ...]


async def course_documents(course_id: str, owner_id: str) -> list[dict]:
    if not course_id or not owner_id:
        raise ValueError("An authenticated course is required to select an Explain document.")

    def read():
        response = (get_supabase().table("documents")
                    .select("id,filename,course_id,storage_path,file_size,page_count,index_chunk_count,content_hash,index_config,courses!inner(user_id)", count="exact")
                    .eq("course_id", course_id).eq("courses.user_id", owner_id)
                    .eq("index_status", "ready").order("id").limit(_MAX_DOCUMENTS).execute())
        if response.count != len(response.data or []):
            raise RuntimeError("Incomplete course document catalog")
        return response.data or []

    return await asyncio.to_thread(read)


async def load_owned_explain_pages(document: dict, owner_id: str) -> list[str]:
    """Reuse the indexing extractor and verify the bytes against the selected index."""
    from worker import download_document, extract_pages, InvalidDocument

    source_hash = document.get("content_hash")
    index_version = document.get("index_config")
    if not source_hash or not index_version:
        raise ExplainSourceError("La version indexée du PDF est indisponible.")
    try:
        data = await download_document(document, owner_id)
        if hashlib.sha256(data).hexdigest() != source_hash:
            raise ExplainSourceError("Le PDF a changé depuis son indexation.")
        pages = await extract_pages(data)
    except InvalidDocument as exc:
        raise ExplainSourceError("Le texte du PDF source n’a pas pu être vérifié.") from exc
    if len(pages) != document.get("page_count"):
        raise ExplainSourceError("Le nombre de pages diffère de la version indexée.")
    return pages


async def load_explain_course_map(document: dict) -> list[dict]:
    """Read the same current-version section rows as the course context panel."""
    def read():
        return (get_supabase().table("document_summaries")
                .select("document_id,document_version,title,page_start,page_end")
                .eq("course_id", document["course_id"]).eq("document_id", document["id"])
                .eq("document_version", document["content_hash"]).eq("level", "section")
                .order("page_start").order("section_index").execute().data or [])

    try:
        return await asyncio.to_thread(read)
    except Exception as exc:
        logger.info("explain_course_map_unavailable error_type=%s", type(exc).__name__)
        return []


async def load_qcm_inventory(document: dict, owner_id: str, ordinals: tuple[int, ...]) -> QcmInventory:
    pages = await load_owned_explain_pages(document, owner_id)
    return build_qcm_inventory(pages, str(document["id"]), document["content_hash"], document["index_config"], ordinals)


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


def resolve_explain_sources(documents: list[dict], topic: str, explicit_id: str | None) -> ExplainSources:
    text = _fold(topic).replace("’", "'")
    task_text, *reference_text = re.split(
        r"\b(?:en utilisant|en t'appuyant sur|en s'appuyant sur|a l'aide d[eu]|avec (?:le |les )?cours|"
        r"using|based on|references?\s*:)\s*", text, maxsplit=1,
    )
    selected = select_document(documents, "", [], explicit_id, .7).document if explicit_id else None

    def named_in(value):
        found = []
        for doc in documents:
            filename = _fold(doc.get("filename") or "")
            stem = filename.removesuffix(".pdf")
            if filename and (
                re.search(r"(?<![\w.-])" + re.escape(filename) + r"(?![\w-]|\.[\w-])", value)
                or len(stem) >= 3 and re.search(r"[\"“«]\s*" + re.escape(stem) + r"\s*[\"”»]", value)
            ):
                found.append(doc)
        if len({_fold(doc.get("filename") or "") for doc in found}) != len(found):
            raise ExplainSourceError("Plusieurs PDF ont le même nom. Choisissez le document par son identifiant.")
        return found

    tasks = named_in(task_text)
    if len(tasks) > 1 or (not tasks and re.search(r"\.pdf\b", task_text)):
        raise ExplainSourceError("Identifiez un seul PDF de travail indexé.")
    no_refs = bool(re.search(r"\b(?:sans (?:utiliser |consulter )?(?:d'autres |les )?(?:references?|autres pdf)|without (?:any )?references?)\b", text))
    refs = [] if no_refs or not reference_text else named_in(reference_text[0])
    if reference_text and re.search(r"\.pdf\b", reference_text[0]) and not refs and not no_refs:
        raise ExplainSourceError("Le PDF de référence demandé est indisponible dans ce cours.")
    reference_ids = {str(doc["id"]) for doc in refs}
    if not tasks and not selected:
        candidates = [doc for doc in documents if str(doc["id"]) not in reference_ids]
        if len(candidates) != 1:
            raise ExplainSourceError("Sélectionnez un seul PDF indexé ou indiquez son nom exact.")
        selected = candidates[0]
    task = tasks[0] if tasks else selected
    task_id = str(task["id"])
    if task_id in reference_ids:
        raise ExplainSourceError("Choisissez des PDF de travail et de référence distincts.")
    return ExplainSources(task, tuple(doc for doc in (() if no_refs else refs or documents) if str(doc["id"]) != task_id))


async def load_reference_chunks(course_id: str, owner_id: str, documents: tuple[dict, ...]) -> list[dict]:
    references = []
    for document in documents:
        try:
            chunks, scope = await document_inventory_chunks(course_id, owner_id, document, [])
        except Exception as exc:
            logger.info("explain_reference_unavailable error_type=%s", type(exc).__name__)
            continue
        if scope == "full_document":
            references.extend({**row, "filename": document["filename"]} for row in chunks)
    return references


def rank_reference_chunks(text: str, chunks: list[dict], limit: int = 6, *, prefer_content: bool = False) -> list[dict]:
    def terms(value):
        folded = _fold(value)
        words = set(re.findall(r"[^\W_]{4,}", folded)) - {
            "avec", "dans", "cette", "choix", "comme", "cours", "faire", "leur", "leurs", "mais",
            "nous", "pour", "quand", "quelle", "quelles", "sont", "tout", "tous", "which", "with",
        }
        if prefer_content:
            words -= {
                "spark", "mllib", "sbihi", "processus", "decisionnel", "etape", "exercice", "analyser",
                "pourquoi", "comment", "utiliser", "generer", "realiser", "faire", "plutot", "suivant",
                "resultats", "choisir", "permet", "doit", "faut",
            }
            words.update(re.findall(r"\b(?:sql|auc|f1|csv|rdd|api)\b", folded))
        return words
    wanted = terms(text)
    heading_terms = terms(text.lstrip().split("\n", 1)[0]) if prefer_content else set()
    if not wanted:
        return []
    matches = []
    for chunk in chunks:
        content = chunk["content"].strip()
        title = content.split("\n", 1)[0]
        shared = terms(content) & wanted
        title_matches = terms(title) & wanted
        front_matter = bool(re.match(r"^(?:plan du cours|table des matieres|sommaire|objectifs|course outline)\b", _fold(title)))
        opening_page = 1 <= chunk["page_number"] <= 3
        if prefer_content and (front_matter or opening_page) and len(title_matches & heading_terms) < 3:
            continue
        if shared and (not prefer_content or len(shared) >= 2):
            matches.append((chunk, shared, title_matches))
    frequencies = Counter(term for _, shared, _ in matches for term in shared)
    matches.sort(key=lambda item: -(sum(1 / frequencies[term] for term in item[1])
                                    + (sum(1 / frequencies[term] for term in item[2]) if prefer_content else 0)
                                    + sum(2 / frequencies[term] for term in item[1] & heading_terms)))
    by_page = {}
    for chunk, _, _ in matches:
        if len(by_page) == limit:
            break
        by_page.setdefault((chunk["document_id"], chunk["page_number"]), chunk)
    return list(by_page.values())


def complete_index(chunks: list[dict], document: dict, expected_count: int | None = None) -> bool:
    count = expected_count if expected_count is not None else document.get("index_chunk_count")
    pages = document.get("page_count")
    if type(count) is not int or not 1 <= count <= _MAX_CHUNKS or len(chunks) != count:
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
) -> tuple[list[dict], str]:
    """Verify a full index snapshot or return only the already retrieved excerpts."""
    if not course_id or not owner_id:
        raise ValueError("An authenticated course is required to read Explain source material.")
    document_id = str(document["id"])
    selected = [chunk for chunk in retrieved if str(chunk.get("document_id")) == document_id]
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
