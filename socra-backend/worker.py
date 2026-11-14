"""Run durable PDF and exam processing separately from Uvicorn: uv run python -m worker."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from shutil import which
from time import monotonic

from agents.course_summarizer import summarize_document
from agents.llm import provider_error_code
from config import get_settings
from db.job_credentials import decrypt_key
from db.jobs import claim_job, job_rpc
from db.supabase_client import get_supabase
from rag.embeddings import embed_documents
from rag.ocr import OcrInputError, SCANNED_MESSAGE, recognize_pages

logger = logging.getLogger("socra.worker")
PDF_EXTRACTOR = Path(__file__).resolve().parent.parent / "socra" / "scripts" / "extract-pdf.mjs"
MAX_BYTES = 50 * 1024 * 1024
CHUNK_CONFIG = "unpdf-1.6.0:lines-v1:3200-320-v1:retrieval-document"


def index_config() -> str:
    settings = get_settings()
    return f"{settings.embedding_model}:{settings.embedding_dim}:{CHUNK_CONFIG}"


class InvalidDocument(ValueError):
    pass


class Superseded(Exception):
    pass


async def download_document(document: dict, owner: str) -> bytes:
    path = document["storage_path"]
    if not path.startswith(f"{owner}/{document['course_id']}/"):
        raise InvalidDocument("The PDF storage path does not belong to this course.")
    data = await asyncio.to_thread(lambda: get_supabase().storage.from_("documents").download(path))
    if document.get("file_size") is not None and len(data) != document["file_size"]:
        raise InvalidDocument("Storage returned a different PDF size. Upload the file again.")
    if not 0 < len(data) <= MAX_BYTES:
        raise InvalidDocument("The PDF is empty or exceeds the file size limit.")
    if b"%PDF-" not in data[:1024]:
        raise InvalidDocument("The stored file has no PDF header.")
    return data


async def extract_pages(data: bytes, *, allow_scanned: bool = False) -> list[str]:
    def extract() -> list[str]:
        result = subprocess.run(
            [os.environ.get("SOCRA_NODE_BIN", "node"), "--max-old-space-size=384", str(PDF_EXTRACTOR)],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=45, check=False,
        )
        if result.returncode == 2:
            raise InvalidDocument("This PDF could not be read. Check that it opens and has no password.")
        if result.returncode == 3:
            raise InvalidDocument("This PDF exceeds the 300-page or extracted-text limit. Split it into smaller files.")
        if result.returncode:
            raise RuntimeError("The PDF extractor could not start.")
        return json.loads(result.stdout)

    pages = await asyncio.to_thread(extract)
    if not allow_scanned and not any(page.strip() for page in pages):
        raise InvalidDocument(f"{SCANNED_MESSAGE} The PDF has no searchable text.")
    return pages


def chunk_pages(pages: list[str]) -> list[dict]:
    rows = []
    for page_number, page in enumerate(pages, 1):
        text = re.sub(r"\n{3,}", "\n\n", page).strip()
        start = 0
        while start < len(text):
            end = min(start + 3_200, len(text))
            if end < len(text):
                boundary = max(text.rfind("\n", start + 2_000, end), text.rfind(" ", start + 2_000, end))
                if boundary > start:
                    end = boundary
            content = text[start:end].strip()
            if content:
                rows.append({"content": content, "page_number": page_number, "chunk_index": len(rows)})
            if end == len(text):
                break
            start = end - 320
    return rows


async def require_lease(job: dict, name: str, **fields) -> None:
    if not await job_rpc(job, name, **fields):
        raise Superseded


def timing(job: dict, stage: str, start: float, **counts) -> None:
    logger.info("pdf_timing job_id=%s document_id=%s kind=%s stage=%s attempt=%d duration_ms=%d%s",
                job["id"], job["document_id"], job["kind"], stage, job["attempts"], (monotonic() - start) * 1000,
                "".join(f" {key}={value}" for key, value in counts.items()))


async def document_job(job: dict) -> None:
    started = monotonic()
    rows = await asyncio.to_thread(lambda: get_supabase().table("documents").select(
        "id,course_id,storage_path,file_size,index_generation,courses!inner(user_id)",
    ).eq("id", job["document_id"]).eq("index_generation", job["generation"]).limit(1).execute().data)
    if not rows:
        raise Superseded
    doc = rows[0]
    try:
        key = decrypt_key(job["encrypted_key"], str(doc["id"]))
    except ValueError as exc:
        raise InvalidDocument(str(exc)) from None
    pages = job["pages"]
    digest = job["content_hash"]
    if pages is None:
        await require_lease(job, "update_pdf_stage", state="extracting", label="Reading PDF")
        stage = monotonic()
        data = await download_document(doc, str(doc["courses"]["user_id"]))
        timing(job, "download", stage, bytes=len(data))
        actual_digest = hashlib.sha256(data).hexdigest()
        if digest and digest != actual_digest:
            raise InvalidDocument("The stored PDF changed. Upload it as a new document.")
        digest = actual_digest
        stage = monotonic()
        if job.get("use_ocr"):
            pages = await extract_pages(data, allow_scanned=True)
            await require_lease(job, "update_pdf_stage", state="extracting", label="Recognizing text on scanned pages")
            try:
                pages = await asyncio.to_thread(recognize_pages, data, pages)
            except OcrInputError as exc:
                raise InvalidDocument(str(exc)) from None
            except subprocess.CalledProcessError:
                raise InvalidDocument("OCR could not read the scan. Check that the worker has the required language files and retry.") from None
        else:
            pages = await extract_pages(data)
        timing(job, "parse", stage, pages=len(pages))

    if job["kind"] == "index":
        await require_lease(job, "publish_pdf_pages", digest=digest, source_pages=pages)
        config_key = index_config()
        if job.get("use_ocr"):
            config_key += ":ocr-tesseract-v1:" + os.getenv("SOCRA_OCR_LANGUAGES", "eng+fra")
        if await job_rpc(job, "reuse_pdf_index", digest=digest, page_total=len(pages), config_key=config_key):
            timing(job, "index_reused", started, pages=len(pages))
            return
        stage = monotonic()
        chunks = chunk_pages(pages)
        texts = list(dict.fromkeys(row["content"] for row in chunks))
        timing(job, "chunk", stage, chunks=len(chunks), unique_passages=len(texts))
        await require_lease(job, "update_pdf_stage", state="embedding", label=f"Embedding 0 of {len(texts)} unique passages")

        async def on_batch(completed: int, total: int) -> None:
            await require_lease(job, "update_pdf_stage", state="embedding",
                                label=f"Embedding {completed} of {total} unique passages")

        stage = monotonic()
        vectors = await embed_documents(texts, api_key=key, on_batch=on_batch,
                                        job_id=job["id"])
        timing(job, "embed", stage, chunks=len(chunks), unique_passages=len(texts), batches=(len(texts) + 31) // 32)
        encoded = {text: json.dumps(vector, separators=(",", ":")) for text, vector in zip(texts, vectors, strict=True)}
        for row in chunks:
            row["embedding"] = encoded[row["content"]]
        await require_lease(job, "update_pdf_stage", state="indexing", label="Publishing search index")
        stage = monotonic()
        await require_lease(job, "activate_versioned_pdf_index", digest=digest, page_total=len(pages),
                            chunks=chunks, config_key=config_key)
        timing(job, "vector_insert", stage, chunks=len(chunks))
    else:
        await require_lease(job, "update_pdf_stage", state="processing", label="Generating Course Map")
        stage = monotonic()
        state = {"course_id": str(doc["course_id"]), "request_id": str(job["id"])}
        if key:
            state["api_key"] = key
        summary = await summarize_document(state, pages)
        timing(job, "summarize", stage, pages=len(pages), sections=len(summary["sections"]))
        summaries = [summary["document"], *summary["sections"]]
        await require_lease(job, "activate_document_summary", digest=digest, summaries=summaries)
    timing(job, "total", started, pages=len(pages))


async def process_job(job: dict) -> None:
    started = monotonic()
    try:
        if job["attempts"] > 3:
            await job_rpc(job, "fail_pdf_job", message="Processing was interrupted repeatedly. Retry to start again.",
                          terminal=True)
            return
        async with asyncio.timeout(210):
            await document_job(job)
    except Superseded:
        timing(job, "superseded", started)
    except Exception as exc:
        provider_code = provider_error_code(exc)
        timing(job, "failed", started, error_type=type(exc).__name__, provider_status=provider_code or "unknown")
        invalid = isinstance(exc, InvalidDocument)
        key_error = provider_code in {"API_KEY_INVALID", "API_KEY_ACCESS_DENIED"}
        message = (
            str(exc) if invalid else
            "The Gemini key was rejected. Check Settings, then retry." if key_error else
            "Gemini is limiting requests. Check the key quota or wait before retrying."
            if provider_code in {"API_KEY_QUOTA_EXCEEDED", "API_RATE_LIMITED"} else
            "Processing could not finish. Retry when the service is available."
        )
        await job_rpc(job, "fail_pdf_job", message=message, terminal=invalid or key_error)


async def consume(kind: str) -> None:
    while True:
        try:
            job = await claim_job(kind)
            if job:
                await process_job(job)
            else:
                await asyncio.sleep(2)
        except Exception as exc:
            logger.warning("worker_poll_failed kind=%s error_type=%s", kind, type(exc).__name__)
            await asyncio.sleep(10)


async def cleanup_uploads() -> None:
    while True:
        try:
            await asyncio.to_thread(remove_abandoned_uploads)
            await asyncio.to_thread(remove_deleted_pdf_objects)
        except Exception as exc:
            logger.warning("pdf_cleanup_failed error_type=%s", type(exc).__name__)
        await asyncio.sleep(300)


def remove_abandoned_uploads() -> None:
    client = get_supabase()
    expired = client.table("pdf_uploads").select("id,status,storage_path").lte(
        "cleanup_after", datetime.now(timezone.utc).isoformat(),
    ).order("cleanup_after").limit(30).execute().data or []
    for upload in expired:
        try:
            retained = upload["status"] == "finished" and bool(client.table("documents").select("id")
                .eq("id", upload["id"]).eq("storage_path", upload["storage_path"]).limit(1).execute().data)
            if not retained:
                client.storage.from_("documents").remove([upload["storage_path"]])
            client.table("pdf_uploads").delete().eq("id", upload["id"]).execute()
        except Exception as exc:
            logger.warning("pdf_cleanup_item_failed upload_id=%s error_type=%s", upload["id"], type(exc).__name__)


def remove_deleted_pdf_objects() -> None:
    client = get_supabase()
    rows = client.table("deleted_pdf_objects").select("storage_path").order("created_at").limit(30).execute().data or []
    for row in rows:
        path = row["storage_path"]
        try:
            referenced = client.table("documents").select("id").eq("storage_path", path).limit(1).execute().data
            if not referenced:
                client.storage.from_("documents").remove([path])
            client.table("deleted_pdf_objects").delete().eq("storage_path", path).execute()
        except Exception as exc:
            logger.warning("pdf_deleted_object_cleanup_failed error_type=%s", type(exc).__name__)


async def run() -> None:
    if not PDF_EXTRACTOR.is_file() or not which(os.environ.get("SOCRA_NODE_BIN", "node")):
        raise RuntimeError("Run the worker from a full Socra checkout with Node.js and frontend dependencies installed.")
    # One consumer per job kind. Exam generation also bounds per-slot concurrency.
    from exam_worker import consume_exam_jobs

    await asyncio.gather(consume("index"), consume("summary"), cleanup_uploads(),
                         consume_exam_jobs("generation", decrypt_key), consume_exam_jobs("grading", decrypt_key))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run())
