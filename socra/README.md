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
