"""Authenticate a study socket and stream ordered, public LangGraph results."""
from __future__ import annotations

import asyncio
import json
from hashlib import sha256
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from agents.llm import is_transient_provider_error, provider_error_code, provider_error_message
from agents.notebook import NOTE_ACTIONS, load_notebook_context

from api.security import RateLimit, consume_study_quota
from agents.explain_lifecycle import correction_event
from agents.explain_document import educational_documents_enabled
from config import get_settings
from db import messages as messages_db
from db.chat_turns import session_turn
from db.explain_progress import KEY as UNIT_CHECKPOINT_KEY, CheckpointRejected, TurnCheckpoint, source_is_current
from db.exams import get_exam_for_session
from db.attempts import (
    get_exercise_for_owner,
    get_latest_attempt_for_owner,
    get_latest_exercise_for_owner,
    has_revealed_solution,
    reveal_solution_for_owner,
)
from db.supabase_client import get_supabase
from graph.orchestrator import get_compiled_graph
from graph.state import ChatTurn, SocraState
from models.schemas import ExerciseActionRequest, ExerciseAttemptRequest
from rag.retriever import request_id as retrieval_request_id, retrieval_scope
from rag.unit_map import unit_pipeline_enabled


_UNIT_ACTIONS = {"continue_learning", "deepen_unit"}
_UNIT_PROTOCOL_ACTIONS = _UNIT_ACTIONS | {"restore_unit_progress"}
router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)
chat_limit = RateLimit(20)
auth_limit = RateLimit(60)


class TurnCancelled(Exception):
    pass


async def _turn_events(graph, state, cancelled):
    events = graph.astream_events(state, version="v2")
    stop = asyncio.create_task(cancelled.wait())
    try:
        async with asyncio.timeout(180):
            while True:
                event = asyncio.create_task(anext(events, None))
                try:
                    await asyncio.wait((event, stop), return_when=asyncio.FIRST_COMPLETED)
                    if stop.done():
                        raise TurnCancelled
                    item = event.result()
                    if item is None:
                        break
                    yield item
                finally:
                    if not event.done():
                        event.cancel()
                        await asyncio.gather(event, return_exceptions=True)
    finally:
        stop.cancel()
        await asyncio.gather(stop, return_exceptions=True)
        await events.aclose()


def _object(raw: str) -> dict[str, Any]:
    if len(raw) > 65_536:
        raise ValueError("Message is too large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Invalid message")
    return value


def _build_initial_state(
    *,
    session_id: str,
    course_id: str,
    user_id: str,
    student_message: str,
    history: list[ChatTurn],
    profile: dict[str, Any] | None,
    is_first_message: bool,
    api_key: str = "",
    model: str = "",
    provider: str = "google",
    mode: str = "socratic",
    language: str = "fr",
) -> SocraState:
    state: SocraState = {
        "session_id": session_id,
        "course_id": course_id,
        "user_id": user_id,
        "messages": history,
        "student_message": student_message,
        "mode": mode,
        "language": "en" if language == "en" else "fr",
        "is_first_message": is_first_message,
        "profile": {
            "session_id": session_id,
            "user_id": user_id,
            "mastered_concepts": (profile or {}).get("mastered_concepts") or [],
            "fragile_concepts": (profile or {}).get("fragile_concepts") or [],
            "misconception_history": (profile or {}).get("misconception_history") or [],
            "bloom_progression": (profile or {}).get("bloom_progression") or [],
            "total_exchanges": int((profile or {}).get("total_exchanges") or 0),
            "exercise_performance": (profile or {}).get("exercise_performance") or [],
        },
    }
    if api_key:
        state["api_key"] = api_key
    if model:
        state["model"] = model
    if provider:
        state["provider"] = provider
    return state


async def _send(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, default=str))


def _display_message(display_text: Any, student_message: str) -> str:
    """Use a concise client label for internal actions while retaining normal text."""
    if isinstance(display_text, str) and display_text.strip():
        return display_text.strip()[:500]
    return student_message


def _authenticate_exercise_request(session_id: str, course_id: str, access_token: str) -> str:
    """Authenticate and verify ownership before exposing course-derived work."""
    if not access_token:
        raise ValueError("Sign in again to generate an exercise.")
    auth_user = get_supabase().auth.get_user(access_token).user
    if not auth_user:
        raise ValueError("Your session has expired. Sign in again.")
    session = (
        get_supabase().table("sessions").select("course_id")
        .eq("id", session_id).single().execute()
    ).data
    if not session or str(session.get("course_id")) != course_id:
        raise ValueError("This inquiry does not belong to the selected course.")
    course = (
        get_supabase().table("courses").select("user_id")
        .eq("id", course_id).single().execute()
    ).data
    if not course or str(course.get("user_id")) != str(auth_user.id):
        raise ValueError("You do not have access to this course.")
    return str(auth_user.id)


@router.websocket("/ws/chat/{session_id}")
async def chat_ws(ws: WebSocket, session_id: str) -> None:
    origin = ws.headers.get("origin")
    if origin and origin.rstrip("/") != get_settings().frontend_url.rstrip("/"):
        await ws.close(code=1008)
        return
    await ws.accept()
    connected_at = monotonic()
    connection_id = str(uuid4())
    try:
        session_id = str(UUID(session_id))
        if not auth_limit.allow(ws.client.host if ws.client else "unknown"):
            raise ValueError("Connection limit reached")
        auth = _object(await asyncio.wait_for(ws.receive_text(), timeout=20))
        legacy_action = auth.get("action") != "authenticate"
        if legacy_action and not auth.get("accessToken"):
            raise ValueError("Authentication required")
        protocol = 2 if auth.get("version") == 2 else 1
        access_token = str(auth.get("accessToken") or "").strip()
        course_id_resolved = str(UUID(str(auth.get("courseId"))))
        user_id_resolved = await asyncio.to_thread(
            _authenticate_exercise_request, session_id, course_id_resolved,
            access_token,
        )
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await _send(ws, {"type": "error", "content": {"code": "AUTH_REQUIRED", "message": "Sign in again to open this inquiry."}})
            await ws.close(code=1008)
        except (WebSocketDisconnect, OSError, RuntimeError):
            return
        return

    graph = get_compiled_graph()
    try:
        await _send(ws, {"type": "connected", "session_id": session_id, "connection_id": connection_id, "version": protocol})
    except (WebSocketDisconnect, OSError, RuntimeError):
        return
    logger.info("chat_connected connection_id=%s duration_ms=%d", connection_id, (monotonic() - connected_at) * 1000)
    incoming: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=3)
    cancelled = asyncio.Event()
    current_request = ""
    response_finished = False
    disconnected = asyncio.Event()
    queued_cancellations: set[str] = set()

    async def receive_actions():
        try:
            while True:
                try:
                    payload = _object(await ws.receive_text())
                except ValueError:
                    payload = {"action": "invalid"}
                if payload.get("action") == "cancel":
                    request = str(payload.get("requestId") or "")
                    if request == current_request and not response_finished:
                        cancelled.set()
                    elif request != current_request and len(queued_cancellations) < 12:
                        queued_cancellations.add(request)
                    continue
                if incoming.full():
                    await ws.close(code=1008)
                    return
                incoming.put_nowait(payload)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            disconnected.set()
            if not response_finished:
                cancelled.set()
            if not incoming.full():
                incoming.put_nowait(None)

    if legacy_action:
        incoming.put_nowait(auth)
    receiver = asyncio.create_task(receive_actions())

    async def process_action(
        payload: dict[str, Any], action: str, requested_mode: str, student_message: str,
        display_message: str, attempt_request: ExerciseAttemptRequest | None,
        emit: Callable[..., Awaitable[None]], card: Callable[[str, Any], Awaitable[None]],
        progress: Callable[[str], Awaitable[None]], timing: Callable[..., None], turn_started: float, lease: str,
    ) -> None:
        nonlocal response_finished
        course_id, user_id = course_id_resolved, user_id_resolved
        first_text_sent = False
        node_started: dict[str, float] = {}
        model_started: dict[str, float] = {}
        if action == "restore_unit_progress":
            try:
                reference = str(UUID(str(payload.get("fromRequestId"))))
                snapshot = await asyncio.to_thread(messages_db.load_study_turn, session_id, user_id, reference)
                if not snapshot or snapshot.get("is_exam"):
                    raise ValueError
                messages = {row["role"]: row for row in snapshot["request_messages"]}
                saved_card = (messages.get("assistant", {}).get("metadata") or {}).get("explanation") or {}
                checkpoint = (messages.get("user", {}).get("metadata") or {}).get(UNIT_CHECKPOINT_KEY)
                if checkpoint and any(row.get("kind") == "educational_document" for row in checkpoint["versions"]):
                    raise ValueError
                if not checkpoint and saved_card.get("schema_version") == 2:
                    saved_progress = saved_card["course_progress"]
                    checkpoint = {**saved_progress, "generation": saved_progress["index_generation"],
                                  "versions": saved_card["versions"]}
                if not checkpoint:
                    raise ValueError
                if not await asyncio.to_thread(source_is_current, checkpoint, course_id, user_id):
                    raise ValueError
            except (ValueError, KeyError):
                await emit("error", "There is no current unit progress for this request.")
                return
            versions = checkpoint["versions"]
            latest = {row["output"]["logical_id"]: row for row in versions}
            if protocol == 2:
                for row in latest.values():
                    await emit("unit_ready" if row["stage"] == "ready" else "unit_draft",
                               {key: value for key, value in row.items() if key != "deterministic_facts"}
                               | {"replayed": True})
                for row in versions:
                    if row["stage"] != "ready":
                        continue
                    for change in row["change_log"]:
                        await emit("unit_correction", correction_event(row, change))
            if saved_card:
                await card("explanation", saved_card)
            await emit("turn_finalized")
            await emit("done")
            return
        if action in ("restore_exercise", "reveal_solution", "submit_attempt") and await asyncio.to_thread(
            get_exam_for_session, session_id=session_id, user_id=user_id,
        ):
            await emit("error", "Open the exam page to work on this session.")
            return

        if action == "restore_exercise":
            try:
                latest_exercise = await asyncio.to_thread(get_latest_exercise_for_owner,
                    session_id=session_id,
                    course_id=course_id,
                    user_id=user_id,
                )
                if latest_exercise:
                    exercise_data = latest_exercise.get("exercise_data") or {}
                    await card("exercise", {
                        "id": latest_exercise["id"],
                        "concept": latest_exercise["concept"],
                        "difficulty": latest_exercise["difficulty"],
                        "bloom_level": latest_exercise["bloom_level"],
                        "prompt": latest_exercise["prompt"],
                        "citations": latest_exercise["citations"],
                        "hints": latest_exercise["hints"],
                        "exercise_type": latest_exercise.get("exercise_type") or "short_answer",
                        "choices": exercise_data.get("choices") or [],
                        "numeric_unit": exercise_data.get("numeric_unit") or "",
                        "code_language": exercise_data.get("code_language") or "",
                        "code_task_mode": exercise_data.get("code_task_mode") or "write",
                        "starter_code": exercise_data.get("starter_code") or "",
                        "sql_setup": exercise_data.get("sql_setup") or [],
                    })
                    latest_attempt = await asyncio.to_thread(get_latest_attempt_for_owner,
                        exercise_id=str(latest_exercise["id"]),
                        session_id=session_id,
                        user_id=user_id,
                    )
                    if latest_attempt:
                        await card("correction", {
                            "attempt_id": latest_attempt["id"],
                            "total_score": latest_attempt["total_score"],
                            "max_score": latest_attempt["max_score"],
                            "overall_feedback": latest_attempt["feedback"],
                            "error_category": latest_attempt["error_category"],
                            "criterion_feedback": latest_attempt["criterion_feedback"],
                            "citations": latest_attempt["citations"],
                            "next_step": latest_attempt["next_step"],
                            "hints_used": latest_attempt["hints_used"],
                        })
                        if latest_attempt.get("solution_revealed"):
                            await card("solution", {
                                "exercise_id": latest_exercise["id"],
                                "expected_answer": latest_exercise["expected_answer"],
                                "common_mistakes": latest_exercise.get("common_mistakes") or [],
                            })
            except Exception:
                logger.warning("chat_restore_failed request_id=%s", current_request)
                await emit("error", "Could not restore the saved exercise.")
                return
            await emit("done")
            return

        exercise_id = str(payload.get("exerciseId") or "").strip()
        exercise_record: dict[str, Any] | None = None
        if action == "submit_attempt" and attempt_request:
            exercise_id = str(attempt_request.exercise_id)
        elif action == "reveal_solution":
            try:
                exercise_id = str(ExerciseActionRequest.model_validate({"exercise_id": exercise_id}).exercise_id)
            except ValidationError:
                await emit("error", "Choose a valid exercise before revealing the solution.")
                return

        if action == "reveal_solution":
            try:
                solution = await asyncio.to_thread(reveal_solution_for_owner,
                    exercise_id=exercise_id,
                    session_id=session_id,
                    course_id=course_id,
                    user_id=user_id,
                )
            except ValueError as exc:
                await emit("error", str(exc))
                return
            except Exception:
                logger.warning("chat_reveal_failed request_id=%s", current_request)
                await emit("error", "Could not reveal the solution. Please try again.")
                return
            try:
                await asyncio.to_thread(messages_db.merge_latest_assistant_metadata, session_id, {"solution": solution})
            except Exception:
                logger.warning("chat_reveal_save_failed request_id=%s", current_request)
            await card("solution", solution)
            await emit("done")
            return

        # Per-request LLM overrides from the Settings dialog. Keys are
        # never logged; only explicitly supported providers are honored.
        client_api_key = str(payload.get("apiKey") or "").strip()
        client_model = str(payload.get("model") or "").strip()
        client_provider = str(payload.get("provider") or "").strip().lower()
        if len(client_api_key) > 2000 or len(client_model) > 120:
            await emit("error", "Check the model and API key in Settings.")
            return
        if client_provider not in ("google", "groq"):
            client_api_key = ""
            client_model = ""
            client_provider = "google"

        if not student_message or len(student_message) > 10_000:
            message = "Write a message of 1 to 10,000 characters."
            await emit("error", message)
            return
        if not course_id:
            await emit("error", "Missing course_id")
            return

        snapshot = await asyncio.to_thread(messages_db.load_study_turn, session_id, user_id, current_request)
        if not snapshot:
            await emit("error", "This inquiry is unavailable.")
            return
        if snapshot.get("is_exam"):
            await emit("error", "Open the exam page to work on this session.")
            return
        existing_messages = snapshot["recent"]
        session_language = snapshot["language"]
        loaded_profile = snapshot["profile"]
        stored_diagnostic = snapshot["diagnostic"]
        notebook = payload.get("notebook")
        context = None
        note_action = None
        note_id = None
        if notebook is not None:
            if action != "message" or not isinstance(notebook, dict):
                await emit("error", "Invalid Notebook action.")
                return
            note_action = notebook.get("action", "ask")
            selection = notebook.get("selection") or ""
            try:
                note_id = str(UUID(str(notebook.get("id"))))
                if not isinstance(note_action, str) or note_action not in NOTE_ACTIONS or not isinstance(selection, str) or len(selection) > 6000:
                    raise ValueError("Invalid Notebook context.")
                if (note_action == "quiz") != (requested_mode == "exercise"):
                    raise ValueError("Invalid Notebook study mode.")
            except ValueError:
                await emit("error", "The Notebook selection or context is unavailable. Save the note and try again.")
                return
        fingerprint_fields = [action, requested_mode, exercise_id, student_message, attempt_request.hints_used if attempt_request else 0]
        prior_course = None
        unit_action = None
        target_unit = None
        if payload.get("continueCourseFrom") is not None or action in _UNIT_ACTIONS:
            from agents.explain_tasks import explain_flag

            try:
                if requested_mode != "explain" or action not in _UNIT_ACTIONS | {"message"} or not explain_flag("EXPLAIN_INTENT_PLANS"):
                    raise ValueError
                prior_request = str(UUID(str(payload.get("fromRequestId") if action in _UNIT_ACTIONS else payload["continueCourseFrom"])))
                previous = await asyncio.to_thread(messages_db.load_study_turn, session_id, user_id, prior_request)
                prior_card = next(
                    (row.get("metadata") or {}).get("explanation") or {}
                    for row in (previous or {}).get("request_messages", []) if row["role"] == "assistant"
                )
                prior_course = prior_card.get("course_progress")
                if not prior_course:
                    raise ValueError
                if unit_pipeline_enabled() and prior_card.get("schema_version") == 2 and "learning_state" in prior_card:
                    unit_action = action if action in _UNIT_ACTIONS else "continue_learning"
                    command = next(item for item in prior_card["learning_state"]["next_actions"]
                                   if item["action"] == unit_action and item["request_id"] == current_request)
                    target_unit = command["logical_id"]
                    if unit_action == "deepen_unit":
                        if target_unit != payload.get("unitId"):
                            raise ValueError
                elif action != "message" or prior_course.get("next_request_id") != current_request:
                    raise ValueError
            except (ValueError, StopIteration):
                await emit("error", "Open the saved course part in this inquiry to continue.")
                return
            fingerprint_fields = ["continue_course", prior_request]
            if unit_action:
                fingerprint_fields = [unit_action, target_unit, prior_course["document_id"],
                                      prior_course["source_hash"], prior_course["index_generation"]]
        if note_id:
            fingerprint_fields.extend([note_id, note_action, selection])
        if unit_action and payload.get("documentId") is not None and (
                str(payload["documentId"]).lower() != prior_course["document_id"]):
            await emit("error", "The selected PDF differs from the saved explanation.")
            return
        if unit_pipeline_enabled() and not unit_action and requested_mode == "explain" and payload.get("documentId") is not None:
            fingerprint_fields.append(str(payload["documentId"]).lower())
        fingerprint = sha256(json.dumps(
            fingerprint_fields,
            ensure_ascii=False,
        ).encode()).hexdigest()
        by_role = {row["role"]: row for row in snapshot["request_messages"]}
        prior_prompt = by_role.get("user")
        if prior_prompt and (prior_prompt.get("metadata") or {}).get("request_fingerprint") != fingerprint:
            await emit("error", "This request ID belongs to a different prompt.")
            return
        existing_response = by_role.get("assistant")
        if existing_response:
            metadata = existing_response.get("metadata") or {}
            stored_document = metadata.get("explanation") or {}
            if stored_document.get("schema_version") == 3:
                source = stored_document["source"]
                if not await asyncio.to_thread(source_is_current, {
                    **source, "generation": source["index_generation"],
                }, course_id, user_id):
                    metadata = metadata | {"explanation": stored_document | {"historical_source": True}}
            if protocol == 2 and unit_pipeline_enabled():
                saved_card = metadata.get("explanation") or {}
                saved_progress = saved_card.get("course_progress") or {}
                if saved_card.get("versions") and "index_generation" in saved_progress:
                    source = {**saved_progress, "generation": saved_progress["index_generation"]}
                    if not await asyncio.to_thread(source_is_current, source, course_id, user_id):
                        metadata = metadata | {"explanation": saved_card | {"historical_source": True}}
                        saved_card = {}
                for row in saved_card.get("versions", []):
                    if row["stage"] == "ready":
                        await emit("unit_ready", row | {"replayed": True})
                        for change in row["change_log"]:
                            await emit("unit_correction", correction_event(row, change))
            for card_kind in ("exercise", "explanation", "correction"):
                if metadata.get(card_kind):
                    await card(card_kind, metadata[card_kind])
            response_finished = True
            if protocol == 1 and requested_mode == "socratic":
                await emit("content_delta", {"text": existing_response["content"]})
            await emit("response_complete", {"message_id": existing_response["id"], "text": existing_response["content"]})
            if metadata.get("course_context"):
                await emit("context_update", metadata["course_context"])
            await emit("turn_finalized")
            await emit("done")
            return
        if note_id:
            try:
                context = await asyncio.to_thread(load_notebook_context, user_id, session_id, note_id, selection, student_message)
            except ValueError as exc:
                await emit("error", str(exc))
                return
            except Exception as exc:
                logger.warning("notebook_context_unavailable error_type=%s", type(exc).__name__)
                await emit("error", "Could not load Notebook context.")
                return
            if not context:
                await emit("error", "This inquiry is not linked to that note.")
                return
        quota = await consume_study_quota(user_id, "correction" if action == "submit_attempt" else requested_mode)
        if quota is not True:
            await emit("error", {"code": "REQUEST_RATE_LIMITED" if quota is False else "REQUEST_UNAVAILABLE",
                                 "message": "Too many study requests. Wait a minute and try again." if quota is False
                                 else "Study requests are temporarily unavailable. Retry shortly."})
            return
        if action == "submit_attempt":
            try:
                exercise_record = await asyncio.to_thread(get_exercise_for_owner,
                    exercise_id=exercise_id,
                    session_id=session_id,
                    course_id=course_id,
                    user_id=user_id,
                )
                revealed = await asyncio.to_thread(has_revealed_solution,
                    exercise_id=exercise_id,
                    session_id=session_id,
                    user_id=user_id,
                )
            except Exception:
                logger.warning("chat_attempt_load_failed request_id=%s", current_request)
                await emit("error", "Could not load this exercise. Please try again.")
                return
            if not exercise_record:
                await emit("error", "This exercise is not available in the selected inquiry.")
                return
            if revealed:
                await emit("error", "The solution has been revealed, so this exercise can no longer be submitted.")
                return

        history = [
            {"role": row["role"], "content": row["content"]}
            for row in existing_messages
            if row.get("role") in ("user", "assistant") and row.get("content")
            and (row.get("metadata") or {}).get("request_id") != current_request
            and ((row.get("metadata") or {}).get("notebook_action") in (None, "ask", "related") or not context)
        ]
        has_answer = snapshot["has_assistant"]
        is_first_message = not stored_diagnostic and not has_answer
        if cancelled.is_set():
            await emit("cancelled")
            return

        if is_first_message and action == "message" and not context:
            try:
                await asyncio.to_thread(messages_db.set_default_session_title_from_prompt, session_id, student_message)
            except Exception:
                logger.warning("chat_title_save_failed request_id=%s", current_request)

        try:
            prompt_row = await asyncio.to_thread(messages_db.save_message, session_id, "user", display_message,
                                   metadata={"learning_mode": requested_mode, "request_id": current_request,
                                         **({"notebook_action": note_action} if context else {}),
                                         "request_fingerprint": fingerprint})
        except Exception as exc:
            logger.warning("chat_prompt_save_failed request_id=%s error_type=%s", current_request, type(exc).__name__)
            await emit("error", "Could not save your prompt. Try again.")
            return

        if prior_course:
            student_message = prior_course["topic"]
        history.append({"role": "user", "content": student_message})

        initial_state = _build_initial_state(
            session_id=session_id,
            course_id=course_id,
            user_id=user_id,
            student_message=student_message,
            history=history,
            profile=loaded_profile,
            is_first_message=is_first_message,
            api_key=client_api_key,
            model=client_model,
            provider=client_provider or "google",
            mode="correct" if action == "submit_attempt" else requested_mode,
            language=(str(payload.get("language")) if payload.get("language") in ("fr", "en") else session_language),
        )
        if stored_diagnostic:
            initial_state["diagnostic"] = stored_diagnostic
        initial_state["request_id"] = current_request
        if prior_course:
            initial_state["explain_course_prior"] = prior_course
        document_run = educational_documents_enabled() and not prior_course and not unit_action
        if (unit_pipeline_enabled() or document_run) and requested_mode == "explain" and not context:
            initial_state["explain_checkpoint"] = TurnCheckpoint(
                session_id, course_id, user_id, current_request, prior_prompt or prompt_row, lease=lease,
            )
            if protocol == 2:
                initial_state["explain_document_event" if document_run else "explain_unit_event"] = emit
            if unit_action:
                initial_state["explain_unit_action"] = unit_action
                if target_unit:
                    initial_state["explain_target_unit"] = target_unit
        initial_state["explain_language_explicit"] = payload.get("language") in ("fr", "en")
        if requested_mode == "explain" and payload.get("documentId") is not None:
            try:
                initial_state["explain_document_id"] = str(UUID(str(payload["documentId"])))
            except ValueError:
                await emit("error", "Choose a valid PDF for this inquiry.")
                return
        if context:
            initial_state["notebook_context"] = context
            initial_state["notebook_action"] = note_action
            if note_action == "quiz":
                initial_state["requested_exercise_type"] = "short_answer"

        async def delta(text: str | None, *, preview: bool = False) -> None:
            nonlocal first_text_sent
            if text and not first_text_sent:
                first_text_sent = True
                timing("first_text", turn_started)
            await emit("content_delta", {"text": text, "preview": preview})

        saved: dict[str, Any] = {}

        async def complete_socratic(text: str) -> None:
            nonlocal response_finished, saved
            if cancelled.is_set():
                raise TurnCancelled
            # Commit has begun. Cancellation applies only before this point.
            response_finished = True
            try:
                saved = await asyncio.to_thread(
                    messages_db.save_message, session_id, "assistant", text,
                    metadata={"learning_mode": requested_mode, "request_id": current_request},
                )
            except Exception:
                response_finished = False
                raise
            timing("answer_complete", turn_started)
            await emit("response_complete", {"message_id": saved["id"], "text": text})

        if protocol == 2:
            initial_state["preview"] = lambda text: delta(text, preview=True)
        initial_state["tutor_delta"] = delta
        initial_state["emit_diagnostic"] = lambda report: emit("diagnostic", report)
        if stored_diagnostic and not has_answer and requested_mode == "socratic":
            await emit("diagnostic", stored_diagnostic)
        initial_state["progress"] = progress
        initial_state["complete_socratic"] = complete_socratic
        if action == "submit_attempt":
            initial_state["exercise_record"] = exercise_record or {}
            initial_state["student_answer"] = student_message
            initial_state["hints_used"] = attempt_request.hints_used if attempt_request else 0

        final_state: SocraState = initial_state
        exercise_result: dict[str, Any] | None = None
        correction_result: dict[str, Any] | None = None
        explanation_result: dict[str, Any] | None = None

        try:
            async for ev in _turn_events(graph, initial_state, cancelled):
                kind = ev.get("event")
                event_name = ev.get("name")
                run_id = str(ev.get("run_id"))
                if kind == "on_chain_start" and event_name in {
                    "diagnostiqueur", "tuteur_socratique", "evaluateur", "memoire",
                    "exercise_generator", "explicateur", "correcteur",
                }:
                    node_started[run_id] = monotonic()
                if kind == "on_chat_model_start":
                    model_started[run_id] = monotonic()
                    for parent in reversed(ev.get("parent_ids") or []):
                        if parent in node_started:
                            timing("before_model", node_started[parent])
                            break
                if kind == "on_chat_model_end" and run_id in model_started:
                    timing("model", model_started.pop(run_id))
                if kind == "on_chain_end" and run_id in node_started:
                    timing(str(event_name), node_started.pop(run_id))

                if kind == "on_chain_start" and event_name == "diagnostiqueur":
                    await progress("Running your initial diagnostic.")
                elif kind == "on_chain_start" and event_name == "correcteur":
                    await progress("Reviewing your answer.")

                if kind == "on_chain_end":
                    name = ev.get("name")
                    data_out = ev.get("data", {}).get("output") or {}

                    if name == "exercise_generator" and isinstance(data_out, dict):
                        exercise_result = data_out.get("exercise")
                    if name == "explicateur" and isinstance(data_out, dict):
                        explanation_result = data_out.get("explanation")
                    if name == "correcteur" and isinstance(data_out, dict):
                        correction_result = data_out.get("correction")

                    # The whole graph finishing — capture the final state.
                    if not ev.get("parent_ids") and isinstance(data_out, dict):
                        final_state = data_out  # type: ignore[assignment]

        except TurnCancelled:
            if disconnected.is_set():
                return
            timing("cancelled", turn_started)
            await emit("cancelled")
            return
        except CheckpointRejected:
            await emit("error", {"code": "EXPLAIN_CHECKPOINT_REJECTED",
                                 "message": "Unit progress changed. Reopen the inquiry before retrying."})
            return
        except Exception as exc:
            timing("failed", turn_started, error_type=type(exc).__name__)
            if response_finished:
                timing("total", turn_started, mode=requested_mode)
                await emit("turn_finalized")
                await emit("done")
                return
            provider_code = provider_error_code(exc)
            if provider_code is None and is_transient_provider_error(exc):
                provider_code = "PROVIDER_UNAVAILABLE"
            if provider_code:
                await emit("error", {
                    "code": provider_code,
                    "message": provider_error_message(provider_code),
                })
            else:
                await emit("error", "The tutor could not complete this request. Try again or narrow the topic.")
            return

        evaluation = final_state.get("evaluation")
        generated = final_state.get("exercise") or exercise_result
        explanation = final_state.get("explanation") or explanation_result
        correction = final_state.get("correction") or correction_result
        if not response_finished:
            if cancelled.is_set():
                await emit("cancelled")
                return
            metadata: dict[str, Any] = {"learning_mode": requested_mode, "request_id": current_request}
            if context:
                metadata["notebook_action"] = note_action
            if generated:
                metadata["exercise"] = generated
                text = f"Exercise ready: {generated.get('concept', 'your topic')}."
            elif explanation:
                metadata["explanation"] = explanation
                text = "Course explanation ready."
                if explanation.get("schema_version") == 3:
                    french_document = explanation["intent"]["language"] == "French"
                    if explanation["state"] == "approved":
                        text = "Document pédagogique prêt." if french_document else "Educational document ready."
                    else:
                        text = "Document pédagogique incomplet." if french_document else "Educational document incomplete."
            elif correction:
                metadata.update(correction=correction, exercise_id=exercise_id)
                text = f"You scored {correction['total_score']} out of {correction['max_score']}. Review your feedback below."
            elif final_state.get("notebook_result"):
                text = final_state["notebook_result"]
            else:
                await emit("error", "The tutor returned an empty response. Try again.")
                return
            try:
                checkpoint = initial_state.get("explain_checkpoint")
                if checkpoint and checkpoint.document and explanation and explanation.get("schema_version") in {2, 3}:
                    saved = await checkpoint.finalize(text, metadata)
                else:
                    saved = await asyncio.to_thread(messages_db.save_message, session_id, "assistant", text, metadata=metadata)
            except CheckpointRejected:
                await emit("error", {"code": "EXPLAIN_CHECKPOINT_REJECTED",
                                     "message": "Explanation progress changed. Reopen the inquiry before retrying."})
                return
            except Exception as exc:
                logger.warning("chat_response_save_failed request_id=%s error_type=%s", current_request, type(exc).__name__)
                await emit("error", "Could not save this response. Try again.")
                return
            response_finished = True
            timing("answer_complete", turn_started)
            if protocol == 1:
                await emit("content_delta", {"text": text})
            for card_kind in ("exercise", "explanation", "correction"):
                if metadata.get(card_kind):
                    await card(card_kind, metadata[card_kind])
            await emit("response_complete", {"message_id": saved["id"], "text": text})

        if evaluation and saved.get("id"):
            try:
                await asyncio.to_thread(messages_db.merge_message_metadata, saved["id"], {
                    "course_context": {"key_terms": evaluation.get("key_terms", []),
                                       "suggested_readings": evaluation.get("suggested_readings", [])},
                })
            except Exception as exc:
                logger.warning("chat_context_save_failed request_id=%s error_type=%s", current_request, type(exc).__name__)
            await emit("context_update", evaluation)
        try:
            await asyncio.to_thread(messages_db.touch_session, session_id)
        except Exception:
            logger.warning("chat_session_touch_failed request_id=%s", current_request)
        timing("total", turn_started, mode=requested_mode)
        await emit("turn_finalized")
        await emit("done")

    try:
        while True:
            # --------------------------------------------------------------
            # Wait for the next student message from the client.
            # --------------------------------------------------------------
            payload = await incoming.get()
            if payload is None or disconnected.is_set():
                return
            try:
                current_request = str(UUID(str(payload.get("requestId")))) if protocol == 2 else str(uuid4())
            except ValueError:
                await _send(ws, {"type": "error", "content": "Invalid request ID."})
                continue
            cancelled.clear()
            response_finished = False
            sequence = 0
            turn_started = monotonic()

            def timing(stage: str, start: float, **counts: Any) -> None:
                logger.info("chat_timing connection_id=%s request_id=%s stage=%s duration_ms=%d%s",
                            connection_id, current_request, stage, (monotonic() - start) * 1000,
                            "".join(f" {key}={value}" for key, value in counts.items()))

            async def emit(event_type: str, content: Any = None) -> None:
                nonlocal sequence
                if disconnected.is_set():
                    return
                if protocol == 1:
                    if event_type == "content_delta":
                        if content["text"] is None or content.get("preview"):
                            return
                        event_type, content = "token", content["text"]
                    elif event_type == "card_ready":
                        event_type, content = content["kind"], content["card"]
                    elif event_type == "context_update":
                        event_type = "context"
                sequence += 1
                try:
                    await _send(ws, {"type": event_type, "content": content, "version": protocol,
                                     "request_id": current_request, "session_id": session_id,
                                     "sequence": sequence, "timestamp": datetime.now(timezone.utc).isoformat()})
                except (WebSocketDisconnect, RuntimeError, OSError):
                    disconnected.set()
                    if not response_finished:
                        cancelled.set()

            async def card(kind: str, value: Any) -> None:
                await emit("card_ready", {"kind": kind, "card": value})

            stage_started = monotonic()
            previous_stage = "waiting"

            async def progress(stage: str) -> None:
                nonlocal stage_started, previous_stage
                timing("progress_stage", stage_started, label=previous_stage.replace(" ", "_"))
                previous_stage = stage
                stage_started = monotonic()
                await emit("progress", {"stage": stage})

            if current_request in queued_cancellations:
                queued_cancellations.discard(current_request)
                await emit("cancelled")
                continue

            action = str(payload.get("action") or "message").strip().lower()
            if action not in ("message", "submit_attempt", "reveal_solution", "restore_exercise") and not (
                unit_pipeline_enabled() and action in _UNIT_PROTOCOL_ACTIONS
            ):
                await emit("error", "Unsupported chat action")
                continue
            student_message = (
                str(payload.get("answer") or "").strip()
                if action == "submit_attempt"
                else str(payload.get("message") or
                         {"continue_learning": "Continue learning", "deepen_unit": "Deepen this unit"}.get(action, "")).strip()
            )
            display_message = _display_message(payload.get("displayText"), student_message)
            attempt_request = None
            if action == "submit_attempt":
                try:
                    attempt_request = ExerciseAttemptRequest.model_validate({
                        "exercise_id": payload.get("exerciseId"),
                        "answer": payload.get("answer"),
                        "hints_used": payload.get("hintsUsed", 0),
                    })
                    student_message = attempt_request.answer
                except ValidationError:
                    await emit("error", "Enter an answer under 10,000 characters and choose a valid exercise.")
                    continue
            course_id, user_id = course_id_resolved, user_id_resolved
            if str(payload.get("courseId", course_id)).lower() != course_id or str(payload.get("sessionId", session_id)).lower() != session_id:
                await emit("error", "This action does not belong to the open inquiry.")
                continue
            requested_mode = str(payload.get("mode") or "socratic").strip().lower()
            if requested_mode not in ("socratic", "exercise", "explain"):
                await emit("error", "Unsupported learning mode")
                continue
            if action in _UNIT_PROTOCOL_ACTIONS and requested_mode != "explain":
                await emit("error", "Unit actions require Explain mode")
                continue
            if action not in _UNIT_PROTOCOL_ACTIONS | {"message"} and requested_mode != "exercise":
                await emit("error", "Exercise actions require Short Answer Practice mode")
                continue
            if not chat_limit.allow(user_id):
                await emit("error", {"code": "REQUEST_RATE_LIMITED", "message": "Too many study requests. Wait a minute and try again."})
                continue
            await emit("request_accepted")
            timing("acknowledgement", turn_started)
            action_token = str(payload.get("accessToken") or access_token)
            try:
                verified_user = await asyncio.to_thread(
                    _authenticate_exercise_request, session_id, course_id,
                    action_token,
                )
                if verified_user != user_id:
                    raise ValueError("Account changed")
            except Exception:
                timing("authorization_failed", turn_started)
                await emit("error", {"code": "AUTH_REQUIRED", "message": "Sign in again to continue this inquiry."})
                if not disconnected.is_set():
                    await ws.close(code=1008)
                return

            access_token = action_token
            if disconnected.is_set():
                return
            await progress("Waiting for the inquiry to be available.")
            async with session_turn(session_id, user_id) as lease:
                if not lease:
                    await emit("error", "This inquiry is busy in another tab. Try again shortly.")
                    continue
                if cancelled.is_set():
                    timing("cancelled", turn_started)
                    await emit("cancelled")
                    continue
                context_token = retrieval_request_id.set(current_request)
                try:
                    async with retrieval_scope():
                        await process_action(payload, action, requested_mode, student_message, display_message,
                                             attempt_request, emit, card, progress, timing, turn_started, lease)
                finally:
                    timing("progress_stage", stage_started, label=previous_stage.replace(" ", "_"))
                    retrieval_request_id.reset(context_token)

    except WebSocketDisconnect:
        logger.info("WS disconnected: session=%s", session_id)
    except Exception as exc:
        logger.warning("chat_connection_failed session_id=%s error_type=%s", session_id, type(exc).__name__)
        try:
            await _send(ws, {"type": "error", "content": "The tutor connection closed. Please retry."})
            await ws.close(code=1011)
        except Exception:
            pass
    finally:
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)
