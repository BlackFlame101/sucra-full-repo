"""Agent Mémoire — long-term student profile maintenance.

Loads the current :class:`StudentProfile` from Supabase, mutates it
according to the latest :class:`EvaluationResult`, and persists the new
profile back. The Tuteur reads this profile on the next turn to personalise
its questioning.

Decisions are deterministic so the behaviour is predictable and inspectable
during the academic demo. (We can layer an LLM-narrated summary later.)
"""
from __future__ import annotations

import logging
from typing import Iterable

from db import profiles as profiles_db
from graph.state import BloomLevel, EvaluationResult, SocraState, StudentProfile
from prompts.memoire_prompt import (
    FRAGILE_THRESHOLD,
    MASTERY_THRESHOLD,
    MAX_BLOOM_HISTORY,
    MAX_FRAGILE,
    MAX_MASTERED,
    MAX_MISCONCEPTION_HISTORY,
)


logger = logging.getLogger(__name__)


def _dedup_capped(items: Iterable[str], cap: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        if not raw:
            continue
        s = raw.strip()
        key = s.lower()
        if not s or key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out[-cap:]


def _ensure_profile_shape(p: dict | None, session_id: str, user_id: str) -> StudentProfile:
    base: StudentProfile = {
        "session_id": session_id,
        "user_id": user_id,
        "mastered_concepts": [],
        "fragile_concepts": [],
        "misconception_history": [],
        "bloom_progression": [],
        "total_exchanges": 0,
        "exercise_performance": [],
    }
    if not p:
        return base
    for key in (
        "mastered_concepts",
        "fragile_concepts",
        "misconception_history",
        "bloom_progression",
    ):
        v = p.get(key)
        base[key] = v if isinstance(v, list) else []  # type: ignore[literal-required]
    base["total_exchanges"] = int(p.get("total_exchanges") or 0)
    evidence = p.get("exercise_performance")
    base["exercise_performance"] = evidence if isinstance(evidence, list) else []
    return base


def _apply_evaluation(
    profile: StudentProfile,
    evaluation: EvaluationResult,
    *,
    bloom_level: BloomLevel | None,
) -> StudentProfile:
    score = float(evaluation.get("comprehension_score") or 0.0)
    understood = list(evaluation.get("concepts_understood") or [])
    misconceptions = list(evaluation.get("misconceptions") or [])

    mastered = list(profile.get("mastered_concepts") or [])
    fragile = list(profile.get("fragile_concepts") or [])
    misc_history = list(profile.get("misconception_history") or [])
    bloom_hist = list(profile.get("bloom_progression") or [])

    if score >= MASTERY_THRESHOLD:
        mastered.extend(understood)
        # Anything mastered should leave the fragile list.
        mastered_lower = {c.lower() for c in understood}
        fragile = [c for c in fragile if c.lower() not in mastered_lower]
    elif score <= FRAGILE_THRESHOLD:
        fragile.extend(understood)
    else:
        # Mid-band: add to fragile if not already mastered.
        mastered_lower = {c.lower() for c in mastered}
        fragile.extend(c for c in understood if c.lower() not in mastered_lower)

    misc_history.extend(misconceptions)

    if bloom_level:
        bloom_hist.append(bloom_level)

    return {
        "session_id": profile["session_id"],
        "user_id": profile["user_id"],
        "mastered_concepts": _dedup_capped(mastered, MAX_MASTERED),
        "fragile_concepts": _dedup_capped(fragile, MAX_FRAGILE),
        "misconception_history": _dedup_capped(misc_history, MAX_MISCONCEPTION_HISTORY),
        "bloom_progression": bloom_hist[-MAX_BLOOM_HISTORY:],
        "exercise_performance": list(profile.get("exercise_performance") or []),
        "total_exchanges": int(profile.get("total_exchanges") or 0) + 1,
    }


def _apply_exercise_correction(
    profile: StudentProfile,
    correction: dict,
    exercise: dict,
) -> StudentProfile:
    concept = str(exercise.get("concept") or "Short-answer exercise").strip()
    total = int(correction.get("total_score") or 0)
    maximum = max(1, int(correction.get("max_score") or 10))
    ratio = total / maximum
    mastered = list(profile.get("mastered_concepts") or [])
    fragile = list(profile.get("fragile_concepts") or [])
    if ratio >= MASTERY_THRESHOLD:
        mastered.append(concept)
        fragile = [item for item in fragile if item.casefold() != concept.casefold()]
    elif ratio <= FRAGILE_THRESHOLD and all(item.casefold() != concept.casefold() for item in mastered):
        fragile.append(concept)

    bloom = exercise.get("bloom_level")
    bloom_hist = list(profile.get("bloom_progression") or [])
    if bloom:
        bloom_hist.append(str(bloom))
    evidence = list(profile.get("exercise_performance") or [])
    evidence.append({
        "exercise_id": str(exercise.get("id") or ""),
        "concept": concept,
        "total_score": total,
        "max_score": maximum,
        "error_category": correction.get("error_category"),
        "hints_used": int(correction.get("hints_used") or 0),
        "criterion_feedback": correction.get("criterion_feedback") or [],
    })
    return {
        **profile,
        "mastered_concepts": _dedup_capped(mastered, MAX_MASTERED),
        "fragile_concepts": _dedup_capped(fragile, MAX_FRAGILE),
        "bloom_progression": bloom_hist[-MAX_BLOOM_HISTORY:],
        "exercise_performance": evidence[-30:],
        "total_exchanges": int(profile.get("total_exchanges") or 0) + 1,
    }


async def run_memoire(state: SocraState) -> SocraState:
    session_id = state.get("session_id", "")
    user_id = state.get("user_id", "")
    evaluation = state.get("evaluation") or {}
    correction = state.get("correction") or {}
    tutor_signal = state.get("tutor_signal") or {}
    bloom_level = tutor_signal.get("bloom_level")

    if not session_id or not user_id:
        logger.warning("memoire: missing session_id/user_id, skipping persistence")
        return {**state, "current_node": "memoire"}

    # Prefer the profile already in state (loaded once at WS connect time).
    current_profile_dict = state.get("profile") or {}
    if not current_profile_dict:
        try:
            current_profile_dict = profiles_db.get_profile(session_id) or {}
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("memoire: failed to load profile: %s", exc)
            current_profile_dict = {}

    current_profile = _ensure_profile_shape(current_profile_dict, session_id, user_id)
    if correction:
        updated_profile = _apply_exercise_correction(
            current_profile,
            correction,
            state.get("exercise_record") or {},
        )
    else:
        updated_profile = _apply_evaluation(current_profile, evaluation, bloom_level=bloom_level)

    try:
        profiles_db.upsert_profile(
            session_id,
            user_id,
            mastered_concepts=updated_profile["mastered_concepts"],
            fragile_concepts=updated_profile["fragile_concepts"],
            misconception_history=updated_profile["misconception_history"],
            bloom_progression=updated_profile["bloom_progression"],
            total_exchanges=updated_profile["total_exchanges"],
            exercise_performance=updated_profile["exercise_performance"],
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("memoire: failed to persist profile: %s", exc)

    return {
        **state,
        "profile": updated_profile,
        "current_node": "memoire",
    }
