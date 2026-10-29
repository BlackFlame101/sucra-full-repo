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
| `GEMINI_API_KEY` | Gemini key used for frontend upload embeddings and model calls |
| `GROQ_API_KEY` | Optional Groq key used by the backend when configured as a server fallback |
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
- Vercel Functions cap request and response bodies at 4.5 MB. The current upload route sends the PDF through a Vercel Function, even though the app accepts larger files in its UI. PDFs over that platform limit need a direct-to-storage upload flow or an upload endpoint hosted outside Vercel.
- The frontend and backend need matching production URLs: Vercel’s origin in Render `FRONTEND_URL`, and Render’s HTTPS/WSS URL in the Vercel backend variables.
