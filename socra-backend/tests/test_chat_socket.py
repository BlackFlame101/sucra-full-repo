"""Exercise the actual LangGraph and FastAPI WebSocket with fake providers/DB."""
from __future__ import annotations

import asyncio
import threading
import unittest
from contextlib import ExitStack, asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.genai.errors import ClientError, ServerError
from langchain_core.messages import AIMessageChunk

from api import websocket
from graph import nodes

SOURCE = {"id": "chunk", "document_id": str(uuid4()), "filename": "fixture.pdf",
          "page_number": 3, "content": "A model is a simplified representation.", "similarity": 0.9}


@asynccontextmanager
async def lease(*_):
    yield True


class SocketTests(unittest.TestCase):
    def setUp(self):
        self.session = str(uuid4())
        self.course = str(uuid4())
        self.rows = {}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        app = FastAPI()
        app.include_router(websocket.router)
        self.client = TestClient(app)
        self.auth = self.stack.enter_context(patch.object(websocket, "_authenticate_exercise_request", return_value="owner"))
        self.stack.enter_context(patch.object(websocket, "session_turn", lease))
        self.exam = self.stack.enter_context(patch.object(websocket, "get_exam_for_session", return_value=None))
        self.stack.enter_context(patch.object(websocket.chat_limit, "allow", return_value=True))
        self.stack.enter_context(patch.object(websocket.auth_limit, "allow", return_value=True))
        self.quota = self.stack.enter_context(patch.object(websocket, "consume_study_quota", AsyncMock(return_value=True)))
        self.stack.enter_context(patch.object(websocket.messages_db, "merge_message_metadata", side_effect=self.merge))
        self.load = self.stack.enter_context(patch.object(
            websocket.messages_db, "load_study_turn",
            side_effect=lambda _, owner, request: {
                "recent": list(self.rows.values()), "language": "en", "profile": None,
                "diagnostic": {"topic": "Modeling"},
                "has_assistant": any(role == "assistant" for role, _ in self.rows),
                "request_messages": [row for (role, key), row in self.rows.items() if key == request],
            },
        ))
        self.stack.enter_context(patch.object(websocket.messages_db, "get_turn_message",
            side_effect=lambda _session, role, request: self.rows.get((role, request))))
        self.stack.enter_context(patch.object(websocket.messages_db, "save_message", side_effect=self.save))
        self.stack.enter_context(patch.object(websocket.messages_db, "touch_session"))

    def save(self, session, role, text, metadata):
        request = metadata["request_id"]
        return self.rows.setdefault((role, request),
            {"id": str(uuid4()), "role": role, "content": text, "metadata": metadata})

    def merge(self, message_id, metadata):
        for row in self.rows.values():
            if row["id"] == message_id:
                row["metadata"].update(metadata)

    def test_quota_rejection_happens_before_generation(self):
        self.quota.return_value = False
        socket = self.connect()
        self.send(socket, mode="explain")
        self.assertEqual(self.until(socket, "done")[-1]["content"]["code"], "REQUEST_RATE_LIMITED")
        self.assertFalse(self.rows)
        self.quota.assert_awaited_once_with("owner", "explain")

    def test_notebook_chat_streams_and_replays_without_reloading_changed_selection(self):
        note_id = str(uuid4())
        note = {"id": note_id, "title": "Models", "excerpt": "A simplified representation.", "course_id": None}
        context = self.stack.enter_context(patch.object(websocket, "load_notebook_context", return_value=note))

        async def model_stream(_):
            yield AIMessageChunk(content="A model highlights selected details.")

        model = SimpleNamespace(astream=Mock(side_effect=model_stream))
        self.stack.enter_context(patch("agents.notebook.get_chat_llm", return_value=model))
        ws = self.connect()
        payload = {"id": note_id, "action": "ask", "selection": note["excerpt"]}
        request = self.send(ws, mode="explain", notebook=payload)
        events = self.until(ws, "done")
        self.assertIn("content_delta", [event["type"] for event in events])
        self.assertEqual(self.rows[("assistant", request)]["metadata"]["notebook_action"], "ask")
        context.side_effect = ValueError("The selection changed.")
        ws.close()
        ws = self.connect()
        self.send(ws, mode="explain", request=request, notebook=payload)
        replay = self.until(ws, "done")
        self.assertIn("response_complete", [event["type"] for event in replay])
        context.assert_called_once()
        model.astream.assert_called_once()

    def connect(self, version=2):
        ws = self.stack.enter_context(self.client.websocket_connect(f"/ws/chat/{self.session}"))
        ws.send_json({"action": "authenticate", "courseId": self.course, "accessToken": "fake", "version": version})
        self.assertEqual(ws.receive_json()["type"], "connected")
        return ws

    def send(self, ws, mode="socratic", request=None, **values):
        request = request or str(uuid4())
        ws.send_json({"requestId": request, "courseId": self.course, "sessionId": self.session,
                      "message": "I understand that a model is a simplified representation.",
                      "mode": mode, **values})
        return request

    def until(self, ws, end):
        events = []
        while True:
            event = ws.receive_json()
            events.append(event)
            if event["type"] in {end, "error"}:
                return events

    def test_rejects_before_history_and_rechecks_each_action(self):
        self.auth.side_effect = ValueError("invalid")
        with self.client.websocket_connect(f"/ws/chat/{self.session}") as ws:
            ws.send_json({"action": "authenticate", "version": 2, "courseId": self.course, "accessToken": "bad"})
            self.assertEqual(ws.receive_json()["content"]["code"], "AUTH_REQUIRED")
        self.load.assert_not_called()
        self.auth.side_effect = ["owner", ValueError("course ownership changed")]
        ws = self.connect()
        self.send(ws)
        self.assertEqual(self.until(ws, "done")[-1]["content"]["code"], "AUTH_REQUIRED")
        self.load.assert_not_called()

    def test_socratic_first_text_and_commit_precede_follow_up_and_retry_replays(self):
        stream_release = threading.Event()
        evaluation_release = threading.Event()
        self.addCleanup(stream_release.set)
        self.addCleanup(evaluation_release.set)

        async def model_stream(_):
            yield AIMessageChunk(content=[{"type": "reasoning", "text": "private reasoning"}])
            yield AIMessageChunk(content="Think ")
            await asyncio.to_thread(stream_release.wait, 4)
            yield AIMessageChunk(content="about the data.")

        async def evaluate(state):
            await asyncio.to_thread(evaluation_release.wait, 4)
            return {**state, "evaluation": {"key_terms": ["data"]}}

        model = Mock()
        model.with_config.return_value = model
        model.astream.side_effect = model_stream
        self.stack.enter_context(patch("agents.tuteur_socratique.get_chat_llm", return_value=model))
        self.stack.enter_context(patch("agents.tuteur_socratique.retrieve_chunks", AsyncMock(return_value=[])))
        self.stack.enter_context(patch.object(nodes, "run_evaluateur", side_effect=evaluate))
        self.stack.enter_context(patch.object(nodes, "run_memoire", side_effect=lambda state: state))
        ws = self.connect()
        request = self.send(ws)
        first = self.until(ws, "content_delta")
        self.assertEqual(first[-1]["content"]["text"], "Think ")
        self.assertNotIn(("assistant", request), self.rows)
        stream_release.set()
        second = self.until(ws, "response_complete")
        self.assertEqual(second[-1]["type"], "response_complete")
        self.assertEqual(self.rows[("assistant", request)]["content"], "Think about the data.")
        self.assertNotIn("private reasoning", str(first + second))
        evaluation_release.set()
        last = self.until(ws, "done")
        self.assertEqual([event["type"] for event in last], ["context_update", "turn_finalized", "done"])
        self.assertEqual([e["sequence"] for e in first + second + last], list(range(1, len(first + second + last) + 1)))
        ws.close()
        ws = self.connect()
        self.send(ws, request=request)
        replay = self.until(ws, "done")
        self.assertEqual(len(self.rows), 2)
        self.assertEqual(self.rows[("assistant", request)]["metadata"]["course_context"]["key_terms"], ["data"])
        self.assertIn("context_update", [event["type"] for event in replay])
        self.assertEqual(model.astream.call_count, 1)
        self.assertEqual([e["content"]["message_id"] for e in replay if e["type"] == "response_complete"],
                         [self.rows[("assistant", request)]["id"]])

    def test_cancellation_leaves_no_final_answer(self):
        cancelled = threading.Event()

        async def tutor(state):
            try:
                await state["tutor_delta"]("Partial")
                await asyncio.sleep(20)
            finally:
                cancelled.set()

        self.stack.enter_context(patch.object(nodes, "run_tuteur", side_effect=tutor))
        ws = self.connect()
        request = self.send(ws)
        self.assertEqual(self.until(ws, "content_delta")[-1]["content"]["text"], "Partial")
        ws.send_json({"action": "cancel", "requestId": request})
        self.assertEqual(self.until(ws, "cancelled")[-1]["type"], "cancelled")
        self.assertTrue(cancelled.wait(3))
        self.assertNotIn(("assistant", request), self.rows)

    def test_disconnect_cancels_an_uncommitted_stream(self):
        stopped = threading.Event()

        async def tutor(state):
            try:
                await state["tutor_delta"]("Partial")
                await asyncio.sleep(20)
            finally:
                stopped.set()

        self.stack.enter_context(patch.object(nodes, "run_tuteur", side_effect=tutor))
        ws = self.connect()
        request = self.send(ws)
        self.until(ws, "content_delta")
        ws.close()
        self.assertTrue(stopped.wait(3))
        self.assertNotIn(("assistant", request), self.rows)

    def test_explain_streams_before_a_validated_card_and_binds_citations(self):
        release = threading.Event()
        self.addCleanup(release.set)

        async def stream(_):
            yield AIMessageChunk(content='{"definition":"A model')
            await asyncio.to_thread(release.wait, 4)
            yield AIMessageChunk(content=(' is a simplified representation.","intuition":"Think of a map.",'
                  '"course_example":"A small map.","common_pitfalls":[],"sections":[{"heading":"Example","content":"A detailed example explains the model."}],'
                  '"citations":[{"source_index":1}],"check_question":"What is a model?"}'))

        model = SimpleNamespace(astream=stream)
        self.stack.enter_context(patch("agents.explicateur.get_chat_llm", return_value=model))
        self.stack.enter_context(patch("agents.explicateur.retrieve_summary_guided_chunks", AsyncMock(return_value=[SOURCE])))
        ws = self.connect()
        request = self.send(ws, mode="explain", message="Explain modeling")
        events = self.until(ws, "content_delta")
        self.assertEqual(events[-1]["content"], {"text": "\n\nA model", "preview": True})
        self.assertNotIn(("assistant", request), self.rows)
        release.set()
        events = self.until(ws, "done")
        card = next(e["content"]["card"] for e in events if e["type"] == "card_ready")
        self.assertEqual(card["citations"][0]["page_number"], 3)
        self.assertEqual(card["check_question"], "What is a model?")
        self.assertEqual(self.rows[("assistant", request)]["metadata"]["explanation"], card)

    def test_v1_receives_token_and_done(self):
        async def tutor(state):
            await state["tutor_delta"]("Think.")
            return {**state, "tutor_signal": {"response_text": "Think."}}

        self.stack.enter_context(patch.object(nodes, "run_tuteur", side_effect=tutor))
        ws = self.connect(version=1)
        self.send(ws)
        events = self.until(ws, "done")
        self.assertEqual([e["content"] for e in events if e["type"] == "token"], ["Think."])
        self.assertEqual(events[-1]["type"], "done")

    def test_explain_restarts_an_interrupted_provider_stream_and_saves_one_card(self):
        calls = 0

        async def stream(_):
            nonlocal calls
            calls += 1
            if calls == 1:
                yield AIMessageChunk(content='{"definition":"Interrupted draft')
                raise ServerError(503, {"error": {"status": "UNAVAILABLE"}})
            yield AIMessageChunk(content=('{"definition":"A model is a simplified representation.",'
                  '"intuition":"Think of a map.","course_example":"","common_pitfalls":[],'
                  '"sections":[{"heading":"Example","content":"A detailed example explains the model."}],'
                  '"citations":[1],"check_question":"What is a model?"}'))

        self.stack.enter_context(patch("agents.explicateur.get_chat_llm", return_value=SimpleNamespace(astream=stream)))
        self.stack.enter_context(patch("agents.explicateur.retrieve_summary_guided_chunks", AsyncMock(return_value=[SOURCE])))
        ws = self.connect()
        request = self.send(ws, mode="explain", message="Explain modeling")
        events = self.until(ws, "done")
        self.assertEqual(calls, 2)
        self.assertEqual(events[-1]["type"], "done")
        previews = [event["content"]["text"] for event in events if event["type"] == "content_delta"]
        self.assertEqual(previews[:2], ["\n\nInterrupted draft", None])
        self.assertIn("A model is a simplified representation.", previews[2])
        self.assertTrue(any("Retrying" in event["content"]["stage"] for event in events if event["type"] == "progress"))
        cards = [event["content"]["card"] for event in events if event["type"] == "card_ready"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["citations"][0]["page_number"], 3)
        self.assertEqual(self.rows[("assistant", request)]["metadata"]["explanation"], cards[0])

    def test_explain_keeps_the_draft_if_the_retry_fails_before_replacement(self):
        calls = 0

        async def stream(_):
            nonlocal calls
            calls += 1
            if calls == 1:
                yield AIMessageChunk(content='{"definition":"Interrupted draft')
            raise ServerError(500, {"error": {"status": "INTERNAL"}})

        self.stack.enter_context(patch("agents.explicateur.get_chat_llm", return_value=SimpleNamespace(astream=stream)))
        self.stack.enter_context(patch("agents.explicateur.retrieve_summary_guided_chunks", AsyncMock(return_value=[SOURCE])))
        ws = self.connect()
        request = self.send(ws, mode="explain", message="Explain modeling")
        events = self.until(ws, "error")
        self.assertEqual(calls, 2)
        self.assertEqual(events[-1]["content"]["code"], "PROVIDER_UNAVAILABLE")
        self.assertEqual([event["content"]["text"] for event in events if event["type"] == "content_delta"],
                         ["\n\nInterrupted draft"])
        self.assertNotIn(("assistant", request), self.rows)

    def test_explain_does_not_retry_a_rejected_api_key(self):
        async def stream(_):
            yield AIMessageChunk(content='{"definition":"Interrupted draft')
            raise ClientError(401, {"error": {"status": "UNAUTHENTICATED"}})

        model = SimpleNamespace(astream=Mock(side_effect=stream))
        self.stack.enter_context(patch("agents.explicateur.get_chat_llm", return_value=model))
        self.stack.enter_context(patch("agents.explicateur.retrieve_summary_guided_chunks", AsyncMock(return_value=[SOURCE])))
        ws = self.connect()
        request = self.send(ws, mode="explain", message="Explain modeling")
        events = self.until(ws, "error")
        model.astream.assert_called_once()
        self.assertEqual(events[-1]["content"]["code"], "API_KEY_INVALID")
        self.assertNotIn(("assistant", request), self.rows)

    def test_practice_stream_contains_only_public_card_fields(self):
        async def practice(state):
            await state["progress"]("Generating a course-based exercise.")
            await state["progress"]("Verifying the exercise against your course.")
            return {**state, "exercise": {"id": "exercise", "concept": "Modeling", "prompt": "Explain models."},
                    "internal_candidate": {"rubric": "private rubric", "expected_answer": "private answer"}}

        self.stack.enter_context(patch.object(nodes, "run_exercise_generator", side_effect=practice))
        ws = self.connect()
        request = self.send(ws, mode="exercise")
        events = self.until(ws, "done")
        self.assertNotIn("content_delta", [e["type"] for e in events])
        self.assertNotIn("private rubric", str(events))
        self.assertNotIn("private answer", str(events))
        self.assertEqual(self.rows[("assistant", request)]["metadata"]["exercise"]["id"], "exercise")

    def test_exam_session_cannot_use_practice_actions(self):
        self.exam.return_value = {"status": "in_progress"}
        lookup = self.stack.enter_context(patch.object(websocket, "get_exercise_for_owner"))
        ws = self.connect()
        self.send(ws, mode="exercise", action="submit_attempt", exerciseId=str(uuid4()), answer="Guess")
        self.assertEqual(self.until(ws, "done")[-1]["type"], "error")
        lookup.assert_not_called()
