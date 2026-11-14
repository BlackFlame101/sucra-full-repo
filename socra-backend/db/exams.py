"""Server-only persistence for mixed course exams."""
from __future__ import annotations

from typing import Any

from db.supabase_client import get_supabase


def get_exam_for_owner(*, exam_id: str, user_id: str) -> dict[str, Any] | None:
    result = (
        get_supabase().table("exams").select("*")
        .eq("id", exam_id).eq("user_id", user_id).limit(1).execute()
    )
    return result.data[0] if result.data else None


def get_exam_for_session(*, session_id: str, user_id: str) -> dict[str, Any] | None:
    result = (
        get_supabase().table("exams").select("*")
        .eq("session_id", session_id).eq("user_id", user_id)
        .order("created_at", desc=True).limit(1).execute()
    )
    return result.data[0] if result.data else None


def get_course_exams(*, course_id: str, user_id: str) -> list[dict[str, Any]]:
    result = (
        get_supabase().table("exams").select("id, session_id, status")
        .eq("course_id", course_id).eq("user_id", user_id)
        .order("created_at", desc=True).execute()
    )
    return result.data or []


def get_exam_exercises(exam: dict[str, Any]) -> list[dict[str, Any]]:
    ids = [str(value) for value in exam.get("exercise_ids") or []]
    if not ids:
        return []
    rows = (
        get_supabase().table("exercises").select("*")
        .in_("id", ids)
        .eq("session_id", exam["session_id"])
        .eq("course_id", exam["course_id"])
        .eq("user_id", exam["user_id"])
        .eq("verification_status", "verified")
        .execute()
    ).data or []
    by_id = {str(row["id"]): row for row in rows}
    return [by_id[exercise_id] for exercise_id in ids if exercise_id in by_id]


def get_exam_job_exam(exam_id: str) -> dict[str, Any] | None:
    rows = get_supabase().table("exams").select("*").eq("id", exam_id).limit(1).execute().data
    return rows[0] if rows else None


def get_exam_slots(job_id: str) -> list[dict[str, Any]]:
    return get_supabase().table("exercises").select("exam_slot,prompt").eq(
        "exam_job_id", job_id,
    ).eq("verification_status", "verified").execute().data or []


def count_exam_slots(exam_id: str) -> int:
    jobs = get_supabase().table("exam_jobs").select("id").eq("exam_id", exam_id).eq(
        "kind", "generation",
    ).limit(1).execute().data
    if not jobs:
        return 0
    result = get_supabase().table("exercises").select("id", count="exact", head=True).eq(
        "exam_job_id", jobs[0]["id"],
    ).eq("verification_status", "verified").execute()
    return result.count or 0
