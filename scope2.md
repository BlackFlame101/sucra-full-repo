# Socra — Backend V2 Scope
## Multi-Agent Socratic Tutoring System (Python + LangGraph)

> **Academic requirement**: 4AISDR — Module SMA Agentic AI  
> **Presentation**: Week of 18 May 2026  
> **Frontend**: Next.js (unchanged)  
> **New backend**: Python FastAPI + LangGraph multi-agent pipeline

---

## What Changes and What Stays

### Stays Exactly the Same
- All Next.js frontend code (landing, auth, dashboard, course management, chat UI, context panel)
- Supabase database schema (courses, documents, sessions, messages, key_terms tables)
- Supabase Auth
- Supabase Storage (PDF files)
- Supabase pgvector (embeddings)
- PDF upload flow (Next.js API route `/api/upload` stays — it already works)
- BYOK settings modal

### What Changes
- `/api/chat` route in Next.js → replaced by a call to the Python backend
- `/api/context` route in Next.js → replaced by a call to the Python backend
- The single LLM call with a system prompt → replaced by a **4-agent LangGraph pipeline**
- Embeddings generation for RAG queries → Python handles this now
- Key term extraction → handled by Agent Évaluateur

### New Pages Needed in Next.js
- `/dashboard/course/[courseId]/inquiry/[sessionId]/diagnostic` — A short diagnostic screen before the first inquiry in a session (Agent Diagnostiqueur runs here)

---

## Architecture Overview

```
Next.js Frontend
       │
       │  WebSocket (ws://)
       ▼
FastAPI Python Backend  (new)
       │
       ▼
LangGraph Orchestrator
       │
  ┌────┴─────────────────────────────┐
  │                                  │
  ▼                                  ▼
Agent Diagnostiqueur          Agent Tuteur Socratique
(entry point, first message)   (main dialogue loop)
       │                                  │
       └──────────────┬───────────────────┘
                      │
              Agent Évaluateur
              (after each student response)
                      │
              Agent Mémoire
              (updates student profile in Supabase)
       │
       ▼
  Supabase pgvector  (RAG — same embeddings already there)
  Supabase PostgreSQL (session memory, student profile)
```

---

## Technology Stack (Full)

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | Next.js 14+ (unchanged) | UI |
| Backend | FastAPI + Uvicorn | Python API server |
| Agent Orchestration | LangGraph | Multi-agent state machine |
| Agent Framework | LangChain | Agent body/mind/tools |
| LLM | Gemini 2.5 Flash (google-generativeai) | All 4 agents |
| Embeddings | Gemini text-embedding-004 | RAG queries |
| Vector Store | Supabase pgvector (existing) | RAG retrieval |
| Database | Supabase PostgreSQL (existing) | Sessions, messages, profiles |
| Streaming | WebSockets (FastAPI) | Real-time chat streaming |
| Inter-agent Messages | Structured JSON (TypedDict) | LangGraph state |

---

## The 4-Agent Architecture

### Agent 1 — Diagnostiqueur
**Trigger**: First message of a new session  
**Mission**: Assess the student's starting knowledge on the topic via 2-3 open questions. Identify missing prerequisites from the uploaded course material.  
**Techniques**: Few-shot prompting, RAG on course PDFs  
**Output**: `DiagnosticReport` JSON → passed to Agent Tuteur

```python
class DiagnosticReport(TypedDict):
    topic: str
    initial_level: str          # "beginner" | "intermediate" | "advanced"
    identified_gaps: list[str]  # ["doesn't understand entropy", ...]
    prerequisite_concepts: list[str]
    first_socratic_question: str
```

---

### Agent 2 — Tuteur Socratique
**Trigger**: Every student message after diagnosis  
**Mission**: Never give direct answers. Ask targeted open questions that lead the student to reason through the answer themselves. Use Bloom's Taxonomy levels.  
**Techniques**: Chain-of-Thought, ReAct, RAG on course PDFs  
**Output**: Streamed response (text) + `TutorSignal` JSON

```python
class TutorSignal(TypedDict):
    response_text: str
    bloom_level: str            # "remember"|"understand"|"apply"|"analyze"|"evaluate"|"create"
    should_evaluate: bool       # True when student gives a substantive answer
    key_concepts_mentioned: list[str]
```

---

### Agent 3 — Évaluateur
**Trigger**: When `should_evaluate = True` from Agent Tuteur  
**Mission**: Silently analyze the student's last response. Detect misconceptions, measure comprehension level, extract key terms discussed, find relevant suggested readings.  
**Techniques**: Tool calling, conversational memory  
**Output**: `EvaluationResult` JSON → fed to Agent Mémoire + sent to frontend context panel

```python
class EvaluationResult(TypedDict):
    comprehension_score: float  # 0.0 to 1.0
    misconceptions: list[str]
    concepts_understood: list[str]
    key_terms: list[str]        # → KeyTerms panel in frontend
    suggested_readings: list[dict]  # → SuggestedReading panel in frontend
    next_micro_objective: str
```

---

### Agent 4 — Mémoire
**Trigger**: After every EvaluationResult  
**Mission**: Maintain the student's learning profile. Track mastered vs fragile concepts. Personalize the next Tuteur prompt based on history.  
**Techniques**: Long-term memory via Supabase, vector store  
**Output**: Updated `StudentProfile` written to DB, enriched context passed back to Agent Tuteur

```python
class StudentProfile(TypedDict):
    session_id: str
    mastered_concepts: list[str]
    fragile_concepts: list[str]
    misconception_history: list[str]
    bloom_progression: list[str]
    total_exchanges: int
```

---

## LangGraph State Machine

```python
class SocraState(TypedDict):
    # Inputs
    session_id: str
    course_id: str
    messages: list[dict]           # Full conversation history
    student_message: str           # Latest student input

    # Agent outputs
    diagnostic: DiagnosticReport
    tutor_signal: TutorSignal
    evaluation: EvaluationResult
    profile: StudentProfile

    # RAG context
    retrieved_chunks: list[dict]

    # Flow control
    is_first_message: bool
    current_node: str
```

**Graph edges:**
```
START
  │
  ├─(is_first_message=True)──→ diagnostiqueur ──→ tuteur_socratique
  │
  └─(is_first_message=False)─→ tuteur_socratique
                                        │
                               (should_evaluate=True)
                                        │
                                   evaluateur
                                        │
                                    memoire
                                        │
                                      END
```

---

## New Database Tables

```sql
-- Student learning profiles (Agent Mémoire persistence)
CREATE TABLE student_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  mastered_concepts JSONB DEFAULT '[]'::jsonb,
  fragile_concepts JSONB DEFAULT '[]'::jsonb,
  misconception_history JSONB DEFAULT '[]'::jsonb,
  bloom_progression JSONB DEFAULT '[]'::jsonb,
  total_exchanges INTEGER DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Diagnostic results per session
CREATE TABLE diagnostics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
  topic TEXT,
  initial_level TEXT,
  identified_gaps JSONB DEFAULT '[]'::jsonb,
  prerequisite_concepts JSONB DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

---

## Python Backend Folder Structure

```
socra-backend/
│
├── main.py                         # FastAPI app entry point
│
├── api/
│   ├── websocket.py                # WebSocket endpoint /ws/chat/{session_id}
│   └── routes/
│       ├── health.py               # GET /health
│       └── context.py              # POST /context (key terms + suggested reading)
│
├── agents/
│   ├── __init__.py
│   ├── diagnostiqueur.py           # Agent 1 — diagnosis chain
│   ├── tuteur_socratique.py        # Agent 2 — Socratic dialogue chain
│   ├── evaluateur.py               # Agent 3 — evaluation + key term extraction
│   └── memoire.py                  # Agent 4 — profile management
│
├── graph/
│   ├── __init__.py
│   ├── state.py                    # SocraState TypedDict + all sub-TypedDicts
│   ├── orchestrator.py             # LangGraph graph definition + edges
│   └── nodes.py                    # Node functions (wrap each agent)
│
├── rag/
│   ├── __init__.py
│   ├── retriever.py                # Supabase pgvector similarity search
│   └── embeddings.py               # Gemini text-embedding-004 calls
│
├── db/
│   ├── __init__.py
│   ├── supabase_client.py          # Supabase Python client
│   ├── messages.py                 # Save/load messages
│   ├── profiles.py                 # Read/write student_profiles
│   └── diagnostics.py              # Save diagnostic results
│
├── prompts/
│   ├── __init__.py
│   ├── diagnostiqueur_prompt.py
│   ├── tuteur_socratique_prompt.py
│   ├── evaluateur_prompt.py
│   └── memoire_prompt.py
│
├── models/
│   └── schemas.py                  # Pydantic models for API I/O
│
├── tests/
│   ├── test_diagnostiqueur.py
│   ├── test_tuteur.py
│   ├── test_evaluateur.py
│   ├── test_memoire.py
│   ├── test_graph.py
│   └── scenarios/
│       ├── scenario_entropy.json
│       ├── scenario_sql_joins.json
│       └── scenario_data_warehouse.json
│
├── requirements.txt
├── .env
├── .env.example
└── README.md
```

---

## Next.js Changes (Minimal)

### 1. Replace `/api/chat/route.ts`
Instead of calling Gemini directly, open a WebSocket to the Python backend:

```typescript
// hooks/useChat.ts — change transport
const ws = new WebSocket(`ws://localhost:8000/ws/chat/${sessionId}`)
ws.send(JSON.stringify({ message, courseId, sessionId }))
ws.onmessage = (event) => {
  const data = JSON.parse(event.data)
  if (data.type === 'token') appendToken(data.content)
  if (data.type === 'context') updateContextPanel(data.content)  // key terms + reading
  if (data.type === 'done') finalize()
}
```

### 2. Replace `/api/context/route.ts`
Context (key terms, suggested reading) now comes through the same WebSocket as a `context` message type — no separate HTTP call needed.

### 3. New Diagnostic Page
`app/(dashboard)/course/[courseId]/inquiry/[sessionId]/diagnostic/page.tsx`

Simple screen shown before chat starts. Displays the 2-3 diagnostic questions from Agent Diagnostiqueur. Student answers → redirected to chat with diagnostic already done.

---

## Environment Variables

### Python Backend (`.env`)
```env
# Supabase
SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key

# Gemini
GEMINI_API_KEY=your_gemini_key

# App
BACKEND_PORT=8000
FRONTEND_URL=http://localhost:3000
```

### Next.js (additions to `.env.local`)
```env
# Python backend
NEXT_PUBLIC_BACKEND_WS_URL=ws://localhost:8000
BACKEND_URL=http://localhost:8000
```

---

## Detailed Phase Breakdown

---

### Phase 1 — Python Project Setup (Days 1–2)

#### 1.1 Initialize Project
- [ ] Create `socra-backend/` directory alongside the Next.js project
- [ ] Create and activate virtual environment (`python -m venv venv`)
- [ ] Create `requirements.txt` with all dependencies
- [ ] Install: `fastapi uvicorn[standard] langchain langchain-google-genai langgraph supabase python-dotenv pydantic`
- [ ] Create `.env` and `.env.example`
- [ ] Create folder structure as defined above
- [ ] Create `main.py` with basic FastAPI app
- [ ] Test: `uvicorn main:app --reload` runs without errors

#### 1.2 Supabase Python Client
- [ ] Create `db/supabase_client.py`
- [ ] Initialize Supabase client with service role key (Python needs service role to bypass RLS for agent writes)
- [ ] Test connection with a simple query
- [ ] Create `db/messages.py` — functions: `save_message()`, `load_messages(session_id)`
- [ ] Create `db/profiles.py` — functions: `get_profile()`, `upsert_profile()`
- [ ] Create `db/diagnostics.py` — functions: `save_diagnostic()`

#### 1.3 New Database Tables
- [ ] Run SQL in Supabase to create `student_profiles` table
- [ ] Run SQL in Supabase to create `diagnostics` table
- [ ] Add RLS policies for both tables
- [ ] Test inserts/reads from Python client

---

### Phase 2 — RAG Retriever in Python (Days 2–3)

#### 2.1 Embeddings Module
- [ ] Create `rag/embeddings.py`
- [ ] Implement `embed_query(text: str) -> list[float]` using Gemini `text-embedding-004`
- [ ] Test: embed a sample query and verify 768-dim vector returned

#### 2.2 Retriever Module
- [ ] Create `rag/retriever.py`
- [ ] Implement `retrieve_chunks(query: str, course_id: str, k: int = 5) -> list[dict]`
- [ ] Call the existing `match_embeddings` Supabase function (already in DB)
- [ ] Return chunks with `content`, `document_id`, `page_number`, `similarity`
- [ ] Test: retrieve chunks for a thermodynamics question against an uploaded course

---

### Phase 3 — LangGraph State Definition (Day 3)

#### 3.1 Define State
- [ ] Create `graph/state.py`
- [ ] Define `DiagnosticReport` TypedDict
- [ ] Define `TutorSignal` TypedDict
- [ ] Define `EvaluationResult` TypedDict
- [ ] Define `StudentProfile` TypedDict
- [ ] Define `SocraState` TypedDict (master state)

#### 3.2 Define Graph Skeleton
- [ ] Create `graph/orchestrator.py`
- [ ] Create `graph/nodes.py` with stub functions for all 4 nodes
- [ ] Wire up edges: START → diagnostiqueur_or_tuteur → evaluateur → memoire → END
- [ ] Add conditional edge: `is_first_message` routes to diagnostiqueur vs tuteur
- [ ] Add conditional edge: `should_evaluate` routes to evaluateur or skips
- [ ] Test: run graph with mock state, verify correct node execution order

---

### Phase 4 — Agent Diagnostiqueur (Days 3–4)

#### 4.1 Write Prompt
- [ ] Create `prompts/diagnostiqueur_prompt.py`
- [ ] System prompt: you are an academic diagnostic agent. Your goal is to assess the student's starting knowledge on {topic} using their course material. Ask 2 open questions maximum. Do NOT teach. Do NOT answer questions. Output a structured JSON DiagnosticReport.
- [ ] Include few-shot examples of good diagnostic questions
- [ ] Include course context from RAG in prompt

#### 4.2 Implement Agent
- [ ] Create `agents/diagnostiqueur.py`
- [ ] Build LangChain chain: prompt → Gemini → JSON parser
- [ ] Add RAG call: retrieve relevant chunks for the topic before prompting
- [ ] Parse output to `DiagnosticReport`
- [ ] Handle parsing errors gracefully (fallback DiagnosticReport)
- [ ] Implement `run_diagnostiqueur(state: SocraState) -> SocraState`

#### 4.3 Test
- [ ] Write `tests/test_diagnostiqueur.py`
- [ ] Test with topic: "Data Warehousing" against an uploaded course PDF
- [ ] Verify output is valid `DiagnosticReport`
- [ ] Verify questions are open-ended, not leading, not giving answers

---

### Phase 5 — Agent Tuteur Socratique (Days 4–5)

#### 5.1 Write Prompt
- [ ] Create `prompts/tuteur_socratique_prompt.py`
- [ ] System prompt includes all Socratic rules: never answer directly, always ask what the student thinks first, identify the exact point of misunderstanding, push deeper when correct
- [ ] Include `DiagnosticReport` context: known gaps, initial level
- [ ] Include `StudentProfile` context: fragile_concepts, misconception_history
- [ ] Include RAG chunks as course context
- [ ] Include full conversation history
- [ ] Prompt must output both `response_text` (streamed) and `TutorSignal` JSON at end

#### 5.2 Implement Agent
- [ ] Create `agents/tuteur_socratique.py`
- [ ] Build LangChain chain with streaming enabled
- [ ] Implement `run_tuteur(state: SocraState) -> AsyncGenerator` — yields tokens
- [ ] At end of stream, parse `TutorSignal` from the final structured section
- [ ] Set `should_evaluate = True` when student gives a substantive answer (>20 words, factual claim)
- [ ] Test streaming works correctly

#### 5.3 Test
- [ ] Write `tests/test_tuteur.py`
- [ ] Test scenario: student says "entropy always increases" — verify tutor asks a question not confirms
- [ ] Test scenario: student says "what is this shit?" — verify tutor stays patient and redirects
- [ ] Verify `should_evaluate` set correctly

---

### Phase 6 — Agent Évaluateur (Day 5–6)

#### 6.1 Write Prompt
- [ ] Create `prompts/evaluateur_prompt.py`
- [ ] System prompt: silently analyze the student's response. Identify what they understood, what they got wrong, extract key academic terms from the conversation, find the most relevant section of the course material. Output EvaluationResult JSON only.
- [ ] This agent is invisible to the student — its output only goes to the context panel and Agent Mémoire

#### 6.2 Implement Agent
- [ ] Create `agents/evaluateur.py`
- [ ] Chain: conversation history + RAG context → Gemini → EvaluationResult JSON
- [ ] `key_terms`: extract 3-5 terms from conversation (feeds KeyTerms panel)
- [ ] `suggested_readings`: use RAG to find 1-2 most relevant document sections (feeds SuggestedReading panel)
- [ ] `comprehension_score`: float 0.0–1.0 based on student response quality
- [ ] Implement `run_evaluateur(state: SocraState) -> SocraState`

#### 6.3 Test
- [ ] Write `tests/test_evaluateur.py`
- [ ] Test: verify key_terms extracted match the conversation topic
- [ ] Test: verify suggested_readings point to real pages in the uploaded PDF

---

### Phase 7 — Agent Mémoire (Day 6)

#### 7.1 Write Prompt
- [ ] Create `prompts/memoire_prompt.py`
- [ ] Given the EvaluationResult and existing StudentProfile, update the profile. Move concepts from fragile to mastered if comprehension_score > 0.8. Add new misconceptions. Increment exchange count.

#### 7.2 Implement Agent
- [ ] Create `agents/memoire.py`
- [ ] Load current profile from Supabase at session start
- [ ] Update profile based on EvaluationResult
- [ ] Save updated profile to Supabase
- [ ] Return enriched context for next Tuteur call
- [ ] Implement `run_memoire(state: SocraState) -> SocraState`

#### 7.3 Test
- [ ] Write `tests/test_memoire.py`
- [ ] Test: after high comprehension score, concept moves to mastered
- [ ] Test: profile correctly persists to Supabase between calls

---

### Phase 8 — LangGraph Full Orchestration (Day 7)

#### 8.1 Wire All Nodes
- [ ] Implement all node functions in `graph/nodes.py` calling real agents
- [ ] Build complete graph in `graph/orchestrator.py`
- [ ] Test full pipeline: mock student message → all 4 agents run in correct order → state updated

#### 8.2 Inter-Agent Message Format
- [ ] All inter-agent data flows via `SocraState` (no direct calls between agents)
- [ ] Each agent reads from state, writes to state — LangGraph manages the flow
- [ ] Validate JSON schemas at each node boundary

#### 8.3 Test Full Graph
- [ ] Write `tests/test_graph.py`
- [ ] Run 3 full scenarios end-to-end:
  - [ ] `scenarios/scenario_entropy.json` — thermodynamics session
  - [ ] `scenarios/scenario_sql_joins.json` — SQL session  
  - [ ] `scenarios/scenario_data_warehouse.json` — data warehouse session
- [ ] Verify student never receives a direct answer
- [ ] Verify context panel data is produced correctly

---

### Phase 9 — FastAPI WebSocket Endpoint (Day 8)

#### 9.1 WebSocket Handler
- [ ] Create `api/websocket.py`
- [ ] Endpoint: `ws://localhost:8000/ws/chat/{session_id}`
- [ ] On connect: load session messages from Supabase, load student profile
- [ ] On message receive: parse `{ message, courseId, sessionId }`
- [ ] Run LangGraph pipeline
- [ ] Stream tokens back as `{ type: "token", content: "..." }`
- [ ] After stream: send context panel data as `{ type: "context", content: EvaluationResult }`
- [ ] Send `{ type: "done" }` when complete
- [ ] Save assistant message to Supabase after stream completes
- [ ] Handle disconnect gracefully

#### 9.2 CORS Configuration
- [ ] Configure FastAPI CORS for `http://localhost:3000`
- [ ] Configure for production Vercel URL

#### 9.3 Health Route
- [ ] `GET /health` returns `{ status: "ok", agents: ["diagnostiqueur", "tuteur", "evaluateur", "memoire"] }`

#### 9.4 Test WebSocket
- [ ] Use `wscat` or a test script to connect and send a message
- [ ] Verify tokens stream correctly
- [ ] Verify context message arrives after stream

---

### Phase 10 — Next.js Integration (Days 8–9)

#### 10.1 Update Chat Hook
- [ ] Modify `hooks/useChat.ts` to use WebSocket instead of Vercel AI SDK
- [ ] Handle token streaming → append to message
- [ ] Handle context message → update context panel state
- [ ] Handle connection errors gracefully (reconnect logic)
- [ ] Remove dependency on `@ai-sdk/react` for chat (keep for other uses if any)

#### 10.2 Update Context Panel
- [ ] `ContextPanel.tsx` now receives data via WebSocket message instead of polling `/api/context`
- [ ] Pass `EvaluationResult` fields to `KeyTerms` and `SuggestedReading` components
- [ ] No other changes needed — components already work

#### 10.3 New Diagnostic Page
- [ ] Create `app/(dashboard)/course/[courseId]/inquiry/[sessionId]/diagnostic/page.tsx`
- [ ] When a new session starts, redirect here first
- [ ] Page shows: "Before we begin, let me understand where you are..."
- [ ] Calls `/api/chat` (or WS) to trigger Agent Diagnostiqueur
- [ ] Displays 2 diagnostic questions
- [ ] Student answers → submitted → redirect to main chat with `diagnosticDone=true`

#### 10.4 Update New Inquiry Flow
- [ ] When "New Inquiry" is clicked, create session → redirect to `/diagnostic` first, not directly to chat
- [ ] After diagnostic complete, redirect to `/inquiry/[sessionId]` with state

---

### Phase 11 — Testing with Academic Scenarios (Day 9–10)

The PDF requirement is to test with 3-5 different pedagogical scenarios and verify the student reaches understanding without receiving direct answers.

#### 11.1 Scenario Testing
- [ ] Scenario 1: "Explain entropy and the second law of thermodynamics" — student starts with wrong intuition
- [ ] Scenario 2: "What is a star schema in data warehousing?" — student has never heard of it
- [ ] Scenario 3: "What is the difference between a fact table and a dimension table?" — student confuses the two
- [ ] Scenario 4: "Explain what an isolated system is" — student gives a partially correct answer
- [ ] Scenario 5: Student types frustration ("I don't understand any of this") — verify graceful handling

#### 11.2 Verification Checklist Per Scenario
- [ ] Tutor never says "correct, the answer is X"
- [ ] Tutor always asks at least one question per response
- [ ] Student profile updated correctly after session
- [ ] Key terms panel shows relevant terms
- [ ] Suggested reading cites real pages from uploaded PDF
- [ ] Conversation saved and resumable

---

### Phase 12 — Deployment (Day 10–11)

#### 12.1 Deploy Python Backend
- [ ] Choose hosting: **Railway** (recommended — free tier, supports Python, easy env vars) or Render
- [ ] Create `Procfile`: `web: uvicorn main:app --host 0.0.0.0 --port $PORT`
- [ ] Push backend to GitHub (separate repo or `/backend` subfolder)
- [ ] Set environment variables on Railway
- [ ] Test deployed WebSocket endpoint

#### 12.2 Update Next.js Environment
- [ ] Update `NEXT_PUBLIC_BACKEND_WS_URL` to Railway production URL (`wss://...`)
- [ ] Redeploy to Vercel
- [ ] Test full production flow

#### 12.3 Production Testing
- [ ] Upload a real course PDF
- [ ] Run a complete session through all 4 agents
- [ ] Verify streaming works in production
- [ ] Verify context panel updates

---

### Phase 13 — Academic Deliverables (Days 11–14)

#### 13.1 PowerPoint (15–20 slides)
- [ ] Slide 1: Title, team, project name
- [ ] Slide 2: Problem + Socratic method value
- [ ] Slide 3: Architecture diagram (4 agents + LangGraph)
- [ ] Slide 4: Agent Diagnostiqueur — role, prompt technique, output
- [ ] Slide 5: Agent Tuteur Socratique — Socratic rules, Chain-of-Thought, ReAct
- [ ] Slide 6: Agent Évaluateur — tool calling, key term extraction
- [ ] Slide 7: Agent Mémoire — long-term profile, Supabase persistence
- [ ] Slide 8: LangGraph state machine diagram
- [ ] Slide 9: RAG pipeline (chunking → embedding → pgvector → retrieval)
- [ ] Slide 10: Inter-agent JSON message format (show real example)
- [ ] Slide 11: Demo screenshot — diagnostic flow
- [ ] Slide 12: Demo screenshot — Socratic dialogue with key terms panel
- [ ] Slide 13: Tech stack justification
- [ ] Slide 14: Results — did students get answers directly? (spoiler: no)
- [ ] Slide 15: Limits + future improvements
- [ ] Slide 16: Conclusion

#### 13.2 Technical Report (10–15 pages)
- [ ] Architecture overview with diagrams
- [ ] Prompt engineering choices (zero-shot vs few-shot vs CoT vs ReAct — where each is used)
- [ ] RAG implementation details
- [ ] Agent communication protocol (JSON schema)
- [ ] LangGraph orchestration design decisions
- [ ] Test results from 5 scenarios
- [ ] Known limitations

#### 13.3 Demo Preparation
- [ ] Prepare a course PDF to upload live during presentation
- [ ] Rehearse full flow: upload PDF → new inquiry → diagnostic → Socratic dialogue → context panel updating
- [ ] Prepare a "student who is wrong" scenario for the jury to see the agent correct without giving the answer
- [ ] Have BYOK settings modal ready to show (bonus point — shows production thinking)

---

## Evaluation Grid Mapping

| Criterion | Points | How Socra Covers It |
|-----------|--------|---------------------|
| Architecture multi-agents | /4 | 4 agents, differentiated roles, JSON inter-agent messages via LangGraph |
| Maîtrise technique | /4 | RAG (pgvector), tool calling (Evaluateur), session memory (Supabase), LangChain/LangGraph |
| Démonstration live | /4 | Full working app, streaming chat, context panel, diagnostic flow |
| Présentation orale | /3 | 15-20 slides, balanced team presentation |
| Livrables annexes | /3 | TP + comptes rendus + devoirs |
| Originalité & bonus | /2 | BYOK settings, dark/light mode, production deployment, PDF citation with page numbers |

**Target: 18-20/20**

---

## Key Dependencies (`requirements.txt`)

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
langchain==0.3.0
langchain-google-genai==2.0.0
langgraph==0.2.0
supabase==2.7.0
python-dotenv==1.0.0
pydantic==2.8.0
websockets==13.0
python-multipart==0.0.9
```

---

*Scope V2 — Last updated: May 2026*
*Frontend: unchanged (Next.js)*
*Backend: Python FastAPI + LangGraph (new)*