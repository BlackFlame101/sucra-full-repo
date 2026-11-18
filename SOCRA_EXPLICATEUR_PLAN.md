# SOCRA_EXPLICATEUR_PLAN.md

> **Status:** M2, Phase 2 and Phases 3a–3b are complete. Phase 6 adds offline-verified adaptive modes and page-scoped course continuation behind a flag. Live model evaluation and the remaining Phase 6 acceptance checks are pending.
> **Scope:** Socra's course inquiry **Explain / Explicateur** path, with only the smallest necessary changes to retrieval, schemas, UI rendering and testing.
> **Working principle:** One small phase at a time. Preserve user data and the existing product. Keep Gemini/Groq free-tier usage under control.

## CURRENT PHASE: Phase 6 adaptive explanations and course continuation

> Update this line after each phase. Each Codex session should read this header, Sections A-D, and **only** the section for the current phase.

## Phase 6 implementation report

### 6A diagnosis

The inputs are the five exact French requests and the screenshots of the rendered cards. The archived provider payloads, profiles and chunk traces for those requests were unavailable. The five prompts are permanent fixtures. Payload regressions use synthetic reproductions and mocks.

| Screenshot | Confirmed current mechanism | Unverified for the original run |
| --- | --- | --- |
| Short summary | `_request_style` and `is_brief_request` selected brevity. `_normalize_explanation_payload` lacked an inline-list repair and `_bind_sources` bound structured citations while leaving inline indexes untouched. | Whether the provider emitted newlines or the serialization already contained inline bullets. |
| Standard | `_EXPLANATION_RESPONSE_SCHEMA` required code, code language and walkthrough keys. `StudyCode` gave unmatched text snippets executable chrome. | The exact field and language supplied for each conceptual block. |
| Beginner | `classify_explain_task` had no beginner route. The general `_section_guidance` included a screenshot instruction and could send it with lecture prompts. | The historical task classification and whether the model took the heading from that guidance or the PDF. |
| Revision sheet | `classify_explain_task` had no revision route. The shared prompt and schema allowed code plus repeated walkthrough snippets. | The exact duplicate snippet values before rendering. |
| Whole course | `build_inventory` and `_check_and_repair` evaluated extracted assignment requirements. `retrieve_summary_guided_chunks` ranked page excerpts rather than retrieving an ordered part. `get_current_course_sections` already exposed the current-version Course Map to the backend. | The exact indexed pages and the number of source requirements available in the real PDF. |

Repeated scroll buttons in the stitched screenshots were treated as seams. The existing viewport placement has a regression check.

### 6B–6G implementation

- `agents/explain_intent.py`, `agents/explain_tasks.py`, `agents/explicateur.py`: deterministic intent, language, audience, scope and format selection. The five lecture routes receive distinct plans. Existing lab and exercise workflows continue through their original prompt and coverage path.
- `agents/explicateur.py`, `components/notebook/NotebookReply.tsx`, `lib/ai/explanation-card-layout.ts`: schema-compatible prose sections, ordered Markdown, conservative duplicate snippet handling, verified citation-marker cleanup, page sorting, and quiet rendering for plain text blocks. Genuine shell commands and executable code retain their copy controls.
- `agents/explain_course.py`, `agents/explicateur.py`, `graph/state.py`: versioned inventory and ordered token-aware parts derived from the current Course Map and verified indexed chunks. Part evidence is filtered by exact page range before generation. Lexical, source-page and expected-content checks keep covered, partial, missing, unverifiable, and not yet generated distinct.
- `api/websocket.py`, `hooks/useSocraChat.ts`, `lib/socra-ws.ts`, inquiry page and `components/chat/ChatPanel.tsx`: continuation resolves its predecessor from the authenticated inquiry, uses a stable request ID and replays committed results through the existing persisted turn. The existing chat lease serializes concurrent requests.
- `components/chat/ExplanationCard.tsx`, Library detail page and `lib/ai/explanation-note.ts`: shared card layout and existing design tokens with adaptive headings, course progress, prior-part links, resume from the original inquiry, and course status in Notebook export. Revision sheets request self-test questions without generated answers.

No new database schema. Assistant metadata adds optional `language`, `course_progress`, and adaptive presentation values. Stored course metadata records the version, document, part history, section statuses, and next request ID. Existing cards may omit all these fields. The client sends an optional `continueCourseFrom` with an explain message. `EXPLAIN_INTENT_PLANS` follows existing flag behavior and defaults off in production. Existing flags, generation deadline (90 seconds), and shared format/transport retry (at most one) still apply. A successful adaptive answer or explicitly requested course part uses one generation call. Course parts run no automatic coverage repair or continuation. Existing lab recovery and explicit exercise batching keep their prior budgets. Provider token reporting stays in the existing model instrumentation.

### 6H–6K verification and rollout

Backend verification command from `socra-backend` on a host with working localhost sockets:

```powershell
.venv/Scripts/python.exe -m unittest tests.test_explain_intent tests.test_explicateur tests.test_explain_phase2 tests.test_explain_coverage tests.test_chat_socket tests.test_structured_output
```

The Windows workspace blocked asyncio's localhost socketpair. The offline suite ran with this test-process-only substitute for the event loop wakeup. No application code or runtime dependencies use it.

```powershell
.venv/Scripts/python.exe -u -c "import asyncio, sys, unittest; from types import SimpleNamespace; from asyncio.proactor_events import BaseProactorEventLoop as L; pulse=lambda loop: loop.call_later(.01,pulse,loop); L._make_self_pipe=lambda loop:(setattr(loop,'_csock',SimpleNamespace(fileno=lambda:-1)),pulse(loop)); L._loop_self_reading=lambda self:None; L._write_to_self=lambda self:None; L._close_self_pipe=lambda self:None; unittest.main(module=None)" tests.test_explain_intent tests.test_explicateur tests.test_explain_phase2 tests.test_explain_coverage tests.test_chat_socket tests.test_structured_output
```

Frontend verification commands from `socra`:

```powershell
node scripts/test-explanation-rendering.mjs
node scripts/test-notebook.mjs
node scripts/test-study-routes.mjs
node node_modules/typescript/bin/tsc --noEmit
node node_modules/eslint/bin/eslint.js components/chat/ExplanationCard.tsx components/chat/ChatPanel.tsx components/notebook/NotebookReply.tsx hooks/useSocraChat.ts lib/socra-ws.ts lib/ai/explanation-card-layout.ts lib/ai/explanation-note.ts 'app/(dashboard)/dashboard/course/[courseId]/inquiry/[sessionId]/page.tsx' 'app/(dashboard)/dashboard/library/[id]/page.tsx'
$env:SOCRA_TEST_BROWSER = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
node scripts/test-chat-browser.mjs
```

- [x] Exact French intent fixtures and synthetic formatting regressions pass. The offline continuation test generates two scoped parts with two generation calls and keeps future sections separate. The WebSocket test reconnects, continues from saved state, and confirms a duplicate request replays the stored card.
- [x] Shared JavaScript rendering, Notebook and study-route fixtures pass. The headless Chromium chat smoke test passes with a mocked WebSocket. It covers chat behavior, while the adaptive cards were checked with rendering fixtures.
- Backend suite reported 126 passed, 0 failed. Frontend suites reported 22 rendering tests, 8 Notebook tests and 9 study-route tests passed, with 0 failures. TypeScript and targeted ESLint passed.
- [ ] Full adaptive card matrix in desktop and mobile browsers, print output and manual screen-reader checks. Existing responsive styles and native disclosure semantics are reused. These checks were not performed.
- [ ] Real PDF and provider evaluation. The Course Map is treated as an identified-section inventory. Lexical and structural coverage cannot verify pedagogical correctness, formula accuracy, or extraction of every concept. Dense single sections can exceed the budget and are reported as unverifiable if excerpts are omitted. A course with an incomplete index cannot continue through all parts. Explicit source markers that cannot be resolved safely may remain visible.

No deployment, push, migration, production data changes, feature-flag activation in production, or live provider calls.

## What changed

### v1 -> v2
1. 0b no longer makes a continuation call; it only salvages complete sections and returns an explicit incomplete status. The continuation call lives in Phase 3a, where the inventory exists.
2. Multi-exercise batching moved out of 0a. 0a only stops the runaway loop (single-call fallback plus a hard cap).
3. Retrieved-page coverage cannot be measured offline, so manual step **M1** was added.
4. Offline tests verify logic (routing, prompts, language precedence, checker on golden fixtures). Assertions about real model output moved to the Phase 4 live run.
5. Phase 3 split into **3a** (backend) and **3b** (schema + UI).
6. Phase 2 got a minimal document-selection path so full-document mode can actually trigger.
7. Manual step **M2** (provider limits config) added before Phase 2.
8. Explicit flag defaults: off in prod until Phase 4 passes, on in dev.
9. Phase 4 requires you to supply the evaluation documents; real PDFs stay out of git.

### v2 -> v2.1 (after external review)
1. **0b:** do not assume `explanation_preview` can return deserializable section objects. Inspect it; implement a small tested partial-section extractor or return an explicit truncation error.
2. **M1 and Phase 2 go/no-go:** page coverage is not enough. Also measure chunk coverage, whether required markers (Capture N, Question N, Annexe...) reached the model, and retrieved tokens. One PDF does not decide the strategy for all PDFs.
3. **Inventory vs retrieval:** the requirement inventory is built from the **whole selected document's indexed text** (Python, no LLM), independent of which chunks the model receives. If the document cannot be resolved, the inventory is marked `retrieved_only` and the answer can never be called complete for the document.
4. **Code-fence normalizer:** `_normalize_explanation_payload` pulls the first fenced block out of `content` into `code`, which breaks the order of mixed GUI/command guides. Fixed for lab mode in Phase 1a. Phase 3b preserves fence order across all Explain modes and renders Markdown in sequence.
5. **Incomplete-status persistence rule** (new Section B2): incomplete notices must survive reload, not exist only as progress events.
6. **Coverage thresholds** are per requirement type; content and anchor checks matter more than length.
7. **Flag-off semantics** clarified: flags restore old routing/prompt/retrieval behavior but keep all Phase 0 safety fixes.
8. **Phase 1 split** into **1a** (classification, language, prompts, normalizer) and **1b** (flagged batching). The optional depth selector is deferred, not scheduled.

## How to use this file with Codex

1. Copy this file into the **root of the Socra repository** as `SOCRA_EXPLICATEUR_PLAN.md`.
2. Open the full repository (frontend, `socra-backend`, and any Supabase migrations) in Codex.
3. Give Codex the **one-phase prompt** from [Codex execution prompts](#e-codex-execution-prompts). **Start with Phase 0a.**
4. Codex must inspect the actual code before editing. The code observations below came from an earlier supplied snapshot of `explicateur.py`; the checkout may have changed.
5. After each phase: implement, test offline, review diffs, update **only genuinely finished checkboxes**, paste the **actual test command output** into the report, and list limitations and remaining work. Stop before the next phase.
6. Record measured baselines before changing behavior. Never fabricate timings, token usage, retrieved page counts or passing tests.
7. Do not push, deploy, change production Supabase data, enable paid infrastructure, or run live-provider calls without explicit authorization.

### Phase overview

| Order | Phase | Goal | Extra LLM calls in normal use |
|---|---|---|---|
| 1 | **0a: Baseline, loop guard, citations, logging** | Stop runaway per-item calls, make citation binding robust, add instrumentation | **0** |
| - | **M1 (manual, you)** | Run the TP request once in dev; record page and chunk coverage and required-marker presence | 1 free-tier call |
| 2 | **0b: Retry budget, truncation salvage, streaming** | Shared retry budget, transient recovery, salvage complete sections on truncation, preview throttling | **0** in success path |
| 3 | **1a: Task-aware Explicateur** | Intent/detail classification, language precedence, short mode prompts, graded-question behavior, lab-safe code-fence normalization | **0** |
| 4 | **1b: Flagged multi-exercise batching** | Grouped generation for explicit multi-exercise requests | 0 extra; bounded groups |
| - | **M2 (manual, you)** | Look up real quota/context limits for your exact models; write config note | none |
| 5 | **2: Document coverage** | Go/no-go on full-document answer path, document selection, full-document inventory | **0** for classification/inventory; full-context generation costs more tokens |
| 6 | **3a: Coverage validation and repair (backend)** | Deterministic coverage check, bounded repair/continuation | **0** normally; at most 1 bounded repair |
| 7 | **3b: Citations and rendering (schema + UI)** | Optional per-section fields, correct code/GUI rendering, ordered mixed content | **0** |
| 8 | **4: Cross-document evaluation** | Quality, cost, robustness across subjects | Offline first; live runs only if authorized |
| 9 | **5: Final quality polish** | Contextual results, coverage calibration and formatting verification | **0** extra in normal use |

Do not interpret these as services or LLM agents. Keep a single Explicateur and its existing LangGraph integration.

### Feature flags (defaults)

| Flag | Controls | Default in prod | Default in your dev env |
|---|---|---|---|
| `EXPLAIN_TASK_MODES` | Phase 1a intent routing, mode prompts, lab-safe normalization | **off** | **on** |
| `EXPLAIN_MULTI_EXERCISE_BATCHING` | Phase 1b grouped multi-exercise generation | **off** | **on** |
| `EXPLAIN_DOCUMENT_INVENTORY` | Phase 2 source selection, inventory and bounded missing evidence | **off** | **on** |
| `EXPLAIN_FULL_DOCUMENT` | Reserved for whole-document answer retrieval after a positive coverage decision | **off** | **off** |
| `EXPLAIN_COVERAGE_CHECK` | Phase 3a coverage check and repair | **off** | **on** |

Phase 0a/0b guardrails (loop cap, tolerant citations, retry budget, truncation handling) are **not** flagged: they are safety fixes and ship on. Flags flip to on in production only after the Phase 4 report justifies it.

**Flag-off semantics:** turning a flag off restores the previous *routing, prompt and retrieval* behavior but **keeps all Phase 0a/0b safety fixes**. Never restore the unbounded per-item loop, the all-or-nothing citation rejection, or the identical retry after truncation.

---

## A. Current system: from the supplied `explicateur.py` snapshot

The snapshot showed the following. Codex must verify each against the actual checkout.

- `_request_style(message)` yields `("short summary" | "detailed teaching explanation", assignment_mode: bool)`. Phrases such as "complete this TP", "every install", "each screenshot" are **not** recognized as practical-guide intent.
- `run_explicateur` uses `retrieve_summary_guided_chunks(query, course_id, k=6 | 20 | 30)`. An assignment fallback can also call `retrieve_chunks(..., hybrid=True)`.
- `_assignment_inventory` matches headings such as `exercise`, `exercice`, `question`, `partie`, `part`, `\d+.\d+` and numbered lines, from **retrieved chunks only**.
- `targets = (labelled_exercises or inventory) if assignment_mode else []` may trigger one generation per target. `_generate_valid_explanation` has its own retries, so calls can multiply. The *number* of targets for the TP is **not measured**.
- The response schema requires `definition`, `intuition`, `sections`, `course_example`, `common_pitfalls`, `citations`, `check_question`. Each section has `heading`, `content`, `code`, `code_language`, `walkthrough`.
- The base prompt pushes runnable solutions, walkthroughs and a check question even for GUI procedures.
- `_bind_sources` can reject the **entire** answer on one bad index or unusable excerpt.
- `_generate_valid_explanation` streams JSON through `explanation_preview(raw)` on the accumulated buffer. Transient stream retry only happens when some text was already displayed. Invalid output triggers another attempt. `finish_reason=length` is rejected and retried with the same limits.
- `_normalize_explanation_payload` extracts the **first** fenced code block from a section's `content` into `code` when `code` is empty, and also converts lines shaped like `` `code`: explanation `` into `walkthrough` rows. Both can reorder or mangle mixed GUI/command lab sections.
- Language maps session state to English or French only; Arabic is not a response language.
- Models use `temperature=0.3` and `max_completion_tokens=16_000` in this snapshot.
- The global citation list is capped at 1-8 by prompt guidance. "Course sources (8)" **does not mean only 8 chunks were retrieved**.
- The retry message tells the model to "keep only the exercise explicitly requested", which would harm a lab guide.
- The frontend receives preview and final-card events; explanations are saved to history / Library / Notebook. Preserve that.

**Inspect actual files:** `socra-backend/agents/explicateur.py` (or current location), `agents/llm.py`, `agents/structured_output.py`, `agents/explanation_preview.py`, `models/schemas.py`, `rag/retriever.py`, `agents/course_summarizer.py`, `api/websocket.py`, `graph/orchestrator.py`, frontend `useSocraChat.ts`, `socra-ws.ts`, `ChatPanel.tsx`, `ExplanationCard.tsx`, `PdfCitation.tsx`, saved-explanation / Notebook converters, tests.

### The reference regression document

**PDF:** `TP_Complementaire_Orange_KNIME(1).pdf`, 15 pages. Use a **local, gitignored** fixture or a derived/synthetic excerpt. Do not commit the teacher's PDF. Do not assume the chat attachment is available in Codex.

**Original student request (English):**

> I want you to detail everything of what i need to do to complete this tp in my laptop with every install of any application and every code that i need and every command i need to run and everything i need to do for each screen shot detailed at the end of the file as well

The original answer treated this as a generic teaching explanation, compressed the steps, labelled GUI instructions as Python code, and omitted screenshot instructions, mandatory questions and the dataset fallback.

**PDF facts used as regression anchors** (checked in the Phase 4 live run, and by golden-fixture tests of the checker):

- **Installation:** Orange via the official Windows installer **or** a dedicated Python venv (Python **3.11+**; `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` if activation is refused). KNIME 5.x installer, workspace `Documents\knime-workspace`, Modern UI.
- **Data:** `transactions.csv`, 5,000 rows, 568 frauds; copied from `tp4-automl`; Annex A regenerates it with `donnees.py` (venv, `pip install numpy pandas`).
- **Orange:** `File` with `fraude` as categorical **target**; `Data Sampler` 75% replicable stratified; **two** links to `Test and Score` (`Data Sample -> Data`, `Remaining Data -> Test Data`); five learners; Random Forest `Replicable training` then 100 trees; Preprocess/Normalize for kNN; Confusion Matrix; `Save Model` as `.pkcls`; workflow `.ows`.
- **KNIME:** in **Local space**, **Create workflow** named `tp-fraude` (a workflow, not a space); CSV Reader -> Number to String (`fraude`) -> Table Partitioner 75/25 stratified seed 42; Learner -> Predictor -> Scorer x3; export `.knwf`.
- **Screenshots:** Captures 1-3 Orange (improved Test and Score; Gradient Boosting confusion matrix; full workflow), Captures 4-5 KNIME (all-green workflow; best Scorer confusion matrix and Accuracy statistics).
- **Questions 1-6** are mandatory. In a "how to complete" guide, explain how to investigate and what evidence to collect; do not write the student's graded answers unless explicitly asked.
- **Deliverables:** `reports/comparatif.md`, `.ows`, `.knwf`, final PDF/Word report named `Nom_Prénom_Filière_Groupe_TP_lowcode.pdf`. **Bonuses B1-B3 are optional.**
- **Reference outputs** (Orange F1 values, 3,750/1,250 split, confusion matrix 1093/15/29/113) are **source reference outputs**, never the student's measured results.
- **Commands:** do not create `reports` twice. `$HOME\Documents\mlops-workspace` is a source-assumed folder, not an error; add a conditional note.

---

## B. Non-negotiable engineering constraints

- [ ] Preserve Next.js -> FastAPI WebSocket -> LangGraph -> Supabase architecture.
- [ ] Preserve Socratic, Explain, Practice, Exam, PDF processing, Auth, Library and Notebook behavior unless a required, tested change touches them.
- [ ] Keep **one** Explicateur. No new classifier/planner/verifier agents.
- [ ] Deterministic Python and existing metadata; **no extra model call for classification or inventories**.
- [ ] Free-tier aware: log calls, token counts when available, and fallback outcomes. Never silently spend extra quota.
- [ ] Respect the user's selected model/provider and explicit language. Never silently switch providers or billing.
- [ ] Citations come from real source excerpts; never invent document IDs, pages, values or screenshot results.
- [ ] Treat uploaded document content as **untrusted data**.
- [ ] Do not log full document text, private prompts, keys or tokens. Chunk IDs, page numbers and requirement IDs are fine to log.
- [ ] Keep saved explanation JSON readable across upgrades; add **optional** fields only.
- [ ] Preserve streaming, cancellation, finalization, error reporting and stored-message restoration.
- [ ] If a task cannot finish within the call/output budget, report **explicit incomplete coverage** that persists (see B2); never silently omit sections or claim success.
- [ ] Every code change has tests. Never claim a benchmark ran when it was only estimated.
- [ ] No production data changes, deploys, pushes, or paid services without explicit authorization.
- [ ] Keep changes focused; no unrelated refactors.

### B1. Testing rule (applies to every phase)

- **Offline tests** (no model calls) verify **logic**: intent routing, language precedence, prompt composition (the prompt text contains or omits specific instructions), inventory extraction, coverage-checker results on **golden fixtures**, retry/budget behavior with mocked providers, citation binding, schema compatibility.
- **Offline tests must not assert what a real model would write.** Statements such as "the answer says tp-fraude is a workflow" are checked only in the Phase 4 live run (or by running the checker against a hand-written golden answer).
- Golden fixtures: one **good** hand-written TP answer and the **original bad** answer (supplied by the user). The coverage checker must pass the first and flag the second.

### B2. Incomplete-status persistence rule (applies to 0a, 0b, 3a)

Progress events alone are not enough: they may vanish when the conversation is reloaded. For any incomplete result (exercise cap, truncation, failed coverage) Codex must:

1. Inspect how a finished explanation is saved and restored.
2. If the saved payload can already carry a status, use it.
3. Otherwise, when some valid content exists, append a plain final **section** (for example heading "Incomplete: not covered", content listing the missing items and how to ask for them). It is stored with the explanation without a schema change.
4. When nothing valid exists, return a clear error instead.
5. Test (with a mocked persistence layer): save, restore, and confirm the incomplete notice is still present.

Never present an incomplete answer as complete, and never rely only on a transient progress message.

---

## Phase 0a: Baseline, stop runaway calls, harden citations, instrument

**Purpose:** Make current behavior safer and cheaper before changing intent, prompts or retrieval. **No new features, no batching.**

**Primary code:** `explicateur.py` and its existing offline tests.

### 0a.1 Baseline capture before any behavior change

- [x] Record the git commit and working-tree state. Do not overwrite unrelated changes.
- [x] If the TP text is available as a local fixture, run `_assignment_inventory` on it and record labels, duplicates, pages and the **number of targets the current code would generate**. Do not assume the earlier 15-20 estimate.
- [ ] Save the user's original bad answer as a fixed fixture (golden "bad" example). Do not generate a new live answer.
- [x] Record model-call routing and retry **upper bounds** from code or mocks, separating measured from theoretical.
- [x] Add 3-4 small existing fixtures (coding, maths, language, exercise/data/research) if they exist. Mark missing baselines as **not measured**.
- [x] Mark retrieved-page and chunk coverage for the TP request as **not measurable offline** (it needs live DB and embeddings). That measurement is manual step M1.
- [x] Save the baseline report in the repo. No user content or credentials unless clearly authorized.

### 0a.2 Stop the runaway loop (no batching yet)

- [x] Numbered lists, `Partie`, `Part`, `Question`, outline headings and `\d+.` lines must **not** be treated as exercises.
- [x] Per-exercise generation runs only when the student explicitly asks to solve exercises **and** genuine labelled `Exercise/Exercice` items are detected.
- [x] If no genuine labelled exercise is found, use **one** normal generation call.
- [x] A named exercise ("exercise 2", "exercice 3.1") keeps its targeting and original numbering.
- [x] Add a **hard, configurable cap** on per-exercise calls (default small, e.g. 4). If more genuine exercises exist than the cap, do **not** silently drop them: return an incomplete result listing what was not covered, persisted according to **B2**. Do not invent a new public schema.
- [x] Do not batch exercises in this phase. Batching is Phase 1b behind a flag.
- [x] Do not let prompts mutate across targets in ways that leak content between exercises.

### 0a.3 Citation binding robustness

- [x] Validate each generated citation independently.
- [x] Drop invalid indexes, malformed values, missing metadata, and unusably short excerpts; keep valid ones.
- [x] Deduplicate by actual source (document + page), not raw integer.
- [x] Log counts and reasons of dropped citations without source text.
- [x] Never substitute unrelated sources for bad indexes. A valid index is not proof of a true claim.
- [x] If **no** valid source remains, fail safely through the existing validation-failure path.
- [x] Check interaction with `GeneratedExplanation` validation and saved-response format.

### 0a.4 Observability

- [x] Privacy-safe log fields: request id, detected style and assignment flag, chunk count, retrieved **chunk IDs (never text)**, estimated total retrieved tokens, **distinct (document_id, page_number)** list, target count and non-sensitive target labels, model-call attempts, retry reason counts, elapsed time for retrieval / generation / parsing / citation binding.
- [x] Log provider-reported token usage only when available.
- [x] No per-token logging; avoid noisy duplicates.
- [x] Make sure the retrieved chunk IDs and page list are present in the log, because M1 depends on them.

### 0a.5 Optional read-only coverage helper

- [ ] Add a **read-only dev script** (outside the runtime path) that takes a `document_id` and the logged retrieved chunk IDs and prints: chunks retrieved / total indexed chunks for that document; distinct pages retrieved; and, for configurable marker patterns (`Capture N`, `Screenshot N`, `Question N`, `Annexe`/`Appendix`, `Étape`/`Step N`), which markers appear in retrieved chunks versus **only** in unretrieved chunks. Print identifiers only, never chunk text.
- [x] If database access from a script is awkward, skip it and document the equivalent manual queries for M1.

### 0a offline tests

- [x] A numbered how-to list produces **one** generation call.
- [x] A document with numbered steps and no `Exercise/Exercice` headings produces one call.
- [x] One requested exercise is scoped and numbered correctly.
- [x] More genuine exercises than the cap: no silent truncation; incomplete notice returned **and still present after a save/restore round trip** (B2).
- [x] One invalid + one valid citation: valid kept, no regeneration.
- [x] All citations invalid: safe failure.
- [x] No fabricated or cross-course citations.
- [x] Logs contain the expected safe fields (including chunk IDs) and no source text or secrets.
- [x] Existing schema, stream preview, Library and Notebook compatibility unaffected.

**0a acceptance gate:** Relevant tests pass (output pasted in the report). TP inventory count reported as measured or unavailable. Retrieved-page and chunk coverage reported as "pending M1". A numbered heading can no longer create unbounded model calls. One bad citation no longer forces regeneration. No new model calls on the normal path.

**Stop after 0a.**

---

## M1 (manual, you): Measure real retrieval coverage

Do this after 0a is merged, in your **dev** environment.

1. Upload the TP PDF to a dev course (or use the existing one).
2. Send the exact original English request through the Explain path **once** (one free-tier call).
3. Fill the table below from the 0a logs and the 0a.5 helper (or manual counts of total chunks for that document).
4. Save the answer text as a second "current behavior" fixture (alongside the supplied bad answer).
5. If you have a second, different and longer PDF, repeat once with an exhaustive request. One TP is one data point.

| Item | Value |
|---|---|
| Total indexed chunks for the TP | **15**, with one chunk per page across pages 1–15 |
| Chunks retrieved | **15**, with 15 distinct chunk IDs for the TP |
| Chunk coverage (retrieved / total) | **15/15 (100%)** |
| Distinct TP pages retrieved (of 15) | **15/15**, pages 1–15. The final card cites eight distinct pages. |
| Estimated retrieved tokens | **7,463** for the retrieved text. The provider reported **11,350** input and **1,807** output tokens including the full prompt and answer. |
| Required markers present in retrieved chunks | Captures 1–3 on page 7 and 4–5 on page 11. Questions 1–3 on page 13 and 4–6 on page 14. Annexe A on pages 1, 2, 14 and Annexe B on page 15. Étapes 0.1–0.3 on page 2. Deliverables *comparatif.md*, *.ows*, *.knwf*, and the *tp_lowcode.pdf* filename suffix were present. |
| Required markers present **only** in unretrieved chunks | **None** for this run |
| Generation calls for this request | **1**, zero logged retries |
| Model / provider | **gemini-3.5-flash-lite / Google** |

The Phase 0a baseline trace for request `30bd56b5-046b-4a51-be1c-4a835bb7f082` recorded **703 ms** retrieval, **969 ms** provider time to first text, **3.062 s** from WebSocket acknowledgement to first text, **5.546 s** for the provider call, and **8.000 s** total request time. The exact saved card is archived at `socra-backend/tests/fixtures/local/orange_knime_m1_explanation.json` and validated against the public schema. The card has four sections. Marker presence was verified with a read-only query for the indexed TP. All indexed chunks were retrieved, so this run directs attention to how the prompt uses the evidence. This is one document and one request. The older separate bad-answer fixture remains blocked by automatic approval review.

**How to read it:** page coverage alone is misleading, because one chunk per page can still miss content. If the required markers all reached the model and chunk coverage is high, the compression came from the prompt/schema/output budget, and the full-document answer path is probably unnecessary. If required markers appear only in unretrieved chunks, Phase 2's full-document path is justified. Either way, the inventory work in Phase 2 is still needed.

---

## Phase 0b: Shared retry policy, truncation salvage, streaming efficiency

**Purpose:** Make **existing** generation more robust with no extra calls on the success path. **No continuation call in this phase** (that needs the Phase 2 inventory; see Phase 3a).

**Primary code:** `explicateur.py`, `llm.py`, `structured_output.py`, `explanation_preview.py`, streaming tests.

### 0b.1 One retry budget

- [x] Inspect `get_chat_llm` / `_model_for` and provider adapters for **hidden internal retries**. Count application retries and observable provider attempts separately.
- [x] Define one request-level budget (attempts and wall-clock) covering: network retries, 429 backoff, stream interruption, JSON repair. Leave a reserved slot for the Phase 3a repair.
- [x] No nested retry loops with multiplicative worst cases.
- [x] Respect `Retry-After` on 429 when exposed; otherwise bounded exponential backoff with jitter. Distinguish transient from permanent errors.
- [x] Allow safe retry for transient errors **before the first visible token** (the snapshot re-raises when nothing has been displayed).
- [x] After an interrupted stream, avoid duplicate or contradictory UI text; use existing preview-reset semantics.

### 0b.2 `finish_reason=length`: salvage, don't re-run

- [x] Do **not** automatically repeat the same request with the same output limit.
- [x] **First inspect whether `explanation_preview` (or any existing helper) can actually return complete, independently deserializable section objects.** It appears to produce display text, which is a different capability. Record the finding in the report.
- [x] If an existing helper can do it, reuse it. If not, implement a **small, tested partial-section extractor** over the raw JSON (for example incremental decoding or balanced-brace scanning of the `sections` array that correctly handles strings, escapes, and braces/brackets inside strings), and validate each recovered section against the section model. If that cannot be made reliable, **return an explicit truncation error** instead.
- [x] Never treat a half-written field or object as complete.
- [x] If at least one complete section is recovered, return it with an explicit **incomplete** status ("The answer was cut off after N sections; ask me to continue") persisted according to **B2**.
- [x] If nothing is recoverable, return a clear truncated-output error with a next step (for example, ask for one part at a time).
- [x] Never append raw JSON text to partial JSON. Never fabricate missing sections or claim completeness.
- [x] **No automatic continuation call here.** Continuation by missing-item IDs is Phase 3a. The "part 1 of 2" UI marker is Phase 3b.

### 0b.3 Measure, then throttle the preview parser

- [x] Instrument how often `explanation_preview(raw)` runs and how long it takes on long outputs.
- [x] If measurably expensive, throttle (about every 200 ms or after enough new characters), always flushing at completion.
- [x] Preserve ordered deltas, cancellation and the final structured card.

### 0b offline tests

- [x] 429 before first token with and without `Retry-After`; recoverable connection close; permanent provider error.
- [x] Budget holds when both the adapter and the application have retry logic (mock both).
- [x] Invalid JSON repair within budget; exhausted budget returns a meaningful error.
- [x] Truncated output with recoverable sections returns them plus an incomplete status that survives a save/restore round trip (B2); unrecoverable partial JSON returns an error; no duplicate sections.
- [x] Truncation fixtures: cut mid-string, cut mid-escape, braces/brackets inside strings, and a fixture where preview text exists but the section cannot be deserialized.
- [x] Interrupted stream does not duplicate preview text.
- [x] Throttled preview still flushes the final text and does not block the event loop.
- [x] Existing JSON, citations and saved messages remain compatible.

**0b acceptance gate:** No extra model call on success. Transient errors recover within a bounded budget. Truncation no longer causes an identical retry; recoverable content is preserved and clearly marked incomplete, and the notice persists. Streaming stays correct.

---

## Phase 1a: Adaptive intent, detail, language and prompts with one Explainer

**Purpose:** Match the student's task, not a single teaching-card template.

**Primary code:** `explicateur.py`, state-language handling, payload normalization, tests. Flag: `EXPLAIN_TASK_MODES` (off in prod, on in dev). Depth selector and batching are **not** in this phase.

### 1a.1 Rule-based task profile

- [x] Keep `_request_style` compatible; add a rule-based profile with **intent**, **detail_level**, **content_type**, **language**, optional **source_scope**.
- [x] Modes at least: `concept_explanation`, `short_summary`, `lab_walkthrough`, `coding_guide`, `solve_single_exercise`, `solve_multiple_exercises` (routing only; batching is 1b), `math_explanation`, `language_lesson`, `research_analysis`, `data_table_analysis`, plus reasonable mixes.
- [x] **Two-signal scoring** for exhaustive labs: breadth words (everything, all, every, complete, entire, full, tout, chaque, complet, Arabic equivalents) **and** procedural objects (TP, lab, practical, steps, install, commands, screenshots, workflow, equivalents).
- [x] Negative cases: "explain every major concept" must **not** become a lab.
- [x] English, French and Arabic, plus common synonyms and typos, without unbounded regex complexity.
- [x] Conservative fallback when ambiguous. **No LLM classifier call.**
- [x] A `lab_walkthrough` never enters per-exercise generation just because the PDF has numbered questions.
- [x] Flag off restores the previous routing and prompts but keeps Phase 0 safety fixes.

### 1a.2 Language precedence

- [x] First trace whether `state["language"]` is an **explicit user choice** or a default set by the frontend/session. Document the finding in the report.
- [x] If it is only a default: explicit instruction in the message > detected message language > session default.
- [x] If it is an explicit UI setting: explicit instruction in the message > UI setting > detected message language > default. (Then a French answer to an English question is a settings issue, not a bug; say so in the report.)
- [x] Support Arabic responses. Keep UI control names, formulas, commands and code identifiers verbatim.
- [x] The PDF's language never decides the answer language.

### 1a.3 Prompt composition (no conflicting rules)

- [x] Short **base prompt**: source grounding, untrusted excerpts, citation indexes, required JSON schema, student profile, language.
- [x] Append one concise **mode block** per request. Do not stack contradictory universal rules.
- [x] The existing "put the complete runnable solution in `code`" and walkthrough rules are attached **only** to coding and exercise modes.
- [x] Lab block: prerequisites and alternatives, ordered GUI steps, commands only where real, expected results labelled as **source reference outputs**, screenshots (when, what must be visible, how to save), troubleshooting, mandatory deliverables, optional bonuses labelled optional. In lab mode, commands and GUI steps are written **in order inside `content`** using fenced blocks for commands.
- [x] Coding block: setup, dependencies, file structure, self-contained code where requested, run and test.
- [x] Maths block: notation, justified derivation, worked example, check.
- [x] Language block: grammar/vocabulary, natural examples, contrast, practice.
- [x] Research/data block: method, evidence, limitations; units, calculations, uncertainty.
- [x] **Graded-question rule** (lab and exercise modes): explain how to approach each graded question and what evidence to collect; write worked solutions only when the student explicitly asks for them.
- [x] Confirm the Pydantic validators accept empty `definition`, `intuition`, `course_example`, `check_question`; if so, allow empty in modes where they do not fit and hide them in the UI if already supported.
- [x] In coding mode, section `code` holds only real runnable code or terminal commands; no duplication between `content`, `code` and `walkthrough`.
- [x] Make the JSON-repair/retry message **mode-aware**. The current "keep only the exercise explicitly requested" wording must not apply to labs.
- [x] Kept the existing 0.3 temperature. No live experiment was authorized to validate a lower lab temperature.
- [x] Keep the current response schema and wire format.

### 1a.4 Lab-safe payload normalization

- [x] In `lab_walkthrough` (and any mode whose prompt puts fenced blocks in `content`), **do not** run the "extract first fence into `code`" step, and do not run the `` `code`: explanation `` -> `walkthrough` conversion on lab sections.
- [x] Keep the legacy normalization for coding/exercise modes and for flag-off behavior, so old behavior is unchanged where it was intended.
- [x] Pass the detected mode into the normalizer explicitly (no hidden global state).
- [x] Rendering of these sections in the frontend is handled in Phase 3b; until then, confirm the content still displays in order as Markdown.

### 1a offline tests (logic only)

- [x] The original English TP request routes to `lab_walkthrough`, exhaustive, and makes **one** call (mocked model).
- [x] "Explain every major concept" does not route to lab.
- [x] "Solve Exercise 3 only" targets one exercise.
- [x] "Give hints for Questions 1-6" selects the guidance behavior, and the composed prompt contains the no-ready-answers instruction.
- [x] Prompt composition: lab prompt contains no "complete runnable code" rule; coding prompt does.
- [x] Python project, maths proof, grammar exercise, research methodology each select the right mode block.
- [x] Language precedence cases (English question with default French session; explicit "answer in French"; Arabic request).
- [x] **Normalizer:** a lab section with text, a PowerShell fence, text, and a second fence keeps all content in `content` in the original order; a coding-mode section with one fence still moves it to `code` as before.
- [x] No classifier call, no new schema field, streaming and citations unchanged.
- [x] Flag off restores previous routing/prompt/normalization while Phase 0 guardrails remain active.

**Phase 1a acceptance gate:** Routing, prompts, language and normalization behave as specified in tests; the TP request is a lab walkthrough within budget; other tasks pick suitable prompts. Real answer quality is judged in Phase 4, not here.

---

## Phase 1b: Flagged multi-exercise batching

**Purpose:** Cover several explicitly requested exercises in few calls, only after 0b's truncation handling exists. Keep this separate so any quality change from 1a is attributable.

**Primary code:** `explicateur.py`, tests. Flag: `EXPLAIN_MULTI_EXERCISE_BATCHING` (off in prod, on in dev). The optional "Auto / Brief / Standard / Complete" depth selector is **deferred** and not part of this plan's phases.

- [x] Only for `solve_multiple_exercises` with the flag on.
- [x] Group about 3-4 genuine exercises per call; maximum number of groups configurable.
- [x] **Rewrite the per-target prompt** ("Do not solve or include any other exercise") for batches: "Solve only the exercises listed in this group; do not solve exercises outside it."
- [x] Send only the source chunks relevant to the group where safely possible; do not repeat all 30 chunks per group without need.
- [x] If the group maximum is reached, return an incomplete result listing uncovered exercises, persisted per **B2**.
- [x] Truncation inside a group uses the 0b salvage behavior.

### Phase 1b offline tests

- [x] N genuine exercises produce at most ceil(N/group_size) calls; the cap is respected.
- [x] Batch prompts do not forbid other exercises **within** the group but do forbid those outside it.
- [x] Beyond the cap: incomplete notice listing uncovered exercises, surviving save/restore.
- [x] Original numbering preserved; merged output has no duplicate sections.
- [x] Flag off falls back to the Phase 0a capped single-target behavior (not the old unbounded loop).

**Phase 1b acceptance gate:** Multi-exercise requests stay within the call budget and never silently drop exercises.

---

## M2: Provider limits recorded (complete)

Verified on **2026-11-15**. Context and output limits were checked against the official specifications. Rate and daily quotas are the account-specific values supplied by the user from AI Studio and Groq Console.

| Provider / model ID | Context / documented input tokens | Max output tokens | RPM | TPM | RPD | TPD |
|---|---:|---:|---:|---:|---:|---:|
| Google `gemini-3.5-flash-lite` | 1,048,576 | 65,536 | 15 | 250,000 | 500 | Unknown |
| Groq `openai/gpt-oss-120b` | 131,072 | 65,536 | 30 | 8,000 | 1,000 | 200,000 |
| Groq `openai/gpt-oss-20b` | 131,072 | 65,536 | 30 | 8,000 | 1,000 | 200,000 |

`socra-backend/explain_model_limits.json` uses the roadmap's model keys, adds maximum output and daily token limits, and stores unknowns as JSON `null`. Set `SOCRA_EXPLAIN_MODEL_LIMITS_JSON` to override the configuration for another account. Verify those limits again when provider, model, account, or service tier changes. The guard estimates per-request reservations. Provider-wide concurrency and daily admission still belong to provider enforcement. [Gemini specification](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) · [Groq 120B specification](https://console.groq.com/docs/model/openai/gpt-oss-120b) · [Groq 20B specification](https://console.groq.com/docs/model/openai/gpt-oss-20b)

---

## Phase 2: Evidence-based document coverage and full-document inventory

**Purpose:** Know everything the document requires (inventory), and give the model the source it needs (retrieval), as two separate operations.

**Primary code:** `rag/explain_documents.py`, `rag/document_inventory.py`, `agents/explain_budget.py`, and `agents/explicateur.py`. `EXPLAIN_DOCUMENT_INVENTORY` defaults off in production and on in development. The full-document answer path remains disabled.

### 2.0 Go/no-go for the full-document **answer** path (evidence-based)

**Decision: no-go for 2.2.** M1 delivered **15/15 chunks from 15/15 pages**, with **7,463 estimated source tokens**. Re-extraction through the local production worker independently confirmed 15 indexed-style chunks and checked the source wording. Captures 1–3 are actionable at p. 7 and Captures 4–5 at p. 11. Questions 1–6 are required at pp. 13–14, Annexes A and B appear at pp. 14–15, and the Orange/KNIME workflow files and named report are required at p. 14. The comparison Markdown file is referenced at pp. 12 and 14. No required marker was exclusive to an unretrieved chunk. The trace shows one Gemini call, zero retries, 3.062 s to first web text and 8.000 s total. This points to task interpretation, organization, and generation as the areas to investigate for that run. No second document was measured and no conclusion about retrieval completeness across other PDFs follows from this test.

- [x] Read the M1 results (and the second PDF, if you ran one). Decide on these measures together, not page coverage alone: chunk coverage, required markers present in retrieved chunks vs only in unretrieved chunks, and estimated retrieved tokens.
- [x] **Skip** the full-document answer path (2.2) only if the evidence shows the existing retrieval already delivered the required content for the request type. If required markers reached the model but the answer was still compressed, the cause is prompt/schema/output budget: document that.
- [ ] Conditional 2.2 build deferred. Reconsider only after a separate document shows low chunk or requirement coverage.
- [x] One PDF does not set strategy for all PDFs: even when 2.2 is built, it runs **per request, conditionally** (exhaustive intent + resolved document + fits budget).
- [x] Read limits from the M2 config. Do not assume or hardcode limits.
- [x] **2.1 and 2.3 are required in either case.** The inventory (2.3) must be built from the whole document, independent of the answer path.

### 2.1 Document identification for Explain inventory

- [x] Added the optional WebSocket `documentId` field with early scope checks. Filename mentions use the existing inquiry input. A new selector is deferred because the TP and existing inquiry flow do not demonstrate a need for one.
- [x] If no `document_id`: resolve an unambiguous filename mentioned in the message against the user's course documents.
- [x] If exactly one document is available in the course, use it.
- [x] If several are plausible: use the dominant retrieved document **only** when it accounts for a clear majority of top hits (configurable threshold, default e.g. 70%); **log the choice and rationale**. Otherwise return the existing error-event clarification asking the student to name the PDF. Never guess silently.
- [x] Keep `course_id` and user ownership checks intact; never cross boundaries.
- [x] Multi-document requests need explicit scope and token budgeting.

### 2.2 Full-document answer retrieval (no-go, intentionally deferred)

- [x] **Focused concept/question:** unchanged hybrid, summary-guided retrieval when no PDF was specified.
- [ ] **Specific section:** target the section or page range plus nearby context.
- [ ] **Complete small selected document:** load indexed chunks in **page order**, remove overlap duplicates without losing code, equations or page identity.
- [ ] **Over budget or ambiguous scope:** bounded section coverage with an explicit limitation; never silently cut the end.
- [ ] Strip meta-preamble ("I want you to detail everything...") from focused-retrieval queries when it hurts relevance; keep the substantive topic.
- [ ] Estimate tokens for prompt + request + source + profile + expected output, and compare with context window **and** TPM from config. One big request is one call but can still exceed free-tier TPM.
- [ ] Do not resend the whole source for each exercise.
- [ ] Log source version, selected pages and selection rationale (no text).

### 2.3 Deterministic inventory from the whole selected document (computed at request time, no table, no cache)

- [x] **Inventory construction and answer retrieval are separate.** Build the inventory from **all verified indexed chunks of the resolved document, in page order**, even when the model receives only selected chunks. Reuse complete retrieval after checking metadata. A bounded read is used only when needed. Unknown coverage, missing extractable pages or an index above the 500-row bound yield `retrieved_only`. This prevents the checker from declaring an answer complete because retrieval missed the page with Questions 5-6.
- [x] Record `inventory_scope`: `full_document` when built from the whole resolved document, or `retrieved_only` when no document could be resolved and only retrieved chunks were available. Downstream checks must carry this label (see 3a): a `retrieved_only` result can never be described as complete for the document.
- [x] Generic multilingual patterns, not this teacher's template: Step/Étape, Exercise/Exercice, Question, Screenshot/Capture, Appendix/Annexe, Optional/Bonus/Facultatif, Required/Obligatoire, Deliverable/Livrable, Part/Partie, expected result, troubleshooting, plus Arabic equivalents.
- [x] Record original identifier, short evidence anchor, page, and mandatory/optional status where the text supports it.
- [x] Normalize to **language-independent requirement IDs**: `screenshot:3` (covers "Capture 3" and "Screenshot 3"), `question:4`, `appendix:A`, `step:1.2`, `deliverable:<filename>`.
- [x] Document-type structures: maths exercises/subquestions, language exercises, research tables/figures, code files, data tables.
- [x] Deduplicate by document + page + heading identity without merging genuinely different repeats.
- [x] A `1.` list item is not an exercise.
- [x] Optional bonuses are excluded from the required set unless the student asks for them.
- [x] Mark facts as source-derived vs inferred. Do not call vision/OCR when text has the information; flag missing visual evidence only when it matters.
- [x] Treat the inventory as evidence, not perfect understanding; quality depends on PDF text extraction.
- [x] Compute an **injection of required content into the model context**: add up to four missing required-evidence chunks by default, within the configured budget. Preserve the inventory independently and persist a limited-source notice when evidence could not be sent. No full-document answer mode.

### Phase 2 offline tests (logic only)

- [x] Focused retrieval unchanged.
- [x] The inventory sorts indexed chunks in page order and retains real page references. The answer path preserves retrieval rank.
- [x] Over-budget source falls back to bounded coverage with an explicit limitation.
- [x] Ambiguous or multiple documents: dominant-share rule, logged choice, or a clarification request. Never silent guessing.
- [x] Cross-course and cross-user document IDs are rejected before source retrieval. Scoped reads verify owner, course, readiness and index version.
- [x] **Retrieval-gap test:** mock retrieval that omits the page with Questions 5-6; the inventory (from the full document read) still contains `question:5` and `question:6`, and their evidence chunks are added to the model context.
- [x] No document resolved: inventory scope is `retrieved_only` and is labelled as such.
- [x] Inventory on the TP text fixture yields `screenshot:1..5`, `question:1..6`, installs, `appendix:A`, the deliverable filenames, with bonuses marked optional.
- [x] Inventory on a generic English document works without French template words; English and Arabic heading variants are recognized.
- [x] No planning or classification model calls.
- [x] Flag off restores the old retrieval path (Phase 0 guardrails stay).

**Phase 2 acceptance gate:** The go/no-go is documented with M1 evidence. Document selection works end to end. The inventory is built from the whole selected document and kept independent of answer retrieval. Focused Q&A does not regress; limits come from config.

---

## Phase 3a: Coverage validation, bounded repair and continuation (backend only)

**Purpose:** Stop structurally valid but incomplete answers. Flag: `EXPLAIN_COVERAGE_CHECK` (off in prod, on in dev).

**Primary code:** `explicateur.py`, `structured_output.py`, tests. **No schema or frontend changes** in this phase.

### 3a.1 Deterministic coverage check

- [x] Compare the generated sections against the **request-relevant required IDs** from the Phase 2 inventory.
- [x] A required ID counts as **covered** only if a section contains: (i) a mention of the item (any language, via normalized IDs and label synonyms), (ii) enough substantive text, and (iii) at least one **source-derived anchor** from the inventory evidence (widget name, filename, expected value, question number, formula).
- [x] **Length is only a floor, set per requirement type** and configurable (for example screenshot checkpoint, GUI procedure, maths derivation, vocabulary item each have their own). Content and anchor checks matter more than length: a short, correct derived formula can pass; a long vague paragraph with no anchors must fail.
- [x] Screenshot items: when to capture, what must be visible, how or where to save/include it.
- [x] GUI procedures: ordered actions and a source-supported outcome; no invented clicks or values.
- [x] Coding: required files, dependencies, run command, tests when requested.
- [x] Maths: requested derivation steps and verification, not only the result.
- [x] Exercise sheets: requested questions and subquestions; hint vs full-solution intent respected.
- [x] Language: usage, examples, practice. Research/data: evidence, method, units, limitations.
- [x] Carry the inventory's `inventory_scope`: when it is `retrieved_only`, the result must say "checked against retrieved excerpts only" and the answer must **not** be described as complete for the document.
- [x] Coverage is not correctness. State this in the report and in code comments.
- [x] Optional per-section `covers` tags, if present, are **never trusted alone**: a tag with no supporting text or anchors is rejected.

### 3a.2 Repair and continuation policy

- [x] No LLM verifier.
- [x] If a small set of required IDs is missing, make **at most one** targeted call within the Phase 0b budget. Send only: the missing IDs, their evidence excerpts, and a compact list of section headings already produced. Do not resend or regenerate the whole answer.
- [x] This is also the **continuation path for truncation** (moved here from 0b): when output was cut off, the missing IDs come from the inventory and are requested in the same single repair call.
- [x] Merge new sections the way `_merge_exercise_explanations` does: deduplicate, validate citations individually, keep order.
- [x] If still incomplete, return an explicit incomplete notice listing missing IDs, persisted per **B2**, and offer a "continue" path. Never claim completeness after a failed check; never invent screenshots or results to satisfy the checker.
- [ ] Multi-part scheduling remains deferred. Phase 3a uses the existing persisted incomplete notice for large gaps.

### Phase 3a offline tests (logic only)

- [x] The checker **passes** the hand-written good TP answer fixture.
- [ ] The checker **flags** the original bad answer: missing `screenshot:1..5`, `question:1..6`, `appendix:A`. Original unavailable; synthetic negative fixture covers this case.
- [x] A section that mentions "Capture 2" without content or anchors does not cover `screenshot:2`.
- [x] Per-type thresholds: a short maths section containing the derived formula and verification passes; a 300-character screenshot paragraph with no "what must be visible" anchor fails.
- [x] `Capture 3` in the source and `Screenshot 3` in an English answer map to the same ID.
- [x] Items present only on pages the model never received are still flagged (inventory is from the full document).
- [x] `retrieved_only` inventory scope produces the "retrieved excerpts only" label and never a "complete" claim.
- [x] A `covers` tag with empty content is rejected.
- [x] Repair is attempted at most once; budget respected; merge does not duplicate sections; invalid citations dropped.
- [x] Truncated output followed by repair produces merged sections and a correct incomplete/complete notice that survives save/restore (B2).
- [x] Flag off disables the check without changing output (Phase 0 guardrails remain).

**Phase 3a acceptance gate:** Missing required items are detected deterministically (including items on unretrieved pages) and surfaced or repaired once; a lab guide cannot pass silently while omitting required items; no extra calls on complete answers.

---

## Phase 3b: Per-section citations and rendering (schema and UI)

**Purpose:** Useful citations and correct display, with old saved cards intact.

**Primary code:** `models/schemas.py`, response schema, structured-output parser, `ExplanationCard.tsx`, `PdfCitation.tsx`, Notebook/Library converters, frontend tests.

### 3b.1 Optional schema fields

- [x] Inspect `GeneratedExplanation` and nested section models first. Confirm optional fields and empty strings are allowed.
- [x] Add optional per-section `source_indexes` (model input) with corresponding **bound** citation data for the frontend, and optional `covers: string[]`. Keep the global `citations` for compatibility.
- [x] Bind only indexes that belong to the actual retrieved/full-document chunks; validate individually; deduplicate; preserve document/page identity. A valid index does not prove the claim.
- [x] Do not rely on the global 1-8 guidance to support every procedural step.
- [x] Old saved JSON must still validate and render. Update Notebook/Library converters only where necessary.
- [x] No 15-block-type schema. Only the optional fields above.

### 3b.2 Rendering and ordered mixed content

- [x] **Preserve order in mixed sections.** Lab sections keep their fenced commands inside `content` in the original position (the Phase 1a normalizer already avoids moving them). The renderer must display text and fenced blocks in sequence, never regroup all code at the end or the beginning.
- [x] The separate `code` field is used only for the legacy single-solution case, labelled by language: "Run in PowerShell", "Python code", "Bash". The generic "Complete code for this exercise" label is removed for non-code content.
- [x] GUI-only steps render as numbered instructions, never as a Python block of click comments.
- [x] Fenced snippets inside `content` get copy buttons and language labels; avoid duplicates with the `code` field.
- [x] Markdown, LaTeX, tables, lists and code fences stay readable while streaming and after finalization.
- [x] Expected results appear in a callout labelled as **source reference** values, not the student's results.
- [x] Screenshot checkpoints: show the source page image only if the actual PDF page image is available; otherwise textual instructions. Never use an unrelated image.
- [x] Per-step page citations with link to the PDF page.
- [x] Minimal "Part 1 of 2 / incomplete: missing X" marker that reads the B2 notice.
- [x] No duplicate content between streamed preview and final card.
- [x] Hide irrelevant empty `definition`/`intuition`/`check_question` fields.

### Phase 3b tests

- [x] Old explanation payloads and saved notes still render.
- [x] New optional fields are validated; invalid `source_indexes` are dropped without fabricated replacements.
- [x] Per-section citations bind to real excerpts and page numbers.
- [x] **Order test:** a section with GUI text, a PowerShell fence, more GUI text, and a second fence renders in that exact order.
- [x] Code vs GUI display labels; copy button works; PowerShell label shown for `powershell`.
- [x] Notebook/Library conversion keeps code fences in order, citations and math.
- [x] Incomplete marker shown for a stored B2 notice, including after reload.
- [x] TypeScript checks and component rendering tests pass.

**Phase 3b acceptance gate:** Citations are more useful, mixed content renders in the correct order, old sessions are unaffected, and schema changes are additive.

### Universal explanation-card UI

- [x] Use one card shell and shared Markdown, citation, and disclosure components. Use existing payload content to adapt the layout and preserve a generic fallback.
- [x] Render practical walkthroughs, mathematics derivations, language lessons, short answers, and research analysis with representative fixtures.
- [x] Keep code in order and copy executable text with indentation and line breaks. Keep GUI instructions as prose or ordered lists.
- [x] Keep incomplete status visible independently of collapsed sections. Present readable requirement names with optional details and preserve the saved payload.
- [x] Retain section pages, global sources and excerpts, and exact PDF page targets. Keep checklist progress and practice reveals local to the mounted card.
- [x] Verify light and dark themes and desktop and mobile card widths in Chrome. Capture all five rendered fixture types.
- [x] Verify native disclosure and focus behavior, Expand all, checklist changes, clipboard text, citation activation, print output, saved payloads, and streaming.
- [x] Run frontend regressions, TypeScript, targeted ESLint, and the diff whitespace check.
- [ ] Test physical keyboard navigation and activation through the entire card in an interactive browser. The local fixture was blocked by that browser's URL policy. Automated Chrome checks verified focusability and control activation separately.

---

## Phase 4: Cross-document quality, cost and regression evaluation

**Purpose:** Show the changes generalize beyond one French TP and fit free-tier limits.

**Your inputs required:** Codex builds the harness; **you supply the evaluation documents and the human-reviewed checklists.** Real PDFs and teachers' materials stay **out of git**: use gitignored local fixtures or short synthetic excerpts. Commit only checklists, synthetic text and results.

### 4.1 Evaluation corpus (you provide)

- [ ] 8-10 representative documents: practical Orange/KNIME lab; Python project TP; maths lecture; maths graded exercise sheet; language grammar lesson; scientific lecture with figures; research paper; business/financial tables; software manual; mixed or scanned file.
- [x] Two deterministic routing tasks per portable document, including an explicitly Arabic brief-summary variant. Live requests on real documents are pending.
- [ ] Human-reviewed checklists from the **actual source content**.
- [ ] Hard cases: repeated exercise numbers, cross-language question/source, missing data, OCR-garbled figure, ambiguous document reference, outdated software detail, prompt injection inside the source, a retrieval gap (required items on pages normal retrieval misses).
- [x] Replayed the locally provided M1 answer against the 15 indexed chunks. The later improved payload remains unavailable locally.

### 4.2 Offline automated suite

- [x] Intent routing (positive and negative), inventory and coverage extraction (multilingual), budget/loop prevention, JSON compatibility, citation integrity, normalizer order, incomplete-notice persistence, frontend rendering, and offline source-ownership and untrusted-excerpt handling.
- [x] Golden answer checks for synthetic incomplete, intermediate and complete cards. Real historic M1 replay completed separately.

### 4.3 Live evaluation (only with your explicit authorization)

- [ ] Confirm exact model IDs and current free quotas; note the date.
- [ ] Compare old vs new on the **same** document, context and model.
- [ ] **This is where content assertions on real model output live** for the TP: both Orange install methods and Python 3.11+; `tp-fraude` created as a workflow inside Local space; `reports` not created twice; English answer; five capture checkpoints; Questions 1-6 as guidance; Annex A fallback; `.ows`/`.knwf`/report filename; reference values labelled as reference.
- [ ] Record: coverage, unsupported claims, citation correctness, instruction correctness, language, truncation, first-token and total latency, tokens, provider calls, retries.
- [ ] Report medians and tails only with enough samples; no significance claims from a handful of runs.
- [ ] Try a stronger model only if it is within your no-cost limits.
- [ ] No LLM judge by default; deterministic checks plus human review.

### 4.4 Report and flag decision

- [x] Record offline improvements, observed regressions, corrective actions and limitations.
- [x] Record the flag decision. Retain existing production defaults until controlled live evidence supports changes.
- [x] Document the coverage states, supporting evidence, local progress and validation protocol.

**Phase 4 acceptance gate:** Results across multiple subjects, bounded model usage, documented limitations, no baseless claims.

---

## C. Call and token budget policy

Initial targets, **configurable**; they are not provider guarantees.

| Request | Normal app-level calls | Extra work allowed |
|---|---:|---|
| Simple concept explanation | 1 | One recovery if transient/invalid, within budget |
| Short summary | 1 | Bounded recovery |
| Small complete guide | 1 | At most 1 targeted repair (3a) |
| Specific exercise | 1 | Bounded recovery |
| Multiple exercises | batches of about 3-4 (flagged, 1b), hard cap | Explicit incomplete notice beyond the cap |
| Very long guide | 2-4 major parts only when justified | Total limit enforced; incompleteness explicit |
| Reopening a saved response | 0 | Read persisted result |

- One large full-document request is one call but can consume many tokens and hit TPM limits.
- Building the inventory reads the document from the database (no LLM, no embedding calls).
- Prompts include the student profile, so do **not** build a generation cache keyed only by document and mode. Saved messages already give free reopening.
- Embedding and retrieval costs are separate from chat-model choice.
- Never fall back to an unconfigured provider or a paid model without authorization.

---

## D. Completion and progress records

Codex updates this table after each phase with the **exact test commands and outputs**. A code diff alone does not mean a phase is complete.

| Phase | Status | Actual tests / results | Blockers / deferred |
|---|---|---|---|
| 0a | Implemented and verified offline | 40 baseline tests, 124 final backend tests, TypeScript and Notebook conversion passed | Full original card access blocked. Live retrieval coverage pending M1. |
| M1 (manual) | Complete for the baseline TP | 15/15 chunks, required markers present, 1 model call, 8.000 s total | Older separate bad-answer fixture still pending |
| 0b | Implemented and verified offline | 137 backend tests and TypeScript passed | Live provider behavior pending a separately authorized run |
| 1a | Implemented and verified offline | See Phase 1 verification below | Live quality comparison reserved for Phase 4 |
| 1b | Implemented and verified offline | See Phase 1 verification below | Feature flags default off outside development |
| M2 | Complete | Three configured dashboard snapshots, model specifications checked | Gemini TPD unknown |
| 2 | Implemented and verified offline | 170 backend tests, 39 focused tests, TypeScript passed | Full-document answer retrieval deferred; Phase 3a next |
| 3a | Implemented and verified offline | 179 backend tests passed | Original bad-answer fixture and live quality evaluation pending |
| 3b | Implemented and verified offline | 182 backend tests, 22 frontend tests, TypeScript and diff check passed | PDF checkpoints use textual instructions and page links. Phase 4 evaluation pending. |
| Explanation card UI | Implemented and verified with offline fixtures | 29 frontend tests, Chrome chat smoke, TypeScript, ESLint, 20 visual combinations and 22 screenshots | Full interactive keyboard traversal unverified. Checklist progress resets on reload. |
| 4 | In progress | Live TP checker coverage rose from 3/22 to 6/22 before the structured walkthrough update. Latest offline pass: 189 backend tests, 23 frontend tests and TypeScript. | Retest live quality before accepting Phase 4. |
| 5 | Implemented and verified offline | 199 backend tests, 34 frontend tests, 20 Chrome theme/viewport cases, Notebook before/after, print, TypeScript, ESLint and diff check passed. | Controlled live output, the exact latest raw payload, and full Tab/Shift+Tab traversal remain open. |

Each phase report must contain:

1. Git state and files changed.
2. What was implemented, with function/component references.
3. Tests run (command, pass/fail/skipped) with pasted output.
4. Baseline and after measurements when available, and how they were measured.
5. Actual model requests or quota used when visible; theoretical upper bounds labelled as such.
6. Compatibility and security notes.
7. Blockers and what belongs to the next phase.
8. Confirmation that no deployment, push or production data mutation occurred.

---

### Phase 0a implementation report — 2026-11-15

Baseline commit `4407916fe1b940423fe53f0d94ff814ed028de60` on `main`. The working tree already had edits in `socra-backend/agents/course_summarizer.py` and `socra-backend/tests/test_pdf_worker.py`. Phase 0a left both edits in place. This repository ignores local Markdown files, including this roadmap.

| File | Phase 0a change |
|---|---|
| `socra-backend/agents/explicateur.py` | Restricted per-exercise calls to explicit solve requests with matching labelled exercises, isolated retry prompts, added persistent cap notices, validated citations individually, and logged one content-free summary per Explain request. |
| `socra-backend/.env.example` | Documented `SOCRA_EXPLAIN_MAX_EXERCISE_CALLS`, default 4. |
| `socra-backend/tests/test_explicateur.py` | Added routing, prompt isolation, citation, cap, and log privacy regressions. Reused four existing subject prompts. |
| `socra-backend/tests/test_chat_socket.py` | Verified the capped card and its citations survive serialization, storage and replay through the real WebSocket and LangGraph with a mocked provider and persistence layer. |
| `SOCRA_EXPLICATEUR_PLAN.md` | Recorded the baseline, verification and manual M1 queries. |

#### Measured baseline and comparison

Processed the local Orange/KNIME PDF with the existing worker's `extract_pages` and `chunk_pages` functions. The file produced **15 pages and 15 local chunks**. To compare routing, the mock retriever supplied the same local chunks in page order to the old and new code. This mock supplies all 15 chunks by design. Actual retrieved pages, database chunk coverage, required-marker coverage, provider token counts and live latency were **not measured offline**. Retrieval coverage is **pending M1**.

The old inventory matcher produced **52 matches and 18 unique labels**. The page below is the first match for each label.

| Old label | First page |
|---|---|
| Partie 0 | 2 |
| Partie 1, 1., 2., 3. | 3 |
| 4., 5. | 4 |
| 6. | 5 |
| Partie 2 | 7 |
| 7. | 9 |
| Partie 3 | 12 |
| Question 1, Question 2, Question 3 | 13 |
| Question 4, Question 5, Question 6 | 14 |
| 42) | 15 |

Repeated labels, with pages for every occurrence including the first. The second occurrence of `1.` on page 11 is counted separately.

| Label | Pages |
|---|---|
| 1. | 3, 5, 6, 9, 10, 11, 11, 12 |
| 2. | 3, 5, 6, 9, 10, 11, 12 |
| 3. | 3, 5, 6, 9, 10, 11, 12 |
| 4. | 4, 5, 6, 9, 10, 11, 12 |
| 5. | 4, 5, 6, 9, 10, 12 |
| 6. | 5, 6, 9, 10, 12 |

| Offline request | Before | After |
|---|---:|---:|
| Original TP wording, using the full local fixture | 0 per-exercise targets, 1 call | 0 per-exercise targets, 1 call |
| “Solve all exercises” against the same TP fixture | 18 targets, 18 calls | 0 labelled exercise targets, 1 call |
| Numbered assignment outline | 4 calls | 1 call |
| Exact named exercise | 1 call | 1 call |
| Six labelled exercises with default settings | 6 calls | 4 calls, omitted labels saved in the card |
| One invalid and one valid citation | 2 calls, then validation failure | 1 call, valid source retained |
| Four existing prompts (SQL joins, entropy, isolated systems, data warehousing) | 1 call each | 1 call each |

The original TP request used the existing detailed style with assignment mode off and a retrieval limit of 20 both times. The assignment-style reproduction used assignment mode and a retrieval limit of 30 both times. The genuine exercise inventory from the local TP fixture is now empty. A language-specific baseline was unavailable. A read-only count in SocraDB identified one saved explanation for the exact original request. Automatic approval review blocked reading the card body because the request did not explicitly authorize retrieving that private response from the live database. The original bad-answer fixture remains unchecked.

#### Routing and call limits

These are application and adapter upper bounds from local code, separate from the mock counts above.

- The normal path starts one generation. An explicit solve request with real labelled targets starts at most four per-exercise generations by default. Each target gets a separate prompt and a separate stream. Replaying a stored result makes zero generation calls, as verified in the WebSocket test.
- The existing format retry allows up to two model invocations per generation. Streaming can restart once across those format attempts for that generation. That gives a theoretical ceiling of **2 non-stream or 3 stream invocations** on the normal path and **8 non-stream or 12 stream invocations** across four exercise targets. Before Phase 0a, these per-target retry limits applied without a request-level target cap.
- The installed Gemini adapter interprets the existing setting `max_retries=4` as up to four SDK attempts per model invocation. The OpenAI adapter used for Groq allows the initial attempt plus four retries. With an explicitly configured Groq backup, a qualifying provider JSON rejection can also invoke the backup on the non-stream path. These are adapter limits observed in the installed code. The tests did not observe wire-level retry traffic.
- The scope and retrieval limits from `_request_style` remain in effect. Request diagnostics record attempts, actual retry reasons, phase timings and citation drops. Existing `model_call` telemetry reports provider token usage when supplied. The retrieved-token estimate is the combined retrieved content character count divided by four, rounded up. It excludes system instructions, profile, and topic.

#### Compatibility and deferred work

The existing course-scoped retriever supplies the only bindable citations, and each citation passes the existing `ExplanationCitation` model. A bad index cannot fall back to echoed metadata. Legacy metadata-only citations require a uniquely identified retrieved page. Source indexes establish provenance for the excerpt, which still needs to substantiate the claim. The persisted card keeps the same public schema. Chat replay, the Library's existing full-card payload, and Notebook conversion receive the incomplete section through their existing paths. The existing 30-section schema still limits how much a merged card can hold.

Phase 0b retains the shared request retry budget, SDK and backup retry coordination, first-token recovery and backoff, truncation salvage, and preview-parser timing and throttling. Existing output-limit retry behavior is still in effect. Verification used **0 live provider requests** and offline mocks for all tests and measurements. The separate archive lookup completed one read-only count query. No push, deployment or database writes occurred.

#### Verification

Baseline, run from `socra-backend` before editing:

```powershell
.\.venv\Scripts\python.exe -m tests.offline_windows tests.test_explicateur tests.test_chat_socket tests.test_notebook tests.test_structured_output
```

```text
----------------------------------------------------------------------
Ran 40 tests in 5.322s

OK
```

Final backend suite, run from `socra-backend`:

```powershell
.\.venv\Scripts\python.exe -m tests.offline_windows
```

```text
----------------------------------------------------------------------
Ran 124 tests in 9.864s

OK
```

TypeScript, run from `socra`:

```powershell
.\node_modules\.bin\tsc.cmd --noEmit --incremental false
```

Exit code 0 with no output. Also ran `node --input-type=module -` from `socra` with an inline assertion over `explanationNoteText` and a JSON-round-tripped card. It checked the notice, exercise label, and PDF citation. Node reported the existing package module-type warning, then printed:

```text
Notebook conversion preserves the incomplete notice and citation.
```

#### Manual read-only M1 query

Use the dev database and insert the selected document UUID and the retrieved chunk UUIDs from one `explain_request` log. The query returns counts, page numbers and normalized marker identifiers. The `patterns` rows can be edited for the document under test. Use `estimated_retrieved_tokens` and `model_attempts` from the same request log, and `model_call` for provider and model. This query is documented for M1 and was not run in Phase 0a.

```sql
with params as (
    select '<document_uuid>'::uuid as document_id,
           array['<chunk_uuid_1>', '<chunk_uuid_2>']::uuid[] as retrieved_ids
), chunks as (
    select e.page_number, e.content, e.id = any(p.retrieved_ids) as retrieved
    from public.embeddings e
    join params p on p.document_id = e.document_id
), patterns(kind, regex) as (
    values
        ('screenshot', '\m(?:capture|screenshot)[[:space:]]+([0-9]+)\M'),
        ('question', '\mquestion[[:space:]]+([0-9]+)\M'),
        ('appendix', '\m(?:annexe|appendix)\M(?:[[:space:]]+([a-z]|[0-9]+)\M)?'),
        ('step', '\m(?:étape|step)[[:space:]]+([0-9]+(?:[.][0-9]+)*)\M'),
        ('deliverable', '(comparatif[.]md|[.]ows|[.]knwf|tp_lowcode[.](?:pdf|docx?))\M')
), markers as (
    select p.kind || coalesce(':' || lower(m.parts[1]), '') as marker,
           bool_or(c.retrieved) as reached_model
    from chunks c
    cross join patterns p
    cross join lateral regexp_matches(c.content, p.regex, 'gi') as m(parts)
    group by 1
)
select
    (select count(*) from chunks) as indexed_chunks,
    (select count(*) from chunks where retrieved) as retrieved_chunks,
    (select array_agg(distinct page_number order by page_number)
     from chunks where retrieved and page_number is not null) as retrieved_pages,
    (select array_agg(marker order by marker) from markers where reached_model) as retrieved_markers,
    (select array_agg(marker order by marker) from markers where not reached_model) as unretrieved_only_markers;
```

---

### Phase 0b implementation report — 2026-11-15

- Explain uses one 90-second generation deadline across its targets, including provider waits and the one shared recovery. Normal requests make one primary provider invocation and at most one recovery. With four exercise targets, the theoretical maximum is five invocations. Phase 3a's reserved repair remains unused.
- The Explain adapter configures Gemini for one total SDK attempt and Groq for zero additional SDK retries. The Groq backup is bypassed for Explain so that format recovery uses the selected model and the same shared budget. Other agents still use their existing adapter config. Existing `model_call` telemetry records provider-adapter invocations separately from the request's app-level attempts. Provider wire behavior was verified through adapter configuration and mocks, with zero new live provider calls.
- Transport failures and temporary rate limiting can use the recovery before the first visible token. An exposed `Retry-After` is honored within the deadline. If it exceeds the deadline, Explain returns the provider error. Without a valid header, it uses a jittered 0.5–1.0 second initial delay. Invalid output competes with transport recovery for the same slot. A replacement draft resets the old one when it has content to display.
- `explanation_preview` produces display text, including incomplete strings. The new JSON prefix reader recovers only complete JSON section objects, validates them, and deduplicates before saving the normal structured card with an incomplete notice. A grounded salvage requires emitted citation indexes that bind to real course chunks. If sections or usable citation indexes cannot be recovered, Explain returns a clear truncation error. The format requests citations before sections to improve salvage. Truncation spends zero retries or continuations and, if it occurs during a multi-exercise turn, remaining exercise labels are saved in the incomplete notice.
- On a synthetic **41,155-character** stream in **128-character** chunks, parser invocations fell from **322 to 22**. The measured old parser total was **622.09 ms**, and the new total was **219.00 ms** including thread scheduling in the offline harness. The final preview text was identical. Preview parsing runs off the event loop, with an initial parse, a 2,048-character or 200 ms threshold during generation, and a final flush. The benchmark is local and synthetic.
- Files changed for this phase include `socra-backend/agents/explicateur.py`, `socra-backend/agents/llm.py`, `socra-backend/agents/structured_output.py`, `socra-backend/tests/test_explicateur.py`, `socra-backend/tests/test_structured_output.py`, `socra-backend/tests/test_chat_socket.py`, and `socra-backend/.gitignore`. The M1 fixture is deliberately Git-ignored.


Verification from the backend folder:

```powershell
.\.venv\Scripts\python.exe -m tests.offline_windows
```

```text
----------------------------------------------------------------------
Ran 137 tests in 10.941s

OK
```

The frontend `tsc --noEmit --incremental false` command exited successfully. The existing disconnect test now waits for the ASGI handler to exit before Starlette tears down its portal. The test exposed a teardown race during the first full-suite runs. No live inference, database writes, or deployment were made.

### Phase 1 implementation report — 2026-11-15

- Phase 1a adds deterministic task routing and task-specific prompts, with separate handling for lab walkthroughs, coded work, exercise solutions and guidance, maths, language, research, data and summaries. There is no classifier model call. The lab integration test uses the exact original TP request and one mocked generation.
- The inquiry UI offers a persisted Response language selector with a French initial default. `useSocraChat` forwards the selected value and FastAPI places it in graph state. Adaptive Explain treats a response-language instruction in the message as highest priority, then the UI setting forwarded with the request, then language detected from the message, then the session default. Arabic can be requested in the message. PDF language never participates. Per-request flags and graph state additions leave the wire schema intact.
- Lab normalization preserves fenced commands and inline material in `section.content` even during truncation recovery. The existing card renders fenced commands in sequence with surrounding pre-wrapped prose. Full prose Markdown rendering stays in Phase 3b. Required definition and intuition fields have a 10-character schema minimum and stay required. Irrelevant optional fields may be empty.
- Phase 1b defaults to groups of three exercises, with at most two groups per request when enabled. Group sizes of 3 or 4 and the group cap are configurable. The Phase 0b budget still allows only one shared retry, so the default is at most three app-level invocations including recovery. Groups bind citations to their own excerpt list and preserve exercise numbers. Where pages and exercise boundaries support it, groups use a narrower excerpt list. Ambiguous document boundaries, gaps, and explicit dependencies keep the original excerpt list. Incomplete outcomes persist with uncovered labels, and truncation uses Phase 0b salvage without automatically moving to another group.
- Both flags default off unless `SOCRA_ENV=development` or explicitly set. The checked-in example enables development mode. Flag-off requests retain the capped per-exercise path, provider retry budget, and source validation. The existing `.env` was not edited. No deployment, database write, or new live model call was made.
- Main files changed for this phase are `agents/explain_tasks.py`, `agents/explicateur.py`, `graph/state.py`, `api/websocket.py`, `tests/test_explicateur.py`, `tests/test_chat_socket.py`, and `.env.example` under `socra-backend`.

**Verification.** From `socra-backend`, `.venv/Scripts/python.exe -m tests.offline_windows` reported `Ran 148 tests in 16.627s` and `OK`. From `socra`, `tsc --noEmit --incremental false` exited 0. The tests cover routing and language priority, lab command order, batch-local citations and numbering, persisted omissions, flag rollback, and truncation with no continuation.

### Phase 2 implementation report — 2026-11-15

Working tree baseline was `4407916` on `main` with uncommitted Phase 0/1 changes and pre-existing edits. Phase 2 added the following files and changes.

| File | Role |
|---|---|
| `socra-backend/explain_model_limits.json`, `socra-backend/.env.example` | Configurable M2 limits, token policy, feature flag, and source dominance setting |
| `socra-backend/agents/explain_budget.py` | Per-model context and minute-capacity budgeting from configured limits |
| `socra-backend/rag/document_inventory.py` | Source-first English, French, and Arabic inventory with stable type IDs and distinct occurrence keys |
| `socra-backend/rag/explain_documents.py` | Ranked evidence is kept separate from scoped, verified read-only full-index access |
| `socra-backend/agents/explicateur.py` | Feature-gated exhaustive/explicit-PDF path, bounded evidence injection, and persisted limitations |
| `socra-backend/api/websocket.py`, `socra-backend/graph/state.py` | Optional validated `documentId` and internal inventory/evidence state |
| `socra-backend/tests/test_explain_phase2.py`, `socra-backend/tests/test_chat_socket.py` | Offline scope, quota, local TP, portability, and streaming/persistence regressions |
| `socra-backend/tests/fixtures/local/phase2_orange_knime_chunks.json` | Git-ignored 15-chunk private fixture generated through the real local PDF extractor |
| `SOCRA_EXPLICATEUR_PLAN.md` | Status, evidence, policy and actual verification |

The existing authenticated request verifies the session's course and course owner. New catalog reads independently constrain `course_id`, `courses.user_id`, and index readiness. Any missing-index read also matches the selected document and the same index snapshot fields. Explicit invalid IDs are rejected before retrieval. Exact filename, single PDF, and dominance of **at least 70% of distinct retrieved hits** are the default selection paths. Duplicate names and unresolved ties ask for clarification. Explicit multi-source requests use authorized retrieved passages with `retrieved_only` scope. The public explanation schema, streaming events, citation binding, Library and Notebook storage are unchanged.

The inventory records type, stable label, occurrence key, PDF/page/chunk, original heading, evidence anchor and status basis. A complete index is checked with chunk count, distinct indices and extracted page numbers independently of evidence actually sent. Status records distinguish markers on a line from heading/block context. New logs distinguish index pages and chunks, retrieved evidence, sent evidence, requirement count and mandatory evidence gaps. The inventory remains internal to graph state. This phase checks which requirement evidence was sent; answer completeness, correctness, repair, continuation, and per-section citations belong to Phase 3a/3b.

The capacity formula is `min(model context, floor(account TPM × 0.80))`. Estimate UTF-8 bytes of the serialized prompt, schema, and messages at three bytes per token, with 256 framing tokens and 384 planned repair-prompt tokens. Reserve output as the minimum of provider maximum, 16,000 policy maximum, and one-third of capacity. The configured account gives Gemini capacity **200,000**, output **16,000**, and up to **183,360** estimated serialized prompt tokens before framing and repair reserves. Either Groq model gets **6,400**, output **2,133**, and **3,627** estimated serialized prompt tokens before those reserves. The estimate and actual provider usage can differ. The turn reserves prompt plus maximum output again before any existing retry or group. The headroom is not a shared rate limiter. If limits are unknown, keep existing generation settings and skip new evidence expansion. No provider is switched.

No extra generation, classification, or embedding calls were introduced. This phase ran only offline tests and local PDF extraction. There were no live database changes, deployment, Git push, or paid-provider usage.


#### Phase 2 verification

Run from `socra-backend`:

```powershell
.\.venv\Scripts\python.exe -m tests.offline_windows
.\.venv\Scripts\python.exe -m tests.offline_windows tests.test_explain_phase2 tests.test_chat_socket
```

```text
----------------------------------------------------------------------
Ran 170 tests in 17.190s

OK

----------------------------------------------------------------------
Ran 39 tests in 9.277s

OK
```

The real local TP fixture participated in the run. The focused test verifies missing-questions evidence injection, model-window and TPM checks, an aggregate retry reservation, duplicate heading identity, explicit ownership, ambiguity, the no-full-document path, and persisted WebSocket shape. The suite also ran the existing Notebook, storage, and retrieval regressions.

From `socra`, `.\node_modules\.bin\tsc.cmd --noEmit --incremental false` exited 0 with no output. `git diff --check` exited 0. Live answer quality and provider quota behavior were not measured.

### Phase 3a implementation report — 2026-11-15

Starting revision 4407916. Existing uncommitted Phase 0–2 and unrelated edits were preserved. Phase 3a changed `socra-backend/agents/explain_coverage.py`, `socra-backend/agents/explicateur.py`, `socra-backend/.env.example`, `socra-backend/tests/test_explain_coverage.py`, `socra-backend/tests/test_chat_socket.py`, and this plan.

The checker identifies relevant mandatory and explicitly named requirements by occurrence, includes source-referenced fallback appendices, and checks normalized labels, type-specific substance, anchors, and available evidence. The coverage rules are lexical heuristics. Coverage is not correctness, and valid citations do not establish factual accuracy. The threshold can be overridden per kind with `SOCRA_EXPLAIN_COVERAGE_MIN_<KIND>_WORDS`. Existing card fields persist coverage limitations, including when only retrieved excerpts could be checked. No frontend or public schema change.

A normal complete answer spends zero repair calls. One narrowly scoped repair invocation is allowed for up to three missing occurrences with matching indexed excerpts. It shares the existing 90-second deadline and configured token ledger. Repair cannot retry or continue recursively. The original primary generations and one shared Phase 0b recovery otherwise remain as configured. Valid repair sections are appended in order, grounded citations are bound and deduplicated, and unresolved gaps remain visible after replay. Large gaps use the existing incomplete card and ask the user to continue; no additional major-part scheduling was justified by the measured TP. Known model limits and eligible source evidence are required for automatic repair.

The original separate bad-answer fixture remains unavailable. The test instead uses a labeled synthetic negative fixture and a hand-written positive fixture covering captures 1–5, questions 1–6 and fallback Annex A. A real answer quality comparison is deferred. Lexical paraphrase and translated non-technical anchors may require manual review. Section-level citations and dedicated UI rendering remain Phase 3b.

From `socra-backend`, ran `.\.venv\Scripts\python.exe -m tests.offline_windows`:

```text
Ran 179 tests in 17.478s

OK
```

The suite verified failed repair without retry, preservation of truncation salvage, no extra call for complete answers, real saved-card WebSocket replay with mocks, unknown token limits, and flag-off behavior. `git diff --check` passed. Zero live LLM calls, production data mutations, deployments or pushes.

### Phase 3b implementation report - 2026-11-15

Starting revision `4407916` on `main`. The working tree contained uncommitted Phase 0a–3a changes and unrelated edits, which were preserved. This local plan is Git-ignored.

| Files | Phase 3b change |
|---|---|
| `socra-backend/models/schemas.py` | Added optional section `citations` and `covers`. Definition and intuition remain string fields and accept an empty value. Existing message JSON still validates. |
| `socra-backend/agents/explicateur.py`, `explain_tasks.py`, `explanation_preview.py` | Added optional model input `source_indexes`, bound it locally on complete and salvaged responses, kept Markdown fences in position, and improved the append-only preview. |
| `socra-backend/tests/test_explicateur.py`, `test_chat_socket.py` | Covered invalid indexes, duplicate pages, two documents with the same page number, the separate global limit, legacy JSON, ordered preview, and bound citations on persisted truncation replay. |
| `socra/lib/socra-ws.ts`, `socra/hooks/useSocraChat.ts`, `socra/components/chat/Message.tsx`, `TutorMessage.tsx`, `ExplanationCard.tsx` | Added the optional client shape, Explain preview rendering and ordered Markdown final cards with copyable language-labelled code, GUI steps, per-section PDF sources and B2 notices. |
| `socra/components/notebook/NotebookReply.tsx`, `socra/lib/notebook/document.ts`, `socra/app/layout.tsx`, `socra/app/(dashboard)/dashboard/notebook/page.tsx` | Reused the Notebook lexer for ordered markup and math, and made KaTeX styles available to Explain and Library. |
| `socra/components/documents/PdfCitation.tsx`, `socra/lib/documents/pdf-page.ts`, `socra/lib/ai/explanation-presentation.ts`, `explanation-note.ts`, `socra/app/api/notebook/capture/route.ts` | Shared PDF page URLs and duplicate code suppression. Notebook conversion keeps ordered fences, math, and linked citations. Capture verifies section and global citation pages using the owned course's documents. |
| `socra/scripts/test-explanation-rendering.mjs`, `test-notebook.mjs`, `test-study-routes.mjs`, `SOCRA_EXPLICATEUR_PLAN.md` | Added or updated component, conversion, clipboard and saved-source tests and recorded results. |

Section citations resolve one-based indexes against the exact chunks supplied to the generation, including group-local and salvage paths. Invalid, malformed, duplicate and unsupported identities are dropped. Echoed citation objects and model indexes are never serialized as public section references. Global citations keep their existing shape and limit. Model-emitted `covers` labels are advisory and do not establish claim accuracy or satisfy the Phase 3a check. Phase 3b added no provider call sites and kept the existing retry and repair budgets. No live LLM requests, deployments, pushes, or production database changes occurred.

Final cards and Library history use the same renderer. Notebook retains B2 text in its editable note and citation links to the original PDF page. The capture route also verifies page bounds and ownership before storing its source metadata. The document path exposes PDFs and indexed text without page-image assets, so screenshot checkpoints show instructions and page links. The existing Notebook editor retains tables as Markdown text, while chat and Library render them as tables. No live quality, provider quota or latency comparison was run. Phase 4 owns the cross-document corpus, the original bad-answer comparison if supplied, live quality and cost measurement if authorized, and the resulting flag decisions.

#### Phase 3b verification

From `socra-backend`:

```powershell
.\.venv\Scripts\python.exe -m tests.offline_windows
```

```text
----------------------------------------------------------------------
Ran 182 tests in 20.103s

OK
```

From `socra`:

```powershell
.\node_modules\.bin\tsc.cmd --noEmit --incremental false
node --test scripts/test-explanation-rendering.mjs scripts/test-notebook.mjs scripts/test-study-routes.mjs
```

TypeScript exited 0 with no output. The frontend test runner reported:

```text
ℹ tests 22
ℹ suites 0
ℹ pass 22
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
```

`git -c core.safecrlf=false diff --check` exited 0.

### Phase 4 Orange/KNIME live failure and corrective pass — 2026-11-15

The supplied live report recorded a 15/15-chunk English exhaustive lab walkthrough. The inventory had 72 entries and 22 applicable requirements. Coverage flagged 19 gaps with zero missing evidence and no evidence limiting. The request used one model call, zero retries, 11,186 input tokens and 2,665 output tokens against a 16,000-token output reservation. It finished without truncation in 12.375 seconds and persisted an incomplete notice. The original repair guard required one to three gaps, so 19 gaps excluded the repair call.

The main generation prompt had excerpt text and general lab guidance. Request-relevant inventory entries were consumed by the checker after generation. The provider finished below the output ceiling. The public schema allows 30 sections of up to 3,000 content characters each, and lab normalization preserves fence order. Neither was shown to cause this run to end early. An offline regression separately exposed a parser bug: an inner Markdown code fence inside valid response JSON could be mistaken for its outer wrapper.

- `agents/explicateur.py` supplies request-relevant inventory entries to exhaustive lab generation with page numbers and local excerpt indexes. Missing excerpt indexes are explicit. The prompt goes through the existing token-fit check. Repair decisions log a skip reason with the same one-to-three-gap eligibility.
- `agents/explain_tasks.py` specifies separate numbered screenshots and question guidance, complete grounded scripts and run commands, path consistency, verification steps, and a section layout within existing schema limits.
- `agents/structured_output.py` keeps embedded program fences in raw and fenced JSON.
- `agents/explain_coverage.py` recognizes a translated installation heading when the product name matches and the body still has grounded action. It rejects ambiguous-directory substitutions only when a file or deliverable anchor provides a unique relative path with the same root and basename. The checker remains lexical. It does not infer working directories or verify arbitrary paths, correctness, or submission packaging.
- `tests/test_explain_coverage.py` and `tests/test_structured_output.py` cover prompt completeness, short-mode isolation, script preservation, installation paraphrases, supported path contradictions and the many-gap repair skip.

Offline verification from `socra-backend`: `.\.venv\Scripts\python.exe -m tests.offline_windows` reported `Ran 188 tests in 21.509s` and `OK`. From `socra`, `node --test scripts/test-explanation-rendering.mjs scripts/test-notebook.mjs scripts/test-study-routes.mjs` passed 22 tests and `.\node_modules\.bin\tsc.cmd --noEmit --incremental false` exited 0. `git -c core.safecrlf=false diff --check` passed.

Normal generation remains one call. The existing shared recovery and optional single targeted repair retain their prior limits. No new retrieval, schema changes, live model calls, production writes, pushes or deployment. Phase 4 remains open pending a successful live retest and the cross-document evaluation.

### Phase 4 follow-up: structured walkthrough — 2026-11-16

The second live Orange/KNIME run retrieved all 15 chunks, generated 3,308 tokens in 12.97 seconds with one invocation, and completed without truncation. The checker recognized 6/22 requirements with 16 gaps, and repair logged `too_many_missing`. The rendered transcript showed comment-only code, grouped captures without usable instructions, and grouped question paraphrases. The transcript did not establish whether comments came from standalone code or inline fences.

The exhaustive lab provider schema now requests citations and sections only. Source-ordered plan entries designate captures, questions, and appendices as separately headed blocks. The public saved schema is unchanged. The checker evaluates separately labeled screenshot and question blocks, including Markdown subheadings, for procedural guidance and substantive analysis steps. It remains lexical and does not verify script completeness. Backend normalization and frontend rendering handle comment-only blocks as prose and preserve real scripts.

Changed backend files: `agents/explicateur.py`, `agents/explain_tasks.py`, `agents/explain_coverage.py` and `tests/test_explain_coverage.py`. Changed frontend files: `components/notebook/NotebookReply.tsx`, `lib/ai/explanation-presentation.ts`, `lib/ai/explanation-note.ts` and `scripts/test-explanation-rendering.mjs`.

Offline verification: `.\.venv\Scripts\python.exe -m tests.offline_windows` passed 189 tests in 13.971s. `node --test scripts/test-explanation-rendering.mjs scripts/test-notebook.mjs scripts/test-study-routes.mjs` passed 23 tests. TypeScript and `git -c core.safecrlf=false diff --check` passed. No live calls, production writes, deployment or push. Phase 4 remains open. The stricter checker changes scoring, so the next evaluation should review the actual screenshot steps, six questions, and appendix script alongside the counts.

### Universal explanation-card UI implementation report - 2026-11-16

Base revision `4407916`. The worktree already contained changes across the backend and frontend, including the Explain renderer and its helper. This task changes only the files listed below. The roadmap remains a local gitignored file.

| File | Change |
|---|---|
| `socra/components/chat/ExplanationCard.tsx` | Shared card shell, reusable section and source presentation, visible coverage notices, collapsible long sections, checklist progress, and answer reveals. |
| `socra/lib/ai/explanation-card-layout.ts` | Presentation derived from existing Markdown headings, block types and supplied citations, with generic and compact fallbacks. |
| `socra/lib/ai/explanation-presentation.ts` | Keeps original Markdown line endings when separating a persistent coverage notice from the body. |
| `socra/components/notebook/NotebookReply.tsx` | Adds opt-in rendering features used by the card through the existing StudyMarkdown helper. Notebook and preview call sites keep their existing behavior. |
| `socra/scripts/explanation-card-fixtures.mjs` and `socra/scripts/test-explanation-rendering.mjs` | Five synthetic fixtures and regression coverage for control visibility, source links, localization, and fallback. |
| `SOCRA_EXPLICATEUR_PLAN.md` | UI checklist and verification record. |

Compared the five synthetic fixture layouts with the corresponding references. Chrome rendered the production card component with Socra's compiled Tailwind stylesheet, Manrope and Newsreader assets, KaTeX, and the existing Button. The fixtures ran in a standalone local page at desktop and 360 px card viewport widths. The 20 combinations cover all five types in both themes and widths. Two additional screenshots show the guide's initial collapsed state. Checked the step hierarchy and callouts, formula and derivation spacing, two-column language comparisons that stack on narrow layouts, compact answer body, and research evidence tables. All 20 combinations passed the theme and card-overflow assertions.

Verified focusability and browser activation for the coverage summary, section disclosures, checklist, copy action, and citation links. The clipboard test captured the exact fixture payload including CRLF, indentation, and trailing spaces. Expand all preserved closed practice answers. A Chrome print of the collapsed guide produced a two-page PDF whose extracted text includes closed sections, deliverables, and the coverage details. The authenticated course page and live PDFs were outside the fixture environment. Existing mocked route tests covered the ownership check and exact page redirect. Complete keyboard traversal, browser find-in-page behavior, and assistive-technology behavior were not tested directly.

The UI derives hierarchy when existing content has recognizable headings and blocks. Ambiguous formats keep their original order and plain rendering. Practice answers fold only when explicitly marked. Research displays supplied findings and evidence without generating metrics. No schema changes, extra LLM calls, production data edits, deployments, or pushes.

Run from `socra`:

```powershell
node --test scripts/test-explanation-rendering.mjs scripts/test-notebook.mjs scripts/test-study-routes.mjs scripts/test-direct-upload.mjs
$env:SOCRA_TEST_BROWSER='C:\Program Files\Google\Chrome\Application\chrome.exe'
node scripts/test-chat-browser.mjs
node node_modules/typescript/bin/tsc --noEmit --incremental false
node node_modules/eslint/bin/eslint.js components/chat/ExplanationCard.tsx components/notebook/NotebookReply.tsx lib/ai/explanation-card-layout.ts lib/ai/explanation-presentation.ts scripts/explanation-card-fixtures.mjs scripts/test-explanation-rendering.mjs
git diff --check
```

```text
ℹ tests 29
ℹ pass 29
ℹ fail 0
ℹ skipped 0
Chat browser smoke passed
PASS: 20 viewport/theme combinations, 22 screenshots, native disclosure and focus checks, exact clipboard and link activation, preview, legacy replay.
```

TypeScript, targeted lint and the whitespace check exited successfully. The baseline Explain rendering suite passed six tests before the UI changes.

### Phase 4 continuation — stages A–E

**A. Coverage calibration.** The local M1 baseline had 22 applicable requirements and the former Boolean checker flagged all 22. The revised check reports 20 applicable requirements on the same archived answer and evidence, with 16 missing and four partial. Two requirements were counts of structural or duplicate artifact headings. This is a checker replay, so the changed denominator and states do not measure a change in answer quality. Multilingual concrete-anchor matching recognizes selected paraphrases. Dedicated screenshot, question and appendix blocks still require actionable content, and scoped source evidence remains necessary. Diagnostics report the internal occurrence ID, source page, state and reason without text from the document. The latest improved live-answer payload was not present among authorized local fixtures. Its previously reported scores remain historical.

**B. Source-grounded completeness.** Bounded expected-output, troubleshooting and reference-table entries carry the source index, page and nearest known procedure into the existing exhaustive request. The local index verifies the transaction total and fraud count, held-out split, representative F1 values, confusion-matrix entries and KNIME Scorer checks. An explicit date or output in a source is a reference value. A student observation requires student evidence. Graded-question prompts ask for evidence to collect, applicable concepts, how to organize the response and how to verify it. Small comparison templates are requested from supplied source context. Wrapped extracted table cells are best-effort. The appendix checker recognizes script-like content in a fence and cannot certify script completeness or execution. The latest PowerShell concatenation report could not be reproduced without its raw payload. Regression fixtures cover exact CRLF, indentation and intentional PowerShell continuation. Normalization does not guess where to split ambiguous commands.

**C. Card integration.** New coverage notices use page-specific requirement labels and indicate missing, needs more detail or unavailable source. Older hashed identifiers render as generic readable labels. The notice is persisted through the existing card JSON. Task-oriented cards keep checklist overrides in browser storage scoped by owner and persisted message ID. Library items use the same message ID when present and their own item ID for older records. The stored values contain task positions and Boolean states. An unavailable storage backend leaves the card usable in memory. The design system and persistence schema were preserved. Headless Chrome exercised focusability, disclosure and checkbox behavior, exact code copy, citation link activation, practice reveals, legacy replay, streaming preview, and the five layouts in light and dark modes at two widths. Direct Tab, Space and Enter testing through the entire card remains open because the browser approval gate declined access to the isolated loopback fixture. Print smoke output contained closed sections and coverage details.

**D. Offline evaluation.** Portable, written fixtures cover a lab, programming tutorial, derivation, exercise sheet, language lesson, research paper, data report and scientific manual. The suite exercises the classification, detail, language, extracted structure and request-specific prompt contract by fixture. Existing route, WebSocket, frontend and budget tests exercise source selection, access, citations, failure recovery and saved-card compatibility. Synthetic Orange/KNIME-style before, intermediate and after cases are distinct from the actual archived M1 card. One ordinary generation, one shared recovery slot, and at most one eligible repair remain the pre/post call policy. The repair does not retry. The generation deadline stays 90 seconds and applies after retrieval. Existing explicit exercise batching keeps its own configured group cap. No live provider calls, deployment, push, or production data operations took place.

**E. Release decision.**

| Category | Finding |
|---|---|
| Ready based on offline verification | Coverage states, safe incomplete-card persistence, local progress, source ownership and page targets, saved-card compatibility, responsive layouts, and bounded calls. |
| Requires live model validation | Actual quality and coverage of the newer Orange/KNIME response, results across non-lab sources, unsupported claims, current provider quotas, live timing and token use. |
| Requires manual visual/accessibility review | Natural Tab order, visible focus, keyboard-only activation across the card and screen-reader announcements in the authenticated application. |
| Blocking defect | No reproduced offline blocker. A failed live quality check remains a release blocker for enabling the evaluated flags. |

The Explain model is created with the selected provider and model and single-attempt SDK mode, which suppresses the adapter's Groq backup in this route. The request owns retries. The local limits file records historical project quotas, so eligibility for free-tier evaluation must be checked against the authorized project before the run. Missing model limits leave targeted repair unavailable. Global production flag defaults and the deliberately deferred full-document retrieval path are unchanged. Roll back by explicitly disabling the staged Explain flags, preserving the Phase 0 safeguards. The response schema remains compatible with existing cards.

#### Controlled live protocol, pending authorization

Use a non-production course and eligible source PDFs. For each pair use the same course, selected PDF version, authorized project, exact model, prompt, retrieval inputs where reproducible, and captured feature settings. Compare the prior checkpoint with this revision. Preserve the distinction between any change in retrieved context and a change in response quality. Start with Google `gemini-3.5-flash-lite` only after confirming access and quota in the authorized provider dashboard. If separately approved, run a Groq comparison with an explicit configured model from the local limits file. Keep full-document retrieval disabled. Use `EXPLAIN_TASK_MODES=1`, `EXPLAIN_DOCUMENT_INVENTORY=1`, `EXPLAIN_COVERAGE_CHECK=1` and `EXPLAIN_MULTI_EXERCISE_BATCHING=0` for the bounded non-batch test matrix. Check the grouped-exercise flag separately only if testing an explicit multi-exercise request. Never use Gemini 2.5 Flash.

| Document | Exact request | Expected behavior |
|---|---|---|
| Orange/KNIME TP | I want you to detail everything of what i need to do to complete this tp in my laptop with every install of any application and every code that i need and every command i need to run and everything i need to do for each screen shot detailed at the end of the file as well | English exhaustive lab. Five screenshots, actionable guidance for Questions 1–6, the Annex A fallback and a complete runnable script, dependencies, both Orange install methods and Python 3.11+, KNIME workflow in Local space, one creation of the reports folder, uploads, comparison template and correct file paths. Verify expected metrics, troubleshooting and source pages against the PDF. |
| Python parser tutorial | Explain how to implement and test the Python parser in English. | Coding guide. Dependencies, runnable source, line breaks and verification. |
| Mathematics lecture | Derive the quadratic formula from the equation and verify your result in English. | Math explanation. Equations, derivation and verification without lab sections. |
| Exercise sheet | Give hints for Exercise 2 in French. | French exercise guidance scoped to Exercise 2 and its applicable subquestions. |
| Grammar lesson | Explique la grammaire et le vocabulaire avec des exemples. | French language lesson with rules and examples. |
| Research paper | Explain the research paper's methodology, main findings and limitations in English. | Research analysis, source-supported claims, explicit limitations. |
| Data report | Explain the dataset table and compare the reported units in English. | Data analysis with correct units, estimates, and explicit missing data. |
| Scientific manual | Give a brief summary of this manual in Arabic. | Concise Arabic summary without lab structure or invented figure details. |

For each run record document version, task classification, language, stored status, retrieved/sent chunks and pages, requirement coverage, human-reviewed omissions and unsupported claims, citation page checks, instruction correctness, prompt/output tokens, first-token and total latency, model calls, retries, truncation and budget denials. First verify one run per document. Repeat only within the approved quota. Keep single-run timings separate from any sample large enough to report distributions. Inspect incomplete results after reopening and save a reference output for reproducible replay with authorization.

For manual keyboard validation in a permitted local application, start with a lab card and a language card. Use Tab and Shift+Tab through the coverage disclosure, Expand all, section summaries, checkbox, copy, PDF and answer reveal controls. Use Enter or Space as appropriate and verify visible focus and announced state. Reload the lab and open its saved Library card to confirm progress restores. Repeat on a synthetic alternate owner to verify isolation. Print the collapsed lab, confirm headings and status remain available, and test the mobile layout.

#### Files and recorded verification

| Area | Files changed in this continuation |
|---|---|
| Backend | `agents/explain_coverage.py`, `agents/explain_tasks.py`, `agents/explicateur.py`, `rag/document_inventory.py` |
| Frontend | `components/chat/ExplanationCard.tsx`, `components/chat/ChatPanel.tsx`, `lib/ai/explanation-card-layout.ts`, `lib/ai/explanation-progress.ts`, the inquiry and Library detail pages |
| Tests | `test_explain_coverage.py`, `test_explain_phase2.py`, `test_chat_socket.py`, new `test_explain_evaluation.py`, `test-explanation-rendering.mjs` |
| Plan | `SOCRA_EXPLICATEUR_PLAN.md` (local, ignored by the existing repository rule) |

Backend from `socra-backend`:

```powershell
.\.venv\Scripts\python.exe -m tests.offline_windows tests.test_explain_coverage tests.test_explain_phase2
.\.venv\Scripts\python.exe -m tests.offline_windows tests.test_explain_coverage tests.test_explain_phase2 tests.test_chat_socket
.\.venv\Scripts\python.exe -m tests.offline_windows tests.test_explain_coverage tests.test_explain_phase2 tests.test_explicateur tests.test_structured_output
.\.venv\Scripts\python.exe -m tests.offline_windows
```

The focused checkpoints passed 36, 55 and 97 tests. The final backend run passed 194 tests in 15.332 seconds. The checker averaged 6.97 ms across 30 evaluations of the same archived M1 payload in that run.

Frontend from `socra`:

```powershell
$env:SOCRA_TEST_BROWSER='C:\Program Files\Google\Chrome\Application\chrome.exe'
node --test scripts/test-chat-browser.mjs scripts/test-direct-upload.mjs scripts/test-explanation-rendering.mjs scripts/test-notebook.mjs scripts/test-study-routes.mjs
node node_modules/typescript/bin/tsc --noEmit --incremental false
node node_modules/eslint/bin/eslint.js 'app/(dashboard)/dashboard/course/[courseId]/inquiry/[sessionId]/page.tsx' 'app/(dashboard)/dashboard/library/[id]/page.tsx' components/chat/ExplanationCard.tsx components/chat/ChatPanel.tsx lib/ai/explanation-card-layout.ts lib/ai/explanation-progress.ts scripts/test-explanation-rendering.mjs
node .next/explanation-qa/drive.mjs
git diff --check
```

The final frontend test run passed 32 with zero failures and zero skips, including Chrome chat smoke. The local visual fixture harness rendered 20 theme and viewport combinations and captured 22 screenshots. The two-page print output was checked by extracting text and finding collapsed content, deliverables, and the incomplete notice. The end-to-end interactive keyboard check remains open.

### Phase 5 implementation and verification - 2026-11-16

Starting revision: 4407916 on main, with earlier uncommitted Explicateur work and unrelated edits. Phase 5 preserved those edits and the historical results above.

#### 5A. Diagnosis

| Area | Finding | Evidence |
|---|---|---|
| Tables in Explain and Library | Valid GFM survives parsing, normalization, preview, the final card and saved-card reopening. The indexed TP contains space-delimited metric output as well as a pipe-delimited comparison template. | JSON round-trip, GFM fixtures, Chrome and indexed pages. The latest model's raw table payload is unavailable. |
| Notebook tables | The lexer found the table, then Notebook put its raw rows into a single text node. HTML collapsed the row boundaries. | Reproduced using the Notebook schema and serializer in Chrome. |
| Commands | No PowerShell concatenation reproduced in the archived sections, representative JSON preview, final card or code copy. Three archived PowerShell blocks parsed successfully. | Static syntax and formatting checks. Paths, dependencies and applications were not provisioned or executed. An explicit relative script path is a style preference. |
| Result placement | The lab prompt requested adjacent support, then shared instructions requested a standalone reference section. Prompt metadata repeated source text. | Inspected composed messages. The card already keeps source excerpts under disclosures. |
| Coverage | Restatement could satisfy verb and anchor checks. Concrete read/record guidance could fail a second generic verb check. The requested screenshot-checkpoint prefix needed to match numbered source labels. Markdown guidance headings needed to stay inside their question block. | Hand-reviewed question and screenshot cases. Two TP part headings also created artificial installation requirements. |
| Optional items | TP bonuses B1-B3 were already optional. Expected results and table templates under a bonus heading could be treated as general support and inherit the previous procedure. | Indexed TP replay and optional-support fixture. |

The exact initial inadequate answer and latest full improved raw payload and screenshot were unavailable locally. The historical 3/22 and 6/22 numbers are prior live reports with different output and checker behavior. The archived M1 card, its source chunks, and hand-authored fixtures supplied the offline comparisons.

| Replay | Covered | Partial | Missing | What was measured |
|---|---:|---:|---:|---|
| Archived M1 before Phase 5 | 0 | 4 | 16 | Phase 4 checker over the archived card. |
| Archived M1 after Phase 5 | 0 | 4 | 14 | Same card. Two structural headings no longer create installation gaps. The answer still omits the appendix script and mentions the comparative table without supplying it. |
| Synthetic lab low / intermediate / complete | 0 / 0 / 4 | 1 / 3 / 0 | 3 / 1 / 0 | Three hand-authored answers to the same four-item source. |
| Hand-reviewed Phase 5 lab | 2 | 2 | 1 | Four questions and a required fallback appendix. A restatement changed from covered to partial and actionable guidance changed from partial to covered. The optional exercise was excluded. |

The archived replay averaged 6.38 ms over 30 evaluations in the final suite. Coverage is lexical. Factual correctness, complete script fidelity and broader translated paraphrases still need human assessment.

#### 5B. Backend

- The task-mode prompt places source-backed results and troubleshooting beside their procedure. Compact locators link supplied excerpts to same-document, nearby steps, installations or appendices. Ambiguous support has no procedure locator. The 4,000-character allowance prioritizes result and table locators, then restores source order. The original excerpt supplies the values. The TP fixture verifies the relationship between scoring and setup pages, and between the appendix script and its expected output.
- Exhaustive lab guidance calls for supported prerequisites, paths, setup verification and fallbacks, the complete source script, screenshot save instructions, and concrete guidance per graded question. Markdown tables retain metric names, units, reference values and source comparison templates. The prompt differentiates PDF references, computations with stated inputs, student measurements and general tips. Existing hint-first and explicit-solution routing remains in use.
- The checker recognizes concrete investigative verbs and checks for additional substance beyond assignment wording. Guidance subheadings stay under their question and screenshot-checkpoint headings resolve to their numbered requirement. Structural headings and optional support no longer create unrelated required work.
- The advisory flattened-table diagnostic logs a section count for clearly aligned numeric rows outside tables and code. It leaves the payload intact. Concise prompt guidance addresses unnecessary quotations and keeps required scripts, tables and exact commands.
- A full card can store an additional source-coverage notice in the existing course example field. The regression retains a long final script and both coverage notices.

#### 5C. Frontend

New Notebook captures retain editable and copyable Markdown table rows through editor-supported hard breaks. Chat and Library still render GFM tables. Notebook adds a source-reference label only when the section has an excerpt-backed page citation. Tests covered the five existing layouts, ordinary blockquotes, labeled guidance, code copy, inline math, local progress, PDF page links, print and restored incomplete results.

Chrome verified focusability and control activation on synthetic cards. Full interactive Tab/Shift+Tab traversal remains open. The connected browser timed out on the loopback fixture and disallowed local file URLs.

#### 5D. Verification

| Group | Phase 5 files |
|---|---|
| Backend | socra-backend/agents/explicateur.py, agents/explain_tasks.py, agents/explain_coverage.py, rag/document_inventory.py |
| Frontend | socra/lib/notebook/document.ts, lib/ai/explanation-note.ts |
| Tests | socra-backend/tests/test_explain_coverage.py, tests/test_explain_evaluation.py, socra/scripts/test-explanation-rendering.mjs |
| Roadmap | SOCRA_EXPLICATEUR_PLAN.md |

From socra-backend:

~~~powershell
.\.venv\Scripts\python.exe -m tests.offline_windows
~~~

Ran 199 tests in 15.391s. OK, with zero skips. The offline corpus covered eight document types (lab, programming, maths lesson, maths exercises, language, scientific manual, research and data). The suite verified routing, coverage, citation binding, streaming, recovery and mocked WebSocket replay. The local TP revision used the archived M1 payload and 15 indexed chunks. The native PowerShell parser accepted three archived command blocks.

From socra:

~~~powershell
$env:SOCRA_TEST_BROWSER='C:\Program Files\Google\Chrome\Application\chrome.exe'
node --test scripts/test-chat-browser.mjs scripts/test-direct-upload.mjs scripts/test-explanation-rendering.mjs scripts/test-notebook.mjs scripts/test-study-routes.mjs
node node_modules/typescript/bin/tsc --noEmit --incremental false
node node_modules/eslint/bin/eslint.js lib/notebook/document.ts lib/ai/explanation-note.ts scripts/test-explanation-rendering.mjs components/chat/ExplanationCard.tsx components/notebook/NotebookReply.tsx
node .next/phase5-qa/drive.mjs
~~~

34 tests passed, 0 failed, 0 skipped. TypeScript and targeted ESLint exited 0. The local Chrome harness rendered 20 theme/viewport combinations, captured 22 card screenshots and a Notebook before/after, and verified three rendered row breaks and exact plain text. The two-page printout retained collapsed content, the script, screenshot checkpoint, deliverables and incomplete notice. From the repository root, both git diff --check and git -c core.safecrlf=false diff --check exited 0. Direct whitespace checks also covered the changed untracked code.

A normal request uses one primary generation with one shared recovery and at most one eligible targeted repair without retries. The 90-second generation deadline, provider-specific limits, existing batch guards and production flag defaults remain in force. A guide that exceeds the budget uses the existing persisted incomplete status. A student can explicitly request the missing sections. Automatic part scheduling remains deferred. Phase 5 used zero live LLM calls, private production conversation reads, database mutations, deployments or Git pushes.

#### Controlled live release gate

Run only after authorization. Use a non-production Supabase project and owned, indexed PDFs. Record the baseline revision, PDF version and exact model. Verify authorized free quota in the provider dashboard. Run one request per row through Explain, starting with the TP. For a paired comparison use the same PDF version, course setup, prompt, model and flags, and record retrieval differences independently of answer differences.

Backend PowerShell from socra-backend, with existing development credentials:

~~~powershell
$env:SOCRA_ENV='development'
$env:FRONTEND_URL='http://localhost:3000'
$env:CHAT_MODEL='gemini-3.5-flash-lite'
$env:EXPLAIN_TASK_MODES='1'
$env:EXPLAIN_DOCUMENT_INVENTORY='1'
$env:EXPLAIN_COVERAGE_CHECK='1'
$env:EXPLAIN_MULTI_EXERCISE_BATCHING='0'
$env:EXPLAIN_FULL_DOCUMENT='0'
.\.venv\Scripts\python.exe -m uvicorn main:app --port 8000
~~~

In the frontend development environment use the same Supabase project with NEXT_PUBLIC_APP_URL=http://localhost:3000, NEXT_PUBLIC_BACKEND_WS_URL=ws://localhost:8000, and SOCRA_BACKEND_URL=http://localhost:8000. Run **npm run dev -- --port 3000** from socra. In the TP inquiry select English in Response language and open the original indexed PDF.

| Test | Exact request | Acceptance |
|---|---|---|
| Orange/KNIME | I want you to detail everything of what I need to do to complete this TP on my laptop with every install of any application and every code that I need and every command I need to run and everything I need to do for each screenshot detailed at the end of the file as well. | English exhaustive lab. Check both Orange install paths and Python 3.11+, KNIME workflow in Local space, complete dataset script and execution, dataset and split counts, precise model metrics beside their steps, five screenshot checkpoints with saving instructions, six question guides, comparison template, optional bonuses, workflow exports and report paths. Inspect commands in a text editor and execute only in an authorized disposable workspace. Verify sources, save, reopen and capture in Notebook. |
| Mathematics | Derive the quadratic formula from the equation and verify your result in English. | Coherent derivation with equations, justification and verification. |
| Language | Explique la grammaire et le vocabulaire avec des exemples. | French explanation, usable contrasts, examples and practice. |
| Short concept | Briefly explain overfitting in English. | Concise grounded definition and a focused example or contrast. |
| Research or data | Explain the research paper's methodology, main findings and limitations in English. | Method, results, limitations, units where relevant and correct citations. |

For each run record provider and model, active flags, intent/detail/language, PDF version, retrieved and sent chunks and pages, coverage states and human-reviewed errors, first visible text, total time, input/output tokens, calls, recovery and repair, truncation, citation accuracy and educational quality. Correlate explain_request and model_call logs with browser timing. Verify every reference value against its PDF page and keep student measurements separate.

Use Tab and Shift+Tab across coverage disclosure, Expand all, section summaries, checkboxes, code copy and PDF links. Activate each with Enter or Space and verify visible focus and control state. In the language card check that the practice answer remains closed until activated. Reload and reopen a saved test lab in Library and verify the checklist and incomplete status. Production activation remains gated on authorized live results and interactive verification.

### Focused UI and brief-summary follow-up - 2026-11-16

The supplied screenshot shows the same understanding prompt and action twice, a scroll control over the message contents, and workflow labels styled as copyable code. The exact short-answer payload and a replay of the original browser capture were unavailable. In the archived four-section payload, check_question was present once and absent from the section bodies. A streamed question stopped rendering when its final structured card arrived. A separate mocked recovery run reproduced duplicate explanation rows when the persisted message ID was already in history and completion assigned it to the draft. Completion now merges those representations by message ID while preserving card metadata. The question and action use one labelled section and remain covered by a preview-to-final render test.

The scroll control previously used an absolute offset from the chat panel. It now occupies an in-flow row between the message viewport and composer only when the scroll distance exceeds the existing threshold. The control targets the named viewport, respects reduced motion, and moves focus there before the button disappears. The card now limits ordinary prose to 46 rem (736 px at the default root size), uses the card foreground for explanation text, and uses the existing small uppercase supporting labels. Code and tables retain their wider area.

The shared code renderer received the screenshot-equivalent mappings through three supported paths: text fences, section code and walkthrough code. It now presents recognizable arrow chains and lists of UI labels tagged as text in ordinary paragraphs. Ambiguous blocks and real commands retain their code formatting and copy action. Structured mappings retain readable rows when captured in Notebook. Contextual citations retain their PDF targets. The footer adds only pages and excerpts absent from the section citations. Library and Notebook now share the card header and use the persisted message ID. Notebook retains selected-text capture. The two destinations retain their existing server-side ownership checks.

The phrase "give me a short summary" previously passed the brevity classifier but entered the full teaching schema, which asked for optional examples, pitfalls, code and a review question. The brief path now recognizes other English, French and Arabic phrasing, gives precedence to explicit detail, and asks for one concise section, up to four useful bullets, and one or two citations. The provider response schema requests the compact shape under either task-mode setting. The default output ceiling for this path is 1,200 tokens, subject to configured provider limits and the existing budget policy. The public saved explanation format remains compatible. A one-section compact card can use the summary's heading as its title. Exhaustive walkthrough generation stays on its existing path. No new model call site or retrieval system was introduced.

| Area | Files changed in this follow-up |
|---|---|
| Backend | socra-backend/agents/explicateur.py, agents/explain_tasks.py |
| Chat and inquiry | socra/components/chat/ChatPanel.tsx, ExplanationCard.tsx, hooks/useSocraChat.ts, app/(dashboard)/dashboard/course/[courseId]/inquiry/[sessionId]/page.tsx |
| Shared presentation and notes | socra/components/notebook/NotebookReply.tsx, lib/ai/explanation-card-layout.ts, explanation-presentation.ts, explanation-note.ts |
| Regression tests | socra-backend/tests/test_explicateur.py, test_explain_coverage.py, socra/scripts/test-chat-browser.mjs, test-explanation-rendering.mjs |
| Roadmap | SOCRA_EXPLICATEUR_PLAN.md |

From socra-backend:

~~~powershell
.\.venv\Scripts\python.exe -m tests.offline_windows
~~~

200 tests passed in 21.713 s, with zero skips. The exact summary request used one mocked generation with each task-mode setting. Tests cover linguistic variants, explicit detailed requests, structured output and the existing exhaustive path.

From socra:

~~~powershell
$env:SOCRA_TEST_BROWSER='C:\Program Files\Google\Chrome\Application\chrome.exe'
node --test scripts/test-chat-browser.mjs scripts/test-direct-upload.mjs scripts/test-explanation-rendering.mjs scripts/test-notebook.mjs scripts/test-study-routes.mjs
node node_modules/typescript/bin/tsc --noEmit --incremental false
node node_modules/eslint/bin/eslint.js components/chat/ChatPanel.tsx components/chat/ExplanationCard.tsx components/notebook/NotebookReply.tsx hooks/useSocraChat.ts lib/ai/explanation-card-layout.ts lib/ai/explanation-presentation.ts lib/ai/explanation-note.ts scripts/test-chat-browser.mjs scripts/test-explanation-rendering.mjs 'app/(dashboard)/dashboard/course/[courseId]/inquiry/[sessionId]/page.tsx'
node .next/explain-ui-qa/validate-ui.mjs
~~~

38 frontend tests passed, with zero failures or skips. TypeScript, ESLint and git diff --check passed. The local Chrome fixtures rendered before and after with production components and styles. Chrome tested four chat combinations and 20 card combinations covering desktop and mobile, light and dark, all five profiles, scroll geometry and click-to-bottom behavior, focus, source links, grouped save actions and saved selection, prose width, and wider code. Legacy and restored cards passed separate tests. Actual provider output and a complete interactive Tab/Shift+Tab traversal remain pending. Verification used zero live provider calls, production changes, deployments, or pushes.


### Final student-focused walkthrough refinement - 2026-11-16

The supplied screenshots define the layout target. They are not fixtures for TP values or requirement coverage. The exact generating payload and saved row behind the expanded screenshot were unavailable. The local M1 archive contains four sections. Its setup, Orange, and KNIME content already arrives as dense prose. Its final section refers to Q1–Q6 and Captures 1–5 collectively, without distinct guidance for Capture 3 and Questions 5–6. The offline checker reports 14 missing and four partial requirements on that archive. The screenshot shows Capture 2 followed by Capture 4 and question guidance ending at Question 4 before the appendix. Neither the archive nor the screenshot alone establishes whether the photographed answer omitted those items or whether the stitch left them out. The shared renderer iterates stored sections in order, and expanded fixture DOM retains every supplied item.

The model can emit flattened metric rows as prose. The existing advisory lint detects an offline example but leaves its values unchanged. The Markdown pipeline renders real header/separator tables and preserves code, list starts, and continuation lines. There is no defensible column mapping for already-flattened rows. The provider's inline bracket numbers are generated text. The binder resolves structured excerpt indexes to owned-document/page metadata and discards the original structured indexes from saved sections. Bare bracket numbers in older text cannot reliably be mapped to excerpts after reload. The prompt now puts indexes in citation fields only. Section and phase links use bound page metadata and the existing owned PDF route. Excerpt disclosures retain filenames and text. The previous chat smoke and normal Chrome fixture verified one question/action and the scroll button outside the message viewport. No chat offset or duplicate-question changes were needed.

- **Renderer:** The one shared card keeps its five existing profiles. Long walkthroughs number major sections, group explicitly authored heading-only phases with their steps, open the first phase, show collapsed descriptions, and support Expand all and Collapse all. Structured Markdown retains its order. A concise prerequisite list may pair with a short shell block at a wide card width. Long scripts and tables retain the full content area. Authored checked boxes start unchecked and use existing user/message-scoped progress storage. Source links move to section headers and excerpt text remains in the existing disclosures. Coverage shows a short named overview with statuses when available. Details retain the stored requirement text and page references.
- **Generation:** The procedural prompt requests ordered single-action steps, nearby language-tagged commands and results, actual Markdown tables with preserved columns, dedicated capture/question headings, and conditional checklists and troubleshooting. The backend includes existing diagnostic reason text for English coverage entries. Runtime validation, citation ownership, provider call budget, flags, storage and public schema remain as before. Students can ask for follow-up in the existing composer.
- **Changed files:** socra/components/chat/ExplanationCard.tsx, socra/components/notebook/NotebookReply.tsx, socra/lib/ai/explanation-card-layout.ts, socra-backend/agents/explicateur.py, socra-backend/tests/test_explain_coverage.py, socra/scripts/explanation-card-fixtures.mjs, socra/scripts/test-explanation-rendering.mjs, and this plan.
- **Reused:** Existing code copy, Markdown/KaTeX rendering, local checklist persistence, source URL and server ownership validation, preview-to-final replacement, Library reload, Notebook capture/export, and the shared coverage/retry machinery.


Verification after the refinement:

| Check | Result |
|---|---|
| Backend `python -m tests.offline_windows` | 200 passed, 0 skipped. Included one-call mocked lab prompt and archived coverage replay. |
| Frontend `node --test scripts/test-chat-browser.mjs scripts/test-direct-upload.mjs scripts/test-explanation-rendering.mjs scripts/test-notebook.mjs scripts/test-study-routes.mjs` | 39 passed, 0 failed, 0 skipped. Included saved cards, stream recovery, PDF ownership and exact page URLs, and Notebook capture. |
| Targeted ESLint and `tsc --noEmit --incremental false` | Both exited 0. |
| Local Chrome, real card and ContextPanel in a fixture shell | 36 light/dark, mobile/narrow/desktop, and context-layout combinations passed across practical, short, mathematics, language and research profiles. Separate checks passed for the M1 archive and legacy card, accordion state, checklist on reopen, exact clipboard text via a test clipboard, focus, and citation activation. The native keyboard automation connection timed out, so a full real-key traversal was not verified. |
| Print | Chrome printed the collapsed fixture to three pages. Text extraction verified the closed sections, coverage notice and details, task list, full fixture script, screenshot checkpoint and comparison table. |
| Visual artifacts | Captured first-open, fully expanded, fully collapsed, Course Context open and mobile PNGs from Chrome. Inspected the desktop captures and confirmed the full expanded fixture reaches the deliverables. |

The exact screenshot answer and original source-index map remain unavailable. Existing prose and flattened table data remain as authored where the public payload lacks trustworthy structure. These changes need authorized provider evaluation on the selected TP to confirm that future output emits the requested structure with correct source metrics and all five capture and six question guides. No live provider calls, production writes, deployment or push were performed.


### Final universal card, source fidelity, and coverage calibration - 2026-11-16

Implemented the three reference layouts in the shared ExplanationCard. The pasted requirements and three supplied visual references guided the changes. Mockup values remain outside production code.

| Requirement | Audit and implementation |
|---|---|
| Coverage and repair | Existing scope, stable occurrence keys, required/optional handling, substantive floors, evidence checks and bounded repair were reused. Confirmed false negatives came from nested Markdown headings splitting guidance or scripts from their parent, composite capture labels, and Arabic feminine screenshot ordinals. Dedicated bold numbered question rows now keep their own guidance. Bare mentions remain partial or missing. Ambiguous structural gaps remain visible and are excluded from automatic repair; eligible substantive gaps still use the reserved repair slot. The archived M1 card still reports 14 missing and four partial items. |
| Notices and saved scripts | A full 30-section answer with a full example could previously shorten the final section to fit a notice. Final responses now carry optional overflow notices in that case, and both the card and Notebook read them. The model schema is unchanged. The compact notice displays the gap count, and its details show covered/partial/missing totals, readable requirement names, pages and English reasons with the matching section title where available. |
| Source accuracy and tables | Indexed p. 2 contains the standalone code result 5001 and the separate prose wording 5 001 lignes. Indexed p. 7 contains the two matrix rows separately. The newer raw model response and stored production row were unavailable, so the specific merged historical strings could not be attributed to a single layer. The fixture verifies the separate matrix counts and totals against indexed rows and checks the split, fraud counts and CSV lines. The prompt preserves numeric cell boundaries, source labels and blank template values. Markdown copying uses the original table text, including accents, and PDF links sort by page inside each document; existing ownership binding remains in place. |
| Exhaustive walkthrough | Reused native disclosures, checklist persistence, code copy and expected-result/troubleshooting styling. Adjacent authored sections with the same explicit Part/Partie prefix share a phase label and retain independent accordion rows. Heading-only phases still work. Sections, raw labels in exports, citations and authored content retain their order. |
| Standard and brief | Standard concept cards use the article hierarchy with a lead answer, section separators, contextual citations and optional source-backed numeric cards for explicit metric/value tables. Brief cards keep a direct answer, optional points or a small comparison table, compact sources and collapsed existing review material. Explicit one-sentence requests route directly to the same one-section brief generator with a strict sentence instruction. Older cards infer presentation from existing content. |
| Shared behavior | Reused the shared Markdown/KaTeX renderer, saved explanation history and preview-to-final streaming, library and notebook capture, code indentation, responsiveness and separate hidden language practice answers. No global style, schema migration, or provider/default change. |

Files changed in this pass: `socra-backend/agents/{explain_coverage,explain_tasks,explicateur}.py`, `socra-backend/rag/document_inventory.py`, `socra-backend/tests/{test_explain_coverage,test_explain_evaluation,test_explicateur}.py`, `socra/components/chat/ExplanationCard.tsx`, `socra/components/notebook/NotebookReply.tsx`, `socra/lib/ai/{explanation-card-layout,explanation-note}.ts`, `socra/lib/socra-ws.ts`, `socra/scripts/{explanation-card-fixtures,test-explanation-rendering}.mjs`, and this roadmap.

Call boundaries before and after: the normal answer uses one generation, the existing shared recovery budget remains in place, and at most one eligible targeted coverage repair shares the existing 90-second deadline. No additional formatting or continuation requests were added.

Manual live evaluation, pending authorization: with the same selected Orange/KNIME PDF in a test course, run (1) the original exhaustive request, checking each of five captures, six questions, Appendix A, the French comparison template and source counts/pages; (2) “Why normalize the features before kNN?”, checking the direct answer, source-gated values and practical steps; (3) “Give me a short summary”, then (4) “Explain the TP in one sentence.” Record primary/recovery/repair counts and time, compare streamed and persisted content, and save/reopen in Library and Notebook. Run the existing maths, language and research prompts if assessing release readiness. No live provider, production database, deployment or push actions were taken.


Verification:
- From socra-backend, `.\.venv\Scripts\python.exe -m tests.offline_windows` passed 201 tests with zero skips. M1 replay still reported 14 missing and four partial. No production rows were queried.
- From socra, `node --test scripts/test-chat-browser.mjs scripts/test-direct-upload.mjs scripts/test-explanation-rendering.mjs scripts/test-notebook.mjs scripts/test-study-routes.mjs` passed 43 tests with zero skips, with the installed Chrome selected through SOCRA_TEST_BROWSER. Targeted ESLint and `node node_modules/typescript/bin/tsc --noEmit --incremental false` passed.
- `node .next/universal-card-qa/verify.mjs` passed 54 theme/width/sidebar combinations at 360, 1050 and 1320 px across walkthrough, standard, compact, short, single-sentence, mathematics, language and research variants, plus the larger expanded fixture, M1 archive, legacy fixture and interactive walkthrough. The production React renderer and Socra styles were mounted in a local test shell. Eleven screenshots show all three requested presentations. Browser checks passed for focus-visible, source activation, disclosure, local progress across remount, exact clipboard text using a test clipboard, empty template cells, and separate practice-answer disclosure. Full hardware keyboard and assistive-technology traversals remain unverified.
- `node .next/universal-card-qa/print-only.mjs` verified the three-page Chrome PDF with collapsed phases, including its checklist, source/coverage content, final script, screenshot checkpoint and comparison table. `git -c core.safecrlf=false diff --check` passed.

## E. Codex execution prompts

One prompt per Codex session. Stop at the stated boundary. Attach the TP PDF, the bad-answer fixture and the `explicateur.py` snapshot only when useful; the real checkout is the primary source.

### Start here: Phase 0a

```text
Read SOCRA_EXPLICATEUR_PLAN.md (header, sections A-D including B1 and B2, and Phase 0a only), then inspect the actual Socra codebase.

Implement PHASE 0a ONLY:
1. Capture the baseline before editing (git state, TP inventory count if the TP text fixture is available locally, model-call upper bounds). Mark retrieved-page and chunk coverage as "pending M1".
2. Stop the runaway per-exercise LLM loop: numbered lists, Partie/Part/Question headings and "1." lines are not exercises; use ONE call when no genuine Exercise/Exercice is labelled; add a hard configurable cap on per-exercise calls with an incomplete result when exceeded, persisted per rule B2. Do NOT implement batching.
3. Make citation binding tolerant of individual invalid citations without ever fabricating citations.
4. Add privacy-safe diagnostics, including retrieved chunk IDs (never text), estimated retrieved tokens, and the distinct (document_id, page_number) list.
5. Optionally add the read-only coverage helper script from 0a.5, or document the manual queries for M1.

Use offline tests and mocks only. Do not call live models. Preserve old schemas, streaming, Notebook, Library and Supabase data. Do not implement 0b or later phases. Do not deploy or push.

Make real code changes and tests. Update only the completed 0a checkboxes, paste the actual test command output into your report, and list files changed, call-count limits and blockers.
```

### After 0a and your manual step M1: Phase 0b

```text
Read SOCRA_EXPLICATEUR_PLAN.md (header, sections A-D including B1 and B2, and Phase 0b only) and the Phase 0a report. Implement PHASE 0b ONLY: audit nested retries and add one shared bounded retry budget; handle transient errors before the first token with backoff and Retry-After; on finish_reason=length FIRST inspect whether explanation_preview or any existing helper can truly return complete deserializable sections (record the finding), otherwise implement a small tested partial-section extractor or return an explicit truncation error; salvage complete sections with an incomplete notice persisted per B2 and NO continuation model call; measure and, if needed, throttle explanation_preview parsing. Preserve streaming and stored-card compatibility. Offline tests and mocks only. Update the 0b checklist, paste test output, and STOP before Phase 1a. Do not deploy, push or call live models.
```

### After 0b: Phase 1a

```text
Read SOCRA_EXPLICATEUR_PLAN.md (header, sections A-D, and Phase 1a only) and the earlier reports. Implement PHASE 1a ONLY: rule-based intent/detail/content detection with two-signal scoring and negative cases; trace and document how state["language"] is set, then implement the matching language precedence including Arabic; short mode-specific prompts with no conflicting rules and the graded-question guidance rule; mode-aware repair messages; and the lab-safe payload normalization (do not extract the first fence into `code` or convert `code`: explanation lines into walkthrough rows for lab sections, passing the mode explicitly). Flag EXPLAIN_TASK_MODES defaults off in prod and on in dev; flag-off keeps the Phase 0 guardrails. Keep the existing schema and call budget. Do NOT implement batching or a depth selector. Offline logic tests only; do not assert real model output. Update the 1a checklist, paste test output, and STOP before Phase 1b. No deploy, push or live calls.
```

### After 1a: Phase 1b

```text
Read SOCRA_EXPLICATEUR_PLAN.md (header, sections A-D including B2, and Phase 1b only) and the earlier reports. Implement PHASE 1b ONLY: flagged (EXPLAIN_MULTI_EXERCISE_BATCHING) grouped generation of about 3-4 genuine exercises per call with a rewritten batch prompt, a configurable group cap, an incomplete notice persisted per B2 beyond the cap, and 0b truncation salvage inside groups. Flag off falls back to the Phase 0a capped behavior, never the old loop. Offline tests only. Update the 1b checklist, paste test output, and STOP. No deploy, push or live calls.
```

### Before Phase 2, you do M2 (limits config). Then: Phase 2

```text
Read SOCRA_EXPLICATEUR_PLAN.md (header, sections A-D, and Phase 2 only), the M1 results and the M2 limits config. FIRST do the 2.0 go/no-go using chunk coverage, required-marker presence in retrieved vs unretrieved chunks and retrieved tokens (not page coverage alone), and document the decision. Implement PHASE 2 ONLY: validated document selection (optional document_id in the request payload with a minimal UI selector, filename resolution, dominant-share fallback with logging, otherwise ask); the deterministic multilingual inventory built from ALL indexed chunks of the resolved document (independent of the chunks sent to the model) with language-independent requirement IDs and an inventory_scope label (full_document or retrieved_only); adding evidence chunks for required IDs that retrieval missed; and, only if 2.0 says build, budget-aware page-ordered full-document answer retrieval reading limits from config. Preserve focused RAG, ownership checks and flag rollback. Offline tests only, including the retrieval-gap test. Update the Phase 2 checklist, paste test output, and STOP before Phase 3a. No deploy, push or live calls.
```

### After Phase 2: Phase 3a

```text
Read SOCRA_EXPLICATEUR_PLAN.md (header, sections A-D including B2, and Phase 3a only) and earlier reports. Implement PHASE 3a ONLY (backend, no schema or frontend changes): the deterministic coverage checker (mention + per-type substantive floor + source-derived anchor, language-independent IDs, inventory_scope carried into the result), at most one bounded targeted repair/continuation call within the shared budget that sends only missing IDs and evidence, merging like _merge_exercise_explanations, and an incomplete notice persisted per B2 when still missing. Test the checker against two golden fixtures (good TP answer passes, original bad answer is flagged), plus per-type threshold, unretrieved-page, and retrieved_only cases. Flag EXPLAIN_COVERAGE_CHECK default off in prod. Offline tests only. Update the 3a checklist, paste output, and STOP before 3b.
```

### After 3a: Phase 3b

```text
Read SOCRA_EXPLICATEUR_PLAN.md (header, sections A-D including B2, and Phase 3b only) and earlier reports. Implement PHASE 3b ONLY: inspect GeneratedExplanation first, then add the optional per-section source_indexes and covers fields with individual validation and bound citations, keeping global citations; fix rendering so mixed GUI/command content in `content` displays in its original order, commands get language labels and copy buttons, GUI steps are numbered instructions, expected results are callouts labelled as source reference, and a stored B2 incomplete notice shows a clear marker (also after reload); hide empty irrelevant fields. Preserve old saved explanations, streaming, Library and Notebook. Add backend and frontend tests including the order test, run TypeScript checks, update the 3b checklist, paste output, and STOP before Phase 4. No deploy, push or live calls.
```

### Final: Phase 4 (after you provide the documents)

```text
Read SOCRA_EXPLICATEUR_PLAN.md (header, sections A-D, and Phase 4 only) and all earlier reports. Implement PHASE 4 ONLY: build the offline evaluation harness over the local, gitignored documents and checklists I provide (commit only synthetic text, checklists and results), compare against the recorded baselines, and produce a report on coverage, citations, language, responsiveness and call budgets. Prepare, but do not run, the live evaluation script. Run live provider tests only if I explicitly authorize them. Report flag-default recommendations and documentation updates. Do not deploy or push.
```

---

## F. Definition of success

A successful final Explicateur should:

1. Turn the exact English Orange/KNIME request into a **complete, actionable Windows TP walkthrough**, not a generic lecture.
2. Include source prerequisites, both Orange installation methods, KNIME setup, commands or conditional fallbacks, GUI connections and expected outcomes, in the order the student performs them.
3. Provide the **five capture checkpoints**, guidance for the six required questions, and the required report and exports; label bonuses optional.
4. Give **source-grounded** page citations; never call screenshots or results "verified" unless the student produced them.
5. Use code blocks **only for real code and commands**, preserve math, Markdown and ordering, avoid duplicated snippets.
6. Handle maths, languages, coding, data, research, exercise sheets and mixed documents with task-appropriate structure.
7. Honor explicit language choices, including Arabic where supported.
8. Use one generation call for typical requests; no uncontrolled per-section or per-exercise loops.
9. Know what the whole document requires (inventory) independently of what retrieval returned, and surface missing evidence or incomplete coverage persistently instead of inventing answers.
10. Preserve existing chat, RAG, auth, streaming, citations, Library and Notebook behavior.

**Highest-priority principle:** the improvements are not "write more tokens" or "use a paid model". They are: understand the task, know what the source requires, give the model the right material, format correctly, verify what matters, and stay within a bounded cost.
