"""Read/write the long-term StudentProfile maintained by Agent Mémoire."""
from __future__ import annotations

from typing import Any

from db.supabase_client import get_supabase


def get_profile(session_id: str) -> dict[str, Any] | None:
    res = (
        get_supabase()
        .table("student_profiles")
        .select("*")
        .eq("session_id", session_id)
        .maybe_single()
        .execute()
    )
    return res.data if res and res.data else None


def upsert_profile(
    session_id: str,
    user_id: str,
    *,
    mastered_concepts: list[str] | None = None,
    fragile_concepts: list[str] | None = None,
    misconception_history: list[str] | None = None,
    bloom_progression: list[str] | None = None,
    total_exchanges: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "session_id": session_id,
        "user_id": user_id,
    }
    if mastered_concepts is not None:
        payload["mastered_concepts"] = mastered_concepts
    if fragile_concepts is not None:
        payload["fragile_concepts"] = fragile_concepts
    if misconception_history is not None:
        payload["misconception_history"] = misconception_history
    if bloom_progression is not None:
        payload["bloom_progression"] = bloom_progression
    if total_exchanges is not None:
        payload["total_exchanges"] = total_exchanges

    res = (
        get_supabase()
        .table("student_profiles")
        .upsert(payload, on_conflict="session_id")
        .execute()
    )
    return res.data[0] if res.data else {}


def get_user_id_for_session(session_id: str) -> str | None:
    """Resolve the ``user_id`` that owns a session via sessions → courses."""
    res = (
        get_supabase()
        .table("sessions")
        .select("courses(user_id)")
        .eq("id", session_id)
        .single()
        .execute()
    )
    if not res.data:
        return None
    courses = res.data.get("courses")
    if isinstance(courses, list):
        return courses[0]["user_id"] if courses else None
    if isinstance(courses, dict):
        return courses.get("user_id")
    return None
