from __future__ import annotations

import unittest

from agents.course_summarizer import _batches
from rag.retriever import RetrievedChunk
from rag.retriever import constrain_chunks_to_sections, current_version_summaries


class CourseSummaryTests(unittest.TestCase):
    def test_batches_keep_real_pdf_page_numbers_across_empty_pages(self) -> None:
        batches = _batches(["first", "", "third"], max_chars=100)
        self.assertEqual(len(batches), 1)
        self.assertIn("[Page 1]", batches[0][2])
        self.assertIn("[Page 3]", batches[0][2])
        self.assertEqual((batches[0][0], batches[0][1]), (1, 3))

    def test_batches_split_with_nonoverlapping_ranges(self) -> None:
        batches = _batches(["a" * 30, "b" * 30, "c" * 30], max_chars=45)
        self.assertEqual([(x[0], x[1]) for x in batches], [(1, 1), (2, 2), (3, 3)])


class SummaryRetrievalTests(unittest.TestCase):
    def test_current_section_summaries_constrain_chunks_and_keep_real_pages(self) -> None:
        summaries = [{"document_id": "doc", "document_version": "v1", "level": "section",
                      "title": "Entropy", "summary": "Entropy describes disorder", "page_start": 2, "page_end": 3}]
        docs = [{"id": "doc", "content_hash": "v1"}]
        chunk_a: RetrievedChunk = {"id": "a", "content": "source", "document_id": "doc", "page_number": 2,
                                   "chunk_index": 0, "filename": "Course.pdf", "similarity": 0.9}
        chunk_b: RetrievedChunk = {"id": "b", "content": "other", "document_id": "doc", "page_number": 8,
                                   "chunk_index": 1, "filename": "Course.pdf", "similarity": 0.8}

        current = current_version_summaries(summaries, docs)
        chunks = constrain_chunks_to_sections([chunk_a, chunk_b], current)
        self.assertEqual([item["id"] for item in chunks], ["a"])
        self.assertEqual(chunks[0]["page_number"], 2)

    def test_stale_versions_are_ignored(self) -> None:
        summary = {"document_id": "doc", "document_version": "old", "level": "section",
                   "title": "Entropy", "summary": "Entropy", "page_start": 1, "page_end": 1}
        self.assertEqual(current_version_summaries([summary], [{"id": "doc", "content_hash": "new"}]), [])


if __name__ == "__main__":
    unittest.main()
