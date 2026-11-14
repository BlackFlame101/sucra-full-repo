"""Phase 6 regression coverage for mixed exam creation and completion."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.routes.exams import (
    DEFAULT_QUESTION_TYPES,
    _has_answer_for_every_question,
    _public_exam,
    _require_complete_answers,
    _schedule_question_types,
    _candidate_scopes,
    _scope_for_exam_question,
    router,
)


class MixedExamTests(unittest.TestCase):
    def test_validation_response_never_echoes_a_provider_key(self) -> None:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            response = client.post("/exams/start", json={"api_key": "private-example", "question_count": 1})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": "Check the exam settings and try again."})
        self.assertNotIn("private-example", response.text)

    def test_start_returns_queued_progress_for_authenticated_owner(self) -> None:
        app = FastAPI()
        app.include_router(router)
        course_id, session_id, exam_id = (str(uuid4()) for _ in range(3))
        queued = {"id": exam_id, "status": "preparing", "question_count": 3}
        queue = AsyncMock(return_value=exam_id)
        with TestClient(app) as client, patch("api.routes.exams._user_id_from_header", return_value="owner"), \
             patch("api.routes.exams.rpc", queue), patch("api.routes.exams.get_exam_for_session", return_value=None), \
             patch("api.routes.exams.consume_study_quota", AsyncMock(return_value=True)), patch("api.routes.exams.get_exam_for_owner", return_value=queued), \
             patch("api.routes.exams.count_exam_slots", return_value=1):
            response = client.post("/exams/start", json={
                "course_id": course_id, "session_id": session_id, "question_count": 3,
            }, headers={"Authorization": "Bearer fixture"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["progress"], {"completed": 1, "total": 3})
        self.assertEqual(response.json()["questions"], [])
        function, params = queue.await_args.args
        self.assertEqual(function, "queue_exam")
        self.assertEqual((params["owner"], params["course"], params["inquiry"]), ("owner", course_id, session_id))
        self.assertNotIn("api_key", params["plan"])

    def test_submission_replay_returns_progress_and_does_not_queue_again(self) -> None:
        app = FastAPI()
        app.include_router(router)
        exam_id = str(uuid4())
        grading = {"id": exam_id, "status": "grading", "question_count": 3,
                   "results": [{"feedback": "hidden until complete"}]}
        queue = AsyncMock()
        with TestClient(app) as client, patch("api.routes.exams._user_id_from_header", return_value="owner"), \
             patch("api.routes.exams.get_exam_for_owner", return_value=grading) as read, patch("api.routes.exams.rpc", queue):
            response = client.post(f"/exams/{exam_id}/submit", json={}, headers={"Authorization": "Bearer fixture"})
        read.assert_called_once_with(exam_id=exam_id, user_id="owner")
        queue.assert_not_awaited()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["progress"], {"completed": 1, "total": 3})
        self.assertEqual(response.json()["results"], [])

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
