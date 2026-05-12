# Phase 11 — Scenario Test Report

_Generated: 2026-05-07 12:51:30 UTC_

This report exercises the full multi-agent LangGraph pipeline
(Diagnostiqueur → Tuteur Socratique → Évaluateur → Mémoire) against
five academic scenarios and validates the six-point checklist defined
in `scope2.md §11.2`.

## Summary

| Scenario | Turns | Pass | Fail | Skip | Verdict |
|---|---:|---:|---:|---:|:---:|
| **Fact table vs dimension table** | 5 | 6 | 1 | 0 | ❌ FAIL |
| **Entropy and the second law of thermodynamics** | 5 | 6 | 1 | 0 | ❌ FAIL |
| **Graceful handling of student frustration** | 5 | 6 | 1 | 0 | ❌ FAIL |
| **What is an isolated system** | 5 | 6 | 1 | 0 | ❌ FAIL |
| **Star schema in data warehousing** | 5 | 6 | 1 | 0 | ❌ FAIL |
| **Total** | — | **30** | **5** | **0** | ❌ SOME FAILED |

## Scenario — Fact table vs dimension table

- **id**: `fact_vs_dimension`
- **session_id**: `f74198d0-ac1d-4ad2-b998-b7d299e42e89`
- **turns**: 5

| # | Check | Status | Detail |
|---:|---|:---:|---|
| 1 | Tutor never gives direct answers | ✅ PASS | checked 5 turn(s) |
| 2 | Tutor asks ≥1 question per turn | ✅ PASS | all 5 turn(s) contain '?' |
| 3 | Profile updated after session | ✅ PASS | total_exchanges: 0 → 3 (+3); has_concept_lists=True |
| 4 | Key terms extracted | ❌ FAIL | 3 evaluation(s) but 0 key terms extracted |
| 5 | Suggested readings cite real pages | ✅ PASS | 6/6 reading(s) properly cited (e.g. 'SID - Data Warehouse.pdf' p.15) |
| 6 | Conversation persisted & resumable | ✅ PASS | 5 user + 5 assistant message(s) in DB |
| 7 | Diagnostic produced for first turn | ✅ PASS | topic='I think a fact table holds names and labels and a dimension table holds the numbers.' |

## Scenario — Entropy and the second law of thermodynamics

- **id**: `entropy`
- **session_id**: `0ce7070d-570f-41aa-a957-066cbebe1d90`
- **turns**: 5

| # | Check | Status | Detail |
|---:|---|:---:|---|
| 1 | Tutor never gives direct answers | ✅ PASS | checked 5 turn(s) |
| 2 | Tutor asks ≥1 question per turn | ✅ PASS | all 5 turn(s) contain '?' |
| 3 | Profile updated after session | ✅ PASS | total_exchanges: 0 → 2 (+2); has_concept_lists=True |
| 4 | Key terms extracted | ❌ FAIL | 2 evaluation(s) but 0 key terms extracted |
| 5 | Suggested readings cite real pages | ✅ PASS | 4/4 reading(s) properly cited (e.g. 'SID - Data Warehouse.pdf' p.13) |
| 6 | Conversation persisted & resumable | ✅ PASS | 5 user + 5 assistant message(s) in DB |
| 7 | Diagnostic produced for first turn | ✅ PASS | topic='Entropy is just a measure of disorder, right? Like how messy a room is.' |

## Scenario — Graceful handling of student frustration

- **id**: `frustration`
- **session_id**: `84ef8fbd-ccb0-4c91-a96e-a491ebe7d3a7`
- **turns**: 5

| # | Check | Status | Detail |
|---:|---|:---:|---|
| 1 | Tutor never gives direct answers | ✅ PASS | checked 5 turn(s) |
| 2 | Tutor asks ≥1 question per turn | ✅ PASS | all 5 turn(s) contain '?' |
| 3 | Profile updated after session | ✅ PASS | total_exchanges: 0 → 2 (+2); has_concept_lists=True |
| 4 | Key terms extracted | ❌ FAIL | 2 evaluation(s) but 0 key terms extracted |
| 5 | Suggested readings cite real pages | ✅ PASS | 4/4 reading(s) properly cited (e.g. 'SID - Data Warehouse.pdf' p.13) |
| 6 | Conversation persisted & resumable | ✅ PASS | 5 user + 5 assistant message(s) in DB |
| 7 | Diagnostic produced for first turn | ✅ PASS | topic="Honestly I don't understand any of this. It's all just symbols and words to me." |

## Scenario — What is an isolated system

- **id**: `isolated_system`
- **session_id**: `5e7f4366-12da-42da-ac08-964e10c429e0`
- **turns**: 5

| # | Check | Status | Detail |
|---:|---|:---:|---|
| 1 | Tutor never gives direct answers | ✅ PASS | checked 5 turn(s) |
| 2 | Tutor asks ≥1 question per turn | ✅ PASS | all 5 turn(s) contain '?' |
| 3 | Profile updated after session | ✅ PASS | total_exchanges: 0 → 1 (+1); has_concept_lists=True |
| 4 | Key terms extracted | ❌ FAIL | 1 evaluation(s) but 0 key terms extracted |
| 5 | Suggested readings cite real pages | ✅ PASS | 2/2 reading(s) properly cited (e.g. 'SID - Introduction.pdf' p.7) |
| 6 | Conversation persisted & resumable | ✅ PASS | 5 user + 5 assistant message(s) in DB |
| 7 | Diagnostic produced for first turn | ✅ PASS | topic="An isolated system is one that doesn't exchange anything with its surroundings." |

## Scenario — Star schema in data warehousing

- **id**: `data_warehouse`
- **session_id**: `5e11ef18-4912-4473-bcab-f2aa24d23961`
- **turns**: 5

| # | Check | Status | Detail |
|---:|---|:---:|---|
| 1 | Tutor never gives direct answers | ✅ PASS | checked 5 turn(s) |
| 2 | Tutor asks ≥1 question per turn | ✅ PASS | all 5 turn(s) contain '?' |
| 3 | Profile updated after session | ✅ PASS | total_exchanges: 0 → 1 (+1); has_concept_lists=True |
| 4 | Key terms extracted | ❌ FAIL | 1 evaluation(s) but 0 key terms extracted |
| 5 | Suggested readings cite real pages | ✅ PASS | 2/2 reading(s) properly cited (e.g. 'SID - Data Warehouse.pdf' p.13) |
| 6 | Conversation persisted & resumable | ✅ PASS | 5 user + 5 assistant message(s) in DB |
| 7 | Diagnostic produced for first turn | ✅ PASS | topic='I have no idea what a star schema is. Never heard the term before.' |

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

