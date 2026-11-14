"""Compare the actual Socra agents on synthetic course material without database writes."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from contextlib import ExitStack
from decimal import Decimal
from math import ceil
from statistics import median
from time import perf_counter
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from agents.correcteur import grade_exercise
from agents.diagnostiqueur import run_diagnostiqueur
from agents.evaluateur import run_evaluateur
from agents.exercise_generator import generate_verified_exercise
from agents.explicateur import run_explicateur
from agents.tuteur_socratique import run_tuteur
from config import resolve_google_model
from graph.state import SocraState


SOURCE_ID = "00000000-0000-0000-0000-000000000021"
COURSE_EXCERPTS = [
    {"page_number": 4, "content": (
        "A star schema has one central fact table and surrounding dimension tables. "
        "The fact table stores measurable events such as sales, their amount and quantity, "
        "and foreign keys to dimensions. Dimension tables describe the event by product, date, and store."
    )},
    {"page_number": 7, "content": (
        "The average order value equals total sales divided by the number of orders. "
        "In the sample shop, four orders total 120 dollars, so average order value is 30 dollars. "
        "Revenue is the sum of order totals, not the number of orders."
    )},
    {"page_number": 12, "content": (
        "An INNER JOIN returns matching rows only. A LEFT JOIN retains every row from the left table "
        "and fills missing right-side columns with NULL. The example uses customers as the left table and orders on the right."
    )},
]
CHUNKS = [
    {"id": str(i), "document_id": SOURCE_ID, "filename": "fixture.pdf", "chunk_index": i,
     "similarity": 1.0, **row}
    for i, row in enumerate(COURSE_EXCERPTS)
]


def _grounded(card: dict, expected_page: int) -> bool:
    return any(c["page_number"] == expected_page and c["document_id"] == SOURCE_ID for c in card["citations"])


async def _socratic(state: SocraState) -> bool:
    state = {**state, "student_message": "I think a fact table stores the sales measurements. How do dimensions fit in?"}
    diagnostic = await run_diagnostiqueur(state)
    tutor = await run_tuteur(diagnostic)
    evaluated = await run_evaluateur(tutor)
    return (not evaluated.get("agent_issues") and "?" in tutor["tutor_signal"]["response_text"]
            and bool(evaluated["evaluation"]["key_terms"]))


async def _explain(state: SocraState) -> bool:
    async def discard(_):
        pass

    answer = await run_explicateur({**state, "student_message": "Explain why a LEFT JOIN keeps customers without orders.",
                                  "preview": discard})
    return _grounded(answer["explanation"], 12) and bool(answer["explanation"]["sections"])


async def _practice(state: SocraState) -> bool:
    exercise = await generate_verified_exercise({**state, "student_message": "Give me a QCM asking which table stores sales measures in a star schema.",
                                                 "requested_exercise_type": "multiple_choice"})
    data = exercise["exercise_data"]
    correct_text = next(choice["text"].casefold() for choice in data["choices"] if choice["id"] == data["correct_choice"])
    return _grounded(exercise, 4) and len(data["choices"]) == 4 and "fact" in correct_text


async def _exam(state: SocraState) -> bool:
    exercise = await generate_verified_exercise({
        **state, "student_message": "Ask the student to compute average order value from four orders totaling 120 dollars.",
        "course_search_query": "Average order value in the sample shop", "requested_exercise_type": "numerical",
        "requested_difficulty": "beginner", "for_exam": True,
    })
    data = exercise["exercise_data"]
    answer = f"30 {data['numeric_unit']}".strip()
    grade = await grade_exercise({**state, "student_answer": answer, "exercise_record": {"id": str(uuid4()), **exercise}})
    return _grounded(exercise, 7) and Decimal(data["numeric_answer"]) == 30 and grade["total_score"] == grade["max_score"] == 10


SCENARIOS = {"socratic": _socratic, "explain": _explain, "practice": _practice, "exam": _exam}


async def run(models: list[str], modes: list[str], samples: int) -> int:
    retrieval = AsyncMock(side_effect=lambda *args, **kwargs: list(CHUNKS))
    failures = 0
    with ExitStack() as stack:
        for module in ("diagnostiqueur", "tuteur_socratique", "evaluateur"):
            stack.enter_context(patch(f"agents.{module}.retrieve_chunks", retrieval))
        for module in ("explicateur", "exercise_generator"):
            stack.enter_context(patch(f"agents.{module}.retrieve_summary_guided_chunks", retrieval))
        stack.enter_context(patch("agents.diagnostiqueur.diag_db.save_diagnostic"))
        stack.enter_context(patch("agents.evaluateur._persist_key_terms"))
        stack.enter_context(patch("agents.exercise_generator.get_recent_exercise_prompts", return_value=[]))
        for spec in models:
            provider, model = spec.split(":", 1)
            key = os.environ["GEMINI_API_KEY" if provider == "google" else "GROQ_API_KEY"]
            for mode in modes:
                timings, passed = [], 0
                for _ in range(samples):
                    request = str(uuid4())
                    state: SocraState = {"provider": provider, "model": model, "api_key": key, "language": "en",
                                         "request_id": request, "session_id": "fixture", "course_id": "fixture", "user_id": "fixture"}
                    start = perf_counter()
                    try:
                        passed += bool(await SCENARIOS[mode](state))
                    except Exception as exc:
                        print(f"{spec} {mode} request_id={request} error_type={type(exc).__name__}")
                    timings.append((perf_counter() - start) * 1000)
                p95 = sorted(timings)[ceil(0.95 * samples) - 1]
                failures += samples - passed
                print(f"{spec} {mode} quality={passed}/{samples} p50_ms={median(timings):.1f} p95_ms={p95:.1f}")
    return int(failures > 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", required=True, metavar="PROVIDER:MODEL")
    parser.add_argument("--mode", action="append", choices=SCENARIOS)
    parser.add_argument("--samples", type=int, choices=range(1, 21), default=1)
    parser.add_argument("--live", action="store_true", help="Run with provider APIs using the configured API keys and their quotas.")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to send the synthetic excerpts to the selected providers.")
    for spec in args.model:
        provider, _, model = spec.partition(":")
        if provider not in {"google", "groq"} or not model:
            parser.error("Expected google:MODEL or groq:MODEL.")
        if provider == "google" and resolve_google_model(model) != model:
            parser.error("Use an exact, permitted Gemini model ID.")
        key_name = "GEMINI_API_KEY" if provider == "google" else "GROQ_API_KEY"
        if not os.environ.get(key_name):
            parser.error(f"Set {key_name} for the selected provider.")
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("agents.metrics").setLevel(logging.INFO)
    return asyncio.run(run(args.model, args.mode or list(SCENARIOS), args.samples))


if __name__ == "__main__":
    raise SystemExit(main())
