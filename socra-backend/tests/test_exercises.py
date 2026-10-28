"""Unit checks for explicit exercise routing and owner-guarded generation."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from api.websocket import _authenticate_exercise_request, _display_message
from agents.exercise_generator import (
    GENERATOR_PROMPT,
    _bind_citations_to_sources,
    _is_duplicate_question,
    _latest_exercise_scope,
    _requested_exercise_type,
    _requested_option_count,
    _validate_type_specific,
    calculate_safe_expression,
)
from graph.orchestrator import _route_entry
from models.schemas import GeneratedExercise, ExerciseRubricCriterion
from agents.sql_runner import run_readonly_sql, sql_results_match


class ExerciseFlowTests(unittest.TestCase):
    def test_generator_prompt_formats_literal_citation_schema(self) -> None:
        prompt = GENERATOR_PROMPT.format(language="English")
        self.assertIn('{"source_index": 1}', prompt)
        self.assertIn("A previous exercise", prompt)
        self.assertIn("is not a restriction", prompt)
        self.assertIn("vary questions across", prompt)

    def test_requested_exercise_type_defaults_to_short_answer(self) -> None:
        self.assertEqual(_requested_exercise_type("Ask me anything about the course"), "short_answer")
        self.assertEqual(_requested_exercise_type("Give me a QCM about databases"), "multiple_choice")
        self.assertEqual(_requested_exercise_type("Give me a numerical exercise"), "numerical")
        self.assertEqual(_requested_exercise_type("Give me a Python coding exercise"), "code")
        self.assertEqual(_requested_exercise_type("Give me an SQL query exercise"), "sql")
        self.assertEqual(_requested_exercise_type("Create a code-writing task for Python"), "code")
        self.assertEqual(_requested_option_count("Give me a multiple-choice question with four options"), 4)
        self.assertEqual(_requested_option_count("Give me a QCM with 3 choices"), 3)

    def test_numerical_expression_is_deterministic_and_rejects_code(self) -> None:
        self.assertEqual(calculate_safe_expression("(12 + 8) / 4"), 5)
        for expression in ("__import__('os')", "1 / 0", "2 ** 99"):
            with self.assertRaises(ValueError):
                calculate_safe_expression(expression)

    def test_sql_runner_returns_rows_and_rejects_writes_and_unsafe_functions(self) -> None:
        setup = [
            "CREATE TABLE people (id INTEGER, name TEXT)",
            "INSERT INTO people VALUES (1, 'Ada'), (2, 'Lin')",
        ]
        expected = run_readonly_sql(setup, "SELECT name FROM people ORDER BY id")
        actual = run_readonly_sql(setup, "SELECT name FROM people ORDER BY id")
        self.assertEqual(expected["rows"], [["Ada"], ["Lin"]])
        self.assertTrue(sql_results_match(expected, actual, ordered=True))
        self.assertFalse(sql_results_match(expected, {"columns": ["name"], "rows": [["Lin"], ["Ada"]]}, ordered=True))
        for query in ("DELETE FROM people", "SELECT load_extension('x')", "SELECT * FROM sqlite_master"):
            with self.subTest(query=query), self.assertRaises(ValueError):
                run_readonly_sql(setup, query)

    def test_generated_code_and_sql_exercises_are_checked_before_display(self) -> None:
        code = GeneratedExercise(
            exercise_type="code", concept="Python functions", difficulty="beginner",
            bloom_level="apply", prompt="Write a function that doubles an integer value.",
            citations=[{"document_id": "00000000-0000-0000-0000-000000000001", "filename": "course.pdf", "page_number": 1, "excerpt": "Python functions accept input values and return computed results."}],
            hints=["Start with a function definition.", "Multiply the input value by two."],
            expected_answer="def double(value):\n    return value * 2",
            rubric=[ExerciseRubricCriterion(criterion="Returns twice the input", points=10)],
            common_mistakes=[], code_language="python",
        )
        _validate_type_specific(code)

        invalid_code = code.model_copy(update={"expected_answer": "def double(:\n    pass"})
        with self.assertRaisesRegex(ValueError, "invalid Python syntax"):
            _validate_type_specific(invalid_code)

        sql = GeneratedExercise(
            exercise_type="sql", concept="Filtering rows", difficulty="beginner",
            bloom_level="apply", prompt="Select the names of people older than 18, ordered by name.",
            citations=[{"document_id": "00000000-0000-0000-0000-000000000001", "filename": "course.pdf", "page_number": 1, "excerpt": "SQL SELECT queries can filter rows with a WHERE clause."}],
            hints=["Use SELECT with a WHERE clause.", "Sort the result with ORDER BY."],
            expected_answer="SELECT name FROM people WHERE age > 18 ORDER BY name",
            rubric=[ExerciseRubricCriterion(criterion="Returns the correct ordered names", points=10)],
            common_mistakes=[], sql_setup=["CREATE TABLE people (name TEXT, age INTEGER)", "INSERT INTO people VALUES ('Ada', 20), ('Lin', 17)"],
        )
        _validate_type_specific(sql)
        self.assertEqual(sql.sql_expected_rows, [["Ada"]])

    def test_repeat_check_rejects_lightly_reworded_question(self) -> None:
        previous = "Based on the provided CV, what is the name of the company where Badr-Eddine completed his internship from July 1 to August 31?"
        repeated = "According to the CV, what was the name of the company where Badr-Eddine completed his internship from July 1 to August 31?"
        self.assertTrue(_is_duplicate_question(repeated, [previous]))

    def test_repeat_check_allows_a_different_question_on_same_topic(self) -> None:
        previous = "What company hosted Badr-Eddine's end-of-year internship?"
        different = "Which backend technologies did he use to build the Delege project?"
        self.assertFalse(_is_duplicate_question(different, [previous]))

    def test_follow_up_keeps_latest_exercise_request_after_explain_mode_history(self) -> None:
        history = [
            {"role": "user", "content": "Ask me anything about this"},
            {"role": "assistant", "content": "Course explanation ready."},
            {"role": "user", "content": "give me questions about my internships"},
            {"role": "assistant", "content": "Exercise ready: Professional Internship Experience."},
            {"role": "user", "content": "That would be TalentMind"},
            {"role": "assistant", "content": "You scored 10 out of 10."},
            {"role": "user", "content": "Generate another question"},
        ]
        self.assertEqual(
            _latest_exercise_scope(history),
            "give me questions about my internships",
        )

    def test_follow_up_scope_skips_legacy_generate_button_prompts(self) -> None:
        history = [
            {"role": "user", "content": "Give me questions about my internships"},
            {"role": "assistant", "content": "Exercise ready: Internships."},
            {"role": "user", "content": "Give me a different short-answer question about Professional Experience. Avoid repeating the previous question."},
            {"role": "assistant", "content": "Exercise ready: Projects."},
            {"role": "user", "content": "Generate another question"},
        ]
        self.assertEqual(_latest_exercise_scope(history), "Give me questions about my internships")

    def test_internal_action_prompt_can_have_a_short_saved_display_label(self) -> None:
        internal = "Generate a question from everywhere. " + "Long internal instructions. " * 30
        self.assertEqual(_display_message("Generate another question", internal), "Generate another question")
        self.assertEqual(_display_message(None, "A normal prompt"), "A normal prompt")
        self.assertLessEqual(len(_display_message("x" * 600, internal)), 500)

    def test_exercise_citations_accept_common_index_shapes_but_bind_retrieved_data(self) -> None:
        chunks = [{
            "document_id": "doc-1", "filename": "Course.pdf", "page_number": 7,
            "content": "Course excerpt about project management responsibilities.",
        }]
        for citation in (1, "[1]", "Source 1", {"source_index": "1"}, {"page_number": 7, "filename": "Course.pdf"}):
            result = _bind_citations_to_sources({"citations": [citation]}, chunks)
            self.assertEqual(result["citations"][0]["page_number"], 7)
        for payload in (
            {"source_index": 1},
            {"citations": {"sourceIndex": 1}},
            {"citations": [{"id": 1}]},
        ):
            result = _bind_citations_to_sources(payload, chunks)
            self.assertEqual(result["citations"][0]["document_id"], "doc-1")

    def test_exercise_citation_rejects_unmatched_index(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not identify|does not match"):
            _bind_citations_to_sources({"citations": ["Source 9"]}, [{"page_number": 7}])

    def test_socratic_route_remains_the_default(self) -> None:
        self.assertEqual(_route_entry({"is_first_message": True}), "diagnostiqueur")
        self.assertEqual(_route_entry({"is_first_message": False}), "tuteur_socratique")

    def test_exercise_mode_routes_explicitly(self) -> None:
        self.assertEqual(
            _route_entry({"mode": "exercise", "is_first_message": True}),
            "exercise_generator",
        )

    def test_explain_mode_routes_explicitly(self) -> None:
        self.assertEqual(
            _route_entry({"mode": "explain", "is_first_message": False}),
            "explicateur",
        )

    def test_attempt_mode_routes_to_correcteur(self) -> None:
        self.assertEqual(
            _route_entry({"mode": "correct", "is_first_message": False}),
            "correcteur",
        )

    def test_exercise_owner_check_accepts_only_session_course_owner(self) -> None:
        client = Mock()
        client.auth.get_user.return_value = SimpleNamespace(
            user=SimpleNamespace(id="owner-1")
        )
        responses = [
            SimpleNamespace(data={"course_id": "course-1"}),
            SimpleNamespace(data={"user_id": "owner-1"}),
        ]
        client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.side_effect = responses
        with patch("api.websocket.get_supabase", return_value=client):
            self.assertEqual(
                _authenticate_exercise_request("session-1", "course-1", "valid-jwt"),
                "owner-1",
            )

    def test_exercise_owner_check_rejects_missing_token(self) -> None:
        with self.assertRaisesRegex(ValueError, "Sign in"):
            _authenticate_exercise_request("session-1", "course-1", "")

    def test_exercise_owner_check_rejects_a_different_session_course(self) -> None:
        client = Mock()
        client.auth.get_user.return_value = SimpleNamespace(
            user=SimpleNamespace(id="owner-1")
        )
        client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = SimpleNamespace(
            data={"course_id": "another-course"}
        )
        with patch("api.websocket.get_supabase", return_value=client):
            with self.assertRaisesRegex(ValueError, "does not belong"):
                _authenticate_exercise_request("session-1", "course-1", "valid-jwt")


if __name__ == "__main__":
    unittest.main()
