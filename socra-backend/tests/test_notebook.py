from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from agents.notebook import load_notebook_context, parse_cards, run_notebook
from graph.orchestrator import _route_entry


class NotebookTests(IsolatedAsyncioTestCase):
    def test_context_requires_owner_and_matching_session(self):
        note = {"title": "A", "content": "Before\nAn owned line", "version": 2, "course_id": None}
        table = Mock()
        table.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(data=[])
        db = SimpleNamespace(table=lambda _: table)
        with patch("agents.notebook.get_supabase", return_value=db), patch("agents.notebook._one") as find:
            find.side_effect = [None, note, None, note, {"note_id": "n"}, note, {"note_id": "n"}]
            self.assertIsNone(load_notebook_context("other", "s", "n", "", "why"))
            self.assertIsNone(load_notebook_context("owner", "wrong", "n", "", "why"))
            context = load_notebook_context("owner", "s", "n", "An owned line", "why")
            self.assertEqual(context["excerpt"], "An owned line")
            with self.assertRaises(ValueError):
                load_notebook_context("owner", "s", "n", "invented", "why")
            self.assertEqual(find.call_args_list[0].kwargs, {"id": "n", "user_id": "other"})

    async def test_suggestion_streams_only_proposed_content(self):
        emitted = []

        async def stream(_messages):
            yield SimpleNamespace(content="New ")
            yield SimpleNamespace(content="sentence.")

        async def delta(text):
            emitted.append(text)

        state = {"notebook_context": {"title": "A", "excerpt": "Before", "course_id": None},
                 "notebook_action": "improve", "student_message": "Improve", "tutor_delta": delta}
        with patch("agents.notebook.get_chat_llm", return_value=SimpleNamespace(astream=stream)), \
                patch("agents.notebook.get_supabase") as database:
            result = await run_notebook(state)
        self.assertEqual(result["notebook_result"], "New sentence.")
        self.assertEqual(emitted, ["New ", "sentence."])
        database.assert_not_called()

    def test_quiz_reuses_exercise_and_card_payload_is_validated(self):
        self.assertEqual(_route_entry({"mode": "exercise", "notebook_action": "quiz"}), "exercise_generator")
        self.assertEqual(_route_entry({"mode": "explain", "notebook_action": "ask"}), "notebook")
        self.assertEqual(parse_cards('{"cards":[{"question":" Q ","answer":" A "}]}'),
                         [{"question": "Q", "answer": "A"}])
        with self.assertRaises(ValueError):
            parse_cards('{"cards":[{"question":"Q"}]}')

    async def test_flashcard_generation_persists_the_note_version(self):
        table = Mock()
        state = {"notebook_context": {"id": "n", "version": 5, "title": "Title", "excerpt": "Reference passage"},
                 "notebook_action": "flashcards", "student_message": "Generate flashcards"}
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(
            content='{"cards":[{"question":"Why?","answer":"Because."}]}')))
        with patch("agents.notebook.get_chat_llm", return_value=model), \
                patch("agents.notebook.get_supabase", return_value=SimpleNamespace(table=lambda _: table)):
            result = await run_notebook(state)
        self.assertEqual(result["notebook_result"], "Flashcards are ready.")
        table.upsert.assert_called_once_with({"note_id": "n", "note_version": 5,
                                             "cards": [{"question": "Why?", "answer": "Because."}]})
        table.upsert.return_value.execute.assert_called_once()
