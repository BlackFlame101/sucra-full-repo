from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from api.routes.exams import _public_exam
from exam_worker import grade_exam, prepare_exam, process_exam_job

JOB = {"id": "job", "exam_id": "exam", "kind": "generation", "attempts": 1, "encrypted_key": None,
       "options": {"difficulty": "beginner", "language": "en", "provider": "groq",
                   "slots": [{"type": kind, "scopes": ["Course scope"]} for kind in
                             ("short_answer", "numerical", "multiple_choice")]}}
EXAM = {"id": "exam", "course_id": "course", "user_id": "owner", "session_id": "session",
        "topic": "", "question_count": 3, "status": "preparing", "requested_types": ["short_answer", "numerical", "multiple_choice"]}


class ExamWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_skips_saved_slot_and_parallel_work_preserves_slot_type(self):
        peak, active, started = 0, 0, []
        saved = {}
        async def generate(state):
            nonlocal peak, active
            kind = state["requested_exercise_type"]
            started.append(kind)
            active += 1
            peak = max(active, peak)
            await asyncio.sleep(0.015 if kind == "numerical" else 0)
            active -= 1
            return {"prompt": {"numerical": "Calculate the average acceleration of the train.",
                               "multiple_choice": "Select the definition of database normalization."}[kind],
                    "exercise_type": kind, "difficulty": "beginner"}

        async def db_call(job, function, **kwargs):
            if function == "save_exam_slot":
                saved[kwargs["slot"]] = kwargs["question"]["exercise_type"]
                return "saved"
            self.assertEqual(function, "publish_exam")
            self.assertEqual(saved, {1: "numerical", 2: "multiple_choice"})
            return True

        with patch("exam_worker.get_exam_slots", return_value=[{"exam_slot": 0, "prompt": "Explain wavelength in optics."}]), \
             patch("exam_worker.generate_verified_exercise", side_effect=generate), \
             patch("exam_worker.generation_concurrency", return_value=2), \
             patch("exam_worker.job_rpc", side_effect=db_call):
            await prepare_exam(JOB, EXAM, None)
        self.assertEqual(peak, 2)
        self.assertEqual(started, ["numerical", "multiple_choice"])

    async def test_partial_generation_never_publishes(self):
        async def generate(state):
            if state["requested_exercise_type"] == "numerical":
                raise ValueError("cannot verify a source")
            return {"prompt": state["requested_exercise_type"] + " original question"}
        rpc = AsyncMock(return_value="saved")
        with patch("exam_worker.get_exam_slots", return_value=[]), \
             patch("exam_worker.generate_verified_exercise", side_effect=generate), \
             patch("exam_worker.job_rpc", rpc):
            with self.assertRaises(ValueError):
                await prepare_exam(JOB, EXAM, None)
        functions = [call.args[1] for call in rpc.await_args_list]
        self.assertIn("save_exam_slot", functions)
        self.assertNotIn("publish_exam", functions)

    async def test_grade_resume_skips_persisted_attempt_and_finalizes_once(self):
        questions = [{"id": key, "concept": key, "prompt": key, "exercise_type": "short_answer"} for key in ("first", "second")]
        exam = {**EXAM, "exercise_ids": ["first", "second"], "exam_language": "en",
                "answers": {"first": "old", "second": "new"},
                "results": [{"exercise_id": "first", "score": 8, "max_score": 10, "error_category": "partial"}]}
        grade = {"answer": "new", "total_score": 10, "max_score": 10, "feedback": "Correct",
                 "error_category": "correct", "criterion_feedback": [], "citations": [], "next_step": "Review"}
        rpc = AsyncMock(return_value=True)
        with patch("exam_worker.get_exam_exercises", return_value=questions), patch("exam_worker.get_profile", return_value=None), \
             patch("exam_worker.grade_exercise", AsyncMock(return_value=grade)) as grader, patch("exam_worker.job_rpc", rpc):
            await grade_exam({**JOB, "kind": "grading"}, exam, None)
        self.assertEqual(grader.await_count, 1)
        self.assertEqual(grader.await_args.args[0]["exercise_record"]["id"], "second")
        self.assertEqual([call.args[1] for call in rpc.await_args_list], ["save_exam_grade", "publish_exam_grades"])
        self.assertEqual(rpc.await_args.kwargs["student_profile"]["total_exchanges"], 2)

    async def test_expired_job_budget_stops_before_any_provider_call(self):
        rpc = AsyncMock(return_value=True)
        with patch("exam_worker.job_rpc", rpc), patch("exam_worker.get_exam_job_exam") as read:
            await process_exam_job({**JOB, "attempts": 4}, lambda *_: None)
        read.assert_not_called()
        self.assertEqual(rpc.await_args.args[1], "fail_exam_job")
        self.assertTrue(rpc.await_args.kwargs["permanent"])

    def test_preparation_and_grading_return_counts_without_private_content(self):
        exercise = {"id": "private-id", "expected_answer": "hidden", "rubric": [{"criterion": "private"}]}
        prep = _public_exam({**EXAM, "validated_count": 2}, [exercise])
        self.assertEqual(prep["progress"], {"completed": 2, "total": 3})
        self.assertEqual(prep["questions"], [])
        grading = _public_exam({**EXAM, "status": "grading", "results": [{"feedback": "hidden"}]}, [exercise])
        self.assertEqual(grading["progress"], {"completed": 1, "total": 3})
        self.assertEqual(grading["results"], [])
        self.assertNotIn("private-id", str(grading))
