# Socra Backend (Python · FastAPI · LangGraph)

Multi-agent Socratic tutoring backend that powers the Next.js Socra frontend.
Orchestrates four agents (**Diagnostiqueur**, **Tuteur Socratique**,
**Évaluateur**, **Mémoire**) with LangGraph and streams answers over
WebSocket.

> Scope: see `../scope2.md`.
> The Next.js frontend (in `../socra/`) is unchanged.

## Status

Phases implemented:

| Phase | Description                                                                  | Status |
| ----- | ---------------------------------------------------------------------------- | ------ |
| 1     | Python project setup, FastAPI skeleton, Supabase client + DB modules         | done   |
| 1.3   | New tables `student_profiles` + `diagnostics` (with RLS) applied via MCP     | done   |
| 2     | RAG layer (Gemini embeddings + pgvector retriever)                           | done   |
| 3     | LangGraph state contracts + orchestrator + conditional edges                 | done   |
| 4     | Agent **Diagnostiqueur** — Gemini chain + JSON parser + RAG + persistence    | done   |
| 5     | Agent **Tuteur Socratique** — streaming, RAG-grounded, profile-aware         | done   |
| 6     | Agent **Évaluateur** — key terms + suggested readings + comprehension score  | done   |
| 7     | Agent **Mémoire** — deterministic profile updates persisted to Supabase      | done   |
| 9     | FastAPI WebSocket endpoint `/ws/chat/{session_id}` with token streaming      | done   |
| 10    | Next.js frontend integration (replace `/api/chat` + diagnostic page)         | not yet |
| —     | Re-embed existing chunks with `gemini-embedding-001` + fix `/api/upload`     | not yet |

## Requirements

- Python 3.12 (managed via [`uv`](https://github.com/astral-sh/uv))
- A Supabase project with the V1 schema + the two new tables (already applied)
- A Gemini API key

## Setup

```bash
cd socra-backend
cp .env.example .env   # fill in your keys
uv sync
```

## Run

```bash
uv run uvicorn main:app --reload --port 8000
```

Endpoints:

- `GET /health` — liveness + agent inventory
- `GET /docs`   — OpenAPI / Swagger UI

## Smoke tests

```bash
# RAG: embed a query and retrieve top-K chunks from a real course
uv run python scripts/smoke_rag.py

# Full LangGraph: Diagnostiqueur → Tuteur → Évaluateur → Mémoire (no streaming)
uv run python scripts/smoke_graph.py

# WebSocket end-to-end: connect, send 2 turns, verify streaming + context panel.
# Requires the server to be running first (see below).
uv run python scripts/smoke_ws.py
```

## WebSocket protocol

Endpoint: `ws://localhost:8000/ws/chat/{session_id}`

**Client → server** (one frame per student message):

```json
{ "message": "I want to learn about star schemas.", "courseId": "<uuid>", "sessionId": "<uuid>" }
```

**Server → client** (multiple frames per turn):

```json
{ "type": "diagnostic", "content": { ...DiagnosticReport } }   // first turn only
{ "type": "token",      "content": "<partial assistant text>" } // many
{ "type": "context",    "content": { ...EvaluationResult } }    // when Évaluateur ran
{ "type": "done" }                                              // always — turn finished
{ "type": "error",      "content": "<message>" }                // on failure
```

## Layout

```
socra-backend/
├── main.py                   FastAPI entry point
├── config.py                 Env-backed Settings (Pydantic)
├── pyproject.toml / uv.lock
├── api/                      HTTP & WebSocket routes
│   ├── routes/health.py
│   └── websocket.py          Phase 9 — /ws/chat/{session_id}
├── agents/                   The 4 Socra agents (all real)
│   ├── llm.py                Shared Gemini chat-LLM factory (with retries)
│   ├── diagnostiqueur.py     Phase 4
│   ├── tuteur_socratique.py  Phase 5 (streaming + heuristic TutorSignal)
│   ├── evaluateur.py         Phase 6 (silent eval, persists key_terms)
│   └── memoire.py            Phase 7 (deterministic profile updater)
├── prompts/                  System prompts (one file per agent)
│   ├── diagnostiqueur_prompt.py
│   ├── tuteur_socratique_prompt.py
│   ├── evaluateur_prompt.py
│   └── memoire_prompt.py     (constants only — Mémoire is deterministic)
├── graph/                    LangGraph state machine
│   ├── state.py              SocraState + sub-TypedDicts
│   ├── nodes.py              Node functions (real + stubs)
│   └── orchestrator.py       Edge wiring
├── rag/
│   ├── embeddings.py         Gemini gemini-embedding-001 (768 dims)
│   └── retriever.py          Supabase match_embeddings RPC
├── db/
│   ├── supabase_client.py    Service-role client singleton
│   ├── messages.py           Read/write chat history
│   ├── profiles.py           Read/write StudentProfile
│   └── diagnostics.py        Read/write DiagnosticReport
├── models/schemas.py         Pydantic API I/O
└── scripts/                  Manual smoke tests
```

## Important notes

### Embedding model migration

Google retired `text-embedding-004` in early 2026. We now use
`gemini-embedding-001` truncated to 768 dims (Matryoshka) to stay compatible
with the existing `vector(768)` column in `public.embeddings`.

The 114 existing chunks in the database were embedded with the old model and
therefore live in a different embedding space than newly produced query
vectors. Cosine similarity still works (≈0.7+ for clearly relevant matches in
our smoke test) but is sub-optimal. **Re-embedding stored chunks with
`gemini-embedding-001` is recommended** before going to production. The
`embed_document()` helper in `rag/embeddings.py` is ready for that script.

The Next.js `/api/upload` route should also switch to `gemini-embedding-001`
to keep the embedding space consistent for any future uploads.

### Why service-role key

The Python backend bypasses RLS so it can write `student_profiles` and
`diagnostics` on behalf of the authenticated user. For reads, the frontend
hits Supabase directly with the user JWT and is restricted by the RLS
policies defined in the migration `add_student_profiles_and_diagnostics`.
