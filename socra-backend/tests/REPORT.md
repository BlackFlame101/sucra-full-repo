# Phase 11 — Scenario Test Report

_Generated: 2026-10-27 23:42:25 UTC_

This report exercises the full multi-agent LangGraph pipeline
(Diagnostiqueur → Tuteur Socratique → Évaluateur → Mémoire) against
academic scenarios and validates the required checklist defined
in `scope2.md §11.2`, plus fallback and response-language checks.

## Summary

| Scenario | Turns | Pass | Fail | Skip | Verdict |
|---|---:|---:|---:|---:|:---:|
| **Entropy and the second law of thermodynamics** | 5 | 9 | 0 | 0 | ✅ PASS |
| **Total** | — | **9** | **0** | **0** | ✅ ALL PASSED |

## Scenario — Entropy and the second law of thermodynamics

- **id**: `entropy`
- **session_id**: `73aa30e4-dec3-4906-a568-a7f0a5e3f3a2`
- **turns**: 5

| # | Check | Status | Detail |
|---:|---|:---:|---|
| 1 | Tutor never gives direct answers | ✅ PASS | checked 5 turn(s) |
| 2 | Tutor asks ≥1 question per turn | ✅ PASS | all 5 turn(s) contain '?' |
| 3 | Profile updated after session | ✅ PASS | total_exchanges: 0 → 2 (+2); has_concept_lists=True |
| 4 | Key terms extracted | ✅ PASS | Persisted to key_terms: 8 unique term(s): Heat flow, Irreversibility, Second law of thermodynamics, Spontaneous process, disorder… |
| 5 | Suggested readings cite real pages | ✅ PASS | 4/4 reading(s) properly cited (e.g. 'SID - Data Warehouse.pdf' p.13) |
| 6 | Conversation persisted & resumable | ✅ PASS | 5 user + 5 assistant message(s) in DB |
| 7 | Diagnostic produced for first turn | ✅ PASS | topic='Entropy is just a measure of disorder, right? Like how messy a room is.' |
| 8 | Core agents completed without fallback | ✅ PASS | no agent fallback recorded |
| 9 | Tutor follows scenario language | ✅ PASS | checked 5 turn(s), expected English |

---

## Scope alignment (`scope2.md §11.2`)

| Required check | Implemented |
|---|:---:|
| Tutor never says 'correct, the answer is X' | ✅ `check_no_direct_answers` |
| Tutor always asks at least one question per response | ✅ `check_asks_question_per_turn` |
| Student profile updated correctly after session | ✅ `check_profile_updated` |
| Key terms panel shows relevant terms | ✅ `check_key_terms_extracted` |
| Suggested reading cites real pages from uploaded PDF | ✅ `check_suggested_readings_real_pages` |
| Conversation saved and resumable | ✅ `check_conversation_resumable` |

> Sessions created by this runner are prefixed with `[TEST-Phase11]` and remain in Supabase so they can be inspected in the UI sidebar. Re-running the script creates fresh sessions.

