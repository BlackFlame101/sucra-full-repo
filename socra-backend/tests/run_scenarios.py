"""Phase 11 — academic scenario test runner.

Exercises the full LangGraph pipeline (Diagnostiqueur → Tuteur → Évaluateur →
Mémoire) end-to-end against the JSON scenarios under :mod:`tests.scenarios`,
then runs the six-point verification checklist from ``scope2.md §11.2``.

Usage::

    cd socra-backend
    uv run python -m tests.run_scenarios

Output:
    - tests/REPORT.md             — pretty markdown report
    - stdout summary              — pass/fail per scenario
    - Real Supabase rows under sessions / messages / diagnostics /
      student_profiles, prefixed ``[TEST-Phase11]`` for easy cleanup
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow `python -m tests.run_scenarios` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import messages as messages_db  # noqa: E402
from db import profiles as profiles_db  # noqa: E402
from db.supabase_client import get_supabase  # noqa: E402
from graph.orchestrator import get_compiled_graph  # noqa: E402
from graph.state import ChatTurn, SocraState  # noqa: E402

from tests.verifier import (  # noqa: E402
    CheckResult,
    ScenarioReport,
    check_asks_question_per_turn,
    check_conversation_resumable,
    check_diagnostic_topic,
    check_agents_no_fallback,
    check_response_language,
    check_key_terms_extracted,
    check_no_direct_answers,
    check_profile_updated,
    check_suggested_readings_real_pages,
)


logger = logging.getLogger("tests.run_scenarios")
SCENARIOS_DIR = Path(__file__).parent / "scenarios"
REPORT_PATH = Path(__file__).parent / "REPORT.md"
TEST_PREFIX = "[TEST-Phase11]"


# ---------------------------------------------------------------------------
# Supabase helpers — the runner is a self-contained client (no WS layer).
# ---------------------------------------------------------------------------

def resolve_first_course() -> tuple[str, str]:
    """Pick any existing course/user pair so we don't hit FK violations.

    Returns ``(course_id, user_id)``. Fails fast if no course exists yet —
    the user is expected to have created at least one in the UI.
    """
    res = (
        get_supabase()
        .table("courses")
        .select("id, user_id, name")
        .order("created_at", desc=False)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise RuntimeError(
            "No course found in Supabase — create one in the UI first "
            "(http://localhost:3000) before running scenarios."
        )
    return rows[0]["id"], rows[0]["user_id"]


def create_test_session(course_id: str, scenario_title: str) -> str:
    """Create a fresh session row and return its UUID.

    Sessions are tagged with a clear prefix so they can be filtered out of
    the regular UI sidebar (or bulk-deleted later).
    """
    title = f"{TEST_PREFIX} {scenario_title} — {datetime.now(timezone.utc):%Y-%m-%d %H:%M}"
    res = (
        get_supabase()
        .table("sessions")
        .insert({"course_id": course_id, "title": title})
        .execute()
    )
    row = (res.data or [{}])[0]
    if not row.get("id"):
        raise RuntimeError(f"Failed to create test session: {res}")
    return row["id"]


# ---------------------------------------------------------------------------
# Scenario loading
# ---------------------------------------------------------------------------

def load_scenarios(filter_id: str | None = None) -> list[dict[str, Any]]:
    files = sorted(SCENARIOS_DIR.glob("scenario_*.json"))
    out: list[dict[str, Any]] = []
    for path in files:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if filter_id and data.get("id") != filter_id:
            continue
        data.setdefault("forbidden_phrases", [])
        data.setdefault("expected_topic_keywords", [])
        out.append(data)
    if not out:
        raise RuntimeError(f"No scenarios found in {SCENARIOS_DIR}")
    return out


# ---------------------------------------------------------------------------
# Per-scenario execution
# ---------------------------------------------------------------------------

async def run_one_turn(
    graph,
    *,
    session_id: str,
    course_id: str,
    user_id: str,
    student_message: str,
    history: list[ChatTurn],
    profile: dict[str, Any],
    is_first_message: bool,
    api_key: str = "",
    model: str = "",
    provider: str = "google",
    language: str = "en",
) -> dict[str, Any]:
    """Invoke the graph for a single student turn and return the final state."""
    state: SocraState = {
        "session_id": session_id,
        "course_id": course_id,
        "user_id": user_id,
        "messages": history,
        "student_message": student_message,
        "language": language,
        "is_first_message": is_first_message,
        "profile": {
            "session_id": session_id,
            "user_id": user_id,
            "mastered_concepts": profile.get("mastered_concepts") or [],
            "fragile_concepts": profile.get("fragile_concepts") or [],
            "misconception_history": profile.get("misconception_history") or [],
            "bloom_progression": profile.get("bloom_progression") or [],
            "total_exchanges": int(profile.get("total_exchanges") or 0),
        },
    }
    if api_key:
        state["api_key"] = api_key
    if model:
        state["model"] = model
    if provider:
        state["provider"] = provider
    final = await graph.ainvoke(state)
    return final


async def run_scenario(
    scenario: dict[str, Any],
    *,
    api_key: str = "",
    model: str = "",
    provider: str = "google",
    inter_turn_delay: float = 0.0,
) -> ScenarioReport:
    """Drive one scenario from start to finish, then run the checklist."""
    print(f"\n{'─' * 72}")
    print(f"▶  Scenario [{scenario['id']}] — {scenario['title']}")
    print(f"{'─' * 72}")
    print(f"   persona  : {scenario['persona_summary']}")
    print(f"   language : {scenario.get('language', 'en')}")
    print(f"   turns    : {len(scenario['turns'])}")

    course_id, user_id = resolve_first_course()
    session_id = create_test_session(course_id, scenario["title"])
    print(f"   session  : {session_id}")

    graph = get_compiled_graph()

    history: list[ChatTurn] = []
    profile: dict[str, Any] = {}

    # Capture artefacts produced across all turns.
    initial_profile = profiles_db.get_profile(session_id) or {}
    diagnostic_seen: dict[str, Any] | None = None
    tutor_responses: list[str] = []
    evaluations: list[dict[str, Any]] = []
    agent_issues: list[dict[str, str]] = []

    for turn_idx, student_msg in enumerate(scenario["turns"]):
        is_first = turn_idx == 0
        print(f"\n   ── Turn {turn_idx + 1}/{len(scenario['turns'])} ──")
        print(f"   student> {student_msg!r}")

        # Persist the student turn first (mirrors the WS handler).
        try:
            messages_db.save_message(session_id, "user", student_msg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("save user message failed: %s", exc)

        history = [*history, {"role": "user", "content": student_msg}]

        try:
            t0 = time.perf_counter()
            final = await run_one_turn(
                graph,
                session_id=session_id,
                course_id=course_id,
                user_id=user_id,
                student_message=student_msg,
                history=history,
                profile=profile,
                is_first_message=is_first,
                api_key=api_key,
                model=model,
                provider=provider,
                language=scenario.get("language", "en"),
            )
            dt = time.perf_counter() - t0
        except Exception as exc:  # noqa: BLE001
            logger.exception("Graph failed mid-scenario: %s", exc)
            tutor_responses.append("")
            continue

        if is_first:
            diagnostic_seen = final.get("diagnostic") or {}
            print(f"   diagnostic.topic  = {diagnostic_seen.get('topic')!r}")
            print(f"   diagnostic.level  = {diagnostic_seen.get('initial_level')!r}")
        agent_issues.extend(final.get("agent_issues") or [])

        signal = final.get("tutor_signal") or {}
        evaluation = final.get("evaluation")
        new_profile = final.get("profile") or {}

        tutor_text = (
            (final.get("streamed_response") or "").strip()
            or signal.get("response_text", "").strip()
        )
        tutor_responses.append(tutor_text)

        # Echo a short preview of the tutor's reply.
        preview = tutor_text.replace("\n", " ⏎ ")
        if len(preview) > 200:
            preview = preview[:197] + "…"
        print(f"   tutor>   {preview}")
        print(f"   bloom={signal.get('bloom_level')!r} eval={signal.get('should_evaluate')} dt={dt:.2f}s")

        if evaluation:
            evaluations.append(evaluation)
            n_terms = len(evaluation.get("key_terms") or [])
            n_reads = len(evaluation.get("suggested_readings") or [])
            print(f"   eval>    score={evaluation.get('comprehension_score')} terms={n_terms} reads={n_reads}")

        # Persist the assistant turn so the resumability check can see it.
        try:
            if tutor_text:
                messages_db.save_message(session_id, "assistant", tutor_text)
                history = [*history, {"role": "assistant", "content": tutor_text}]
            messages_db.touch_session(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("save assistant message failed: %s", exc)

        if new_profile:
            profile = dict(new_profile)

        # Optional small pause between turns to stay under per-minute rate
        # limits when the user is on a constrained Gemini free tier.
        if inter_turn_delay > 0 and turn_idx < len(scenario["turns"]) - 1:
            await asyncio.sleep(inter_turn_delay)

    # Final profile from DB (Mémoire writes there on its own).
    final_profile = profiles_db.get_profile(session_id) or profile
    persisted_terms: list[str] = []
    try:
        term_res = (
            get_supabase().table("key_terms").select("term")
            .eq("session_id", session_id).execute()
        )
        persisted_terms = [
            str(row.get("term") or "").strip()
            for row in (term_res.data or [])
            if str(row.get("term") or "").strip()
        ]
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to verify persisted key terms: %s", exc)

    # ------------------------------------------------------------------
    # Checklist
    # ------------------------------------------------------------------
    checks: list[CheckResult] = [
        check_no_direct_answers(tutor_responses, scenario.get("forbidden_phrases")),
        check_asks_question_per_turn(tutor_responses),
        check_profile_updated(initial_profile, final_profile),
        check_key_terms_extracted(
            [{"key_terms": persisted_terms}] if persisted_terms else []
        ),
        check_suggested_readings_real_pages(evaluations),
        check_conversation_resumable(session_id, len(scenario["turns"])),
        check_diagnostic_topic(diagnostic_seen, scenario.get("expected_topic_keywords") or []),
        check_agents_no_fallback(agent_issues),
        check_response_language(tutor_responses, scenario.get("language", "en")),
    ]
    checks[3].detail = "Persisted to key_terms: " + checks[3].detail

    # Pretty per-scenario summary
    print()
    for c in checks:
        glyph = {"PASS": "✓", "FAIL": "✗", "SKIP": "○"}.get(c.status, "?")
        print(f"   {glyph} [{c.status}] {c.name} — {c.detail}")

    return ScenarioReport(
        scenario_id=scenario["id"],
        title=scenario["title"],
        session_id=session_id,
        turns_count=len(scenario["turns"]),
        checks=checks,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def render_report(reports: list[ScenarioReport]) -> str:
    """Render the markdown report consumed by the academic deliverable."""
    lines: list[str] = []
    lines.append("# Phase 11 — Scenario Test Report")
    lines.append("")
    lines.append(f"_Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S UTC}_")
    lines.append("")
    lines.append("This report exercises the full multi-agent LangGraph pipeline")
    lines.append("(Diagnostiqueur → Tuteur Socratique → Évaluateur → Mémoire) against")
    lines.append("academic scenarios and validates the required checklist defined")
    lines.append("in `scope2.md §11.2`, plus fallback and response-language checks.")
    lines.append("")

    # Top-level summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Scenario | Turns | Pass | Fail | Skip | Verdict |")
    lines.append("|---|---:|---:|---:|---:|:---:|")
    overall_pass = 0
    overall_fail = 0
    overall_skip = 0
    for r in reports:
        n_pass = sum(1 for c in r.checks if c.status == "PASS")
        n_fail = sum(1 for c in r.checks if c.status == "FAIL")
        n_skip = sum(1 for c in r.checks if c.status == "SKIP")
        overall_pass += n_pass
        overall_fail += n_fail
        overall_skip += n_skip
        verdict = "✅ PASS" if n_fail == 0 else "❌ FAIL"
        lines.append(
            f"| **{r.title}** | {r.turns_count} | {n_pass} | {n_fail} | {n_skip} | {verdict} |"
        )
    lines.append(
        f"| **Total** | — | **{overall_pass}** | **{overall_fail}** | **{overall_skip}** | "
        f"{'✅ ALL PASSED' if overall_fail == 0 else '❌ SOME FAILED'} |"
    )
    lines.append("")

    # Per-scenario detail
    for r in reports:
        lines.append(f"## Scenario — {r.title}")
        lines.append("")
        lines.append(f"- **id**: `{r.scenario_id}`")
        lines.append(f"- **session_id**: `{r.session_id}`")
        lines.append(f"- **turns**: {r.turns_count}")
        lines.append("")
        lines.append("| # | Check | Status | Detail |")
        lines.append("|---:|---|:---:|---|")
        for i, c in enumerate(r.checks, start=1):
            glyph = {"PASS": "✅", "FAIL": "❌", "SKIP": "⚪"}.get(c.status, "?")
            detail = c.detail.replace("|", "\\|")
            lines.append(f"| {i} | {c.name} | {glyph} {c.status} | {detail} |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Scope alignment (`scope2.md §11.2`)")
    lines.append("")
    lines.append("| Required check | Implemented |")
    lines.append("|---|:---:|")
    lines.append("| Tutor never says 'correct, the answer is X' | ✅ `check_no_direct_answers` |")
    lines.append("| Tutor always asks at least one question per response | ✅ `check_asks_question_per_turn` |")
    lines.append("| Student profile updated correctly after session | ✅ `check_profile_updated` |")
    lines.append("| Key terms panel shows relevant terms | ✅ `check_key_terms_extracted` |")
    lines.append("| Suggested reading cites real pages from uploaded PDF | ✅ `check_suggested_readings_real_pages` |")
    lines.append("| Conversation saved and resumable | ✅ `check_conversation_resumable` |")
    lines.append("")
    lines.append(
        "> Sessions created by this runner are prefixed with "
        f"`{TEST_PREFIX}` and remain in Supabase so they can be inspected "
        "in the UI sidebar. Re-running the script creates fresh sessions."
    )
    lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 11 scenario tests.")
    parser.add_argument(
        "--scenario",
        help="Run only the scenario with this id (e.g. 'entropy').",
        default=None,
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip writing tests/REPORT.md (still prints to stdout).",
    )
    parser.add_argument(
        "--api-key",
        help=(
            "Override GEMINI_API_KEY for this run only. Useful when the "
            "default key is rate-limited."
        ),
        default="",
    )
    parser.add_argument(
        "--model",
        help="Override the chat model (default: server config, e.g. gemini-2.5-flash-lite).",
        default="",
    )
    parser.add_argument(
        "--provider", choices=("google", "groq"), default="google",
        help="Chat provider for this run (default: google).",
    )
    parser.add_argument(
        "--delay",
        help=(
            "Seconds to sleep between turns within a scenario (helps stay "
            "under per-minute Gemini quotas; 0 = no delay)."
        ),
        type=float,
        default=0.0,
    )
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s — %(message)s",
    )

    scenarios = load_scenarios(filter_id=args.scenario)
    print(f"Loaded {len(scenarios)} scenario(s) from {SCENARIOS_DIR}")
    if args.api_key:
        print(f"Using runtime --api-key override (***{args.api_key[-4:]})")
    if args.model:
        print(f"Using runtime --model override: {args.model}")
    if args.delay > 0:
        print(f"Inter-turn delay: {args.delay}s")

    reports: list[ScenarioReport] = []
    t0 = time.perf_counter()
    for scn in scenarios:
        try:
            report = await run_scenario(
                scn,
                api_key=args.api_key,
                model=args.model,
                provider=args.provider,
                inter_turn_delay=args.delay,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Scenario %s crashed: %s", scn["id"], exc)
            report = ScenarioReport(
                scenario_id=scn["id"],
                title=scn["title"],
                session_id="(crashed)",
                turns_count=len(scn["turns"]),
                checks=[CheckResult("Scenario executed without crash", "FAIL", str(exc))],
            )
        reports.append(report)
    elapsed = time.perf_counter() - t0

    print(f"\n{'═' * 72}")
    print(f"All scenarios finished in {elapsed:.1f}s")
    n_fail = sum(1 for r in reports for c in r.checks if c.status == "FAIL")
    n_pass = sum(1 for r in reports for c in r.checks if c.status == "PASS")
    n_skip = sum(1 for r in reports for c in r.checks if c.status == "SKIP")
    print(f"Total checks: {n_pass} PASS · {n_fail} FAIL · {n_skip} SKIP")

    if not args.no_report:
        REPORT_PATH.write_text(render_report(reports), encoding="utf-8")
        print(f"Report written to {REPORT_PATH}")

    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
