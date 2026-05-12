"""WebSocket endpoint that streams the LangGraph pipeline to the frontend.

Protocol::

    client -> server:  {
        "message":   str,
        "courseId":  uuid,
        "sessionId": uuid,
        "apiKey":    str | null,    # optional - overrides server GEMINI_API_KEY
        "model":     str | null,    # optional - overrides server default model
    }
    server -> client:  { "type": "diagnostic", "content": DiagnosticReport }   (first turn only)
                       { "type": "token",      "content": "<partial text>" }   (many)
                       { "type": "context",    "content": EvaluationResult }   (when applicable)
                       { "type": "done" }                                       (always)
                       { "type": "error",      "content": "<message>" }        (on failure)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agents.tuteur_socratique import TUTEUR_LLM_TAG
from db import messages as messages_db
from db import profiles as profiles_db
from db.diagnostics import get_course_id_for_session
from graph.orchestrator import get_compiled_graph
from graph.state import ChatTurn, SocraState


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
) -> SocraState:
    state: SocraState = {
        "session_id": session_id,
        "course_id": course_id,
        "user_id": user_id,
        "messages": history,
        "student_message": student_message,
        "is_first_message": is_first_message,
        "profile": {
            "session_id": session_id,
            "user_id": user_id,
            "mastered_concepts": (profile or {}).get("mastered_concepts") or [],
            "fragile_concepts": (profile or {}).get("fragile_concepts") or [],
            "misconception_history": (profile or {}).get("misconception_history") or [],
            "bloom_progression": (profile or {}).get("bloom_progression") or [],
            "total_exchanges": int((profile or {}).get("total_exchanges") or 0),
        },
    }
    if api_key:
        state["api_key"] = api_key
    if model:
        state["model"] = model
    return state


async def _send(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, default=str))


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

            student_message = (payload.get("message") or "").strip()
            course_id = (payload.get("courseId") or course_id_resolved or "").strip()
            user_id = user_id_resolved or ""

            # Per-request LLM overrides from the Settings dialog. Only Google /
            # Gemini is wired through right now (other providers are disabled
            # in the frontend); the keys are NOT logged.
            client_api_key = (payload.get("apiKey") or "").strip()
            client_model = (payload.get("model") or "").strip()
            client_provider = (payload.get("provider") or "").strip().lower()
            # Defensive: only honour overrides if the provider is explicitly
            # google. An OpenAI / Anthropic key would be useless against the
            # Gemini SDK and would just produce confusing 401s.
            if client_provider and client_provider != "google":
                client_api_key = ""
                client_model = ""

            if not student_message:
                await _send(ws, {"type": "error", "content": "Empty message"})
                continue
            if not course_id:
                await _send(ws, {"type": "error", "content": "Missing course_id"})
                continue

            # First message of the session = no prior assistant turns.
            is_first_message = not any(m["role"] == "assistant" for m in history)

            # Persist the user message before invoking the graph so it survives
            # any crash and is visible to subsequent turns.
            try:
                messages_db.save_message(session_id, "user", student_message)
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
            )

            assistant_text_parts: list[str] = []
            final_state: SocraState = initial_state
            sent_diagnostic = False

            try:
                async for ev in graph.astream_events(initial_state, version="v2"):
                    kind = ev.get("event")

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

                        # The whole graph finishing — capture the final state.
                        if name in ("LangGraph", "__start__") and isinstance(data_out, dict):
                            final_state = data_out  # type: ignore[assignment]

            except Exception as exc:
                logger.exception("Graph execution failed: %s", exc)
                await _send(ws, {"type": "error", "content": str(exc)})
                continue

            # --------------------------------------------------------------
            # Reconstruct the assistant's full reply: prefer the streamed
            # tokens (so the user-visible text == the persisted text), fall
            # back to the state's ``streamed_response``.
            # --------------------------------------------------------------
            assistant_text = "".join(assistant_text_parts).strip()
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
                    messages_db.save_message(session_id, "assistant", assistant_text)
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
