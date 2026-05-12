"""Agent Diagnostiqueur — first node of the LangGraph pipeline.

Workflow::

  topic + RAG excerpts ─► Gemini ─► JSON DiagnosticReport ─► Supabase persist
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agents.llm import get_chat_llm
from db import diagnostics as diag_db
from graph.state import DiagnosticReport, SocraState
from prompts.diagnostiqueur_prompt import SYSTEM_PROMPT, USER_TEMPLATE
from rag.retriever import format_chunks_for_prompt, retrieve_chunks


logger = logging.getLogger(__name__)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _coerce_json(raw: str) -> dict[str, Any]:
    """Best-effort extraction of a JSON object from an LLM response."""
    text = raw.strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1)
    else:
        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last != -1 and last > first:
            text = text[first : last + 1]
    return json.loads(text)


def _fallback_report(topic: str, reason: str) -> DiagnosticReport:
    logger.warning("Diagnostiqueur fallback (%s) for topic %r", reason, topic)
    return DiagnosticReport(
        topic=topic or "Unknown topic",
        initial_level="beginner",
        identified_gaps=[],
        prerequisite_concepts=[],
        first_socratic_question=(
            f"Before we begin with {topic or 'this topic'}, in your own words, "
            "what do you already think you know about it?"
        ),
    )


def _normalise_report(data: dict[str, Any], topic: str) -> DiagnosticReport:
    level = str(data.get("initial_level", "beginner")).lower()
    if level not in ("beginner", "intermediate", "advanced"):
        level = "beginner"

    def _as_str_list(v: Any) -> list[str]:
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    return DiagnosticReport(
        topic=str(data.get("topic") or topic).strip(),
        initial_level=level,  # type: ignore[arg-type]
        identified_gaps=_as_str_list(data.get("identified_gaps")),
        prerequisite_concepts=_as_str_list(data.get("prerequisite_concepts")),
        first_socratic_question=str(
            data.get("first_socratic_question")
            or f"What do you already know about {topic or 'this topic'}?"
        ).strip(),
    )


async def run_diagnostiqueur(state: SocraState) -> SocraState:
    """Async entry point used as a LangGraph node."""
    topic = (state.get("student_message") or "").strip()
    course_id = state.get("course_id", "")
    session_id = state.get("session_id", "")

    if not topic:
        topic = "the chosen topic"

    chunks = await retrieve_chunks(topic, course_id, k=4) if course_id else []
    context = format_chunks_for_prompt(chunks)

    llm = get_chat_llm(
        temperature=0.3,
        streaming=False,
        api_key=state.get("api_key"),
        model=state.get("model"),
    )
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=USER_TEMPLATE.format(topic=topic, course_context=context)),
    ]

    try:
        result = await llm.ainvoke(messages)
        raw = result.content if isinstance(result.content, str) else str(result.content)
        report = _normalise_report(_coerce_json(raw), topic)
    except json.JSONDecodeError as exc:
        report = _fallback_report(topic, f"json-decode: {exc}")
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Diagnostiqueur LLM call failed: %s", exc)
        report = _fallback_report(topic, f"llm-error: {exc}")

    if session_id:
        try:
            diag_db.save_diagnostic(
                session_id,
                topic=report["topic"],
                initial_level=report["initial_level"],
                identified_gaps=report.get("identified_gaps", []),
                prerequisite_concepts=report.get("prerequisite_concepts", []),
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Failed to persist diagnostic for session %s: %s", session_id, exc)

    return {
        **state,
        "diagnostic": report,
        "retrieved_chunks": chunks,
        "current_node": "diagnostiqueur",
    }
