"""Server-only persistence for mixed course exams."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db.supabase_client import get_supabase


def create_exam(
    *, session_id: str, course_id: str, user_id: str, topic: str,
    exercise_ids: list[str], requested_types: list[str],
) -> dict[str, Any]:
    result = get_supabase().table("exams").insert({
        "session_id": session_id,
        "course_id": course_id,
        "user_id": user_id,
        "topic": topic,
        "exercise_ids": exercise_ids,
        "requested_types": requested_types,
        "status": "in_progress",
    }).execute()
    if not result.data:
        raise RuntimeError("Supabase did not return the created exam")
    return result.data[0]


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


def save_exam_answer(*, exam: dict[str, Any], exercise_id: str, answer: str) -> dict[str, Any]:
    if exam.get("status") != "in_progress":
        raise ValueError("This exam is already submitted")
    ids = [str(value) for value in exam.get("exercise_ids") or []]
    if exercise_id not in ids:
        raise ValueError("This question does not belong to the exam")
    answers = dict(exam.get("answers") or {})
    answers[exercise_id] = answer
    result = (
        get_supabase().table("exams").update({"answers": answers})
        .eq("id", exam["id"]).eq("user_id", exam["user_id"])
        .eq("status", "in_progress").select("*").execute()
    )
    if not result.data:
        raise ValueError("This exam is no longer accepting answers")
    return result.data[0]


def save_exam_results(*, exam: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    result = (
        get_supabase().table("exams").update({"results": results})
        .eq("id", exam["id"]).eq("user_id", exam["user_id"])
        .eq("status", "in_progress").select("*").execute()
    )
    if not result.data:
        raise ValueError("This exam is no longer accepting submissions")
    return result.data[0]


def complete_exam(*, exam: dict[str, Any], score: int, results: list[dict[str, Any]]) -> dict[str, Any]:
    result = (
        get_supabase().table("exams").update({
            "status": "completed",
            "score": score,
            "results": results,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", exam["id"]).eq("user_id", exam["user_id"])
        .eq("status", "in_progress").select("*").execute()
    )
    if not result.data:
        raise ValueError("This exam was already submitted")
    return result.data[0]
