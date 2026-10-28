"""Persistence for generated course-grounded exercises."""
from __future__ import annotations

from typing import Any

from db.supabase_client import get_supabase


def get_recent_exercise_prompts(
    *, session_id: str, course_id: str, user_id: str, limit: int = 8
) -> list[dict[str, Any]]:
    """Return recent prompts for this owner's session, without private answers/rubrics."""
    bounded_limit = max(1, min(limit, 20))
    result = (
        get_supabase().table("exercises")
        .select("concept, prompt, exercise_type, citations")
        .eq("session_id", session_id)
        .eq("course_id", course_id)
        .eq("user_id", user_id)
        .eq("verification_status", "verified")
        .order("created_at", desc=True)
        .limit(bounded_limit)
        .execute()
    )
    return [
        {
            "concept": str(row.get("concept") or ""),
            "prompt": str(row.get("prompt") or ""),
            "exercise_type": str(row.get("exercise_type") or ""),
            "citations": row.get("citations") or [],
        }
        for row in (result.data or [])
        if row.get("prompt")
    ]


def create_exercise(
    *,
    session_id: str,
    course_id: str,
    user_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    row = {
        "session_id": session_id,
        "course_id": course_id,
        "user_id": user_id,
        **payload,
    }
    result = get_supabase().table("exercises").insert(row).execute()
    if not result.data:
        raise RuntimeError("Supabase did not return the created exercise")
    return result.data[0]
