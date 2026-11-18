# Socra — Implementation Roadmap

**Purpose:** Execute the full performance, UX, security, and reliability overhaul in **three batches of three phases**. The initial batch prioritizes what users notice most: immediate feedback, genuine AI streaming, and faster PDF readiness.

**Status:** Phases 1–9 have source changes in the repository. The remaining work is disposable-database verification, live workflow tests and provider measurements, and an authorized rollout.

## Phase implementation checklist

- [x] Phase 1 - Profiling and immediate chat feedback
- [x] Phase 2 - Authenticated WebSockets and streaming
- [x] Phase 3 - Background PDF indexing and Course Maps
- [x] Phase 4 - Direct uploads and index reuse
- [x] Phase 5 - Model selection and retrieval improvements
- [x] Phase 6 - Durable Practice and Exam workflows
- [x] Phase 7 - Study experience, citations, OCR, and password recovery
- [x] Phase 8 - Security, quotas, and database bootstrap
- [x] Phase 9 - Offline verification, cleanup, and rollout documentation

Checked phases have code in the repository. Open tasks below track remaining environment checks, measurements, and rollout.

## How to execute this plan with Codex

1. Open the entire Socra repository (Next.js frontend, FastAPI backend, Supabase migrations) on a dedicated Git branch.
2. Give Codex this file. Run **exactly three phases per implementation pass**: **1–3**, then **4–6**, then **7–9**.
3. At the start of each pass, inspect current code, note existing uncommitted changes, and verify prerequisites. Paths and architecture described below are **leads**, not guaranteed current facts.
4. Implement code, migrations, tests, and documentation relevant to **only** the selected three phases; avoid unrelated refactors. When tasks in a selected phase require an earlier security or data-integrity prerequisite, fix that prerequisite first.
5. After each phase, run applicable checks and update this file's task checkboxes only for work actually completed. Do not represent untested or blocked work as complete.
6. Finish each pass with: changed files, design decisions, tests run/results, measured before/after latency (if available), migration/env/deployment steps, blockers, and the **next three phases**.
7. **Do not deploy, spend money, change production data, or rotate credentials without explicit permission.** Use mocks or test data for automated tests, and preserve other developers' changes.

## Product baseline (verify in repo)

- **Frontend:** Next.js / React / TypeScript / Tailwind; `useSocraChat.ts`, `socra-ws.ts`, inquiry/diagnostic/course/exam pages, upload route and components.
- **Backend:** FastAPI / WebSockets / LangGraph; agents Diagnostiqueur, Tuteur Socratique, Évaluateur, Mémoire, Explicateur, Générateur d'exercices, Correcteur.
- **Data:** Supabase Auth, PostgreSQL, pgvector, Storage; course documents, document summaries, passages/embeddings, sessions, messages, profiles, exams, Library and Notebook.
- **Hosting:** Vercel and Render; cold starts and cross-region latency are **hypotheses** until measured.
- **Known symptoms:** Socratic tutor streams some text; Explain/Practice/exams can wait for complete structured output; an eight-page PDF reportedly takes ~2 minutes before upload flow finishes.

## Global rules for every phase

- Preserve all seven agents and existing modes, page citations, French/English support, course ownership, persistence, Library/Notebook integration, and exam answer secrecy.
- **Authenticate and authorize before reading session/course content** with service-role access. Every added background/job endpoint must enforce authorization.
- No raw private answer keys, rubrics, provider credentials, or internal model reasoning in client streams or logs.
- User-visible streaming must originate from the **actual model output**, not a fake typewriter over a complete response. Honest loading states are fine.
- No fake progress percentages. Use real stages, completed chunk counts, or indeterminate progress.
- Keep working indexes active until a replacement index is fully built; protect document versions against stale jobs.
- Do not assume an embedding provider call is fast or that a Render cold start is the culprit; **measure first**.
- Never rely on fire-and-forget in a short-lived web process for durable document jobs.
- Limit concurrency and retries; honor provider rate limits and prevent duplicate jobs/messages/grades.
- Use backward-compatible events/schema changes or migrations for old sessions and documents.
- Preserve uncommitted changes. Avoid production operations and costs without user approval.

## Engineering success targets (aspirational; measure p50 and p95)

| Metric | Target / requirement |
|---|---|
| Send-button UI response | Immediate local placeholder, ideally <100 ms |
| First text on warm, ordinary chat | Initial target ~2–6 s; measure actual |
| Explain responses | Visible genuine token/chunk streaming |
| PDF ready for RAG (ordinary 8-page text PDF) | Aim <30 s under healthy conditions; do not wait for Course Map |
| Course Map | Can finish later; independent of readiness |
| Exams / Practice | Real progress, safe validation, no solution leakage |
| Reliability | Recovery after refresh/disconnect/retry; no duplicate writes |
| Security | No session/document access before auth + ownership checks |

---

# Batch A — First pass: Phases 1–3

## Phase 1 — Baseline profiling + immediate feedback

**Outcome:** Student sees feedback immediately, and developers can locate actual latency bottlenecks.

### Tasks
- [x] Map live code paths for chat, diagnostic, Explain, Practice, exam, upload, embeddings, and summaries. Verify dependency versions and deployment settings.
- [x] Inspect `git status`; protect existing changes. Record baseline test/lint/typecheck outcomes.
- [x] Add correlated `request_id` / `job_id` and structured **timings**, without logging documents, prompts, answers, or secrets: socket connect, acknowledgement, retrieval, first token, model calls, verification, post-response evaluation, PDF upload, parse, chunk, embed, vector insert, summarize, and total.
- [x] Log page/chunk/batch counts, retries, and provider status for PDF operations.
- [ ] Compare warm and cold behavior in a representative environment.
- [x] On Send, immediately show the user message + assistant placeholder (typing indicator or skeleton), before the backend replies.
- [x] Make frontend stages honest: connecting, waiting, retrieving, generating, verifying, complete, failed; show elapsed time if helpful.
- [x] Open the socket on authenticated inquiry/diagnostic page mount when appropriate; clean up and reconnect safely with backoff, without duplicate connections.
- [x] Add clear timeout, retry and failure UI. Do not label a delay as “server waking up” without supporting evidence.
- [x] Test pending, slow, rejected, disconnected, and retry cases; verify no stuck loading UI.

### Done when
- The interface always shows immediate acknowledgement of user interaction, even with a slow backend.
- Timings make it possible to distinguish connection/cold start, retrieval, generation, validation, and summary latency.
- There are no duplicate messages from connect/retry paths; targeted checks pass.

## Phase 2 — Secure WebSocket + true conversation and Explain streaming

**Outcome:** Socratic and Explain answers display actual generated text as it arrives, while follow-up work no longer unnecessarily blocks the UI.

### Tasks
- [x] **Security gate:** Authenticate WebSocket before protected history/profile reads; verify user, course, and session ownership for every action, including Socratic turns. Avoid tokens in logged URLs. Add unauthorized-access tests.
- [x] Authenticate and authorize privileged document-summary/API routes before adding new job triggers.
- [x] Define and type a versioned event contract: `request_accepted`, `progress`, `content_delta`, `context_update`, `card_ready`, `response_complete`, `turn_finalized`, `error`. Include IDs and ordering; preserve compatibility with existing `token` / `done` clients during migration.
- [x] Trace LangGraph -> FastAPI -> WebSocket -> React; remove buffering, and stream **real** model deltas with efficient frontend batching.
- [x] Socratic path: profile initial diagnostic bottleneck; display diagnostic progress and simplify/restructure only when semantics are preserved. Do not blindly parallelize tutor and a diagnostic it depends on.
- [x] Persist visible answer before emitting `response_complete`; let Évaluateur/Mémoire finish separately (or update context afterwards) without races, out-of-order profile writes, or accidental mixing with a new turn.
- [x] Explain: stream readable Markdown or validated individual sections progressively, bind verified citations afterward, retain structured final cards, check questions, history reload, Library and Notebook saving.
- [x] Practice: display actual retrieval/generation/verification stages and skeletons; never stream private solution or rubric fields. Expose only validated exercise content.
- [x] Implement Stop, Retry, Regenerate, partial/cancelled states, safe backend cancellation and reconnect behavior; do not silently save partial content as verified final.
- [x] Improve live Markdown/code rendering, streaming update batching, accessibility announcements, and auto-scroll that respects user scroll position.
- [x] Add integration/component tests for event ordering, early answer completion, late context, cancellation, disconnect, content assembly, no duplicate messages, auth rejection and secrecy.

### Done when
- Socratic and Explain show actual generated content as it arrives.
- The student can type again after their answer completes, without waiting for optional evaluation, and profile consistency is preserved.
- Practice displays honest progress; no answer keys or internal model reasoning leak.
- WebSocket ownership is enforced, including before session data is loaded.

## Phase 3 — Make PDFs searchable before Course Map completion

**Outcome:** A PDF becomes usable when its index is ready; summary work continues safely in the background.

### Tasks
- [ ] Use Phase 1 timings to identify which part of the eight-page upload dominates. Record observed findings; do not claim speedups without measurements.
- [x] Separate `index_status` from `summary_status` (or adapt existing fields): pending/extracting/embedding/indexing/ready/failed and pending/running/ready/failed/not_applicable. Write additive, reversible-in-practice migrations and compatible API responses.
- [x] Change product readiness to **index ready**. Normal course-scoped vector search must work without section summaries; summary-guided retrieval activates once summaries are available.
- [x] Return request success / readiness without blocking on summary-generation LLM calls. Keep summary failures independent of indexing success.
- [x] Introduce **durable** jobs + a real worker for indexing/summarizing (prefer Supabase Queues/pgmq if suitable for the existing repo; use another existing supported queue if clearly better). Never depend solely on `after()`, `waitUntil()`, or in-process background tasks for durable work.
- [x] Implement job status, bounded retries/backoff, idempotency, version/content-hash guards, timeouts, worker restart recovery, permanent failure state, and safe document deletion while jobs run.
- [x] Run independent summary and embedding work concurrently after extraction where practical, with quota-aware concurrency; do not create redundant extraction.
- [x] Persist status for refresh/navigation; UI displays upload vs indexing vs summary status, real progress where available, Retry indexing/Retry summary, and actionable errors.
- [x] Ensure failed reindex operations don't destroy a working index; use an atomic or version-activation approach for index swaps.
- [x] Add and pass offline tests for search before Course Map completion, summary failure, retry and worker recovery, stale leases, and scanned, empty, or corrupt files.
- [x] Add SQL fixtures for duplicate dispatch, deletion while running, and stale activation.
- [ ] Run the PDF lifecycle SQL fixtures on disposable Supabase.
- [x] Document worker configuration, deployment needs and migration steps; do not deploy or purchase hosting without approval.

### Done when
- Search/QA works as soon as vectors are committed, even if Course Map is still processing or failed.
- Long-running jobs survive web request completion and can be recovered/retried.
- Real progress survives refresh and does not misrepresent document readiness.

---


# Batch B — Second pass: Phases 4–6

## Phase 4 — Direct uploads, duplicate handling, and ingestion efficiency

**Outcome:** Large and multiple PDFs upload reliably without the Vercel Function body-size bottleneck.

### Tasks
- [x] Replace multipart proxy-through-Next upload with browser-to-Supabase Storage using **server-authorized** upload destinations; verify course ownership, controlled path, uploaded object size/type and completion before enqueuing processing.
- [x] Consider resumable TUS uploads for larger files; provide actual network transfer progress, cancel/retry, and cleanup of abandoned storage objects.
- [x] Support bounded multi-file concurrency (initially 2–3), independent progress and failures, and worker backpressure.
- [x] Enforce separate upload, file-size, and processing quotas.
- [ ] Verify the configured 50 MiB maximum through upload, Storage, and indexing.
- [x] Use SHA-256-based duplicate detection/reuse keyed by embedding model/dimensions/chunking/preprocessing version; maintain per-user ownership isolation and avoid exposing cross-user text.
- [ ] Optimize chunk sizing, overlap, empty/duplicate chunks, vector insert batching, and provider requests **according to measurements**, not assumptions.
- [x] Keep re-embedding atomic/version-safe and avoid duplicating vectors when retrying.
- [x] Add and pass offline tests for small, large, multiple, and duplicate PDF workflows, interrupted upload, and orphan cleanup.
- [x] Add SQL fixtures for authorization, quota enforcement, and vector consistency.
- [ ] Run the upload and vector reuse SQL fixtures on disposable Supabase.

### Done when
- The full PDF no longer travels through a size-limited Next.js Function.
- Multi-file and duplicate flows are reliable, observable, and safe.

## Phase 5 — LLM, LangGraph, and RAG optimization

**Outcome:** Lower measured latency and model cost without losing educational correctness.

### Tasks
- [x] Profile every agent: model, first-token/total latency, input/output tokens where available, retries, structured-output errors and estimated cost.
- [x] Identify and reduce unnecessary sequential model calls, repeated retrieval, query embedding, excessive history, and avoidable database round trips.
- [x] Cache per-turn query embeddings and safe repeated computation; use bounded parallel execution only for independent retrieval/calls.
- [ ] Run the live Gemini/Groq comparison across Socratic, Explain, Practice and Exam. The runner is implemented and isolated from Supabase. This environment cannot reach either provider and has no configured Groq key.
- [x] Honor permitted provider selections and remove the Gemini 2.5 Flash family and floating Flash aliases from model selection and provider calls.
- [x] Review reasoning settings for lightweight calls. Gemini 3.5 Flash-Lite already defaults to minimal and the Groq GPT-OSS configuration already uses low, its lowest setting. Other reasoning changes await live quality data.
- [x] Evaluate whether structural checks can replace second-pass verification. A fixture with a valid citation, rubric and internally consistent choices still gave a factually wrong SQL answer. Independent verification stays enabled.
- [x] Improve retrieval quality with keyword and semantic search, page-aware citations, section guidance and identifier-ranked code examples. Labeled English, French and code questions passed the synthetic page checks. Representative live course retrieval remains unmeasured.
- [x] Review embedding model compatibility. Keep the supported 768-dimensional model, align query tasks and validate vector shape. Switching models requires a separate benchmark and full reindex before cutover.
- [x] Add regression tests and latency comparisons documenting outcomes and trade-offs.

### Done when
- Optimizations are backed by repeatable measurements and no known deterioration in grading/source-grounding tests.

## Phase 6 — Faster, reliable Practice and Exams

**Outcome:** Exercises and exams show progress and complete faster without compromising answers or scoring.

### Tasks
- [x] Provide immediate Practice placeholders and verifiable generation stages; release only validated student-safe exercises.
- [x] Generate independent exam questions with configurable bounded concurrency (start at 2–3), preserving requested formats, difficulty, balanced topics, source grounding, ordering and uniqueness.
- [x] Make exam generation a durable, resumable job with progress as **validated questions / requested total**, retries and safe cleanup on failure.
- [x] Persist each validated question idempotently; avoid duplicate questions on retries or out-of-order worker completion.
- [x] Permit answering before exam fully ready **only if** question immutability, final count, scoring and failure recovery can be guaranteed; otherwise keep exam gated.
- [x] Preserve deterministic grading for suitable formats and model-assisted grading for subjective work; never send answer keys/rubrics before authorization permits.
- [x] Make exam answer saving and submission idempotent and recoverable after interruption; avoid duplicate grading.
- [x] Pass offline tests for concurrent generation, topic and format planning, question secrecy, partial failures, and restart recovery.
- [x] Add SQL fixtures for attempt idempotency and final scoring.
- [ ] Run the exam SQL fixtures on disposable Supabase.

### Done when
- Exams expose real preparation progress and complete more efficiently, without inconsistencies or accidental answer disclosure.

---

# Batch C — Third pass: Phases 7–9

## Phase 7 — Study UX, context, Library, Notebook, and learning features

**Outcome:** A polished, consistent learning workflow across devices and refreshes.

### Tasks
- [x] Persist evaluator key terms and source-verified suggested readings on the completed assistant message. Reload them into Course Context and replay them on retry.
- [x] Verify that later Socratic turns load the stored diagnostic and keep using the existing session profile.
- [x] Open the exact source PDF page through an ownership-checked redirect. Provide a side panel from suggested readings and Course Map sections.
- [x] Display partial or missing Course Map state with retry and rebuild controls.
- [x] Implement optional local OCR with page preservation, clear latency and quota information, retry support, and offline tests. Real Poppler and Tesseract recognition on a representative scan awaits a configured worker.
- [x] Save completed Explain cards from persisted assistant metadata, reopen them in Library, and convert them into editable Notebook notes.
- [x] Use mobile viewport height, accessible panel controls, focus restoration, Escape, and status announcements in the study UI.
- [x] Implement forgot-password and recovery-session-bound password update. Live email delivery and reset verification remain pending.
- [x] Review cross-session mastery and spaced repetition. Defer new learning features until the core workflows are verified in a live environment.

- [ ] Run password recovery through live Supabase email and verify OCR with Poppler/Tesseract against a representative scan.

### Done when
- Context survives refresh; documents and citations are easy to inspect; Library/Notebook continue to work with streamed content.

## Phase 8 — Defense-in-depth security, data integrity and operations

**Outcome:** All privileged pathways are consistently protected and long-running operations are safe.

### Tasks
- [x] Review Next.js routes, FastAPI, WebSockets, jobs, exams, Storage and service-role writes. Remove redundant public model entry points and enforce owned PDF and explanation sources.
- [x] Add shared per-user operation quotas for chat, Practice, Explain, exam jobs, OCR and PDF retries. Preserve existing upload and processing caps.
- [x] Review browser key storage, durable credential encryption, logging and content rendering. Add baseline security headers and bind recovery cookies to the authenticated session.
- [x] Verify the worker claims and writes jobs directly through service-only Supabase operations, with leases, ownership checks, version guards and bounded retries. It has no backend HTTP endpoint.
- [x] Verify upload MIME and actual PDF content, bound extraction memory and text, and treat retrieved PDF instructions as untrusted evidence.
- [x] Keep atomic index swaps and exam transactions. Queue Storage cleanup on deletion and preserve OCR mode across a retry.
- [x] Add a loopback-only Supabase bootstrap with core tables, RLS, Storage and migrations. Running it from an empty disposable stack is still pending.
- [x] Add offline and SQL tests for cross-user access, private answers, invalid files, stale leases, quotas and cleanup. SQL fixture execution requires local Postgres.

- [ ] Execute the entire SQL migration chain and security fixtures in a disposable Supabase instance.

### Done when
- Sensitive data and expensive model operations are consistently protected; schema and job state can be reproduced and recovered safely.

## Phase 9 — End-to-end verification, code cleanup and deploy readiness

**Outcome:** Tested, documented changes that can be deployed deliberately.

### Tasks
- [x] Run and record offline backend, TypeScript, ESLint, browser, route and frontend build checks.
- [x] Cover chat ordering and streaming, cancellation, upload retries, indexing, OCR recovery and exam jobs with fixtures. A live authenticated run of the full workflow remains pending.
- [x] Resolve the affected frontend lint findings, including the existing JSX escaping and hydration diagnostics.
- [x] Remove the legacy Next.js chat and context routes and their provider adapters after checking the repository for consumers.
- [x] Update architecture, environment configuration, socket events, queue/worker setup and migration instructions.
- [x] Document the benchmark and load procedure. Record offline p50/p95 and leave live measurement pending until a representative environment is available.
- [x] Review source for secrets, unsafe defaults, migrations and compatibility issues. Record deployment prerequisites and existing operational limits.
- [x] Document Vercel, Render, worker and Supabase rollout steps and cost-requiring decisions.
- [x] Record shipped features, tests, performance, blockers, and remaining manual checks.

- [ ] Run live workflow and representative load/provider benchmarks before rollout.

### Done when
- The repository builds/tests in the available environment, documentation matches code, and deployment steps are explicit; any untested or blocked items remain visibly unchecked.

---

## Batch completion checklist (repeat after every three phases)

- [x] Tests run and exact results recorded, including existing failures versus introduced failures.
- [x] Pass offline regression checks for unauthorized requests, private-answer projection, and credential redaction.
- [ ] Verify access controls and logs in a live test environment.
- [x] Pass offline workflow checks for chat, exams, PDF citations, and Library-to-Notebook conversion.
- [ ] Run the signed-in course, chat, exam, Library, and Notebook smoke checklist.
- [x] Document database migrations and deployment requirements.
- [ ] Verify the full migration chain and rollback procedure on disposable Supabase.
- [x] Measurements and claims distinguish **observed** results from expected benefits.
- [x] This roadmap reflects what actually changed, with uncompleted tasks left unchecked.
- [x] Final report identifies remaining verification and rollout work.


## Batch A verification

| Check | Result |
| --- | --- |
| Backend baseline | 60 tests passed. The backend uses unittest and has no pytest dependency. |
| After Phase 1 | Existing 60 backend tests and the TypeScript check passed. |
| Phase 2 integration | FastAPI and real LangGraph with fake providers and database covered authorization, genuine deltas, card validation, cancellation, disconnect, early completion, late context, replay and exam isolation. |
| Phase 3 and combined backend suite | 75 tests passed. Worker tests covered parse and page numbering, corrupt/empty PDFs, persisted extraction reuse, vector readiness without a summary, lease loss and bounded recovery. |
| Browser | The production React hook passed the headless Chromium smoke test with a fake socket. It exercised immediate feedback, slow stages, delta assembly, Stop, rejection, disconnect, retry, late context and refresh recovery. |
| Frontend build | TypeScript passed. An isolated webpack production build passed with mocked Google Font responses. The default build hit the sandbox's Google Fonts network restriction. |
| ESLint | Workspace baseline had 22 errors and 9 warnings. The remaining diagnostics are in existing untouched files (20 errors and 4 warnings in the full workspace). |
| Database | Verified core table columns, RLS policies and the vector RPC through hosted read-only metadata. The new local SQL fixture covers duplicate dispatch, lease reclaim, atomic replacement, stale activation and deletion. It requires a disposable database with the baseline schema. |
| Local PDF timing | An eight-page synthetic PDF with eight chunks took 218.9 ms p50 and 260.0 ms p95 to parse and chunk over 20 runs, including Node startup. Storage, provider and SQL times were excluded. |
| Live timing | Warm/cold socket, first model text, end-to-end PDF readiness and the source of the reported eight-page delay remain unmeasured. |

Rollout requires applying the two migrations in order, starting the Python PDF worker from a full checkout, and releasing the frontend and WebSocket backend together. See `DEPLOYMENT.md`. Remaining verification covers the migrations against disposable Postgres, real providers, and an authenticated Library/Notebook smoke test. No deployments, production writes or infrastructure purchases were performed.

## Batch B verification

| Check | Result |
| --- | --- |
| Phase 4 | Direct upload and PDF worker tests cover signed transfer, resuming from Storage's offset, finalization retry, origin validation, two-file concurrency, index reuse and orphan cleanup. The SQL fixture additionally checks ownership, separate quotas and atomic reuse. |
| Phase 5 | Retrieval tests cover keyword fallback, request-local coalescing, rank fusion, bounded history, source pages and content-free metrics. Synthetic retrieval fallback p50/p95 went from 114.7/137.9 ms to 52.7/64.5 ms over 15 samples. |
| Phase 6 | Exam tests cover balanced schedules, concurrent slots, ordering, secrecy, partial failure, resuming saved questions and grades, and rejecting incomplete submissions. The SQL fixture checks ownership, answer replay, duplicate attempts and final score. Six simulated question slots took 187.5/196.2 ms p50/p95 sequentially and 93.5/94.6 ms with concurrency of two over 15 samples. |
| Combined verification | 91 offline backend tests and four direct-upload tests passed. TypeScript, ESLint on changed source files, the Chromium chat smoke test and an isolated webpack production build with mocked Google Fonts passed. Full-workspace ESLint reports 20 errors and four warnings in existing files. |
| Deferred verification | The SQL fixtures require a disposable Socra database. The configured 50 MiB limit has been inspected. End-to-end maximum upload size, real provider latency and cost, representative retrieval accuracy, and hosted exam recovery are unmeasured. |

The synthetic timings use simulated provider/database delays. The second-pass exercise verification and current embedding model are retained. Real Gemini/Groq comparisons, reasoning settings, representative chunk and index tuning, and any full reindex remain open. See `DEPLOYMENT.md` for migration order, signed upload rollout, and worker configuration. No hosted changes or deployments were made.

### Phase 5 follow-up

The historical repository had a Gemini 2.5 Flash-Lite default. The current source also offered Gemini 2.5 Flash in Settings. Hosted message metadata contains no model IDs, so historical provider usage cannot be reconstructed from those rows. Client migration, the Next.js resolver and the Python model factory now use the pinned default for blocked IDs.

Read-only Supabase verification found 245 existing vectors across 19 documents, all 768-dimensional and without a model tag. The existing HNSW index is present. Three labeled synthetic questions returned the expected page first in PostgreSQL keyword ranking and in the offline hybrid ranking fixture. A separate fixture rejects a structurally valid question with an incorrect answer through the independent verifier. The follow-up passed 97 offline backend tests, four upload tests, TypeScript and the Chromium smoke test with saved model migration. Re-running the simulated retrieval benchmark gave 114.8/124.6 ms p50/p95 before and 43.3/63.7 ms after. Real-provider latency, token cost and representative course retrieval remain open.

## Batch C verification

| Check | Result |
| --- | --- |
| Backend | 102 offline tests cover authenticated socket ordering, cancellation and replay, context persistence and citation grounding, PDF parsing and OCR orchestration, deleted Storage object cleanup, and exam generation/grading restart. |
| Frontend | Eight Node tests and the Chromium chat smoke passed. The isolated Next.js webpack production build, TypeScript and full-workspace ESLint passed. The build used mocked Google Fonts because the environment cannot fetch external fonts. |
| Database | Read-only hosted metadata confirmed the existing core schema, RLS, pgvector extension and owner/course path format for all 20 documents. New SQL fixtures and fresh local bootstrap still need a disposable Supabase stack. |
| Simulated performance | Retrieval fallback was 115.4/125.2 ms p50/p95 before and 52.3/69.3 ms after. Six exam slots were 188.5/218.2 ms sequentially and 94.7/129.3 ms at concurrency two. These are offline fixtures, not hosted measurements. |
| Rollout | Apply the feature migrations in order, release Next.js, FastAPI and the worker together, configure recovery redirects, and install OCR binaries on the worker host. See `DEPLOYMENT.md`. No production changes were made. |

All roadmap phases now have code. Live acceptance, database migration verification, representative provider/load measurements and rollout are still open.

## What Codex should report at the end of each batch

Use this compact format:

1. **Implemented:** Phases and features actually changed.
2. **Files/migrations:** Key paths and migration order.
3. **Tests:** Commands, passed/failed/skipped with reasons.
4. **Performance:** Baseline and new metrics, or say `not measured`.
5. **Deployment:** Environment/worker/queue changes; any approval needed.
6. **Remaining:** Blockers and next three phases.

**Remember:** A successful batch means working source changes plus evidence—not a generated plan or unverified completion claim.
