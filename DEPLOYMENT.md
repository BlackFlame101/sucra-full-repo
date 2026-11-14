# Socra deployment

This repository contains two apps in one GitHub repository:

- `socra/`: the Next.js web app, deployed to Vercel.
- `socra-backend/`: the FastAPI and LangGraph API, deployed to Render.

Both services use the existing Supabase project. Do not create a new Supabase project unless you intend to migrate the existing course data.

## 1. Deploy the backend to Render

1. In Render, choose **New → Blueprint** and connect `BlackFlame101/sucra-full-repo` on branch `main`.
2. Render reads the root `render.yaml` and creates the `socra-backend` web service. Choose the Free plan for a no-cost test deployment.
3. Enter these secret values when Render asks:
   - `SUPABASE_URL`: the project URL from Supabase project settings.
   - `SUPABASE_SERVICE_ROLE_KEY`: the server-side service-role/secret key from Supabase. Keep it private.
   - `GEMINI_API_KEY`: the Gemini key used by the backend.
   - `GROQ_API_KEY`: optional server-side Groq key for the Groq provider.
   - `FRONTEND_URL`: the exact production origin for the Vercel site, for example `https://my-socra-project.vercel.app` (no trailing slash).
4. Wait until the service is live, then open `https://<render-service>.onrender.com/health`. A successful response confirms the backend started.

The blueprint sets the backend root directory, locked `uv` install, Uvicorn command, health check, model, and log level. Render assigns the public service URL after creation; use that URL in the next step.

## 2. Deploy the frontend to Vercel

In Vercel, either update the existing project’s Git connection to `BlackFlame101/sucra-full-repo`, or create a new Vercel project from that repository. Set **Root Directory** to `socra` and deploy branch `main`.

Add these variables for the **Production** environment (and Preview too if you want preview deployments to work):

| Variable | Value |
| --- | --- |
| `NEXT_PUBLIC_SUPABASE_URL` | Existing Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Existing Supabase publishable/anon key |
| `SUPABASE_SERVICE_ROLE_KEY` | Existing Supabase service-role/secret key; server-side only |
| `SOCRA_BACKEND_URL` | `https://<render-service>.onrender.com` |
| `NEXT_PUBLIC_BACKEND_WS_URL` | `wss://<render-service>.onrender.com` |
| `NEXT_PUBLIC_APP_URL` | The production Vercel origin, for example `https://my-socra-project.vercel.app` |

After entering the variables, redeploy the frontend. `NEXT_PUBLIC_BACKEND_WS_URL` is embedded in the browser bundle during the build, so changing it requires a new deployment.

## 3. Supabase and authentication

Keep using the current Supabase project so courses, documents, users, and exercises remain available. The current schema already includes the exam, exercise, attempt, and document-summary tables. The repository also includes SQL migrations under `supabase/migrations/`; do not apply them again blindly to the existing database. If you create a different Supabase project, first inspect its migration history and apply only migrations it is missing.

If the Vercel hostname changes, add the production URL to Supabase Auth’s Site URL and Redirect URLs. Keep the service-role key only in server environments; never prefix it with `NEXT_PUBLIC_`.

## 4. Verify the deployment

1. Open the Render `/health` endpoint and confirm it returns a successful response.
2. Open the Vercel site and sign in.
3. Open an existing course and inquiry; confirm the chat WebSocket connects and the course context loads.
4. Try one exam start and one document upload with a small PDF.
5. If chat cannot connect, check `FRONTEND_URL` on Render and `NEXT_PUBLIC_BACKEND_WS_URL` on Vercel. If exam/document server calls fail, check `SOCRA_BACKEND_URL`.

## Hosting limits to know

- Render Free services sleep after 15 minutes without inbound traffic. The next request or WebSocket connection can take about a minute to wake the backend. Upgrade the service if that delay is unacceptable.
- Vercel Functions cap request and response bodies at 4.5 MB. The upload route sends only JSON through Vercel. The browser transfers PDF bytes directly to Supabase Storage.
- The frontend and backend need matching production URLs: Vercel’s origin in Render `FRONTEND_URL`, and Render’s HTTPS/WSS URL in the Vercel backend variables.

## Phases 1–3 rollout

The current entry points are Next.js 16.2.3 / React 19.2.4, the Python 3.12 FastAPI and LangGraph service, and Supabase Auth, Storage and pgvector. Vercel serves Next.js. The existing Render Blueprint starts Uvicorn as a free web service. Start the PDF worker separately on a host you already control with a full checkout, Node.js, Python and the required environment variables.

1. Verify the change in a disposable Supabase environment that already has the Socra baseline schema and historical migrations. The historical migration directory assumes pre-existing core tables. Apply `20261113135000_chat_turns.sql`, then `20261113140000_processing_jobs.sql`. Run `psql -v ON_ERROR_STOP=1 -f supabase/tests/phase_1_3.sql` against that environment with its database connection configured.
2. Install the pinned dependencies with `npm ci` in `socra` and `uv sync --locked --no-dev` in `socra-backend`. Ensure the worker can locate `socra/scripts/extract-pdf.mjs` and the frontend's installed `unpdf` package.
3. Set the worker's `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `GEMINI_API_KEY`. `CHAT_MODEL` follows the existing backend setting. Set `SOCRA_NODE_BIN` if Node is outside PATH. For personal Gemini keys, generate a fresh base64-encoded 32-byte `SOCRA_JOB_ENCRYPTION_KEY` and set the same value in Next.js and the worker. Keep it server-side. Drain pending jobs before changing this key. A personal key is encrypted per document and cleared from job rows on completion or permanent failure.
4. Start the worker from `socra-backend` with `uv run python -m worker`. Start with one worker. It can process one index job and one summary job concurrently. Keep the process running after uploads return. Queue state stays in Postgres when the worker stops.
5. Release the frontend and WebSocket backend together in a maintenance window after the migration. The migration makes derived PDF and chat writes service-role only. The old synchronous upload and unauthenticated Socratic clients need the coordinated release. New chat clients negotiate protocol 2. Authenticated legacy clients can receive protocol 1 events.
6. Verify a text PDF becomes searchable while its Course Map is queued. Then verify first text, Stop, Retry, reload, Explain citation cards, Library/Notebook saving and a Practice attempt in a test account.

For rollback, first pause uploads and drain or retain the queue. Restore prior route code and the prior table grants if rolling the entire application back. Keep the additive columns and job tables so queued work can resume. Use a reviewed forward migration to restore the original vector function and any grants needed by the prior routes. Existing document IDs, Storage objects and committed vectors remain in their original tables.

The worker preserves PDF page numbers, stops at 300 pages or one million extracted characters, and reports scanned/empty PDFs as requiring OCR. The course page lists search and Course Map statuses separately and exposes their retry controls. Rebuilding an existing index retains its current vectors until the database commits the replacement.

## Phases 4-6 rollout

1. After the Phase 1-3 migrations, apply `20261113143000_direct_pdf_uploads.sql`, `20261113150000_retrieval_efficiency.sql`, and `20261113153000_durable_exams.sql` in that order to a disposable Socra database. Use `psql -v ON_ERROR_STOP=1 -f supabase/tests/phase_4_5.sql -f supabase/tests/phase_6.sql` against that database. Both fixtures roll their changes back.
2. Keep the `documents` bucket private, with `application/pdf` enabled. The application and the inspected bucket are configured for up to 50 MiB per file. Run a complete 50 MiB upload and indexing job against the target test environment to verify its project and storage limits. Test a small signed PUT and an interrupted signed TUS transfer above 6 MiB. Confirm resume uses the byte offset returned by Storage. Resume is available while the original file remains in the upload dialog.
3. Coordinate the migrations with the Next.js, FastAPI and worker release. The upload migration restricts browser writes to the documents bucket. The new upload routes issue signed destinations and the server handles deletion. Set the same server-side `SOCRA_JOB_ENCRYPTION_KEY` in Next.js, FastAPI and the worker if accepting student-supplied API keys. Keep that key until jobs using it have finished.
4. Run the existing worker command from a full checkout. One process handles PDF indexing, Course Maps, exam generation, exam grading and upload cleanup. `SOCRA_EXAM_CONCURRENCY` defaults to 2 and accepts 1-3 concurrent slots per generation job. Start with one worker and check provider limits before increasing concurrency. Jobs have a five-minute lease and transient failures get up to three processing attempts. Retrying a failed exam keeps committed questions and grades. Deleting its session cascades the job and the partially generated questions.
5. The upload flow allows up to 24 new reservations per user per rolling 24 hours and eight outstanding reservations. Queued/running PDF work has a separate budget of 12 units per user, with a slot reserved for an index job's dependent Course Map. A file already transferred can retry finalization after the processing queue drains. Cancelled and abandoned reservations and their unreferenced Storage objects become eligible for cleanup after 51 hours.
6. `GROQ_CHAT_MODEL` sets the server default when the request has no selected Groq model. Set `GROQ_BACKUP_MODEL` to enable one structured-generation fallback after a provider JSON rejection. Leave it blank to use the selected model throughout. Set `SOCRA_MODEL_PRICES_JSON` to provider/model entries with `input` and `output` rates in USD per million tokens. Metrics omit token counts and estimated cost when the provider does not return usage. The existing embedding model and dimensions remain compatible with prior vectors.
7. Verify one account cannot reserve, finalize or read another account's files or exams. In the test account, verify Practice and a mixed exam with a worker restart during generation and grading. Check that question order and formats are preserved, no questions are released early, saved answers survive reload and only completed exams expose solutions. For a representative course, record paired warm/cold p50 and p95 and check citation accuracy and verified exercise quality before tuning providers, chunks or verification.

Offline checks are documented in `socra-backend/README.md`.


## Phases 7–9 rollout and verification

### Local database and worker

1. Start a fresh local Supabase stack in a disposable directory with the Supabase CLI and Docker. Keep the bootstrap separate from the hosted migration directory so the production schema is never reset. From this repository, run `pwsh -File supabase/bootstrap/local.ps1 -DatabaseUrl <local-postgres-url>`. It loads the core tables, ownership policies, private bucket and vector index, applies the historical and feature migrations in filename order, then runs the rollback-only SQL fixtures.
2. Install the locked frontend and backend dependencies. Start Next.js, Uvicorn and `uv run python -m worker` in separate processes. The worker authenticates directly to Supabase with the service credential. It has no HTTP entry point. Use a full checkout with Node.js and the frontend's `unpdf` package installed.
3. For local OCR, install Poppler, Tesseract, and the English and French trained data on the worker host. OCR is student-triggered and runs locally on at most 20 textless pages per job. It preserves original page numbers and uses the normal Gemini embedding quota once text is extracted. Use `SOCRA_PDFTOPPM_BIN`, `SOCRA_TESSERACT_BIN` and `SOCRA_OCR_LANGUAGES` only if the worker needs overrides.

### Hosted rollout

1. Confirm a backup and compare the hosted migration history with the repository. Apply the six feature migrations in order from `20261113135000_chat_turns.sql` through `20261113160000_study_security_and_ocr.sql`. Do not run the local bootstrap against the hosted project. Apply migrations before releasing the coordinated frontend, FastAPI and worker versions. The new quota and queue checks depend on the last migration.
2. Allowlist the app's `/auth/callback?next=/reset-password` recovery redirect in Supabase Auth, preserving the existing sign-up callback. Test the configured email template and delivery from a test account. Recovery links use the browser that requested the link.
3. Set the shared encryption key for durable jobs in all three processes, and keep provider keys in the backend/worker environment. The frontend no longer sends model traffic directly to providers. Browser-supplied keys are still stored in local browser storage and are available to same-origin JavaScript. Keep third-party tracing disabled unless the handling of student material has been explicitly approved.
4. Verify short-lived PDF links and embedded PDF rendering in supported browsers. The built-in PDF viewer handles the page fragment. If a browser cannot display the side panel, use the Open PDF link. Exercise and exam solutions remain server-owned.
5. Release the worker on an existing host. Approve any new paid always-on service, paid email provider, or billed model/load test separately. Retain queued work during rollback. Revert the matching application and worker versions together and review compatibility before changing grants or schema.

### SocraDB migration history

All six feature migrations were applied to SocraDB on November 13, 2026. Supabase recorded its own migration versions when applying the SQL. Use the mapping below when comparing history or preparing a future migration push to SocraDB so the same SQL is applied only once. The repository versions still define the order for a fresh database.

| Repository version | SocraDB version | Migration |
| --- | --- | --- |
| 20261113135000 | 20261113230650 | chat_turns |
| 20261113140000 | 20261113230704 | processing_jobs |
| 20261113143000 | 20261113230714 | direct_pdf_uploads |
| 20261113150000 | 20261113230719 | retrieval_efficiency |
| 20261113153000 | 20261113230724 | durable_exams |
| 20261113160000 | 20261113230737 | study_security_and_ocr |

### Workflow and performance checklist

Use a disposable account and synthetic PDFs for these checks. Keep the test database separate from production.

- Sign in, request a password reset and complete it through email in the same browser. Try an expired link and a signed-out PDF citation.
- Upload an eight-page text PDF, a representative scanned PDF, and a file above 6 MiB. Interrupt and resume the larger transfer. Confirm search works before the Course Map finishes, retry its summary, and OCR the scan. Check cited page numbers and then remove a course and confirm its objects are cleaned up by the worker.
- Exercise Socratic first text, Stop, reconnect and retry. Reload after the late evaluator update and compare Course Context. Stream an Explain card, save it, reopen it in Library, convert it into an editable note, then reload. Try access from a second account.
- Start a mixed exam and restart the worker during generation and grading. Confirm persisted progress, duplicate protection, and solution visibility only after scoring. Replay the same request and exercise the per-user limits from two accounts.
- Run the backend unittest suite, `node --test scripts/test-direct-upload.mjs scripts/test-study-routes.mjs`, the Chromium smoke script, TypeScript, ESLint and a production build. See the backend README for commands.
- Record 20 warm runs and a separate cold series. Compare the same PDF and prompts under the same provider/model on each version. Record p50/p95 for socket connect, acknowledgement, first visible text, index activation, Course Map completion and exam completion. Also record queue wait, provider errors and token usage. Start at one client and repeat at two and five only within the approved quotas. Keep deployment cold-start results separate from local fixture results.

### Notebook workspace

Apply `20261114012639_notebook_workspace.sql` after the existing Socra feature migrations in the intended database before releasing this frontend. It preserves legacy text and adds structured content, tags, stars, note versions, and atomic chat capture. Run `supabase/tests/notebook_workspace.sql` against a disposable database and `node --test scripts/test-notebook.mjs` from `socra`. Exercise note creation, a two-tab version conflict, and chat capture before rollout.

SocraDB already has this migration under hosted version `20261114015553`. Match it to repository version `20261114012639` when comparing migration histories.
