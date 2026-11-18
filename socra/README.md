# Socra

Socra is a course-grounded study app with Socratic dialogue, topic explanations, verified short-answer/QCM/numerical/Python/SQL practice, and configurable mixed exams.

## Run locally

Start the FastAPI backend from `socra-backend`:

```powershell
cd ..\socra-backend
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

In a second terminal, start the Next.js app from `socra`:

```powershell
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Configure Supabase and a supported model provider in the app settings. The backend reads its server configuration from `socra-backend/.env`; see `socra-backend/.env.example`. If the backend is hosted elsewhere, set `SOCRA_BACKEND_URL` in the frontend environment.

## Checks

Frontend type and lint checks:

```powershell
npx tsc --noEmit
npm run lint
```

Backend unit checks:

```powershell
cd ..\socra-backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The live review steps for Socratic, Explain, exercise, and exam flows are in `socra-backend/tests/PHASE6_CHECKLIST.md`. They require a signed-in browser, processed course documents, and a configured model provider.

## Explicateur frontend F1

The inquiry's messages own the data. WebSocket v2 events are parsed in
`lib/socra-ws.ts`, checked against the open inquiry and request in
`hooks/useSocraChat.ts`, then reduced into that turn's assistant-message metadata.
The turn model derives from existing saved assistant cards, saved user checkpoints
and live events. It uses the existing history and same-request retry paths.
It does not add browser persistence for the structured explanation.

A unit is keyed by document and logical ID. Its version uses the original request,
source generation and hash, unit content hash, and draft/repaired/ready stage.
A replay can use a different envelope request ID. WebSocket sequence is local
to a request attempt. The backend checkpoint's revision applies to the whole
checkpoint and is not a per-unit or per-event sequence. Replayed versions and
corrections merge by identity. Previous ready content remains available while
a Deepen attempt is provisional.

Lifecycle, coverage and verification are separate. For example, a version can be
ready with coverage `not_generated` and verification `unreviewed`. The saved
`learning_state`, `coverage_ledger` and `course_progress.learning_plan` retain
backend counts, scope, order, decisions, actions, and facts. Source gaps and
missing item IDs travel with the verdict. Citation indexes are one-based into
each unit's source anchors. The model preserves backend extensions, including
per-block provenance, hypothetical examples and any reconciliation or review data.
The model omits checkpoint call accounting and checkpoint-only draft facts.

`ExplanationCard`, Library and Notebook keep using the backend's legacy
`sections` projection and shared Markdown and citation helpers. Existing snapshots
without v2 metadata keep using the same path. The existing Continue button uses
the supported unit action for its label when the server provides a matching
`next_request_id`. Historical-source replays do not offer that action.

The wire contract differs from the mockups. The backend sends `coverage` for
generated output, `status: skipped` plus a scope reason in progress, and
`unverifiable_source` as evidence gaps. `unreviewed` is the backend verification
value. Budget outcomes are supplied as interruption reasons on outputs when present.
The wire contract does not always include a separate budget-exhausted flag,
document-shell classification, checklist descriptions for missing IDs, or
dependency edges. Unit identity metadata is also optional on old or ungenerated
entries. F1 keeps these fields absent when the backend omits them. Some historical
staleness is only signaled on a server replay or in a reconciliation record.

Continue and Deepen are the available unit operations. Arbitrary jumps and
standalone review, regeneration, skipped-unit override, and student controls
are deferred. F2 instructional components, F3 shells, and F4 interaction,
responsive behaviour and lifecycle presentation are outside F1.

## Explicateur frontend F2

The shared explanation card selects the structured unit renderer when it receives
a valid v2 card. That renderer selects the instructional layout from the unit's
backend kind and passes the supplied blocks through the shared study Markdown,
math, code, copy and PDF citation components. The legacy sections remain available
to historical cards and Notebook export.

F2 uses page links when a figure has a source anchor or a single known PDF page.
Phase 7 does not currently send figure crops or per-row example provenance.
Approximation labels require explicit block metadata. Static unit notices show
source gaps, coverage, verification and saved corrections. Document shells,
live unit transitions and interactive review controls belong to later stages.

## Explicateur frontend F3

The structured card uses a single document shell and the existing F2 unit body.
A strict majority of known teaching units selects course, exercise or lab;
unclassified units count against that majority. A tie or insufficient kind
information gives the neutral shell. Source labels and any supplied hierarchy
identify groups. The backend planner determines the order. Its progress ledger
provides totals only when the in-scope teaching rows agree with those totals.

The plan stays inside the explanation card. Earlier ready content can be
expanded on the latest card for the same PDF only when document ID, source hash,
generation and unit content version match. Lab requirements are read-only.
The exercise results summary uses reviewed or deterministically verified
LearningState facts, and dependency references are shown only when supplied.

Continue and Deepen send the backend-issued request IDs and parent request.
Deepen also sends the logical unit ID. Existing legacy continuation remains
available for legacy cards. The backend currently omits much of the source
hierarchy for excluded units, most dependency edges, and the full checkpoint or
deliverable inventory. F3 displays what is available without inferring missed
requirements, student execution, or completed deliverables.

## Explicateur frontend F4

Chat renders complete structured block snapshots during generation and checking.
Continue and Deepen attach their live updates to the originating document card.
When the follow-up is saved, the earlier response remains in a disclosure and
the latest card keeps prior versions available. Budget notices require an
explicit `call_budget` or `token_budget` interruption from Phase 7. Pending
preparation does not imply an evidence count or a preparation failure.

Reading and lab marks are local convenience controls. Keys include the owner,
document, source generation and hash, unit and content version. Lab controls
require a unique sourced checkpoint or deliverable block. Values are booleans,
independent of coverage and verification, with no account or device sync.

Mobile uses the in-card Plan disclosure and an anchor to the single action
area, keeping the existing composer and scroll controls in their own regions.
Earlier corrected or invalidated content remains readable with its own source
references when the backend has retained them.
