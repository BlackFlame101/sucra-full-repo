"""Authenticated API for generating and submitting mixed course exams."""
from __future__ import annotations

import json
import logging
import random
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, model_validator

from agents.exercise_generator import run_exercise_generator
from agents.llm import provider_error_code, provider_error_message
from db.exams import (
    complete_exam,
    create_exam,
    get_course_exams,
    get_exam_exercises,
    get_exam_for_owner,
    get_exam_for_session,
    save_exam_answer,
    save_exam_results,
)
from db.diagnostics import get_language_for_session
from db.supabase_client import get_supabase
from graph.orchestrator import get_compiled_graph
from rag.retriever import get_current_course_sections

router = APIRouter(prefix="/exams", tags=["exams"])
logger = logging.getLogger(__name__)

QUESTION_TYPES = ("short_answer", "multiple_choice", "numerical", "code", "sql")
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


def _fallback_question_types(
    requested_type: str,
    generated: list[dict[str, Any]],
    selected_types: tuple[str, ...] | list[str] = DEFAULT_QUESTION_TYPES,
) -> list[str]:
    """Prefer the least-used other formats if this source cannot support one type."""
    counts = {question_type: 0 for question_type in QUESTION_TYPES}
    for item in generated:
        question_type = item.get("exercise_type")
        if question_type in counts:
            counts[question_type] += 1
    alternatives = list(selected_types)
    if requested_type == "code" and "multiple_choice" not in alternatives:
        alternatives.append("multiple_choice")
    return sorted(
        (
            question_type for question_type in alternatives
            if question_type not in (requested_type, "numerical")
        ),
        key=lambda question_type: (
            question_type != "multiple_choice" if requested_type == "code" else False,
            counts[question_type],
        ),
    )


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


def _verify_course_session(course_id: str, session_id: str, user_id: str) -> None:
    client = get_supabase()
    session = (
        client.table("sessions").select("course_id")
        .eq("id", session_id).limit(1).execute()
    ).data
    course = (
        client.table("courses").select("id")
        .eq("id", course_id).eq("user_id", user_id).limit(1).execute()
    ).data
    if not session or str(session[0].get("course_id")) != course_id or not course:
        raise HTTPException(status_code=404, detail="Course inquiry not found.")


@router.get("/course/{course_id}/sessions")
async def read_course_exam_sessions(
    course_id: UUID,
    authorization: str = Header(default=""),
) -> list[dict[str, Any]]:
    user_id = _user_id_from_header(authorization)
    course = (
        get_supabase().table("courses").select("id")
        .eq("id", str(course_id)).eq("user_id", user_id).limit(1).execute()
    ).data
    if not course:
        raise HTTPException(status_code=404, detail="Course not found.")
    return get_course_exams(course_id=str(course_id), user_id=user_id)


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
    return {
        "id": str(exam["id"]),
        "status": exam["status"],
        "topic": exam.get("topic") or "",
        "requested_types": exam.get("requested_types") or list({item.get("exercise_type", "short_answer") for item in exercises}),
        "questions": [_public_question(row) for row in exercises],
        "answers": exam.get("answers") or {},
        "results": results,
        "score": exam.get("score") if exam.get("status") == "completed" else None,
        "max_score": len(exam.get("exercise_ids") or []) * 10,
    }


@router.post("/start")
async def start_exam(
    request: ExamStartRequest,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    user_id = _user_id_from_header(authorization)
    course_id, session_id = str(request.course_id), str(request.session_id)
    _verify_course_session(course_id, session_id, user_id)
    labels = {
        "short_answer": "short-answer",
        "multiple_choice": "multiple-choice",
        "numerical": "numerical calculation",
        "code": "course-language code-completion",
        "sql": "SQLite SQL query-writing",
    }
    scheduled_types = _schedule_question_types(request.question_count, request.exercise_types)
    sections = await get_current_course_sections(course_id) if not request.topic.strip() else []
    if sections:
        random.shuffle(sections)
    generated: list[dict[str, Any]] = []
    try:
        for question_index, exercise_type in enumerate(scheduled_types, start=1):
            result = None
            generation_error: ValueError | None = None
            candidate_types = [exercise_type]
            for candidate_type in candidate_types:
                for question_scope in _candidate_scopes(
                    request.topic, sections, question_index, candidate_type,
                ):
                    prompt = f"Create one {labels[candidate_type]} exam question about {question_scope}. Use only the course material."
                    prompt += f" This is question {question_index} of a mixed {request.question_count}-question exam. Do not repeat earlier questions."
                    prompt += f" Set its difficulty to {request.difficulty}; match that level in both the reasoning steps and wording."
                    if candidate_type == "numerical":
                        prompt += " Include the requested unit in the question."
                    state: dict[str, Any] = {
                        "student_message": prompt,
                        "course_id": course_id,
                        "session_id": session_id,
                        "user_id": user_id,
                        "language": request.language,
                        "requested_difficulty": request.difficulty,
                        "provider": request.provider,
                        "messages": [],
                    }
                    if request.api_key:
                        state["api_key"] = request.api_key
                    if request.model:
                        state["model"] = request.model
                    try:
                        result = await run_exercise_generator(state)  # includes grounding and independent verification
                        break
                    except ValueError as exc:
                        generation_error = exc
                        logger.warning(
                            "Exam question %d (%s) failed verification (%s); considering a fallback",
                            question_index, candidate_type, type(exc).__name__,
                        )
                if result is not None:
                    break
                if candidate_type == exercise_type:
                    fallbacks = _fallback_question_types(
                        exercise_type, generated, request.exercise_types,
                    )
                    candidate_types.extend(fallbacks)
                    logger.info(
                        "Exam question %d could not be verified as %s; trying fallback types %s",
                        question_index, exercise_type, fallbacks,
                    )
            if result is None:
                if generation_error:
                    raise generation_error
                raise ValueError(f"Could not generate exam question {question_index}")
            generated.append(result["exercise"])
        exam = create_exam(
            session_id=session_id,
            course_id=course_id,
            user_id=user_id,
            topic=request.topic.strip(),
            exercise_ids=[item["id"] for item in generated],
            requested_types=request.exercise_types,
        )
    except Exception as exc:
        logger.exception("Mixed exam generation failed for session %s", session_id)
        generated_ids = [str(item["id"]) for item in generated]
        if generated_ids:
            try:
                get_supabase().table("exercises").delete().in_("id", generated_ids) \
                    .eq("session_id", session_id).eq("course_id", course_id).eq("user_id", user_id).execute()
            except Exception:
                logger.exception("Could not remove partial exam questions for session %s", session_id)
        provider_code = provider_error_code(exc)
        if provider_code:
            raise HTTPException(
                status_code=429 if provider_code in ("API_KEY_QUOTA_EXCEEDED", "API_RATE_LIMITED") else 502,
                detail=f"{provider_code}: {provider_error_message(provider_code)}",
            ) from exc
        raise HTTPException(
            status_code=422,
            detail="Socra could not verify every requested exam question from this course material. Try a shorter exam, a narrower topic, or check that the course includes values for calculation questions.",
        ) from exc
    rows = get_exam_exercises(exam)
    return _public_exam(exam, rows)


@router.get("/{exam_id}")
async def read_exam(
    exam_id: UUID,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    user_id = _user_id_from_header(authorization)
    exam = get_exam_for_owner(exam_id=str(exam_id), user_id=user_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")
    return _public_exam(exam, get_exam_exercises(exam))


@router.get("/session/{session_id}")
async def read_exam_for_session(
    session_id: UUID,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    user_id = _user_id_from_header(authorization)
    exam = get_exam_for_session(session_id=str(session_id), user_id=user_id)
    if not exam:
        raise HTTPException(status_code=404, detail="No exam found for this inquiry.")
    return _public_exam(exam, get_exam_exercises(exam))


@router.post("/{exam_id}/answer")
async def save_answer(
    exam_id: UUID,
    request: ExamAnswerRequest,
    authorization: str = Header(default=""),
) -> dict[str, str]:
    user_id = _user_id_from_header(authorization)
    exam = get_exam_for_owner(exam_id=str(exam_id), user_id=user_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")
    try:
        save_exam_answer(exam=exam, exercise_id=str(request.exercise_id), answer=request.answer)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "saved"}


@router.post("/{exam_id}/submit")
async def submit_exam(
    exam_id: UUID,
    request: ExamSubmitRequest,
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    user_id = _user_id_from_header(authorization)
    exam = get_exam_for_owner(exam_id=str(exam_id), user_id=user_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")
    if exam.get("status") != "in_progress":
        return _public_exam(exam, get_exam_exercises(exam))
    exercises = get_exam_exercises(exam)
    answers = exam.get("answers") or {}
    _require_complete_answers(exercises, exam.get("exercise_ids") or [], answers)

    results = list(exam.get("results") or [])
    already_graded = {str(item.get("exercise_id")) for item in results}
    try:
        for exercise in exercises:
            exercise_id = str(exercise["id"])
            if exercise_id in already_graded:
                continue
            state: dict[str, Any] = {
                "mode": "correct",
                "session_id": str(exam["session_id"]),
                "course_id": str(exam["course_id"]),
                "user_id": user_id,
                "exercise_record": exercise,
                "student_answer": str(answers[exercise_id]),
                "hints_used": 0,
                "language": get_language_for_session(str(exam["session_id"])),
                "provider": request.provider,
                "messages": [],
            }
            if request.api_key:
                state["api_key"] = request.api_key
            if request.model:
                state["model"] = request.model
            corrected = await get_compiled_graph().ainvoke(state)
            correction = corrected["correction"]
            results.append({
                "exercise_id": exercise_id,
                "exercise_type": exercise.get("exercise_type") or "short_answer",
                "concept": exercise.get("concept") or "",
                "prompt": exercise.get("prompt") or "",
                "answer": answers[exercise_id],
                "score": correction["total_score"],
                "max_score": correction["max_score"],
                "feedback": correction["overall_feedback"],
                "criterion_feedback": correction["criterion_feedback"],
                "citations": correction["citations"],
                "next_step": correction["next_step"],
            })
            exam = save_exam_results(exam=exam, results=results)
        total_score = sum(int(item["score"]) for item in results)
        completed = complete_exam(exam=exam, score=total_score, results=results)
    except Exception as exc:
        logger.exception("Exam grading failed for %s", exam_id)
        provider_code = provider_error_code(exc)
        if provider_code:
            raise HTTPException(
                status_code=429 if provider_code in ("API_KEY_QUOTA_EXCEEDED", "API_RATE_LIMITED") else 502,
                detail=f"{provider_code}: {provider_error_message(provider_code)}",
            ) from exc
        raise HTTPException(status_code=503, detail="Socra could not grade the exam reliably. Your answers are saved; try submitting again.") from exc
    return _public_exam(completed, exercises)
