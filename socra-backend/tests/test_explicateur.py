from __future__ import annotations

import unittest

from agents.explicateur import _bind_sources, _normalize_explanation_payload


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

    def test_normalizes_string_pitfalls_to_a_list(self) -> None:
        payload = _normalize_explanation_payload({
            "common_pitfalls": "Failing to launch the program.",
            "sections": [{"heading": "Run", "content": "Run the program from its folder."}],
            "citations": [1],
        })
        self.assertEqual(payload["common_pitfalls"], ["Failing to launch the program."])

    def test_normalizes_string_section_and_citation_shapes(self) -> None:
        payload = _normalize_explanation_payload({
            "sections": ["A detailed section explaining the concept."],
            "citations": "1",
        })
        self.assertEqual(payload["sections"][0]["heading"], "Section 1")
        self.assertEqual(payload["citations"], ["1"])

    def test_splits_inline_code_explanations_into_walkthrough_rows(self) -> None:
        payload = _normalize_explanation_payload({
            "sections": [{
                "heading": "Line by line",
                "content": "Intro\n- `import sys` : Imports arguments support [4].\n- `sc.stop()` : Stops Spark [4].",
            }],
        })
        section = payload["sections"][0]
        self.assertEqual(section["content"], "Intro")
        self.assertEqual(len(section["walkthrough"]), 2)
        self.assertEqual(section["walkthrough"][0]["code"], "import sys")


if __name__ == "__main__":
    unittest.main()
