"""TypedDict state contracts that flow through the LangGraph orchestrator.

These are the *only* shapes shared between agents — every inter-agent message
travels via the master :class:`SocraState`. LangGraph guarantees that each
node reads from the state and writes back into it in a controlled fashion.
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict


# ---------------------------------------------------------------------------
# Agent outputs
# ---------------------------------------------------------------------------

class DiagnosticReport(TypedDict, total=False):
    """Produced once at the start of a session by Agent Diagnostiqueur."""

    topic: str
    initial_level: Literal["beginner", "intermediate", "advanced"]
    identified_gaps: list[str]
    prerequisite_concepts: list[str]
    first_socratic_question: str


BloomLevel = Literal[
    "remember",
    "understand",
    "apply",
    "analyze",
    "evaluate",
    "create",
]


class TutorSignal(TypedDict, total=False):
    """Produced after every Tuteur Socratique turn."""

    response_text: str
    bloom_level: BloomLevel
    should_evaluate: bool
    key_concepts_mentioned: list[str]


class SuggestedReadingItem(TypedDict, total=False):
    document_id: str
    filename: str
    page_number: int | None
    excerpt: str
    similarity: float | None


class EvaluationResult(TypedDict, total=False):
    """Produced by Agent Évaluateur — feeds the context panel + Mémoire."""

    comprehension_score: float
    misconceptions: list[str]
    concepts_understood: list[str]
    key_terms: list[str]
    suggested_readings: list[SuggestedReadingItem]
    next_micro_objective: str
    used_fallback: bool


class StudentProfile(TypedDict, total=False):
    """Long-term student model maintained by Agent Mémoire."""

    session_id: str
    user_id: str
    mastered_concepts: list[str]
    fragile_concepts: list[str]
    misconception_history: list[str]
    bloom_progression: list[BloomLevel]
    total_exchanges: int
    exercise_performance: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Master state
# ---------------------------------------------------------------------------

class ChatTurn(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class SocraState(TypedDict, total=False):
    """The single source of truth handed between LangGraph nodes."""

    # Inputs ----------------------------------------------------------------
    session_id: str
    course_id: str
    user_id: str
    messages: list[ChatTurn]
    student_message: str

    # Optional per-request LLM overrides (forwarded by the WS layer when the
    # student configured their own Gemini API key in the frontend Settings).
    api_key: str
    model: str
    provider: str
    language: str
    mode: Literal["socratic", "exercise", "explain", "correct"]
    requested_difficulty: Literal["beginner", "intermediate", "advanced"]
    exercise_record: dict[str, Any]
    student_answer: str
    hints_used: int

    # Flow control ----------------------------------------------------------
    is_first_message: bool
    current_node: str

    # Retrieval -------------------------------------------------------------
    retrieved_chunks: list[dict[str, Any]]

    # Agent outputs ---------------------------------------------------------
    diagnostic: DiagnosticReport
    tutor_signal: TutorSignal
    evaluation: EvaluationResult
    exercise: dict[str, Any]
    correction: dict[str, Any]
    explanation: dict[str, Any]
    profile: StudentProfile

    # Streaming buffer (filled token-by-token while Tuteur runs) -----------
    streamed_response: str

    # Errors ----------------------------------------------------------------
    error: str
    agent_issues: list[dict[str, str]]
