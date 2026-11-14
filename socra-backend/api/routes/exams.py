"""Authenticated API for generating and submitting mixed course exams."""
from __future__ import annotations

import asyncio
import json
import random
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, model_validator

from api.security import consume_study_quota
from db.exams import (
    count_exam_slots,
    get_course_exams,
    get_exam_exercises,
    get_exam_for_owner,
    get_exam_for_session,
)
from db.supabase_client import get_supabase
from db.jobs import rpc
from db.job_credentials import encrypt_job_key

class ExamRoute(APIRoute):
    def get_route_handler(self):
        handle_request = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await handle_request(request)
            except RequestValidationError:
                # Validation details can contain the request body, including personal model keys.
                raise HTTPException(status_code=422, detail="Check the exam settings and try again.") from None

        return handle


router = APIRouter(prefix="/exams", tags=["exams"], route_class=ExamRoute)

DEFAULT_QUESTION_TYPES = ("short_answer", "multiple_choice", "numerical")


def _schedule_question_types(
    question_count: int, selected_types: list[str] | tuple[str, ...] = DEFAULT_QUESTION_TYPES,
) -> list[str]:
    """Return a shuffled, evenly balanced schedule containing selected types."""
    type_cycle = list(selected_types)
    if not type_cycle or len(type_cycle) > question_count:
        raise ValueError("Choose at least one question type and no more types than questions")
    random.shuffle(type_cycle)
    return [type_cycle[index % len(type_cycle)] for index in range(question_count)]


def _has_answer_for_every_question(
    exercises: list[dict[str, Any]], answers: dict[str, Any],
) -> bool:
    for exercise in exercises:
        answer = str(answers.get(str(exercise["id"])) or "").strip()
        if not answer:
            return False
        data = exercise.get("exercise_data") or {}
        starter_code = str(data.get("starter_code") or "")
        code_task_mode = data.get("code_task_mode") or ("completion" if "____" in starter_code else "write")
        if exercise.get("exercise_type") != "code" or code_task_mode != "completion":
            continue
        blank_count = starter_code.count("____")
        if not 1 <= blank_count <= 5:
            return False
        try:
            values = json.loads(answer)
        except json.JSONDecodeError:
            values = [answer] if blank_count == 1 else None
        if not isinstance(values, list) or len(values) != blank_count or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            return False
    return True


def _scope_for_exam_question(
    requested_topic: str, sections: list[dict[str, Any]], question_index: int, exercise_type: str,
) -> str:
    if requested_topic.strip():
        return requested_topic.strip()
    if not sections:
        return "the main ideas across the course material"
    candidates = sections
    if exercise_type == "numerical":
        numeric_sections = [section for section in sections if any(
            char.isdigit() for char in f"{section.get('title', '')} {section.get('summary', '')}"
        )]
        if numeric_sections:
            candidates = numeric_sections
    section = candidates[(question_index - 1) % len(candidates)]
    title = str(section.get("title") or "Course section")
    summary = str(section.get("summary") or "")[:500]
    return f"{title}: {summary}" if summary else title


def _candidate_scopes(
    requested_topic: str, sections: list[dict[str, Any]], question_index: int, exercise_type: str,
    *, limit: int = 2,
) -> list[str]:
    if requested_topic.strip() or not sections:
        return [_scope_for_exam_question(requested_topic, sections, question_index, exercise_type)]
    scopes: list[str] = []
    for offset in range(len(sections)):
        scope = _scope_for_exam_question("", sections, question_index + offset, exercise_type)
        if scope not in scopes:
            scopes.append(scope)
        if len(scopes) >= limit:
            break
    return scopes


def _require_complete_answers(
    exercises: list[dict[str, Any]], exercise_ids: list[Any], answers: dict[str, Any],
) -> None:
    if len(exercises) != len(exercise_ids) or not _has_answer_for_every_question(exercises, answers):
        raise HTTPException(status_code=409, detail="Answer every question before submitting the exam.")


class ExamStartRequest(BaseModel):
    course_id: UUID
    session_id: UUID
    topic: str = Field(default="", max_length=300)
    question_count: int = Field(default=6, ge=3, le=12)
    difficulty: Literal["beginner", "intermediate", "advanced"] = "beginner"
    exercise_types: list[Literal["short_answer", "multiple_choice", "numerical", "code", "sql"]] = Field(
        default_factory=lambda: list(DEFAULT_QUESTION_TYPES),
        min_length=1,
        max_length=5,
    )
    api_key: str = Field(default="", max_length=2000)
    provider: Literal["google", "groq"] = "google"
    model: str = Field(default="", max_length=120)
    language: Literal["fr", "en"] = "fr"

    @model_validator(mode="after")
    def validate_selected_types(self) -> "ExamStartRequest":
        if len(set(self.exercise_types)) != len(self.exercise_types):
            raise ValueError("Question types cannot be selected more than once")
        if len(self.exercise_types) > self.question_count:
            raise ValueError("Choose at least as many questions as selected question types")
        return self


class ExamAnswerRequest(BaseModel):
    exercise_id: UUID
    answer: str = Field(min_length=1, max_length=10000)
    previous_answer: str | None = Field(default=None, max_length=10000)

    model_config = {"str_strip_whitespace": True}


class ExamSubmitRequest(BaseModel):
    api_key: str = Field(default="", max_length=2000)
    provider: Literal["google", "groq"] = "google"
    model: str = Field(default="", max_length=120)


def _user_id_from_header(authorization: str) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Sign in to use exams.")
    try:
        user = get_supabase().auth.get_user(token.strip()).user
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Your session has expired. Sign in again.") from exc
    if not user:
        raise HTTPException(status_code=401, detail="Your session has expired. Sign in again.")
    return str(user.id)


@router.get("/course/{course_id}/sessions")
async def read_course_exam_sessions(
    course_id: UUID,
    authorization: str = Header(default=""),
) -> list[dict[str, Any]]:
    user_id = await asyncio.to_thread(_user_id_from_header, authorization)
    course = await asyncio.to_thread(lambda: (
        get_supabase().table("courses").select("id")
        .eq("id", str(course_id)).eq("user_id", user_id).limit(1).execute().data
    ))
    if not course:
        raise HTTPException(status_code=404, detail="Course not found.")
    return await asyncio.to_thread(get_course_exams, course_id=str(course_id), user_id=user_id)


def _public_question(exercise: dict[str, Any]) -> dict[str, Any]:
    data = exercise.get("exercise_data") or {}
    return {
        "id": str(exercise["id"]),
        "exercise_type": exercise.get("exercise_type") or "short_answer",
        "concept": exercise.get("concept") or "",
        "difficulty": exercise.get("difficulty") or "beginner",
        "bloom_level": exercise.get("bloom_level") or "understand",
        "prompt": exercise.get("prompt") or "",
        "citations": exercise.get("citations") or [],
        "choices": data.get("choices") or [],
        "numeric_unit": data.get("numeric_unit") or "",
        "code_language": data.get("code_language") or "",
        "starter_code": data.get("starter_code") or "",
        "code_task_mode": data.get("code_task_mode") or (
            "completion" if "____" in str(data.get("starter_code") or "") else "write"
        ),
        "sql_setup": data.get("sql_setup") or [],
    }


def _public_exam(exam: dict[str, Any], exercises: list[dict[str, Any]]) -> dict[str, Any]:
    exercise_by_id = {str(item.get("id")): item for item in exercises}
    results = (exam.get("results") or []) if exam.get("status") == "completed" else []
    if results:
        completed_results = []
        for result in results:
            exercise = exercise_by_id.get(str(result.get("exercise_id")), {})
            data = exercise.get("exercise_data") or {}
            starter_code = str(data.get("starter_code") or "")
            expected_answer = str(exercise.get("expected_answer") or "")
            code_task_mode = data.get("code_task_mode") or (
                "completion" if "____" in starter_code else "write"
            )
            code_expected_answers = data.get("code_expected_answers") or []
            if isinstance(code_expected_answers, str):
                code_expected_answers = [code_expected_answers]
            if code_task_mode == "completion" and not code_expected_answers and expected_answer:
                code_expected_answers = [expected_answer]
            completed_results.append({
                **result,
                "difficulty": exercise.get("difficulty", "beginner"),
                "expected_answer": "; ".join(str(value) for value in code_expected_answers)
                if code_task_mode == "completion" else expected_answer,
                "code_task_mode": code_task_mode,
                "code_language": data.get("code_language") or "",
                "code_expected_answers": code_expected_answers if code_task_mode == "completion" else [],
                "completed_code": "".join(
                    part + (str(code_expected_answers[index]) if index < len(code_expected_answers) else "____")
                    for index, part in enumerate(starter_code.split("____"))
                ) if code_task_mode == "completion" and starter_code.count("____") == len(code_expected_answers) else "",
            })
        results = completed_results
    total = exam.get("question_count") or len(exam.get("exercise_ids") or [])
    status = exam["status"]
    return {
        "id": str(exam["id"]),
        "status": exam["status"],
        "topic": exam.get("topic") or "",
        "requested_types": exam.get("requested_types") or list({item.get("exercise_type", "short_answer") for item in exercises}),
        "questions": [_public_question(row) for row in exercises] if status in ("in_progress", "completed") else [],
        "answers": exam.get("answers") or {},
        "results": results,
        "score": exam.get("score") if exam.get("status") == "completed" else None,
        "max_score": total * 10,
        "question_count": total,
        "error": exam.get("preparation_error"),
        "progress": {
            "completed": len(exam.get("results") or []) if status in ("grading","grading_failed")
                         else exam.get("validated_count", len(exercises)),
            "total": total,
        },
    }


async def _exam_response(exam: dict[str, Any]) -> dict[str, Any]:
    if exam["status"] in ("preparing", "preparation_failed"):
        count = await asyncio.to_thread(count_exam_slots, str(exam["id"]))
        return _public_exam({**exam, "validated_count": count}, [])
    exercises = await asyncio.to_thread(get_exam_exercises, exam) if exam["status"] in ("in_progress", "completed") else []
    return _public_exam(exam, exercises)


async def _require_exam_quota(user_id: str, operation: str) -> None:
    quota = await consume_study_quota(user_id, operation)
    if quota is None:
        raise HTTPException(status_code=503, detail="Exam jobs are temporarily unavailable. Retry shortly.")
    if not quota:
        raise HTTPException(status_code=429, detail="Exam processing limit reached. Try again later.")


def _job_key(api_key: str, session_id: str) -> str | None:
    try:
        return encrypt_job_key(api_key, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/start")
async def start_exam(
    request: ExamStartRequest, response: Response, authorization: str = Header(default=""),
) -> dict[str, Any]:
    user_id = await asyncio.to_thread(_user_id_from_header, authorization)
    course_id, session_id = str(request.course_id), str(request.session_id)
    plan = request.model_dump(exclude={"api_key", "course_id", "session_id"})
    plan["topic"] = request.topic.strip()
    existing = await asyncio.to_thread(get_exam_for_session, session_id=session_id, user_id=user_id)
    if existing and existing["course_id"] == course_id and existing["status"] != "preparation_failed":
        if existing["status"] == "preparing":
            response.status_code = 202
        return await _exam_response(existing)
    await _require_exam_quota(user_id, "exam_generation")
    exam_id = await rpc("queue_exam", {
        "inquiry": session_id, "course": course_id, "owner": user_id,
        "plan": plan, "credential": _job_key(request.api_key, session_id),
    })
    if not exam_id:
        raise HTTPException(status_code=404, detail="Course inquiry not found.")
    exam = await asyncio.to_thread(get_exam_for_owner, exam_id=exam_id, user_id=user_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")
    if exam["status"] == "preparing":
        response.status_code = 202
    return await _exam_response(exam)


@router.get("/{exam_id}")
async def read_exam(exam_id: UUID, authorization: str = Header(default="")) -> dict[str, Any]:
    user_id = await asyncio.to_thread(_user_id_from_header, authorization)
    exam = await asyncio.to_thread(get_exam_for_owner, exam_id=str(exam_id), user_id=user_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")
    return await _exam_response(exam)


@router.get("/session/{session_id}")
async def read_exam_for_session(session_id: UUID, authorization: str = Header(default="")) -> dict[str, Any]:
    user_id = await asyncio.to_thread(_user_id_from_header, authorization)
    exam = await asyncio.to_thread(get_exam_for_session, session_id=str(session_id), user_id=user_id)
    if not exam:
        raise HTTPException(status_code=404, detail="No exam found for this inquiry.")
    return await _exam_response(exam)


@router.post("/{exam_id}/answer")
async def save_answer(exam_id: UUID, request: ExamAnswerRequest, authorization: str = Header(default="")) -> dict[str, str]:
    user_id = await asyncio.to_thread(_user_id_from_header, authorization)
    status = await rpc("write_exam_answer", {
        "exam": str(exam_id), "owner": user_id, "question": str(request.exercise_id),
        "answer": request.answer, "previous": request.previous_answer,
    })
    if status == "missing":
        raise HTTPException(status_code=404, detail="Exam not found.")
    if status == "conflict":
        raise HTTPException(status_code=409, detail="This answer changed in another tab. Reload before saving.")
    if status != "saved":
        raise HTTPException(status_code=409, detail="This exam is no longer accepting that answer.")
    return {"status": "saved"}


@router.post("/{exam_id}/submit")
async def submit_exam(
    exam_id: UUID, request: ExamSubmitRequest, response: Response, authorization: str = Header(default=""),
) -> dict[str, Any]:
    user_id = await asyncio.to_thread(_user_id_from_header, authorization)
    exam = await asyncio.to_thread(get_exam_for_owner, exam_id=str(exam_id), user_id=user_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")
    if exam["status"] in ("grading", "completed"):
        if exam["status"] == "grading":
            response.status_code = 202
        return await _exam_response(exam)
    if exam["status"] not in ("in_progress", "grading_failed"):
        raise HTTPException(status_code=409, detail="Wait for all exam questions before submitting.")
    answers = exam.get("answers") or {}
    exercises = await asyncio.to_thread(get_exam_exercises, exam)
    _require_complete_answers(exercises, exam.get("exercise_ids") or [], answers)
    await _require_exam_quota(user_id, "exam_grading")
    status = await rpc("queue_exam_grading", {
        "exam": str(exam_id), "owner": user_id, "expected_answers": answers,
        "model_options": request.model_dump(exclude={"api_key"}),
        "credential": _job_key(request.api_key, str(exam["session_id"])),
    })
    if status not in ("grading", "completed"):
        raise HTTPException(status_code=409, detail="Your exam changed while submitting. Reload and retry.")
    updated = await asyncio.to_thread(get_exam_for_owner, exam_id=str(exam_id), user_id=user_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Exam not found.")
    if updated["status"] == "grading":
        response.status_code = 202
    return await _exam_response(updated)
