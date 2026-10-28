"""Phase 6 regression coverage for mixed exam creation and completion."""
from __future__ import annotations

import unittest

from fastapi import HTTPException

from api.routes.exams import (
    DEFAULT_QUESTION_TYPES,
    QUESTION_TYPES,
    _has_answer_for_every_question,
    _public_exam,
    _require_complete_answers,
    _schedule_question_types,
    _candidate_scopes,
    _fallback_question_types,
    _scope_for_exam_question,
)


class MixedExamTests(unittest.TestCase):
    def test_question_schedules_are_balanced_and_include_each_type(self) -> None:
        for count in range(3, 13):
            with self.subTest(question_count=count):
                scheduled = _schedule_question_types(count, DEFAULT_QUESTION_TYPES)
                self.assertEqual(len(scheduled), count)
                counts = [scheduled.count(question_type) for question_type in DEFAULT_QUESTION_TYPES]
                self.assertTrue(all(value >= 1 for value in counts))
                self.assertLessEqual(max(counts) - min(counts), 1)

    def test_question_schedule_contains_only_the_selected_types(self) -> None:
        for selected in (["code"], ["sql", "multiple_choice"], ["short_answer", "code", "sql"]):
            result = _schedule_question_types(6, selected)
            self.assertEqual(set(result), set(selected))
            counts = [result.count(item) for item in selected]
            self.assertLessEqual(max(counts) - min(counts), 1)
        with self.assertRaises(ValueError):
            _schedule_question_types(2, ["code", "sql", "numerical"])

    def test_question_schedule_can_select_exactly_one_type(self) -> None:
        self.assertEqual(set(_schedule_question_types(4, ["sql"])), {"sql"})

    def test_answer_check_allows_skips_during_exam_but_detects_missing_at_submit(self) -> None:
        exercises = [{"id": "q1"}, {"id": "q2"}, {"id": "q3"}]
        self.assertFalse(_has_answer_for_every_question(exercises, {"q1": "answer", "q2": "  "}))
        self.assertTrue(_has_answer_for_every_question(exercises, {"q1": "a", "q2": "b", "q3": "c"}))

    def test_broad_exam_scopes_questions_across_course_sections(self) -> None:
        sections = [
            {"title": "Internships", "summary": "Worked from July 2025 to September 2025."},
            {"title": "Projects", "summary": "Built a messaging platform."},
        ]
        self.assertTrue(_scope_for_exam_question("", sections, 1, "short_answer").startswith("Internships:"))
        self.assertTrue(_scope_for_exam_question("", sections, 2, "short_answer").startswith("Projects:"))
        self.assertIn("July 2025", _scope_for_exam_question("", sections, 1, "numerical"))
        self.assertEqual(_scope_for_exam_question("internships", sections, 2, "short_answer"), "internships")
        self.assertEqual(len(_candidate_scopes("", sections, 1, "short_answer")), 2)
        self.assertEqual(_candidate_scopes("internships", sections, 1, "short_answer"), ["internships"])

    def test_unavailable_format_falls_back_to_least_used_verified_types(self) -> None:
        generated = [
            {"exercise_type": "short_answer"},
            {"exercise_type": "multiple_choice"},
            {"exercise_type": "multiple_choice"},
        ]
        fallbacks = _fallback_question_types("numerical", generated)
        self.assertEqual(fallbacks[0], "short_answer")
        self.assertNotIn("numerical", fallbacks)
        self.assertTrue(set(_fallback_question_types("sql", generated, ["sql", "code", "short_answer"])).issubset({"code", "short_answer"}))

    def test_incomplete_exam_submission_is_rejected(self) -> None:
        exercises = [{"id": "q1"}, {"id": "q2"}, {"id": "q3"}]
        with self.assertRaises(HTTPException) as raised:
            _require_complete_answers(exercises, ["q1", "q2", "q3"], {"q1": "saved", "q3": "saved"})
        self.assertEqual(raised.exception.status_code, 409)

    def test_missing_exercise_row_also_blocks_exam_submission(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            _require_complete_answers([{"id": "q1"}], ["q1", "q2"], {"q1": "saved"})
        self.assertEqual(raised.exception.status_code, 409)

    def test_active_exam_projection_does_not_expose_solution_or_rubric(self) -> None:
        question = {
            "id": "q1", "prompt": "Question", "exercise_type": "multiple_choice",
            "exercise_data": {"choices": [{"id": "A", "text": "Option"}], "correct_choice": "A"},
            "expected_answer": "Private solution", "rubric": [{"criterion": "Private criterion"}],
        }
        public = _public_exam({
            "id": "exam-id", "status": "in_progress", "exercise_ids": ["q1"],
            "answers": {}, "results": [],
        }, [question])
        self.assertEqual(public["questions"][0]["choices"], [{"id": "A", "text": "Option"}])
        self.assertNotIn("expected_answer", public["questions"][0])
        self.assertNotIn("correct_choice", public["questions"][0])
        self.assertNotIn("rubric", public["questions"][0])


if __name__ == "__main__":
    unittest.main()
