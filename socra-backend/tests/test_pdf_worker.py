"""Offline PDF parsing and durable worker orchestration checks."""
from __future__ import annotations

import hashlib
from base64 import b64encode
import shutil
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agents.course_summarizer import DocumentSummary, summarize_document
from rag.ocr import OcrInputError, recognize_pages
from rag.retriever import retrieve_summary_guided_chunks
from db.job_credentials import decrypt_key
from worker import InvalidDocument, chunk_pages, extract_pages, process_job, remove_abandoned_uploads, remove_deleted_pdf_objects


class CourseMapTests(unittest.IsolatedAsyncioTestCase):
    async def test_section_indices_are_unique_across_batches(self):
        batches = [(1, 2, "first"), (3, 4, "second"), (5, 6, "third")]
        summaries = [
            DocumentSummary(title="Course", summary="Overview " * 8, sections=[
                {"title": f"Page {page}", "summary": "Grounded summary " * 4,
                 "page_start": page, "page_end": page} for page in range(start, end + 1)
            ]) for start, end, _ in batches
        ]
        with patch("agents.course_summarizer._batches", return_value=batches), \
             patch("agents.course_summarizer._summarize_batch", AsyncMock(side_effect=summaries)):
            result = await summarize_document({}, ["text"] * 6)
        self.assertEqual([section["section_index"] for section in result["sections"]], list(range(6)))
        self.assertEqual([section["page_start"] for section in result["sections"]], list(range(1, 7)))


def fixture_pdf(pages: list[str]) -> bytes:
    """Create a small, valid text PDF without third-party test dependencies."""
    page_ids = " ".join(f"{3 + i * 2} 0 R" for i in range(len(pages)))
    font = 3 + len(pages) * 2
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Count {len(pages)} /Kids [{page_ids}] >>",
    ]
    for i, text in enumerate(pages):
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + i * 2} 0 R "
                       f"/Resources << /Font << /F1 {font} 0 R >> >> >>")
        stream = f"BT /F1 12 Tf 40 730 Td ({text}) Tj ET" if text else ""
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{i} 0 obj\n{obj}\nendobj\n".encode())
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Root 1 0 R /Size {len(offsets)} >>\nstartxref\n{xref}\n%%EOF".encode())
    return bytes(pdf)


def scanned_pdf() -> bytes:
    """A one-page, image-only PDF with an inline RGB image."""
    return fixture_pdf(["SCANIMAGE"]).replace(
        b"BT /F1 12 Tf 40 730 Td (SCANIMAGE) Tj ET",
        b"BI /W 1 /H 1 /BPC 8 /CS /RGB ID abc EI",
    )


class WorkerFixture:

    def setUp(self):
        self.doc = {"id": "doc", "course_id": "course", "storage_path": "owner/course/doc.pdf",
                    "courses": {"user_id": "owner"}}
        config = patch("worker.index_config", return_value="fixture-config")
        config.start()
        self.addCleanup(config.stop)
        self.job = {"id": "job", "lease_token": "lease", "document_id": "doc", "generation": 1,
                    "kind": "index", "attempts": 1, "pages": None, "content_hash": None, "encrypted_key": None}
        db = Mock()
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = (
            SimpleNamespace(data=[self.doc])
        )
        mock = patch("worker.get_supabase", return_value=db)
        self.addCleanup(mock.stop)
        self.db = mock.start()

class WorkerTests(WorkerFixture, unittest.IsolatedAsyncioTestCase):
    def test_local_ocr_keeps_original_page_numbers_and_text(self):
        def run(args, **kwargs):
            from pathlib import Path
            if args[0] == "renderer":
                self.assertEqual(args[2], "2")
                Path(args[-1] + ".png").write_bytes(b"fixture image")
            return SimpleNamespace(stdout=b"Scanned text on page two")
        with patch("rag.ocr.which", side_effect=["renderer", "reader"]), patch("rag.ocr.subprocess.run", side_effect=run):
            pages = recognize_pages(scanned_pdf(), ["Page one", "", "Page three"])
        self.assertEqual(pages, ["Page one", "Scanned text on page two", "Page three"])
        self.assertEqual([chunk["page_number"] for chunk in chunk_pages(pages)], [1, 2, 3])
        with self.assertRaisesRegex(OcrInputError, "up to 20"):
            recognize_pages(b"fixture", [""] * 21)

    async def test_ocr_retry_queues_extracted_pages_under_the_current_lease(self):
        with patch("worker.download_document", AsyncMock(return_value=scanned_pdf())), \
             patch("worker.extract_pages", AsyncMock(return_value=["", ""])) as parse, \
             patch("worker.recognize_pages", return_value=["", "Recovered second page"]) as recognize, \
             patch("worker.job_rpc", AsyncMock(return_value=True)) as rpc:
            await process_job({**self.job, "use_ocr": True})
        self.assertTrue(parse.await_args.kwargs["allow_scanned"])
        recognize.assert_called_once()
        published = next(call for call in rpc.await_args_list if call.args[1] == "publish_pdf_pages")
        self.assertEqual(published.kwargs["source_pages"], ["", "Recovered second page"])

    def test_job_credential_can_only_be_read_for_its_document(self):
        secret = b"a" * 32
        nonce = b"b" * 12
        encrypted = AESGCM(secret).encrypt(nonce, b"test-key", b"doc")
        payload = ".".join(b64encode(value).decode() for value in (nonce, encrypted))
        with patch.dict("os.environ", {"SOCRA_JOB_ENCRYPTION_KEY": b64encode(secret).decode()}):
            self.assertEqual(decrypt_key(payload, "doc"), "test-key")
            with self.assertRaises(ValueError):
                decrypt_key(payload, "other-document")

    @unittest.skipUnless(shutil.which("node"), "Node.js required for PDF fixtures")
    async def test_pdf_preserves_empty_page_numbers_and_rejects_bad_files(self):
        pages = await extract_pages(fixture_pdf(["First page", "", "Third page"]))
        self.assertEqual(pages, ["First page", "", "Third page"])
        self.assertEqual([row["page_number"] for row in chunk_pages(pages)], [1, 3])
        for data, error in [(fixture_pdf(["", ""]), "no searchable text"),
                            (scanned_pdf(), "no searchable text"),
                            (b"%PDF-1.4 this is not a PDF", "could not be read")]:
            with self.subTest(error=error), self.assertRaisesRegex(InvalidDocument, error):
                await extract_pages(data)

    async def test_publishes_pages_before_embeddings_and_activation(self):
        data = b"%PDF-1.4 fixture"
        digest = hashlib.sha256(data).hexdigest()
        history = []

        async def rpc(_job, name, **kwargs):
            history.append(name)
            if name == "publish_pdf_pages":
                self.assertEqual(kwargs["digest"], digest)
                self.assertEqual(kwargs["source_pages"], ["first", "second"])
            if name == "reuse_pdf_index":
                return False
            if name == "activate_versioned_pdf_index":
                self.assertEqual(kwargs["page_total"], 2)
                self.assertEqual(len(kwargs["chunks"]), 2)
            return True

        async def embed(text, **kwargs):
            self.assertIn("publish_pdf_pages", history)
            self.assertNotIn("activate_document_summary", history)
            history.append("embed")
            await kwargs["on_batch"](2, 2)
            return [[0.1] * 768, [0.2] * 768]

        with patch("worker.download_document", AsyncMock(return_value=data)), \
             patch("worker.extract_pages", AsyncMock(return_value=["first", "second"])) as extract, \
             patch("worker.embed_documents", side_effect=embed), patch("worker.job_rpc", side_effect=rpc):
            await process_job(self.job)
        self.assertEqual(extract.await_count, 1)
        self.assertLess(history.index("embed"), history.index("activate_versioned_pdf_index"))

    async def test_recovery_reuses_extraction_and_summary_failure_is_independent(self):
        digest = "a" * 64
        job = {**self.job, "kind": "summary", "attempts": 2, "pages": ["first"], "content_hash": digest}
        with patch("worker.download_document", AsyncMock()) as download, \
             patch("worker.summarize_document", AsyncMock(side_effect=ValueError("invalid summary"))), \
             patch("worker.job_rpc", AsyncMock(return_value=True)) as rpc:
            await process_job(job)
        download.assert_not_awaited()
        self.assertEqual([call.args[1] for call in rpc.await_args_list], ["update_pdf_stage", "fail_pdf_job"])
        self.assertFalse(rpc.await_args.kwargs["terminal"])

    async def test_lost_lease_cannot_activate_an_index(self):
        job = {**self.job, "pages": ["first"], "content_hash": "a" * 64}
        with patch("worker.job_rpc", AsyncMock(return_value=False)) as rpc, \
             patch("worker.embed_documents", AsyncMock()) as embed:
            await process_job(job)
        self.assertEqual(rpc.await_args.args[1], "publish_pdf_pages")
        embed.assert_not_awaited()

    async def test_repeated_worker_crashes_exhaust_the_budget(self):
        with patch("worker.job_rpc", AsyncMock(return_value=True)) as rpc:
            await process_job({**self.job, "attempts": 4})
        self.assertEqual(rpc.await_args.args[1], "fail_pdf_job")
        self.assertTrue(rpc.await_args.kwargs["terminal"])
        self.db.assert_not_called()

    async def test_search_uses_vectors_while_course_map_is_missing(self):
        with patch("rag.retriever.get_current_course_sections", AsyncMock(return_value=[])), \
             patch("rag.retriever.embed_query", AsyncMock(return_value=[0.1] * 768)), \
             patch("rag.retriever._match_terms", return_value=[]), \
             patch("rag.retriever._call_rpc", return_value=[{"id": "vector", "content": "ready vector"}]) as search:
            self.assertEqual(await retrieve_summary_guided_chunks("topic", "course"), [{"id": "vector", "content": "ready vector"}])
        self.assertEqual(search.call_args.args[1], "course")


class UploadReuseTests(WorkerFixture, unittest.IsolatedAsyncioTestCase):
    async def test_identical_verified_index_skips_provider(self):
        job = {**self.job, "pages": ["same"], "content_hash": "a" * 64}
        with patch("worker.job_rpc", AsyncMock(return_value=True)) as rpc, patch("worker.embed_documents", AsyncMock()) as embed:
            await process_job(job)
        self.assertEqual([call.args[1] for call in rpc.await_args_list], ["publish_pdf_pages", "reuse_pdf_index"])
        embed.assert_not_awaited()

    async def test_duplicate_passages_preserve_page_citations_and_use_one_vector(self):
        job = {**self.job, "pages": ["same", "same"], "content_hash": "a" * 64}
        writes = []
        async def rpc(job, function, **kwargs):
            if function == "reuse_pdf_index":
                return False
            if function == "activate_versioned_pdf_index":
                writes.extend(kwargs["chunks"])
            return True
        with patch("worker.job_rpc", side_effect=rpc), patch("worker.embed_documents", AsyncMock(return_value=[[0.2] * 768])) as embed:
            await process_job(job)
        self.assertEqual(embed.await_args.args[0], ["same"])
        self.assertEqual([item["page_number"] for item in writes], [1, 2])
        self.assertEqual(writes[0]["embedding"], writes[1]["embedding"])


class UploadCleanupTests(unittest.TestCase):
    def test_only_expired_unreferenced_objects_are_removed(self):
        db = Mock()
        uploads, documents = Mock(), Mock()
        db.table.side_effect = lambda table: uploads if table == "pdf_uploads" else documents
        uploads.select.return_value.lte.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[
            {"id": "pending", "status": "pending", "storage_path": "pending.pdf"},
            {"id": "finished", "status": "finished", "storage_path": "finished.pdf"},
        ])
        documents.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[{"id": "finished"}])
        with patch("worker.get_supabase", return_value=db):
            remove_abandoned_uploads()
        db.storage.from_.return_value.remove.assert_called_once_with(["pending.pdf"])
        self.assertEqual(uploads.delete.call_count, 2)


    def test_deleted_pdf_object_cleanup_keeps_referenced_and_retries_failed_removal(self):
        client, tombstones, documents = Mock(), Mock(), Mock()
        client.table.side_effect = {"deleted_pdf_objects": tombstones, "documents": documents}.__getitem__
        tombstones.select.return_value.order.return_value.limit.return_value.execute.return_value.data = [
            {"storage_path": "retained.pdf"}, {"storage_path": "retry.pdf"}, {"storage_path": "removed.pdf"},
        ]
        documents.select.return_value.eq.return_value.limit.return_value.execute.side_effect = [
            SimpleNamespace(data=[{"id": "still-in-use"}]), SimpleNamespace(data=[]), SimpleNamespace(data=[]),
        ]
        remove = client.storage.from_.return_value.remove
        remove.side_effect = [RuntimeError("Storage temporarily unavailable"), None]
        with patch("worker.get_supabase", return_value=client):
            remove_deleted_pdf_objects()
        self.assertEqual([call.args[0] for call in remove.call_args_list], [["retry.pdf"], ["removed.pdf"]])
        deleted = tombstones.delete.return_value.eq.call_args_list
        self.assertEqual([call.args[1] for call in deleted], ["retained.pdf", "removed.pdf"])
