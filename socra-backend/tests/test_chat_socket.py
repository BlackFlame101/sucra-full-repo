"""Exercise the actual LangGraph and FastAPI WebSocket with fake providers/DB."""
from __future__ import annotations

import asyncio
import json
import os
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
LEASE = str(uuid4())


@asynccontextmanager
async def lease(*_):
    yield LEASE


class SocketTests(unittest.TestCase):
    def setUp(self):
        self.session = str(uuid4())
        self.course = str(uuid4())
        self.rows = {}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "EXPLAIN_TASK_MODES": "0", "EXPLAIN_MULTI_EXERCISE_BATCHING": "0",
        }))
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

    def test_document_v3_uses_fenced_finalization_and_replays_the_same_markdown(self):
        from agents import explain_document
        from tests.test_educational_document import FixtureProvider, MemoryCheckpoint, source

        bundle = source([{"text": "Part 1 – Model\nExercise A – Validation\nA reliable validation protocol."}])
        provider = FixtureProvider()
        self.enterContext(patch.dict(os.environ, {"EXPLAIN_DOCUMENT_MODE": "true",
                                                 "SOCRA_EXPLAIN_REVIEW_MODEL": "gemini-3.5-flash-lite"}))
        self.enterContext(patch.object(explain_document, "_load_source", AsyncMock(return_value=bundle)))
        self.enterContext(patch.object(explain_document, "get_chat_llm", provider.model))
        current = self.enterContext(patch.object(websocket, "source_is_current", return_value=True))
        calls = []

        class Checkpoint(MemoryCheckpoint):
            def __init__(self, inquiry, course, owner, request, prompt, *, lease):
                super().__init__()
                assert lease == LEASE
                self.inquiry = inquiry
                self.request = request

            async def finalize(inner, content, metadata):
                calls.append(metadata["explanation"])
                return self.save(inner.inquiry, "assistant", content, metadata)

        self.enterContext(patch.object(websocket, "TurnCheckpoint", Checkpoint))
        socket = self.connect()
        message = "Solve Part 1 of this lab."
        request = self.send(socket, mode="explain", message=message, model="gemini-3.5-flash-lite", provider="google")
        events = self.until(socket, "done")
        snapshots = [event["content"] for event in events if event["type"] == "document_snapshot"]
        self.assertTrue(any(card["sections"] for card in snapshots))
        final = next(event["content"]["card"] for event in events if event["type"] == "card_ready")
        self.assertEqual(calls, [final])
        self.assertEqual(final["state"], "approved")
        self.assertTrue(all(card["document_id"] == final["document_id"] for card in snapshots))
        self.assertEqual(self.rows[("assistant", request)]["metadata"]["explanation"], final)
        socket.close()
        socket = self.connect()
        options = dict(mode="explain", request=request, message=message, model="gemini-3.5-flash-lite", provider="google")
        self.send(socket, **options)
        replay = next(event["content"]["card"] for event in self.until(socket, "done") if event["type"] == "card_ready")
        self.assertEqual(replay, final)
        current.return_value = False
        self.send(socket, **options)
        archived = next(event["content"]["card"] for event in self.until(socket, "done") if event["type"] == "card_ready")
        self.assertEqual(archived, final | {"historical_source": True})
        self.assertEqual(provider.calls, ["plan", "generate", "review"])

    def test_unit_progress_restore_after_reconnect_uses_owned_current_checkpoint(self):
        from db.explain_progress import KEY

        reference = str(uuid4())
        self.enterContext(patch.dict(os.environ, {"EXPLAIN_UNIT_PIPELINE": "true"}))
        anchor = {"document_id": SOURCE["document_id"], "source_hash": "text", "generation": 2}
        row = {"stage": "ready", "output": {"logical_id": "shap", "coverage": "partial"},
               "change_log": [{"old_quote": "old", "new_quote": "new", "severity": "high"}]}
        self.save(self.session, "user", "Study SHAP",
                  {"request_id": reference, KEY: anchor | {"versions": [row]}})
        source = self.enterContext(patch.object(websocket, "source_is_current", return_value=True))
        socket = self.connect()
        socket.close()
        socket = self.connect()
        self.send(socket, mode="explain", action="restore_unit_progress", fromRequestId=reference)
        events = self.until(socket, "done")
        ready = next(event for event in events if event["type"] == "unit_ready")
        self.assertTrue(ready["content"]["replayed"])
        correction = next(event for event in events if event["type"] == "unit_correction")
        self.assertEqual(correction["content"]["severity"], "high")
        self.assertLess(ready["sequence"], correction["sequence"])
        self.quota.assert_not_called()
        self.assertEqual(source.call_args.args[1:], (self.course, "owner"))
        source.return_value = False
        self.send(socket, mode="explain", action="restore_unit_progress", fromRequestId=reference)
        self.assertEqual(self.until(socket, "done")[-1]["type"], "error")
        self.load.return_value = None
        self.load.side_effect = None
        self.send(socket, mode="explain", action="restore_unit_progress", fromRequestId=reference)
        self.assertEqual(self.until(socket, "done")[-1]["type"], "error")
        self.assertEqual(source.call_count, 2)

    def test_v2_unit_card_and_legacy_continue_use_the_actual_chat_graph(self):
        from agents import explicateur
        from db.explain_progress import KEY
        from tests.test_explain_unit_generation import block, records_for

        units, raw, evidence = records_for([
            {"text": "II.1 SHAP\nShapley averages marginal contributions across variable orders."},
            {"text": "II.2 LIME\nLIME weights nearby observations to fit a local explanation."},
        ])
        document = {"id": SOURCE["document_id"], "filename": "Course.pdf", "page_count": 2,
                    "content_hash": "hash", "index_generation": 4}
        rows = [SOURCE | row for row in raw]
        self.enterContext(patch.dict(os.environ, {"EXPLAIN_UNIT_PIPELINE": "true", "EXPLAIN_INTENT_PLANS": "true",
                                                  "SOCRA_EXPLAIN_UNIT_MAX_LEARNING_CALLS": "1"}))
        for name, result in {"retrieve_summary_guided_chunks": rows, "course_documents": [document],
                             "document_inventory_chunks": (rows, "full_document"),
                             "load_or_queue_unit_map": {"text_hash": "map", "units": units},
                             "load_prepared_evidence": evidence, "queue_unit_evidence": None}.items():
            self.enterContext(patch.object(explicateur, name, AsyncMock(return_value=result)))

        reject = threading.Event()

        def persist(name, params):
            self.assertEqual(name, "append_explain_checkpoint")
            self.assertEqual(params["p_lease"], LEASE)
            self.assertEqual(params["p_document"], document["id"])
            self.assertEqual(params["p_generation"], document["index_generation"])
            self.assertEqual(params["p_source_hash"], document["content_hash"])
            request = params["p_request"]
            prompt = self.rows[("user", request)]
            self.assertEqual(prompt["id"], params["p_message"])
            data = prompt["metadata"].get(KEY)
            self.assertEqual((data or {}).get("revision"), params["p_expected_revision"])
            if reject.is_set():
                return False
            if final := params["p_final"]:
                return self.save(self.session, "assistant", final["content"], final["metadata"])
            if data is None:
                data = {"request_id": request, "document_id": document["id"], "source_hash": document["content_hash"],
                        "generation": document["index_generation"], "revision": 0, "versions": [], "calls": []}
                prompt["metadata"][KEY] = data
            data["revision"] += 1
            if params["p_call"]:
                data["calls"].append(params["p_call"])
            if params["p_version"]:
                data["versions"].append(params["p_version"])
            return True

        client = Mock()
        client.rpc.side_effect = lambda name, params: Mock(
            retry=Mock(return_value=Mock(execute=lambda: SimpleNamespace(data=persist(name, params))))
        )
        self.enterContext(patch("db.explain_progress.get_supabase", return_value=client))
        self.enterContext(patch("db.explain_progress.load_checkpoints",
                                side_effect=lambda *_: [row["metadata"][KEY] for row in self.rows.values()
                                                        if KEY in row["metadata"]]))
        self.enterContext(patch.object(websocket, "source_is_current", return_value=True))

        async def stream(messages):
            quote = json.loads(messages[-1].content)["sources"][0]["quote"]
            yield AIMessageChunk(content=json.dumps({"blocks": [block("explanation", quote, [1])]}))

        model = self.enterContext(patch.object(explicateur, "get_chat_llm", return_value=SimpleNamespace(astream=stream)))
        socket = self.connect()
        request = self.send(socket, mode="explain", message="Teach me the entire course, all chapters in order.")
        events = self.until(socket, "done")
        types = [event["type"] for event in events]
        for earlier, later in zip(["prep_status", "unit_draft", "unit_checking", "unit_ready"],
                                  ["unit_draft", "unit_checking", "unit_ready", "card_ready"]):
            self.assertLess(types.index(earlier), types.index(later))
        first = self.rows[("assistant", request)]["metadata"]["explanation"]
        self.assertEqual(first["schema_version"], 2)
        self.assertEqual(first["sections"][0]["citations"][0]["page_number"], 1)

        socket.close()
        socket = self.connect()
        continuation = first["course_progress"]["next_request_id"]
        self.send(socket, mode="explain", request=continuation, continueCourseFrom=request)
        self.assertEqual(self.until(socket, "done")[-1]["type"], "done")
        next_card = self.rows[("assistant", continuation)]["metadata"]["explanation"]
        self.assertEqual([item["logical_id"] for item in next_card["units"]], [units[1]["logical_id"]])
        self.send(socket, mode="explain", request=continuation, continueCourseFrom=request)
        self.assertTrue(any(event["type"] == "unit_ready" and event["content"]["replayed"]
                            for event in self.until(socket, "done")))
        self.assertEqual(model.call_count, 2)
        deepen = next(action for action in first["learning_state"]["next_actions"]
                      if action["action"] == "deepen_unit")
        reject.set()
        self.send(socket, mode="explain", action="deepen_unit", request=deepen["request_id"],
                  fromRequestId=request, unitId=deepen["logical_id"])
        error = self.until(socket, "done")[-1]
        self.assertEqual(error["content"]["code"], "EXPLAIN_CHECKPOINT_REJECTED")
        self.assertEqual(model.call_count, 2)
        self.assertNotIn(("assistant", deepen["request_id"]), self.rows)
        self.assertNotIn(KEY, self.rows[("user", deepen["request_id"])]["metadata"])

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
        socket_exited = threading.Event()
        app = self.client.app

        async def observe_socket_exit(scope, receive, send):
            await app(scope, receive, send)
            socket_exited.set()

        # Wait for the ASGI handler as well as the cancelled tutor before
        # Starlette tears down the test portal.
        self.client = TestClient(observe_socket_exit)

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
        self.assertTrue(socket_exited.wait(3))
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

    def test_explain_explicit_pdf_preserves_streaming_and_saved_schema(self):
        self.stack.enter_context(patch.dict(os.environ, {"EXPLAIN_DOCUMENT_INVENTORY": "1"}))
        catalog = self.stack.enter_context(patch("agents.explicateur.course_documents", AsyncMock(return_value=[{
            "id": SOURCE["document_id"], "filename": SOURCE["filename"], "page_count": 3,
            "index_chunk_count": 3,
        }])))
        self.stack.enter_context(patch(
            "agents.explicateur.retrieve_summary_guided_chunks", AsyncMock(return_value=[SOURCE]),
        ))

        async def stream(_):
            yield AIMessageChunk(content=json.dumps({
                "definition": "A model is a simplified representation.",
                "intuition": "Think of a map.",
                "sections": [{"heading": "Example", "content": "A source-based example."}],
                "citations": [1],
            }))

        model = SimpleNamespace(astream=Mock(side_effect=stream))
        self.stack.enter_context(patch("agents.explicateur.get_chat_llm", return_value=model))
        ws = self.connect()
        request = self.send(ws, mode="explain", message="Explain modeling", documentId=SOURCE["document_id"])
        events = self.until(ws, "done")
        self.assertIn("content_delta", [event["type"] for event in events])
        card = next(event["content"]["card"] for event in events if event["type"] == "card_ready")
        self.assertEqual(card["citations"][0]["document_id"], SOURCE["document_id"])
        self.assertNotIn("explain_inventory", card)
        self.assertEqual(self.rows[("assistant", request)]["metadata"]["explanation"], card)
        catalog.assert_awaited_once_with(self.course, "owner")
        model.astream.assert_called_once()

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

    def test_explain_exercise_cap_notice_survives_saved_turn_replay(self):
        self.stack.enter_context(patch.dict(os.environ, {"SOCRA_EXPLAIN_MAX_EXERCISE_CALLS": "2"}))
        source = {
            **SOURCE,
            "content": "\n".join(f"Exercise {number}: Analyze the provided model." for number in range(1, 5)),
        }
        self.stack.enter_context(patch(
            "agents.explicateur.retrieve_summary_guided_chunks", AsyncMock(return_value=[source]),
        ))
        self.stack.enter_context(patch(
            "agents.explicateur.retrieve_chunks", AsyncMock(return_value=[]),
        ))

        async def stream(prompt):
            number = prompt[-1].content.split("this exercise only: Exercise ", 1)[1].split(" ", 1)[0]
            yield AIMessageChunk(content=json.dumps({
                "definition": "A model is a simplified representation.",
                "intuition": "Think of a map.",
                "sections": [{"heading": f"Exercise {number}", "content": "Analyze the model."}],
                "citations": [1],
            }))

        model = SimpleNamespace(astream=Mock(side_effect=stream))
        self.stack.enter_context(patch("agents.explicateur.get_chat_llm", return_value=model))
        ws = self.connect()
        request = self.send(ws, mode="explain", message="Solve all exercises")
        events = self.until(ws, "done")
        self.assertEqual(events[-1]["type"], "done")
        card = next(event["content"]["card"] for event in events if event["type"] == "card_ready")
        self.assertEqual(
            [section["heading"] for section in card["sections"]],
            ["Exercise 1", "Exercise 2", "Incomplete explanation"],
        )
        self.assertIn("Exercise 3, Exercise 4", card["sections"][-1]["content"])
        self.assertEqual(card["citations"][0]["document_id"], source["document_id"])

        row = self.rows[("assistant", request)]
        self.rows[("assistant", request)] = json.loads(json.dumps(row))
        ws.close()
        ws = self.connect()
        self.send(ws, mode="explain", request=request, message="Solve all exercises")
        replay = self.until(ws, "done")
        replayed = next(event["content"]["card"] for event in replay if event["type"] == "card_ready")
        self.assertEqual(replayed, card)
        self.assertEqual(model.astream.call_count, 2)

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

    def test_explain_batch_cap_persists_uncovered_exercise_labels(self):
        self.stack.enter_context(patch.dict(os.environ, {
            "EXPLAIN_TASK_MODES": "1", "EXPLAIN_MULTI_EXERCISE_BATCHING": "1",
            "SOCRA_EXPLAIN_EXERCISES_PER_BATCH": "3", "SOCRA_EXPLAIN_MAX_BATCH_GROUPS": "1",
        }))
        source = {**SOURCE, "content": "\n".join(
            f"Exercise {i} Analyze the supplied model." for i in range(1, 6)
        )}
        self.stack.enter_context(patch("agents.explicateur.retrieve_summary_guided_chunks", AsyncMock(return_value=[source])))
        self.stack.enter_context(patch("agents.explicateur.retrieve_chunks", AsyncMock(return_value=[])))

        async def stream(_):
            yield AIMessageChunk(content=json.dumps({
                "definition": "A model is a simplified representation.",
                "intuition": "Think of a map.",
                "sections": [{"heading": f"Exercise {i}", "content": "Analyze the model."} for i in range(1, 4)],
                "citations": [1],
            }))

        model = SimpleNamespace(astream=Mock(side_effect=stream))
        self.stack.enter_context(patch("agents.explicateur.get_chat_llm", return_value=model))
        ws = self.connect()
        request = self.send(ws, mode="explain", message="Solve all exercises")
        events = self.until(ws, "done")
        card = next(event["content"]["card"] for event in events if event["type"] == "card_ready")
        notice = card["sections"][-1]["content"]
        self.assertIn("Exercise 4, Exercise 5", notice)
        self.assertEqual(self.rows[("assistant", request)]["metadata"]["explanation"], card)

        self.rows[("assistant", request)] = json.loads(json.dumps(self.rows[("assistant", request)]))
        ws.close()
        ws = self.connect()
        self.send(ws, mode="explain", request=request, message="Solve all exercises")
        replay = self.until(ws, "done")
        self.assertEqual(next(e["content"]["card"] for e in replay if e["type"] == "card_ready"), card)
        model.astream.assert_called_once()

    def test_explain_coverage_notice_survives_websocket_replay(self):
        self.stack.enter_context(patch.dict(os.environ, {
            "EXPLAIN_DOCUMENT_INVENTORY": "1", "EXPLAIN_COVERAGE_CHECK": "1",
        }))
        source = {**SOURCE, "content": "Required Questions\nQuestion 5: Compare accuracy metrics."}
        self.stack.enter_context(patch("agents.explicateur.course_documents", AsyncMock(return_value=[
            {"id": source["document_id"], "filename": source["filename"]},
        ])))
        self.stack.enter_context(patch("agents.explicateur.retrieve_summary_guided_chunks", AsyncMock(return_value=[source])))

        async def stream(_):
            yield AIMessageChunk(content='{"citations":[1],"sections":[{"heading":"Partial example","content":"The model is a map."}', response_metadata={"finish_reason": "length"})

        model = SimpleNamespace(astream=Mock(side_effect=stream), ainvoke=AsyncMock(return_value=SimpleNamespace(
            content='{"citations":[1],"sections":[{"heading":"Question 5","content":"Details unavailable."}]}',
            response_metadata={},
        )))
        self.stack.enter_context(patch("agents.explicateur.get_chat_llm", return_value=model))
        ws = self.connect()
        request = self.send(ws, mode="explain", message="Explain Question 5", documentId=source["document_id"])
        events = self.until(ws, "done")
        card = next(event["content"]["card"] for event in events if event["type"] == "card_ready")
        self.assertIn("Checked against retrieved excerpts only.", card["sections"][-1]["content"])
        self.assertIn("Question 5", card["sections"][-1]["content"])
        self.rows[("assistant", request)] = json.loads(json.dumps(self.rows[("assistant", request)]))
        ws.close()
        ws = self.connect()
        self.send(ws, mode="explain", request=request, message="Explain Question 5", documentId=source["document_id"])
        replay = self.until(ws, "done")
        self.assertEqual(next(e["content"]["card"] for e in replay if e["type"] == "card_ready"), card)
        model.astream.assert_called_once()
        model.ainvoke.assert_awaited_once()

    def test_course_continuation_is_saved_and_replayed_by_request_id(self):
        self.stack.enter_context(patch.dict(os.environ, {"EXPLAIN_INTENT_PLANS": "1"}))
        source = {**SOURCE, "filename": "Course.pdf"}
        chunks = [{**source, "id": f"course-{page}", "page_number": page, "chunk_index": page - 1}
                  for page in range(1, 8)]
        document = {"id": source["document_id"], "filename": source["filename"], "page_count": len(chunks)}
        section_map = [{"document_id": document["id"], "title": f"Topic {page}",
                        "page_start": page, "page_end": page, "summary": "Source evidence about modeling"}
                       for page in range(1, 8)]
        for function, result in (
            ("course_documents", [document]),
            ("get_current_course_sections", section_map),
            ("document_inventory_chunks", (chunks, "full_document")),
            ("retrieve_summary_guided_chunks", [chunks[0]]),
        ):
            self.stack.enter_context(patch(f"agents.explicateur.{function}", AsyncMock(return_value=result)))

        async def stream(_):
            yield AIMessageChunk(content=json.dumps({
                "definition": "", "intuition": "", "citations": [1],
                "sections": [{"heading": "Topic", "content": "A model simplifies a real system."}],
            }))

        model = SimpleNamespace(astream=Mock(side_effect=stream))
        self.stack.enter_context(patch("agents.explicateur.get_chat_llm", return_value=model))
        ws = self.connect()
        first_request = self.send(ws, mode="explain", message="Explain the whole course")
        self.until(ws, "done")
        first = self.rows[("assistant", first_request)]["metadata"]["explanation"]["course_progress"]
        payload = {"mode": "explain", "request": first["next_request_id"],
                   "message": "Continue with part 2", "continueCourseFrom": first_request}
        ws.close()
        ws = self.connect()
        self.send(ws, **payload)
        self.until(ws, "done")
        saved = self.rows[("assistant", first["next_request_id"])]
        self.assertEqual(saved["metadata"]["explanation"]["course_progress"]["part"], 2)
        self.send(ws, **payload)
        replay = self.until(ws, "done")
        self.assertEqual(next(event["content"]["message_id"] for event in replay
                              if event["type"] == "response_complete"), saved["id"])
        self.assertEqual(model.astream.call_count, 2)

    def test_explain_salvages_truncation_and_replays_incomplete_card(self):
        section = {"heading": "Complete example", "source_indexes": [1, 999], "covers": ["question:1"],
                   "content": 'A map with braces {[]}, a backslash \\, and "quotes".'}
        raw = '{"citations":[1],"sections":[' + json.dumps(section) + "," + json.dumps(section)
        raw += ',{"heading":"Unfinished section","content":"Half a sentence'

        async def stream(_):
            yield AIMessageChunk(content=raw, response_metadata={"finish_reason": "length"})

        model = SimpleNamespace(astream=Mock(side_effect=stream))
        self.stack.enter_context(patch("agents.explicateur.get_chat_llm", return_value=model))
        self.stack.enter_context(patch("agents.explicateur.retrieve_summary_guided_chunks", AsyncMock(return_value=[SOURCE])))
        ws = self.connect()
        request = self.send(ws, mode="explain", message="Explain modeling")
        events = self.until(ws, "done")
        self.assertEqual(events[-1]["type"], "done")
        card = next(event["content"]["card"] for event in events if event["type"] == "card_ready")
        self.assertEqual([section["heading"] for section in card["sections"]],
                         ["Complete example", "Incomplete explanation"])
        self.assertEqual(card["sections"][0]["content"], section["content"])
        self.assertIn("cut off after 1", card["sections"][1]["content"])
        self.assertNotIn("source_indexes", card["sections"][0])
        self.assertEqual(card["sections"][0]["citations"], card["citations"])
        self.assertEqual(card["sections"][0]["covers"], ["question:1"])
        self.assertEqual(card["citations"][0]["page_number"], 3)

        self.rows[("assistant", request)] = json.loads(json.dumps(self.rows[("assistant", request)]))
        ws.close()
        ws = self.connect()
        self.send(ws, mode="explain", request=request, message="Explain modeling")
        replay = self.until(ws, "done")
        self.assertEqual(next(e["content"]["card"] for e in replay if e["type"] == "card_ready"), card)
        model.astream.assert_called_once()

    def test_explain_preview_flushes_the_last_short_delta(self):
        from agents.explanation_preview import explanation_preview

        draft = '{"definition":"A model is a simplified representation.","intuition":"Think of a map.",'
        draft += '"sections":[{"heading":"Example","content":"A detailed example."}],'
        draft += '"citations":[1],"check_question":"What is a model?"}'
        parser = self.stack.enter_context(patch("agents.explicateur.explanation_preview", wraps=explanation_preview))

        async def stream(_):
            for index in range(0, len(draft), 12):
                yield AIMessageChunk(content=draft[index:index + 12])

        self.stack.enter_context(patch("agents.explicateur.get_chat_llm", return_value=SimpleNamespace(astream=stream)))
        self.stack.enter_context(patch("agents.explicateur.retrieve_summary_guided_chunks", AsyncMock(return_value=[SOURCE])))
        ws = self.connect()
        self.send(ws, mode="explain", message="Explain modeling")
        events = self.until(ws, "done")
        deltas = [e["content"]["text"] for e in events if e["type"] == "content_delta"]
        self.assertEqual("".join(deltas), explanation_preview(draft))
        self.assertLess(parser.call_count, len(draft) // 12)

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
