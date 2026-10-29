"""Regression checks for provider content shapes and safe fallback extraction."""
from __future__ import annotations

import unittest
from uuid import uuid4

from agents.evaluateur import _fallback_key_terms
from agents.structured_output import message_text, parse_json_object
from agents.exercise_generator import (
    _validate_type_specific,
    public_exercise,
    _bind_citations_to_sources,
    _citation_is_grounded,
    _normalize_exercise_payload,
    _validate_rubric_total,
)
from models.schemas import GeneratedExercise


class StructuredOutputTests(unittest.TestCase):
    def test_extracts_text_from_langchain_content_blocks(self) -> None:
        content = [{"type": "text", "text": '{"topic": "Entropy"}'}]
        self.assertEqual(message_text(content), '{"topic": "Entropy"}')
        self.assertEqual(parse_json_object(content), {"topic": "Entropy"})

    def test_parses_fenced_json_and_wrapper_text(self) -> None:
        self.assertEqual(
            parse_json_object('Result:\n```json\n{"score": 0.7}\n```'),
            {"score": 0.7},
        )

    def test_accepts_literal_single_quoted_object_safely(self) -> None:
        self.assertEqual(parse_json_object("{'topic': 'Entropy'}"), {"topic": "Entropy"})

    def test_recovers_first_object_when_provider_adds_trailing_json(self) -> None:
        content = '{"definition": "A topic", "citations": [1]}\n{"extra": true}'
        self.assertEqual(parse_json_object(content), {"definition": "A topic", "citations": [1]})

    def test_recovers_object_after_unstructured_prefix(self) -> None:
        self.assertEqual(parse_json_object('Result follows:\n{"topic": "Entropy"}'), {"topic": "Entropy"})

    def test_rejects_non_object_output(self) -> None:
        with self.assertRaises(ValueError):
            parse_json_object('[{"topic": "Entropy"}]')

    def test_fallback_terms_come_only_from_course_excerpts(self) -> None:
        terms = _fallback_key_terms([
            {"content": "A fact table stores measurable sales amounts. Dimension tables describe customers."}
        ])
        self.assertIn("measurable", terms)
        self.assertNotIn("Could", terms)
        self.assertNotIn("Reprenons", terms)

    def test_public_exercise_never_contains_solution_or_rubric(self) -> None:
        document_id = uuid4()
        exercise = GeneratedExercise.model_validate({
            "concept": "Entropy",
            "difficulty": "beginner",
            "bloom_level": "understand",
            "prompt": "Explain how the course describes entropy in this process.",
            "citations": [{
                "document_id": str(document_id),
                "filename": "Thermodynamics.pdf",
                "page_number": 12,
                "excerpt": "Entropy measures the number of microscopic arrangements.",
            }],
            "hints": ["Think about possible microscopic arrangements.", "Relate those arrangements to the system's macroscopic state."],
            "expected_answer": "Entropy is related to the number of accessible microscopic arrangements.",
            "rubric": [{"criterion": "Connects entropy to arrangements", "points": 10}],
            "common_mistakes": [],
        })
        public = public_exercise(str(uuid4()), exercise)
        self.assertIn("prompt", public)
        self.assertIn("hints", public)
        self.assertNotIn("expected_answer", public)
        self.assertNotIn("rubric", public)
        self.assertTrue(_validate_rubric_total(exercise))
        self.assertTrue(_citation_is_grounded(
            exercise.citations[0].model_dump(mode="json"),
            [{
                "document_id": str(document_id),
                "page_number": 12,
                "content": "Entropy measures the number of microscopic arrangements in a system.",
            }],
        ))

    def test_multiple_choice_public_projection_hides_answer_key(self) -> None:
        exercise = GeneratedExercise.model_validate(_normalize_exercise_payload({
            "exercise_type": "multiple_choice",
            "concept": "Database keys",
            "difficulty": "beginner",
            "bloom_level": "remember",
            "prompt": "Which key uniquely identifies a row in the supplied schema?",
            "citations": [{"document_id": str(uuid4()), "filename": "DB.pdf", "page_number": 1, "excerpt": "A primary key uniquely identifies each row in a table."}],
            "hints": ["Think about uniqueness.", "The key is named after its main role."],
            "expected_answer": "B",
            "rubric": [{"criterion": "Selects the correct key", "points": 10}],
            "common_mistakes": [],
            "choices": [{"id": "A", "text": "Foreign key"}, {"id": "B", "text": "Primary key", "is_correct": "true"}, {"id": "C", "text": "Index"}, {"id": "D", "text": "Unique constraint"}],
            "correct_choice": "B",
            "numeric_answer": 0,
            "numeric_tolerance": None,
            "numeric_unit": None,
        }))
        _validate_type_specific(exercise)
        with self.assertRaisesRegex(ValueError, "exactly 3"):
            _validate_type_specific(exercise, expected_option_count=3)
        public = public_exercise(str(uuid4()), exercise)
        self.assertEqual(public["exercise_type"], "multiple_choice")
        self.assertEqual(len(public["choices"]), 4)
        self.assertNotIn("is_correct", public["choices"][1])
        self.assertNotIn("correct_choice", public)
        self.assertNotIn("expected_answer", public)

    def test_numerical_generation_requires_computed_answer(self) -> None:
        exercise = GeneratedExercise.model_validate({
            "exercise_type": "numerical",
            "concept": "Unit price",
            "difficulty": "beginner",
            "bloom_level": "apply",
            "prompt": "Calculate the unit price using the course values.",
            "citations": [{"document_id": str(uuid4()), "filename": "Math.pdf", "page_number": 1, "excerpt": "Unit price is calculated by dividing total price by quantity."}],
            "hints": ["Identify the two values.", "Divide the total by the quantity."],
            "expected_answer": "2.5 EUR",
            "rubric": [{"criterion": "Calculates the unit price", "points": 10}],
            "common_mistakes": [],
            "numeric_expression": "10 / 4",
            "numeric_answer": "2.5",
            "numeric_tolerance": "0",
            "numeric_unit": "EUR",
        })
        _validate_type_specific(exercise)
        self.assertEqual(exercise.expected_answer, "2.5 EUR")
        exercise.numeric_answer = "2"
        with self.assertRaisesRegex(ValueError, "does not match"):
            _validate_type_specific(exercise)

    def test_exercise_citations_are_bound_to_retrieved_source_metadata(self) -> None:
        document_id = str(uuid4())
        chunks = [{
            "document_id": document_id,
            "filename": "Course.pdf",
            "page_number": 7,
            "content": "A dimension table describes the entities used to analyze measures.",
        }]
        bound = _bind_citations_to_sources(
            {"citations": [{"source_index": 1}]}, chunks
        )
        citation = bound["citations"][0]
        self.assertEqual(citation["document_id"], document_id)
        self.assertEqual(citation["filename"], "Course.pdf")
        self.assertEqual(citation["page_number"], 7)
        self.assertEqual(citation["excerpt"], chunks[0]["content"])

    def test_exercise_citation_rejects_unknown_source_index(self) -> None:
        with self.assertRaisesRegex(ValueError, "source_index"):
            _bind_citations_to_sources({"citations": [{"source_index": 9}]}, [{
                "document_id": str(uuid4()),
                "page_number": 1,
                "content": "Source text",
            }])

    def test_normalizes_gemini_enum_aliases_and_keyed_rubric(self) -> None:
        normalized = _normalize_exercise_payload({
            "difficulty": "Medium",
            "bloom_level": "Understanding",
            "rubric": {
                "Explains the main idea": 6,
                "Uses evidence from the course": 4,
            },
        })
        self.assertEqual(normalized["difficulty"], "intermediate")
        self.assertEqual(normalized["bloom_level"], "understand")
        self.assertEqual(normalized["rubric"], [
            {"criterion": "Explains the main idea", "points": 6},
            {"criterion": "Uses evidence from the course", "points": 4},
        ])

    def test_normalizes_gemini_description_rubric_and_easy_labels(self) -> None:
        normalized = _normalize_exercise_payload({
            "difficulty": "Easy",
            "bloom_level": "Remembering",
            "rubric": [{"description": "Accurate answer", "points": 10}],
        })
        self.assertEqual(normalized["difficulty"], "beginner")
        self.assertEqual(normalized["bloom_level"], "remember")
        self.assertEqual(normalized["rubric"], [
            {"criterion": "Accurate answer", "points": 10},
        ])

    def test_normalizes_gemini_hint_objects_and_allows_one_word_answers(self) -> None:
        normalized = _normalize_exercise_payload({
            "concept": "Delege project",
            "difficulty": "beginner",
            "bloom_level": "remember",
            "prompt": "What is the name of the project described in the CV?",
            "citations": [{
                "document_id": str(uuid4()),
                "filename": "CV.pdf",
                "page_number": 1,
                "excerpt": "Delege was a course project.",
            }],
            "hints": [
                {"hint": "Look in the projects section."},
                {"hint": "The project name starts with D."},
            ],
            "expected_answer": "Delege",
            "rubric": [{"criterion": "Names the project correctly", "points": 10}],
            "common_mistakes": [],
        })

        exercise = GeneratedExercise.model_validate(normalized)
        self.assertEqual(exercise.hints, [
            "Look in the projects section.",
            "The project name starts with D.",
        ])
        self.assertEqual(exercise.expected_answer, "Delege")

    def test_normalizes_null_unused_fields_and_numeric_scalar_types(self) -> None:
        mcq = _normalize_exercise_payload({
            "exercise_type": "multiple_choice",
            "numeric_answer": 0,
            "numeric_tolerance": None,
            "numeric_unit": None,
        })
        self.assertIsNone(mcq["numeric_answer"])
        self.assertEqual(mcq["numeric_tolerance"], "0")
        self.assertEqual(mcq["numeric_unit"], "")

        numerical = _normalize_exercise_payload({
            "exercise_type": "numerical",
            "numeric_answer": 0,
            "numeric_tolerance": None,
            "numeric_unit": None,
        })
        self.assertEqual(numerical["numeric_answer"], "0")
        self.assertEqual(numerical["numeric_tolerance"], "0")
        self.assertEqual(numerical["numeric_unit"], "")


if __name__ == "__main__":
    unittest.main()
