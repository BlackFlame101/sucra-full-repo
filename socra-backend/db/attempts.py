"""Server-only access to private exercise records and submitted attempts."""
from __future__ import annotations

from typing import Any

from db.supabase_client import get_supabase


def get_latest_exercise_for_owner(
    *, session_id: str, course_id: str, user_id: str
) -> dict[str, Any] | None:
    result = (
        get_supabase().table("exercises").select("*")
        .eq("session_id", session_id)
        .eq("course_id", course_id)
        .eq("user_id", user_id)
        .eq("verification_status", "verified")
        .order("created_at", desc=True)
        .limit(1).execute()
    )
    return result.data[0] if result.data else None


def get_exercise_for_owner(
    *, exercise_id: str, session_id: str, course_id: str, user_id: str
) -> dict[str, Any] | None:
    result = (
        get_supabase().table("exercises").select("*")
        .eq("id", exercise_id)
        .eq("session_id", session_id)
        .eq("course_id", course_id)
        .eq("user_id", user_id)
        .limit(1).execute()
    )
    return result.data[0] if result.data else None


def create_attempt(payload: dict[str, Any]) -> dict[str, Any]:
    result = get_supabase().table("exercise_attempts").insert(payload).execute()
    if not result.data:
        raise RuntimeError("Supabase did not return the saved exercise attempt")
    return result.data[0]


def has_submitted_attempt(*, exercise_id: str, session_id: str, user_id: str) -> bool:
    result = (
        get_supabase().table("exercise_attempts").select("id")
        .eq("exercise_id", exercise_id)
        .eq("session_id", session_id)
        .eq("user_id", user_id)
        .limit(1).execute()
    )
    return bool(result.data)


def has_revealed_solution(*, exercise_id: str, session_id: str, user_id: str) -> bool:
    result = (
        get_supabase().table("exercise_attempts").select("id")
        .eq("exercise_id", exercise_id)
        .eq("session_id", session_id)
        .eq("user_id", user_id)
        .eq("solution_revealed", True)
        .limit(1).execute()
    )
    return bool(result.data)


def get_latest_attempt_for_owner(
    *, exercise_id: str, session_id: str, user_id: str
) -> dict[str, Any] | None:
    result = (
        get_supabase().table("exercise_attempts").select("*")
        .eq("exercise_id", exercise_id)
        .eq("session_id", session_id)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(1).execute()
    )
    return result.data[0] if result.data else None


def mark_latest_attempt_solution_revealed(
    *, exercise_id: str, session_id: str, user_id: str
) -> None:
    attempts = (
        get_supabase().table("exercise_attempts").select("id")
        .eq("exercise_id", exercise_id)
        .eq("session_id", session_id)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(1).execute()
    ).data or []
    if not attempts:
        raise ValueError("Submit an attempt before revealing the solution.")
    get_supabase().table("exercise_attempts").update({"solution_revealed": True}) \
        .eq("id", attempts[0]["id"]).eq("user_id", user_id).execute()


def reveal_solution_for_owner(
    *, exercise_id: str, session_id: str, course_id: str, user_id: str
) -> dict[str, Any]:
    exercise = get_exercise_for_owner(
        exercise_id=exercise_id,
        session_id=session_id,
        course_id=course_id,
        user_id=user_id,
    )
    if not exercise:
        raise ValueError("This exercise is not available in the selected inquiry.")
    if not has_submitted_attempt(exercise_id=exercise_id, session_id=session_id, user_id=user_id):
        raise ValueError("Submit an attempt before revealing the solution.")
    mark_latest_attempt_solution_revealed(
        exercise_id=exercise_id,
        session_id=session_id,
        user_id=user_id,
    )
    exercise_data = exercise.get("exercise_data") or {}
    expected_answers = exercise_data.get("code_expected_answers") or []
    if isinstance(expected_answers, str):
        expected_answers = [expected_answers]
    code_task_mode = exercise_data.get("code_task_mode") or (
        "completion" if "____" in str(exercise_data.get("starter_code") or "") else "write"
    )
    expected_answer = exercise.get("expected_answer") or ""
    if exercise.get("exercise_type") == "code" and code_task_mode == "completion":
        if not expected_answers and expected_answer:
            expected_answers = [expected_answer]
        expected_answer = "\n".join(
            f"Blank {index + 1}: {value}" for index, value in enumerate(expected_answers)
        )
    return {
        "exercise_id": exercise_id,
        "expected_answer": expected_answer,
        "common_mistakes": exercise.get("common_mistakes") or [],
    }
