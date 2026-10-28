from __future__ import annotations

import unittest

from agents.explicateur import _bind_sources


class ExplanationCitationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = [{
            "document_id": "00000000-0000-0000-0000-000000000001",
            "filename": "Course.pdf",
            "page_number": 4,
            "content": "A project manager coordinates work toward the project objectives.",
        }]

    def test_binds_source_index_to_retrieved_citation(self) -> None:
        bound = _bind_sources({"citations": [{"source_index": 1}]}, self.chunks)
        self.assertEqual(bound["citations"][0]["page_number"], 4)
        self.assertEqual(bound["citations"][0]["filename"], "Course.pdf")

    def test_accepts_metadata_only_when_it_matches_retrieved_source(self) -> None:
        bound = _bind_sources({"citations": [{"page_number": 4, "filename": "Course.pdf"}]}, self.chunks)
        self.assertEqual(bound["citations"][0]["document_id"], self.chunks[0]["document_id"])

    def test_rejects_unmatched_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not match"):
            _bind_sources({"citations": [{"source_index": 8}]}, self.chunks)


if __name__ == "__main__":
    unittest.main()
