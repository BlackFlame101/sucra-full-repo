"""Read/write diagnostic results produced by Agent Diagnostiqueur."""
from __future__ import annotations

from typing import Any

from db.supabase_client import get_supabase


def save_diagnostic(
    session_id: str,
    *,
    topic: str,
    initial_level: str,
    identified_gaps: list[str],
    prerequisite_concepts: list[str],
) -> dict[str, Any]:
    payload = {
        "session_id": session_id,
        "topic": topic,
        "initial_level": initial_level,
        "identified_gaps": identified_gaps,
        "prerequisite_concepts": prerequisite_concepts,
    }
    res = get_supabase().table("diagnostics").insert(payload).execute()
    return res.data[0] if res.data else {}


def get_diagnostic(session_id: str) -> dict[str, Any] | None:
    res = (
        get_supabase()
        .table("diagnostics")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def get_course_id_for_session(session_id: str) -> str | None:
    res = (
        get_supabase()
        .table("sessions")
        .select("course_id")
        .eq("id", session_id)
        .single()
        .execute()
    )
    if not res.data:
        return None
    return res.data.get("course_id")


def get_language_for_session(session_id: str) -> str:
    res = (
        get_supabase().table("sessions").select("language")
        .eq("id", session_id).single().execute()
    )
    return "en" if (res.data or {}).get("language") == "en" else "fr"
