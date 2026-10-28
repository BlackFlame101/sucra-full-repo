"""Agent Tuteur Socratique — the only agent the student sees directly.

Behaviour:
  • Builds a context block from diagnostic + profile + RAG + conversation.
  • Streams Gemini's reply token-by-token. Tokens flow up to the WebSocket
    layer via LangGraph's ``astream_events`` (no in-band side channel).
  • After the stream completes, derives the :class:`TutorSignal` from
    deterministic heuristics over the student's last message — so the
    visible prose stays clean.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.llm import get_chat_llm
from graph.state import BloomLevel, ChatTurn, SocraState, TutorSignal
from prompts.tuteur_socratique_prompt import CONTEXT_TEMPLATE, SYSTEM_PROMPT
from rag.retriever import format_chunks_for_prompt, retrieve_chunks


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Heuristics that derive the structured signal *without* a second LLM call.
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)
_FACTUAL_MARKERS = (
    " is ", " are ", " was ", " were ", " because ", " therefore ", " means ",
    " est ", " sont ", " parce que ", " donc ", " signifie ", " car ",
)


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def _is_substantive_answer(student_message: str) -> bool:
    msg = (student_message or "").strip().lower()
    if not msg:
        return False
    if _word_count(msg) >= 20:
        return True
    if any(marker in f" {msg} " for marker in _FACTUAL_MARKERS):
        return _word_count(msg) >= 8
    return False


_BLOOM_KEYWORDS: dict[BloomLevel, tuple[str, ...]] = {
    "create":   ("design", "build", "imagine", "compose", "concevez", "imaginez"),
    "evaluate": ("judge", "critique", "compare", "evaluate", "jugez", "comparez", "évaluez"),
    "analyze":  ("why", "analy", "decompose", "pourquoi", "analyse", "distingue"),
    "apply":    ("how would", "apply", "use", "comment ferais", "appliquez"),
    "understand": ("explain", "in your own words", "expliquez", "vos propres mots"),
    "remember": ("define", "list", "recall", "définissez", "listez", "rappelez"),
}


def _infer_bloom(tutor_response: str) -> BloomLevel:
    text = (tutor_response or "").lower()
    for level, keywords in _BLOOM_KEYWORDS.items():
        if any(k in text for k in keywords):
            return level
    return "understand"


def _infer_language(text: str) -> str:
    """Small deterministic language hint for the tutor prompt."""
    lowered = (text or "").lower()
    french_markers = ("é", "è", "ê", "à", "ç", " je ", " est ", " les ", " des ", " pourquoi ", " comment ", "dans ")
    return "French" if any(marker in lowered for marker in french_markers) else "English"


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

def _format_history(messages: Iterable[ChatTurn]) -> list[SystemMessage | HumanMessage | AIMessage]:
    out: list[SystemMessage | HumanMessage | AIMessage] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        if not content:
            continue
        if role == "user":
            out.append(HumanMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
    return out


def _build_context_block(state: SocraState, course_context: str) -> str:
    diag = state.get("diagnostic") or {}
    profile = state.get("profile") or {}
    language_code = (state.get("language") or "").lower()
    language = "French" if language_code.startswith("fr") else "English" if language_code.startswith("en") else _infer_language(state.get("student_message") or "")
    return CONTEXT_TEMPLATE.format(
        response_language=language,
        topic=diag.get("topic") or "(not yet determined)",
        initial_level=diag.get("initial_level") or "(unknown)",
        identified_gaps=", ".join(diag.get("identified_gaps") or []) or "(none recorded)",
        prerequisite_concepts=", ".join(diag.get("prerequisite_concepts") or []) or "(none recorded)",
        first_socratic_question=diag.get("first_socratic_question") or "(none — generate your own opening)",
        mastered_concepts=", ".join(profile.get("mastered_concepts") or []) or "(none yet)",
        fragile_concepts=", ".join(profile.get("fragile_concepts") or []) or "(none yet)",
        misconception_history=", ".join(profile.get("misconception_history") or []) or "(none yet)",
        total_exchanges=profile.get("total_exchanges") or 0,
        course_context=course_context or "(no relevant excerpts found)",
    )


# ---------------------------------------------------------------------------
# Node entry point
# ---------------------------------------------------------------------------

# Tag attached to the LLM call so the WebSocket layer can filter
# `on_chat_model_stream` events that originate from THIS agent only.
TUTEUR_LLM_TAG = "tuteur_socratique_llm"


async def run_tuteur(state: SocraState) -> SocraState:
    student_message = (state.get("student_message") or "").strip()
    course_id = state.get("course_id", "")
    history = state.get("messages") or []

    # The latest student message is already in `messages` if the WS handler
    # appended it before invoking the graph; if not, we add it now.
    if not history or history[-1].get("role") != "user" or history[-1].get("content") != student_message:
        if student_message:
            history = [*history, {"role": "user", "content": student_message}]

    chunks = await retrieve_chunks(student_message, course_id, k=4) if (student_message and course_id) else []
    context_block = _build_context_block(state, format_chunks_for_prompt(chunks))

    llm = get_chat_llm(
        temperature=0.6,
        streaming=True,
        api_key=state.get("api_key"),
        model=state.get("model"),
        provider=state.get("provider"),
    ).with_config(
        tags=[TUTEUR_LLM_TAG],
        run_name="tuteur_socratique",
    )

    messages: list = [
        SystemMessage(content=(
            f"{SYSTEM_PROMPT}\n\nNON-NEGOTIABLE LANGUAGE RULE: Reply only in "
            f"{'French' if (state.get('language') or '').lower().startswith('fr') else 'English' if state.get('language') else _infer_language(student_message)}."
        )),
        SystemMessage(content=context_block),
        *_format_history(history),
    ]

    # Stream explicitly so we can salvage partial output if Gemini errors
    # mid-stream (the public endpoint occasionally returns 503 under load).
    response_parts: list[str] = []
    error: Exception | None = None
    try:
        async for chunk in llm.astream(messages):
            content = chunk.content
            if isinstance(content, str):
                response_parts.append(content)
            elif isinstance(content, list):
                response_parts.extend(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict)
                )
    except Exception as exc:  # noqa: BLE001 - we want to capture all stream errors
        error = exc
        logger.warning("Tuteur stream interrupted (%s); using %d partial parts",
                       exc, len(response_parts))

    response_text = "".join(response_parts).strip()
    if not response_text:
        response_text = (
            "I had trouble formulating my next question. Could you tell me, in "
            "your own words, what you currently understand about this?"
        )
        if error is not None:
            logger.exception("Tuteur LLM call failed completely: %s", error)

    signal: TutorSignal = {
        "response_text": response_text,
        "bloom_level": _infer_bloom(response_text),
        "should_evaluate": _is_substantive_answer(student_message),
        "key_concepts_mentioned": [],
    }

    return {
        **state,
        "agent_issues": [
            *(state.get("agent_issues") or []),
            *([{"agent": "tuteur_socratique", "kind": "fallback"}] if error is not None else []),
        ],
        "tutor_signal": signal,
        "streamed_response": response_text,
        "retrieved_chunks": chunks,
        "current_node": "tuteur_socratique",
    }
