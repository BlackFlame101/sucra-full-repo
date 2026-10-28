"""Checks for Correcteur score binding and structured learning evidence."""
from __future__ import annotations

import unittest

from agents.correcteur import _bind_criterion_feedback, _normalize_category, _objective_correction, _parse_numeric_submission
from agents.memoire import _apply_exercise_correction, _ensure_profile_shape


class CorrecteurTests(unittest.TestCase):
    def test_feedback_scores_are_bound_to_saved_rubric(self) -> None:
        bound = _bind_criterion_feedback(
            {
                "criteria": [
                    {"criterion": "Defines the project goal", "score": 2, "comment": "Clear and accurate."},
                    {"criterion": "Explains the manager's responsibility", "points_awarded": 1, "feedback": "Partly explained."},
                ]
            },
            [
                {"criterion": "Defines the project goal", "points": 2},
                {"criterion": "Explains the manager's responsibility", "points": 3},
            ],
        )
        self.assertEqual(bound["criterion_feedback"][1]["possible_points"], 3)
        self.assertEqual(bound["criterion_feedback"][1]["awarded_points"], 1)

    def test_feedback_rejects_points_outside_the_rubric(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the rubric"):
            _bind_criterion_feedback(
                {"criterion_feedback": [{
                    "criterion": "Defines the project goal",
                    "awarded_points": 5,
                    "feedback": "Good.",
                }]},
                [{"criterion": "Defines the project goal", "points": 2}],
            )

    def test_category_alias_normalization(self) -> None:
        self.assertEqual(_normalize_category("fully correct"), "correct")
        self.assertEqual(_normalize_category("misconception"), "conceptual")

    def test_multiple_choice_is_graded_deterministically(self) -> None:
        result = _objective_correction({
            "exercise_type": "multiple_choice",
            "exercise_data": {"choices": [{"id": "A", "text": "Wrong"}, {"id": "B", "text": "Right"}], "correct_choice": "B"},
            "rubric": [{"criterion": "Selects the correct answer", "points": 10}],
        }, "B", "en")
        self.assertEqual(sum(c.awarded_points for c in result.criterion_feedback), 10)
        self.assertEqual(_objective_correction({
            "exercise_type": "multiple_choice",
            "exercise_data": {"choices": [{"id": "A", "text": "Wrong"}, {"id": "B", "text": "Right"}], "correct_choice": "B"},
            "rubric": [{"criterion": "Selects the correct answer", "points": 10}],
        }, "A", "en").error_category, "incomplete")

    def test_numerical_answer_checks_result_tolerance_and_unit(self) -> None:
        exercise = {
            "exercise_type": "numerical",
            "exercise_data": {"numeric_expression": "10 / 4", "numeric_tolerance": "0.01", "numeric_unit": "m"},
            "rubric": [{"criterion": "Calculates the distance", "points": 10}],
        }
        self.assertEqual(_objective_correction(exercise, "2,5 m", "en").criterion_feedback[0].awarded_points, 10)
        self.assertEqual(_objective_correction(exercise, "2.5 cm", "en").criterion_feedback[0].awarded_points, 0)
        self.assertEqual(_parse_numeric_submission("2,5 m")[0], 2.5)

    def test_memoire_records_rubric_evidence_and_mastery(self) -> None:
        profile = _ensure_profile_shape(None, "session-1", "user-1")
        updated = _apply_exercise_correction(
            profile,
            {
                "total_score": 9,
                "max_score": 10,
                "error_category": "partial",
                "hints_used": 1,
                "criterion_feedback": [{"criterion": "Explains role", "awarded_points": 4, "possible_points": 5}],
            },
            {"id": "exercise-1", "concept": "Project manager", "bloom_level": "understand"},
        )
        self.assertIn("Project manager", updated["mastered_concepts"])
        evidence = updated["exercise_performance"][-1]
        self.assertEqual(evidence["total_score"], 9)
        self.assertEqual(evidence["criterion_feedback"][0]["criterion"], "Explains role")


if __name__ == "__main__":
    unittest.main()
