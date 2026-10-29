"""Pydantic models used by the FastAPI / WebSocket layer."""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    agents: list[str] = Field(
        default_factory=lambda: [
            "diagnostiqueur",
            "tuteur_socratique",
            "evaluateur",
            "exercise_generator",
            "explicateur",
            "correcteur",
            "memoire",
        ]
    )


class ChatRequest(BaseModel):
    message: str
    course_id: str
    session_id: str


class ContextRequest(BaseModel):
    session_id: str
    course_id: str


class ExerciseAttemptRequest(BaseModel):
    exercise_id: UUID
    answer: str = Field(min_length=1, max_length=10000)
    hints_used: int = Field(default=0, ge=0, le=3)

    model_config = {"str_strip_whitespace": True}


class ExerciseActionRequest(BaseModel):
    exercise_id: UUID


class WSMessage(BaseModel):
    type: Literal[
        "token", "context", "diagnostic", "exercise", "correction", "solution", "explanation", "done", "error"
    ]
    content: Any | None = None


class ExerciseCitation(BaseModel):
    document_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    page_number: int = Field(ge=1)
    excerpt: str = Field(min_length=1, max_length=500)


class ExerciseRubricCriterion(BaseModel):
    criterion: str = Field(min_length=3, max_length=200)
    points: int = Field(ge=1, le=10)


class GeneratedExercise(BaseModel):
    exercise_type: Literal["short_answer", "multiple_choice", "numerical", "code", "sql"] = "short_answer"
    concept: str = Field(min_length=3, max_length=160)
    difficulty: Literal["beginner", "intermediate", "advanced"]
    bloom_level: Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]
    prompt: str = Field(min_length=20, max_length=2000)
    citations: list[ExerciseCitation] = Field(min_length=1, max_length=3)
    hints: list[str] = Field(min_length=2, max_length=3)
    expected_answer: str = Field(min_length=1, max_length=4000)
    rubric: list[ExerciseRubricCriterion] = Field(min_length=1, max_length=6)
    common_mistakes: list[str] = Field(max_length=5)
    choices: list[dict[str, str]] = Field(default_factory=list, max_length=6)
    correct_choice: str | None = None
    numeric_expression: str | None = Field(default=None, max_length=256)
    numeric_answer: str | None = Field(default=None, max_length=80)
    numeric_tolerance: str = Field(default="0", max_length=80)
    numeric_unit: str = Field(default="", max_length=40)
    code_language: str = Field(default="", max_length=32)
    code_task_mode: Literal["completion", "write"] = "write"
    starter_code: str = Field(default="", max_length=4000)
    code_expected_answers: list[str] = Field(default_factory=list, max_length=5)
    code_accepted_answers: list[list[str]] = Field(default_factory=list, max_length=5)
    code_explanation: str = Field(default="", max_length=1200)
    sql_setup: list[str] = Field(default_factory=list, max_length=20)
    sql_expected_columns: list[str] = Field(default_factory=list, max_length=20)
    sql_expected_rows: list[list[Any]] = Field(default_factory=list, max_length=200)

    model_config = {"str_strip_whitespace": True}


class ExerciseVerification(BaseModel):
    is_valid: bool
    issues: list[str] = Field(default_factory=list, max_length=6)


class CriterionFeedback(BaseModel):
    criterion: str = Field(min_length=3, max_length=200)
    awarded_points: int = Field(ge=0, le=10)
    possible_points: int = Field(ge=1, le=10)
    feedback: str = Field(min_length=3, max_length=1200)


class CorrectionResult(BaseModel):
    overall_feedback: str = Field(min_length=5, max_length=3000)
    error_category: Literal["correct", "partial", "conceptual", "incomplete", "off_topic"]
    criterion_feedback: list[CriterionFeedback] = Field(min_length=1, max_length=6)
    next_step: str = Field(min_length=3, max_length=1000)


class PublicCorrection(BaseModel):
    attempt_id: UUID
    total_score: int = Field(ge=0, le=10)
    max_score: int = Field(ge=1, le=10)
    overall_feedback: str
    error_category: Literal["correct", "partial", "conceptual", "incomplete", "off_topic"]
    criterion_feedback: list[CriterionFeedback]
    citations: list[ExerciseCitation]
    next_step: str
    hints_used: int = Field(ge=0, le=3)


class PublicSolution(BaseModel):
    exercise_id: UUID
    expected_answer: str
    common_mistakes: list[str]


class PublicExercise(BaseModel):
    """Only fields that may be returned before an attempt is submitted."""
    id: UUID
    exercise_type: Literal["short_answer", "multiple_choice", "numerical", "code", "sql"] = "short_answer"
    concept: str
    difficulty: Literal["beginner", "intermediate", "advanced"]
    bloom_level: Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]
    prompt: str
    citations: list[ExerciseCitation]
    hints: list[str]
    choices: list[dict[str, str]] = Field(default_factory=list)
    numeric_unit: str = ""
    code_language: str = ""
    code_task_mode: Literal["completion", "write"] = "write"
    starter_code: str = ""
    sql_setup: list[str] = Field(default_factory=list)


class ExplanationCitation(BaseModel):
    document_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    page_number: int = Field(ge=1)
    excerpt: str = Field(min_length=20, max_length=700)


class ExplanationSection(BaseModel):
    heading: str = Field(min_length=3, max_length=180)
    content: str = Field(default="", max_length=3000)
    code: str = Field(default="", max_length=12000)
    code_language: str = Field(default="", max_length=32)
    walkthrough: list[dict[str, str]] = Field(default_factory=list, max_length=80)


class GeneratedExplanation(BaseModel):
    definition: str = Field(min_length=10, max_length=3000)
    intuition: str = Field(min_length=10, max_length=3000)
    sections: list[ExplanationSection] = Field(min_length=1, max_length=30)
    course_example: str = Field(default="", max_length=3000)
    common_pitfalls: list[str] = Field(default_factory=list, max_length=8)
    citations: list[ExplanationCitation] = Field(min_length=1, max_length=8)
    check_question: str = Field(default="", max_length=1000)
