"""WebSocket endpoint that streams the LangGraph pipeline to the frontend.

Protocol::

    client -> server:  {
        "message":   str,
        "courseId":  uuid,
        "sessionId": uuid,
        "apiKey":    str | null,    # optional - provider API key override
        "provider":  str | null,    # google (default) or groq
        "model":     str | null,    # optional - overrides provider default model
        "mode":      str | null,    # socratic (default) or exercise
        "action":    str | null,    # message (default), submit_attempt, reveal_solution
        "exerciseId": str | null,  # required for attempt/reveal actions
        "answer":   str | null,    # required for submit_attempt
        "accessToken": str | null,  # required for exercise mode ownership checks
    }
    server -> client:  { "type": "diagnostic", "content": DiagnosticReport }   (first turn only)
                       { "type": "token",      "content": "<partial text>" }   (many)
                       { "type": "context",    "content": EvaluationResult }   (when applicable)
                       { "type": "exercise",   "content": PublicExercise }      (exercise mode)
                       { "type": "explanation", "content": GeneratedExplanation } (explain mode)
                       { "type": "correction", "content": PublicCorrection }   (after attempt)
                       { "type": "solution",   "content": PublicSolution }     (after attempt + explicit reveal)
                       { "type": "progress",   "content": { "stage": str } } (while preparing structured responses)
                       { "type": "done" }                                       (always)
                       { "type": "error",      "content": "<message>" }        (on failure)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from agents.llm import provider_error_code, provider_error_message
from agents.tuteur_socratique import TUTEUR_LLM_TAG
from db import messages as messages_db
from db import profiles as profiles_db
from db.attempts import (
    get_exercise_for_owner,
    get_latest_attempt_for_owner,
    get_latest_exercise_for_owner,
    has_revealed_solution,
    reveal_solution_for_owner,
)
from db.diagnostics import get_course_id_for_session, get_language_for_session
from db.supabase_client import get_supabase
from graph.orchestrator import get_compiled_graph
from graph.state import ChatTurn, SocraState
from models.schemas import ExerciseActionRequest, ExerciseAttemptRequest


router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)


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
    return student_message[:500]


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
    await ws.accept()
    logger.info("WS connected: session=%s", session_id)

    # ------------------------------------------------------------------
    # Up-front: load session-level data once per connection.
    # ------------------------------------------------------------------
    try:
        existing_messages = messages_db.load_messages(session_id) or []
        history: list[ChatTurn] = [
            {"role": m["role"], "content": m["content"]}  # type: ignore[typeddict-item]
            for m in existing_messages
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]

        course_id_resolved = get_course_id_for_session(session_id)
        session_language = get_language_for_session(session_id)
        user_id_resolved = profiles_db.get_user_id_for_session(session_id)

        loaded_profile = profiles_db.get_profile(session_id) or {}
    except Exception as exc:
        logger.exception("Failed to bootstrap WS session %s: %s", session_id, exc)
        await _send(ws, {"type": "error", "content": "Failed to load session"})
        await ws.close(code=1011)
        return

    graph = get_compiled_graph()

    try:
        while True:
            # --------------------------------------------------------------
            # Wait for the next student message from the client.
            # --------------------------------------------------------------
            raw = await ws.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await _send(ws, {"type": "error", "content": "Invalid JSON"})
                continue

            action = str(payload.get("action") or "message").strip().lower()
            if action not in ("message", "submit_attempt", "reveal_solution", "restore_exercise"):
                await _send(ws, {"type": "error", "content": "Unsupported chat action"})
                continue
            student_message = (
                str(payload.get("answer") or "").strip()
                if action == "submit_attempt"
                else str(payload.get("message") or "").strip()
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
                    await _send(ws, {"type": "error", "content": "Enter an answer under 10,000 characters and choose a valid exercise."})
                    continue
            course_id = str(payload.get("courseId") or course_id_resolved or "").strip()
            user_id = user_id_resolved or ""
            requested_mode = str(payload.get("mode") or "socratic").strip().lower()
            if requested_mode not in ("socratic", "exercise", "explain"):
                await _send(ws, {"type": "error", "content": "Unsupported learning mode"})
                continue
            if action != "message" and requested_mode != "exercise":
                await _send(ws, {"type": "error", "content": "Exercise actions require Short Answer Practice mode"})
                continue
            if requested_mode in ("exercise", "explain"):
                try:
                    user_id = _authenticate_exercise_request(
                        session_id,
                        course_id,
                        str(payload.get("accessToken") or "").strip(),
                    )
                except ValueError as exc:
                    await _send(ws, {"type": "error", "content": str(exc)})
                    continue
                except Exception:
                    logger.exception("Learning mode authorization lookup failed")
                    await _send(ws, {"type": "error", "content": "Could not verify access to this course. Please try again."})
                    continue

            if action == "restore_exercise":
                try:
                    latest_exercise = get_latest_exercise_for_owner(
                        session_id=session_id,
                        course_id=course_id,
                        user_id=user_id,
                    )
                    if latest_exercise:
                        exercise_data = latest_exercise.get("exercise_data") or {}
                        await _send(ws, {"type": "exercise", "content": {
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
                        }})
                        latest_attempt = get_latest_attempt_for_owner(
                            exercise_id=str(latest_exercise["id"]),
                            session_id=session_id,
                            user_id=user_id,
                        )
                        if latest_attempt:
                            await _send(ws, {"type": "correction", "content": {
                                "attempt_id": latest_attempt["id"],
                                "total_score": latest_attempt["total_score"],
                                "max_score": latest_attempt["max_score"],
                                "overall_feedback": latest_attempt["feedback"],
                                "error_category": latest_attempt["error_category"],
                                "criterion_feedback": latest_attempt["criterion_feedback"],
                                "citations": latest_attempt["citations"],
                                "next_step": latest_attempt["next_step"],
                                "hints_used": latest_attempt["hints_used"],
                            }})
                            if latest_attempt.get("solution_revealed"):
                                await _send(ws, {"type": "solution", "content": {
                                    "exercise_id": latest_exercise["id"],
                                    "expected_answer": latest_exercise["expected_answer"],
                                    "common_mistakes": latest_exercise.get("common_mistakes") or [],
                                }})
                except Exception:
                    logger.exception("Failed to restore exercise for session %s", session_id)
                    await _send(ws, {"type": "error", "content": "Could not restore the saved exercise."})
                    continue
                await _send(ws, {"type": "done"})
                continue

            exercise_id = str(payload.get("exerciseId") or "").strip()
            exercise_record: dict[str, Any] | None = None
            if action == "submit_attempt" and attempt_request:
                exercise_id = str(attempt_request.exercise_id)
            elif action == "reveal_solution":
                try:
                    exercise_id = str(ExerciseActionRequest.model_validate({"exercise_id": exercise_id}).exercise_id)
                except ValidationError:
                    await _send(ws, {"type": "error", "content": "Choose a valid exercise before revealing the solution."})
                    continue

            if action == "reveal_solution":
                try:
                    solution = reveal_solution_for_owner(
                        exercise_id=exercise_id,
                        session_id=session_id,
                        course_id=course_id,
                        user_id=user_id,
                    )
                except ValueError as exc:
                    await _send(ws, {"type": "error", "content": str(exc)})
                    continue
                except Exception:
                    logger.exception("Failed to reveal exercise solution")
                    await _send(ws, {"type": "error", "content": "Could not reveal the solution. Please try again."})
                    continue
                try:
                    messages_db.merge_latest_assistant_metadata(session_id, {"solution": solution})
                except Exception:
                    logger.exception("Failed to persist revealed solution snapshot")
                await _send(ws, {"type": "solution", "content": solution})
                await _send(ws, {"type": "done"})
                continue

            if action == "submit_attempt":
                try:
                    exercise_record = get_exercise_for_owner(
                        exercise_id=exercise_id,
                        session_id=session_id,
                        course_id=course_id,
                        user_id=user_id,
                    )
                    revealed = has_revealed_solution(
                        exercise_id=exercise_id,
                        session_id=session_id,
                        user_id=user_id,
                    )
                except Exception:
                    logger.exception("Failed to load exercise for submitted attempt")
                    await _send(ws, {"type": "error", "content": "Could not load this exercise. Please try again."})
                    continue
                if not exercise_record:
                    await _send(ws, {"type": "error", "content": "This exercise is not available in the selected inquiry."})
                    continue
                if revealed:
                    await _send(ws, {"type": "error", "content": "The solution has been revealed, so this exercise can no longer be submitted."})
                    continue

            # Per-request LLM overrides from the Settings dialog. Keys are
            # never logged; only explicitly supported providers are honored.
            client_api_key = str(payload.get("apiKey") or "").strip()
            client_model = str(payload.get("model") or "").strip()
            client_provider = str(payload.get("provider") or "").strip().lower()
            if client_provider not in ("google", "groq"):
                client_api_key = ""
                client_model = ""
                client_provider = "google"

            if not student_message:
                message = "Write an answer before submitting it." if action == "submit_attempt" else "Empty message"
                await _send(ws, {"type": "error", "content": message})
                continue
            if not course_id:
                await _send(ws, {"type": "error", "content": "Missing course_id"})
                continue

            # First message of the session = no prior assistant turns.
            is_first_message = not any(m["role"] == "assistant" for m in history)

            if is_first_message and action == "message":
                try:
                    messages_db.set_default_session_title_from_prompt(session_id, student_message)
                except Exception:
                    # Naming is helpful, but must never prevent a learning turn.
                    logger.exception("Failed to name inquiry from its first prompt")

            # Persist the user message before invoking the graph so it survives
            # any crash and is visible to subsequent turns.
            try:
                messages_db.save_message(
                    session_id,
                    "user",
                    display_message,
                    metadata={"learning_mode": requested_mode},
                )
            except Exception as exc:
                logger.exception("Failed to save user message: %s", exc)

            history = [*history, {"role": "user", "content": student_message}]

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
            if action == "submit_attempt":
                initial_state["exercise_record"] = exercise_record or {}
                initial_state["student_answer"] = student_message
                initial_state["hints_used"] = attempt_request.hints_used if attempt_request else 0

            assistant_text_parts: list[str] = []
            final_state: SocraState = initial_state
            exercise_result: dict[str, Any] | None = None
            correction_result: dict[str, Any] | None = None
            sent_diagnostic = False
            active_generation_node = ""
            generation_model_calls = 0

            try:
                async for ev in graph.astream_events(initial_state, version="v2"):
                    kind = ev.get("event")
                    event_name = ev.get("name")

                    if kind == "on_chain_start" and event_name in (
                        "diagnostiqueur", "exercise_generator", "explicateur", "correcteur",
                    ):
                        active_generation_node = str(event_name)
                        generation_model_calls = 0
                        progress_stage = {
                            "diagnostiqueur": "Reviewing the course material…",
                            "exercise_generator": "Finding relevant course material…",
                            "explicateur": "Gathering course pages and citations…",
                            "correcteur": "Reviewing your answer…",
                        }[active_generation_node]
                        await _send(ws, {"type": "progress", "content": {"stage": progress_stage}})

                    elif kind == "on_chat_model_start" and active_generation_node in ("exercise_generator", "explicateur", "correcteur"):
                        generation_model_calls += 1
                        if active_generation_node == "explicateur":
                            progress_stage = "Drafting the explanation…" if generation_model_calls == 1 else "Working through the explanation…"
                        elif active_generation_node == "exercise_generator":
                            progress_stage = "Creating a course-based question…" if generation_model_calls == 1 else "Verifying the question against your course…"
                        else:
                            progress_stage = "Preparing feedback…"
                        await _send(ws, {"type": "progress", "content": {"stage": progress_stage}})

                    # Stream Tuteur tokens to the client as they arrive.
                    if kind == "on_chat_model_stream":
                        tags = ev.get("tags") or []
                        if TUTEUR_LLM_TAG in tags:
                            chunk = ev.get("data", {}).get("chunk")
                            text = ""
                            if chunk is not None:
                                content = getattr(chunk, "content", None)
                                if isinstance(content, str):
                                    text = content
                                elif isinstance(content, list):
                                    text = "".join(
                                        part.get("text", "")
                                        for part in content
                                        if isinstance(part, dict)
                                    )
                            if text:
                                assistant_text_parts.append(text)
                                await _send(ws, {"type": "token", "content": text})

                    # When the Diagnostiqueur node finishes, ship its report.
                    elif kind == "on_chain_end":
                        name = ev.get("name")
                        data_out = ev.get("data", {}).get("output") or {}

                        if name == "diagnostiqueur" and not sent_diagnostic:
                            diag = data_out.get("diagnostic") if isinstance(data_out, dict) else None
                            if diag:
                                await _send(ws, {"type": "diagnostic", "content": diag})
                                sent_diagnostic = True
                            active_generation_node = ""

                        if name == "exercise_generator" and isinstance(data_out, dict):
                            exercise = data_out.get("exercise")
                            if exercise:
                                exercise_result = exercise
                                await _send(ws, {"type": "exercise", "content": exercise})
                            active_generation_node = ""

                        if name == "explicateur" and isinstance(data_out, dict):
                            explanation = data_out.get("explanation")
                            if explanation:
                                await _send(ws, {"type": "explanation", "content": explanation})
                            active_generation_node = ""

                        if name == "correcteur" and isinstance(data_out, dict):
                            correction = data_out.get("correction")
                            if correction:
                                correction_result = correction
                                await _send(ws, {"type": "correction", "content": correction})
                            active_generation_node = ""

                        # The whole graph finishing — capture the final state.
                        if name in ("LangGraph", "__start__") and isinstance(data_out, dict):
                            final_state = data_out  # type: ignore[assignment]

            except Exception as exc:
                logger.exception("Graph execution failed: %s", exc)
                provider_code = provider_error_code(exc)
                if provider_code:
                    await _send(ws, {"type": "error", "content": {
                        "code": provider_code,
                        "message": provider_error_message(provider_code),
                    }})
                else:
                    await _send(ws, {"type": "error", "content": str(exc)})
                continue

            # --------------------------------------------------------------
            # Reconstruct the assistant's full reply: prefer the streamed
            # tokens (so the user-visible text == the persisted text), fall
            # back to the state's ``streamed_response``.
            # --------------------------------------------------------------
            assistant_text = "".join(assistant_text_parts).strip()
            generated = final_state.get("exercise") or exercise_result
            explanation_result = final_state.get("explanation")
            if requested_mode == "exercise" and action == "message" and generated:
                assistant_text = f"Exercise ready: {generated.get('concept', 'your topic')}."
            if requested_mode == "explain" and action == "message":
                assistant_text = "Course explanation ready."
            if action == "submit_attempt":
                correction = final_state.get("correction") or correction_result or {}
                if correction:
                    assistant_text = f"You scored {correction.get('total_score', 0)} out of {correction.get('max_score', 10)}. Review your feedback below."
            if not assistant_text:
                assistant_text = (
                    (final_state.get("streamed_response") or "").strip()
                    or (final_state.get("tutor_signal") or {}).get("response_text", "").strip()
                )

            # If the Tuteur returned without ever streaming (e.g. all-at-once
            # mode), still emit it as a single token so the client renders it.
            if assistant_text and not assistant_text_parts:
                await _send(ws, {"type": "token", "content": assistant_text})

            # Send the context-panel update if Évaluateur ran.
            evaluation = final_state.get("evaluation")
            if evaluation:
                await _send(ws, {"type": "context", "content": evaluation})

            # Persist the assistant message and bump the session.
            try:
                if assistant_text:
                    # Persist only public mode payloads. Exercise answer/rubric
                    # remain private in the exercises table.
                    public_metadata: dict[str, Any] = {"learning_mode": requested_mode}
                    if generated:
                        public_metadata["exercise"] = generated
                    if correction_result or final_state.get("correction"):
                        correction = final_state.get("correction") or correction_result or {}
                        public_metadata["correction"] = correction
                        public_metadata["exercise_id"] = exercise_id
                    if explanation_result:
                        public_metadata["explanation"] = explanation_result
                    # Save text and its card snapshot atomically in one row;
                    # do not depend on an insert response returning an ID.
                    messages_db.save_message(
                        session_id, "assistant", assistant_text, metadata=public_metadata
                    )
                    history = [*history, {"role": "assistant", "content": assistant_text}]
                messages_db.touch_session(session_id)
            except Exception as exc:
                logger.exception("Failed to save assistant message: %s", exc)

            # Refresh the in-connection profile cache for the next turn.
            new_profile = final_state.get("profile")
            if new_profile:
                loaded_profile = dict(new_profile)

            await _send(ws, {"type": "done"})

    except WebSocketDisconnect:
        logger.info("WS disconnected: session=%s", session_id)
    except Exception as exc:
        logger.exception("Unexpected WS error for session %s: %s", session_id, exc)
        try:
            await _send(ws, {"type": "error", "content": str(exc)})
            await ws.close(code=1011)
        except Exception:
            pass
