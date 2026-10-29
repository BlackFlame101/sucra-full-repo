"""Agent Évaluateur — silent analysis after every substantive student turn.

Outputs an :class:`EvaluationResult` that:
  • feeds the right-hand context panel in the frontend (KeyTerms +
    SuggestedReading).
  • feeds Agent Mémoire so the long-term student profile can evolve.

Side-effect: persists the extracted ``key_terms`` to ``public.key_terms``
so they survive page reloads.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agents.llm import get_chat_llm
from agents.structured_output import parse_json_object
from db.supabase_client import get_supabase
from graph.state import ChatTurn, EvaluationResult, SocraState, SuggestedReadingItem
from prompts.evaluateur_prompt import SYSTEM_PROMPT, USER_TEMPLATE
from rag.retriever import retrieve_chunks


logger = logging.getLogger(__name__)


def _format_history(messages: list[ChatTurn], limit: int = 8) -> str:
    recent = messages[-limit:] if messages else []
    if not recent:
        return "(no prior exchanges)"
    lines: list[str] = []
    for m in recent:
        prefix = "Student" if m.get("role") == "user" else "Tutor"
        lines.append(f"{prefix}: {m.get('content', '').strip()}")
    return "\n".join(lines)


def _format_excerpts(chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return "(no excerpts available)"
    lines: list[str] = []
    for i, c in enumerate(chunks, start=1):
        page = c.get("page_number")
        fname = c.get("filename") or "document"
        doc_id = c.get("document_id") or "null"
        snippet = (c.get("content") or "").strip().replace("\n", " ")
        if len(snippet) > 280:
            snippet = snippet[:280].rsplit(" ", 1)[0] + "..."
        lines.append(
            f"[{i}] document_id={doc_id} | filename={fname} | page={page}\n    {snippet}"
        )
    return "\n".join(lines)


_STOP_TERMS = {
    "about", "after", "also", "because", "before", "between", "could",
    "does", "from", "have", "into", "just", "more", "most", "other",
    "over", "same", "some", "such", "than", "that", "their", "them",
    "then", "there", "these", "they", "this", "those", "through", "what",
    "when", "where", "which", "while", "with", "would", "your", "what",
    "dans", "avec", "pour", "mais", "donc", "comme", "cette", "cela",
    "être", "avoir", "plus", "tout", "tous", "elle", "elles", "nous",
    "vous", "leur", "leurs", "qui", "que", "quoi", "comment", "pourquoi",
}


def _fallback_key_terms(
    chunks: list[dict[str, Any]],
) -> list[str]:
    """Conservative fallback terms from course excerpts, never tutor prose."""
    text = " ".join(str(c.get("content") or "") for c in chunks[:3])
    candidates = re.findall(r"\b[A-Za-zÀ-ÖØ-öø-ÿ][\wÀ-ÖØ-öø-ÿ-]{3,}\b", text, flags=re.UNICODE)
    terms: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        term = " ".join(candidate.split()).strip(" -.,:;!?()[]{}")
        words = term.lower().split()
        if not term or len(words) > 1 or all(w in _STOP_TERMS for w in words):
            continue
        if sum(len(w) > 2 and w not in _STOP_TERMS for w in words) == 0:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        terms.append(term)
        if len(terms) == 5:
            break
    return terms


def _normalise_evaluation(
    data: dict[str, Any],
    fallback_chunks: list[dict[str, Any]],
) -> EvaluationResult:
    def _clamp_score(v: Any) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, f))

    def _str_list(v: Any) -> list[str]:
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

    def _normalise_readings(v: Any) -> list[SuggestedReadingItem]:
        out: list[SuggestedReadingItem] = []
        if not isinstance(v, list):
            return out
        for r in v:
            if not isinstance(r, dict):
                continue
            item: SuggestedReadingItem = {
                "document_id": str(r.get("document_id") or "") or None,  # type: ignore[typeddict-item]
                "filename": str(r.get("filename") or "") or None,  # type: ignore[typeddict-item]
                "page_number": (
                    int(r["page_number"])
                    if r.get("page_number") not in (None, "", "null")
                    and str(r["page_number"]).lstrip("-").isdigit()
                    else None
                ),
                "excerpt": str(r.get("excerpt") or "").strip()[:240],
                "similarity": (
                    float(r["similarity"])
                    if isinstance(r.get("similarity"), (int, float))
                    else None
                ),
            }
            out.append(item)
        return out[:2]

    readings = _normalise_readings(data.get("suggested_readings"))
    if not readings and fallback_chunks:
        for c in fallback_chunks[:2]:
            readings.append(
                {
                    "document_id": c.get("document_id"),
                    "filename": c.get("filename"),
                    "page_number": c.get("page_number"),
                    "excerpt": (c.get("content") or "").strip()[:240],
                    "similarity": c.get("similarity"),
                }
            )

    return EvaluationResult(
        comprehension_score=_clamp_score(data.get("comprehension_score")),
        misconceptions=_str_list(data.get("misconceptions"))[:5],
        concepts_understood=_str_list(data.get("concepts_understood"))[:8],
        key_terms=_str_list(data.get("key_terms"))[:5],
        suggested_readings=readings,
        next_micro_objective=str(data.get("next_micro_objective") or "").strip(),
    )


def _persist_key_terms(session_id: str, terms: list[str]) -> None:
    if not session_id or not terms:
        return
    try:
        existing_res = (
            get_supabase()
            .table("key_terms")
            .select("term")
            .eq("session_id", session_id)
            .execute()
        )
        already = {row["term"].lower() for row in (existing_res.data or [])}
        new_rows = [
            {"session_id": session_id, "term": t}
            for t in terms
            if t and t.lower() not in already
        ]
        if new_rows:
            get_supabase().table("key_terms").insert(new_rows).execute()
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to persist key_terms: %s", exc)


async def run_evaluateur(state: SocraState) -> SocraState:
    student_message = (state.get("student_message") or "").strip()
    course_id = state.get("course_id", "")
    session_id = state.get("session_id", "")
    history = state.get("messages") or []
    profile = state.get("profile") or {}
    tutor_signal = state.get("tutor_signal") or {}
    response_language = "French" if (state.get("language") or "fr").lower().startswith("fr") else "English"

    # Reuse any chunks the Tuteur already pulled; otherwise retrieve fresh.
    chunks = state.get("retrieved_chunks") or []
    if not chunks and course_id and student_message:
        chunks = await retrieve_chunks(student_message, course_id, k=4)

    user_prompt = USER_TEMPLATE.format(
        history=_format_history(history),
        tutor_question=tutor_signal.get("response_text") or "(none yet)",
        student_response=student_message or "(empty)",
        excerpts_block=_format_excerpts(chunks),
        mastered=", ".join(profile.get("mastered_concepts") or []) or "(none)",
        fragile=", ".join(profile.get("fragile_concepts") or []) or "(none)",
    )

    llm = get_chat_llm(
        temperature=0.2,
        streaming=False,
        api_key=state.get("api_key"),
        model=state.get("model"),
        provider=state.get("provider"),
    )

    used_fallback = False
    try:
        result = await llm.ainvoke(
            [SystemMessage(content=(
                f"{SYSTEM_PROMPT}\n\nLANGUAGE REQUIREMENT: Write every natural-language value in the JSON "
                f"in {response_language}. Preserve filenames, proper nouns, and quoted source text as given."
            )), HumanMessage(content=user_prompt)]
        )
        data = parse_json_object(result.content)
        evaluation = _normalise_evaluation(data, chunks)
        if not evaluation.get("key_terms"):
            used_fallback = True
    except (ValueError, TypeError) as exc:
        used_fallback = True
        logger.warning("Évaluateur JSON parse failed (%s); using empty evaluation", exc)
        evaluation = _normalise_evaluation({}, chunks)
    except Exception as exc:  # pragma: no cover - defensive
        used_fallback = True
        logger.exception("Évaluateur LLM call failed: %s", exc)
        evaluation = _normalise_evaluation({}, chunks)

    if not evaluation.get("key_terms"):
        fallback_terms = _fallback_key_terms(chunks)
        if fallback_terms:
            evaluation["key_terms"] = fallback_terms
    if used_fallback:
        evaluation["used_fallback"] = True  # type: ignore[typeddict-unknown-key]

    _persist_key_terms(session_id, evaluation.get("key_terms") or [])

    return {
        **state,
        "agent_issues": [
            *(state.get("agent_issues") or []),
            *([{"agent": "evaluateur", "kind": "fallback"}] if used_fallback else []),
        ],
        "evaluation": evaluation,
        "current_node": "evaluateur",
    }
