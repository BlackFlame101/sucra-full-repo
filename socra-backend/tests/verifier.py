"""Phase 11 — academic verification checklist.

Implements the six checks from ``scope2.md §11.2``:

  1. Tutor never says "correct, the answer is X"
  2. Tutor always asks at least one question per response
  3. Student profile updated correctly after session
  4. Key terms panel shows relevant terms
  5. Suggested reading cites real pages from uploaded PDF
  6. Conversation saved and resumable

Each check returns a :class:`CheckResult` so the runner can render a
PASS / FAIL / SKIP table per scenario in the final markdown report.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from db import messages as messages_db
from graph.state import EvaluationResult, StudentProfile


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Single line in the per-scenario report table."""

    name: str
    status: str  # "PASS" | "FAIL" | "SKIP"
    detail: str = ""

    @property
    def is_pass(self) -> bool:
        return self.status == "PASS"


@dataclass
class ScenarioReport:
    scenario_id: str
    title: str
    session_id: str
    turns_count: int
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.status in ("PASS", "SKIP") for c in self.checks)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

# Generic patterns that betray a non-Socratic tutor — i.e. one that hands
# the answer to the student instead of guiding them.
_DIRECT_ANSWER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bthe answer is\b", re.IGNORECASE),
    re.compile(r"\bcorrect[,.!]?\s+the\s+answer\s+is\b", re.IGNORECASE),
    re.compile(r"\byes,?\s+exactly,?\s+(it|that)\s+is\b", re.IGNORECASE),
    re.compile(r"\bhere\s+is\s+the\s+definition\b", re.IGNORECASE),
    re.compile(r"\bthe\s+textbook\s+definition\s+is\b", re.IGNORECASE),
    re.compile(r"\bla\s+r[ée]ponse\s+est\b", re.IGNORECASE),
    re.compile(r"\bvoici\s+la\s+d[ée]finition\b", re.IGNORECASE),
)


def check_no_direct_answers(
    tutor_responses: list[str],
    extra_forbidden: list[str] | None = None,
) -> CheckResult:
    """[1/6] Tutor never says "correct, the answer is X"."""
    forbidden = list(extra_forbidden or [])
    offenders: list[str] = []
    for idx, resp in enumerate(tutor_responses, start=1):
        text = resp or ""
        for pat in _DIRECT_ANSWER_PATTERNS:
            if pat.search(text):
                offenders.append(f"turn {idx}: matched /{pat.pattern}/")
                break
        else:
            for needle in forbidden:
                if needle and needle.lower() in text.lower():
                    offenders.append(f"turn {idx}: contains '{needle}'")
                    break
    if offenders:
        return CheckResult(
            "Tutor never gives direct answers",
            "FAIL",
            "; ".join(offenders),
        )
    return CheckResult(
        "Tutor never gives direct answers",
        "PASS",
        f"checked {len(tutor_responses)} turn(s)",
    )


def check_asks_question_per_turn(tutor_responses: list[str]) -> CheckResult:
    """[2/6] Tutor always asks at least one question per response."""
    missing: list[int] = []
    for idx, resp in enumerate(tutor_responses, start=1):
        if "?" not in (resp or "") and "？" not in (resp or ""):
            missing.append(idx)
    if missing:
        return CheckResult(
            "Tutor asks ≥1 question per turn",
            "FAIL",
            f"turns without '?': {missing}",
        )
    return CheckResult(
        "Tutor asks ≥1 question per turn",
        "PASS",
        f"all {len(tutor_responses)} turn(s) contain '?'",
    )


def check_profile_updated(
    initial: dict[str, Any] | StudentProfile | None,
    final: dict[str, Any] | StudentProfile | None,
    expected_min_growth: int = 1,
) -> CheckResult:
    """[3/6] Student profile updated correctly after session."""
    if not final:
        return CheckResult(
            "Profile updated after session",
            "FAIL",
            "no profile row found in DB",
        )
    init_n = int((initial or {}).get("total_exchanges") or 0)
    final_n = int((final or {}).get("total_exchanges") or 0)
    grew = final_n - init_n
    has_lists = any(
        (final or {}).get(k)
        for k in ("mastered_concepts", "fragile_concepts", "misconception_history", "bloom_progression")
    )
    if grew >= expected_min_growth or has_lists:
        return CheckResult(
            "Profile updated after session",
            "PASS",
            f"total_exchanges: {init_n} → {final_n} (+{grew}); has_concept_lists={has_lists}",
        )
    return CheckResult(
        "Profile updated after session",
        "FAIL",
        f"no growth: {init_n} → {final_n} and no concept lists populated",
    )


def check_key_terms_extracted(
    evaluations: list[EvaluationResult],
) -> CheckResult:
    """[4/6] Key terms panel shows relevant terms."""
    if not evaluations:
        return CheckResult(
            "Key terms extracted",
            "SKIP",
            "Évaluateur never ran (no substantive answer in scenario)",
        )
    all_terms: list[str] = []
    for ev in evaluations:
        all_terms.extend(ev.get("key_terms") or [])
    unique = sorted({t.strip() for t in all_terms if t and t.strip()})
    if not unique:
        return CheckResult(
            "Key terms extracted",
            "FAIL",
            f"{len(evaluations)} evaluation(s) but 0 key terms extracted",
        )
    sample = ", ".join(unique[:5])
    return CheckResult(
        "Key terms extracted",
        "PASS",
        f"{len(unique)} unique term(s): {sample}{'…' if len(unique) > 5 else ''}",
    )


def check_suggested_readings_real_pages(
    evaluations: list[EvaluationResult],
) -> CheckResult:
    """[5/6] Suggested reading cites real pages from uploaded PDF.

    PASS if at least one suggested reading carries a numeric ``page_number``
    AND a non-empty filename. SKIP if no PDF was retrieved for this scenario
    (the test environment may not have a relevant PDF for every topic).
    """
    if not evaluations:
        return CheckResult(
            "Suggested readings cite real pages",
            "SKIP",
            "Évaluateur never ran",
        )
    readings: list[dict[str, Any]] = []
    for ev in evaluations:
        readings.extend(ev.get("suggested_readings") or [])
    if not readings:
        return CheckResult(
            "Suggested readings cite real pages",
            "SKIP",
            "no PDF chunks retrieved for this topic (RAG returned empty)",
        )
    cited = [
        r for r in readings
        if isinstance(r.get("page_number"), int) and r.get("filename")
    ]
    if not cited:
        return CheckResult(
            "Suggested readings cite real pages",
            "FAIL",
            f"{len(readings)} reading(s) but none have a numeric page_number + filename",
        )
    sample = cited[0]
    return CheckResult(
        "Suggested readings cite real pages",
        "PASS",
        f"{len(cited)}/{len(readings)} reading(s) properly cited "
        f"(e.g. {sample.get('filename')!r} p.{sample.get('page_number')})",
    )


def check_conversation_resumable(
    session_id: str,
    expected_user_turns: int,
) -> CheckResult:
    """[6/6] Conversation saved and resumable."""
    try:
        rows = messages_db.load_messages(session_id) or []
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "Conversation persisted & resumable",
            "FAIL",
            f"failed to load messages from DB: {exc}",
        )
    user_msgs = [r for r in rows if r.get("role") == "user"]
    asst_msgs = [r for r in rows if r.get("role") == "assistant"]
    if len(user_msgs) < expected_user_turns:
        return CheckResult(
            "Conversation persisted & resumable",
            "FAIL",
            f"only {len(user_msgs)}/{expected_user_turns} user messages persisted",
        )
    if not asst_msgs:
        return CheckResult(
            "Conversation persisted & resumable",
            "FAIL",
            f"{len(user_msgs)} user msgs but 0 assistant msgs persisted",
        )
    return CheckResult(
        "Conversation persisted & resumable",
        "PASS",
        f"{len(user_msgs)} user + {len(asst_msgs)} assistant message(s) in DB",
    )


# ---------------------------------------------------------------------------
# Bonus: scope-aligned diagnostic check (not in the official 6 but useful)
# ---------------------------------------------------------------------------

def check_diagnostic_topic(
    diagnostic: dict[str, Any] | None,
    expected_keywords: list[str],
) -> CheckResult:
    """Bonus: diagnostic.topic mentions one of the expected keywords."""
    if not diagnostic:
        return CheckResult(
            "Diagnostic produced for first turn",
            "FAIL",
            "no diagnostic in final state",
        )
    if not expected_keywords:
        return CheckResult(
            "Diagnostic produced for first turn",
            "PASS",
            f"topic={diagnostic.get('topic')!r}",
        )
    topic_text = (diagnostic.get("topic") or "").lower()
    if any(kw.lower() in topic_text for kw in expected_keywords):
        return CheckResult(
            "Diagnostic produced for first turn",
            "PASS",
            f"topic={diagnostic.get('topic')!r}",
        )
    return CheckResult(
        "Diagnostic produced for first turn",
        "FAIL",
        f"topic={diagnostic.get('topic')!r} did not match any of {expected_keywords}",
    )


def check_agents_no_fallback(issues: list[dict[str, str]]) -> CheckResult:
    """Fail runs where a core agent substituted a fallback response."""
    if issues:
        agents = ", ".join(sorted({item.get("agent", "unknown") for item in issues}))
        return CheckResult("Core agents completed without fallback", "FAIL", f"fallback used by: {agents}")
    return CheckResult("Core agents completed without fallback", "PASS", "no agent fallback recorded")


def check_response_language(responses: list[str], expected: str) -> CheckResult:
    """Check tutor replies for obvious language mismatches."""
    expected = (expected or "en").lower()
    french = expected.startswith("fr")
    french_markers = (" le ", " la ", " les ", " des ", " est ", " pourquoi ", " comment ", " votre ", " pouvez-vous ", " dans ")
    english_markers = (" the ", " is ", " are ", " what ", " why ", " how ", " your ", " could you ", " can you ", " in your ")
    mismatches = []
    for index, response in enumerate(responses, 1):
        padded = f" {(response or '').lower()} "
        expected_markers, other_markers = (french_markers, english_markers) if french else (english_markers, french_markers)
        if sum(marker in padded for marker in expected_markers) == 0 and sum(marker in padded for marker in other_markers) >= 2:
            mismatches.append(index)
    if mismatches:
        return CheckResult("Tutor follows scenario language", "FAIL", f"likely language mismatch on turn(s): {mismatches}")
    return CheckResult("Tutor follows scenario language", "PASS", f"checked {len(responses)} turn(s), expected {'French' if french else 'English'}")
