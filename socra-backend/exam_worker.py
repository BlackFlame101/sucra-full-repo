"""Run resumable exam jobs using the existing verified exercise and grading agents."""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from time import monotonic

from agents.correcteur import grade_exercise
from agents.exercise_generator import _is_duplicate_question, generate_verified_exercise
from agents.llm import provider_error_code, provider_error_message
from agents.memoire import _apply_exercise_correction, _ensure_profile_shape
from api.routes.exams import _candidate_scopes, _schedule_question_types
from db.diagnostics import get_language_for_session
from db.exams import get_exam_exercises, get_exam_job_exam, get_exam_slots
from db.jobs import job_rpc, rpc
from db.profiles import get_profile
from rag.retriever import get_current_course_sections, request_id, retrieval_scope

logger = logging.getLogger(__name__)
QUESTION_LABELS = {
    "short_answer": "short-answer", "multiple_choice": "multiple-choice",
    "numerical": "numerical calculation", "code": "course-language code-completion",
    "sql": "SQLite SQL query-writing",
}


class JobLost(Exception):
    pass


def generation_concurrency() -> int:
    try:
        return min(3, max(1, int(os.environ.get("SOCRA_EXAM_CONCURRENCY", "2"))))
    except ValueError:
        return 2


async def require_job(job: dict, function: str, **kwargs) -> None:
    if not await job_rpc(job, function, **kwargs):
        raise JobLost


async def generate_slot(job: dict, exam: dict, slot: int, slot_plan: dict, key: str | None,
                        saved: dict[int, dict], write_lock: asyncio.Lock, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        options = job["options"]
        kind = slot_plan["type"]
        scopes = slot_plan["scopes"]
        for attempt in range(2):
            scope = scopes[attempt % len(scopes)]
            prompt = (
                f"Create one {QUESTION_LABELS[kind]} exam question about {scope}. Use only the course material. "
                f"This is question {slot + 1} of {exam['question_count']}. "
                f"Use {options['difficulty']} difficulty. Use a distinct fact or angle from other questions."
            )
            if kind == "numerical":
                prompt += " Include any necessary unit in the question."
            state = {
                "student_message": prompt, "course_search_query": scope, "requested_exercise_type": kind,
                "session_id": exam["session_id"], "course_id": exam["course_id"], "user_id": exam["user_id"],
                "requested_difficulty": options["difficulty"], "language": options["language"],
                "for_exam": True, "model_request_id": job["id"], "provider": options["provider"],
                "model": options.get("model"), "api_key": key,
            }
            try:
                question = await generate_verified_exercise(state)
            except ValueError as exc:
                if provider_error_code(exc):
                    raise
                continue
            async with write_lock:
                if _is_duplicate_question(question["prompt"], [row["prompt"] for row in saved.values()]):
                    continue
                status = await job_rpc(job, "save_exam_slot", slot=slot, question=question)
                if status == "stale":
                    raise JobLost
                if status == "saved":
                    saved[slot] = question
                    logger.info("exam_generation_progress job_id=%s validated=%d requested=%d",
                                job["id"], len(saved), exam["question_count"])
                    return
                if status != "duplicate":
                    raise ValueError("Exam question did not match its planned slot.")
        raise ValueError("Could not verify a distinct question for a planned slot.")


async def prepare_exam(job: dict, exam: dict, key: str | None) -> None:
    options = job["options"]
    plan = options.get("slots")
    if not plan:
        sections = await get_current_course_sections(exam["course_id"]) if not exam["topic"] else []
        plan = [
            {"type": kind, "scopes": _candidate_scopes(exam["topic"], sections, slot + 1, kind)}
            for slot, kind in enumerate(_schedule_question_types(exam["question_count"], options["exercise_types"]))
        ]
        await require_job(job, "save_exam_plan", slot_plan=plan)
    saved = {row["exam_slot"]: row for row in await asyncio.to_thread(get_exam_slots, job["id"])}
    lock, slots = asyncio.Lock(), asyncio.Semaphore(generation_concurrency())
    results = await asyncio.gather(*(
        generate_slot(job, exam, i, item, key, saved, lock, slots)
        for i, item in enumerate(plan) if i not in saved
    ), return_exceptions=True)
    failures = [outcome for outcome in results if isinstance(outcome, BaseException)]
    if failures:
        raise next((failure for failure in failures if isinstance(failure, JobLost) or provider_error_code(failure)), failures[0])
    await require_job(job, "publish_exam")


async def grade_exam(job: dict, exam: dict, key: str | None) -> None:
    questions = await asyncio.to_thread(get_exam_exercises, exam)
    if len(questions) != len(exam["exercise_ids"]):
        raise ValueError("An exam question is missing.")
    language = exam.get("exam_language") or await asyncio.to_thread(get_language_for_session, exam["session_id"])
    existing = {str(result["exercise_id"]): result for result in (exam.get("results") or [])}
    profile = _ensure_profile_shape(await asyncio.to_thread(get_profile, exam["session_id"]),
                                    exam["session_id"], exam["user_id"])
    for question in questions:
        question_id = str(question["id"])
        if question_id not in existing:
            state = {
                "session_id": exam["session_id"], "course_id": exam["course_id"], "user_id": exam["user_id"],
                "student_answer": exam["answers"][question_id], "exercise_record": question, "language": language,
                "provider": job["options"]["provider"], "model": job["options"].get("model"),
                "api_key": key, "model_request_id": job["id"],
            }
            attempt = await grade_exercise(state)
            grade = {
                "exercise_id": question_id, "exercise_type": question["exercise_type"],
                "concept": question["concept"], "prompt": question["prompt"], "answer": attempt["answer"],
                "score": attempt["total_score"], "max_score": attempt["max_score"],
                "feedback": attempt["feedback"], "error_category": attempt["error_category"],
                "criterion_feedback": attempt["criterion_feedback"], "citations": attempt["citations"],
                "next_step": attempt["next_step"],
            }
            await require_job(job, "save_exam_grade", grade=grade)
            existing[question_id] = grade
        result = existing[question_id]
        # Legacy partial grades already updated their profile when they were saved.
        if result.get("error_category"):
            profile = _apply_exercise_correction(profile, {**result, "total_score": result["score"]}, question)
    await require_job(job, "publish_exam_grades", student_profile=profile)


async def process_exam_job(job: dict, decrypt_key: Callable[[str | None, str], str | None]) -> None:
    started = monotonic()
    token = request_id.set(job["id"])
    try:
        if job["attempts"] > 3:
            await job_rpc(job, "fail_exam_job", message="This job was interrupted repeatedly. Retry to continue.", permanent=True)
            return
        async with asyncio.timeout(240), retrieval_scope():
            exam = await asyncio.to_thread(get_exam_job_exam, job["exam_id"])
            if not exam:
                return
            try:
                key = decrypt_key(job["encrypted_key"], exam["session_id"])
            except ValueError as exc:
                await job_rpc(job, "fail_exam_job", message=str(exc), permanent=True)
                return
            operation = prepare_exam if job["kind"] == "generation" else grade_exam
            await operation(job, exam, key)
    except JobLost:
        pass
    except Exception as exc:
        code = provider_error_code(exc)
        message = provider_error_message(code) if code else (
            "Could not verify all requested questions. Retry to continue from the saved questions."
            if job["kind"] == "generation" else "Grading was interrupted. Retry to continue from saved results."
        )
        await job_rpc(job, "fail_exam_job", message=message,
                      permanent=code in {"API_KEY_INVALID", "API_KEY_ACCESS_DENIED"} or isinstance(exc, ValueError) and not code)
        logger.warning("exam_job_failed job_id=%s error_type=%s", job["id"], type(exc).__name__)
    finally:
        request_id.reset(token)
        logger.info("exam_job job_id=%s kind=%s attempt=%d duration_ms=%d",
                    job["id"], job["kind"], job["attempts"], (monotonic() - started) * 1000)


async def consume_exam_jobs(kind: str, decrypt_key: Callable[[str | None, str], str | None]) -> None:
    while True:
        try:
            rows = await rpc("claim_exam_job", {"job_kind": kind})
            if rows:
                await process_exam_job(rows[0], decrypt_key)
            else:
                await asyncio.sleep(2)
        except Exception as exc:
            logger.warning("exam_worker_poll_failed kind=%s error_type=%s", kind, type(exc).__name__)
            await asyncio.sleep(10)
