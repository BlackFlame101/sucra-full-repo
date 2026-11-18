"""Run the Phase 7D manual test services against the verified socra-test project."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "socra-backend"
FRONTEND = ROOT / "socra"
TEST_REF = "cyvqxhuoeanpnyssdoio"
SUPABASE_URL = f"https://{TEST_REF}.supabase.co"
APP_URL = "http://localhost:3001"
API_URL = "http://localhost:8001"
WEBSOCKET_URL = "ws://localhost:8001"
MODEL = "gemini-3.8-flash"


def checked_test_key(value: str | None, role: str) -> str:
    if not value:
        raise ValueError(f"The {role} key is missing from test-socra.env.")
    try:
        _, encoded, _ = value.split(".")
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"The {role} key could not be tied to the verified test project.") from exc
    if payload.get("ref") != TEST_REF or payload.get("role") != role:
        raise ValueError(f"The {role} key in test-socra.env belongs to another project or role.")
    return value


def local_model_limits() -> str:
    original = json.loads((BACKEND / "explain_model_limits.json").read_text(encoding="utf-8"))
    return json.dumps({"policy": original["policy"], "models": [{
        "provider": "google", "model_id": MODEL, "context_tokens": 1048576, "max_output_tokens": 65536,
        # Local ceilings shared by both calls to this model. The provider's project quota may be lower.
        "tokens_per_minute": 187500, "requests_per_minute": 5, "requests_per_day": 8,
        "tokens_per_day": 150000, "checked_on": "2026-11-18",
    }]})


def service_configuration(service: str):
    test = dotenv_values(ROOT / "test-socra.env")
    url = (test.get("SUPABASE_URL") or "").rstrip("/")
    if url not in {SUPABASE_URL, f"{SUPABASE_URL}/rest/v1"}:
        raise ValueError("test-socra.env does not target the verified socra-test project.")
    service_key = checked_test_key(test.get("SUPABASE_SERVICE_ROLE_KEY"), "service_role")
    anon_key = checked_test_key(test.get("SUPABASE_ANON_KEY"), "anon")
    node = shutil.which("node")
    if not node or not (FRONTEND / "node_modules" / "unpdf").exists():
        raise ValueError("Install the locked Socra frontend dependencies with npm ci before starting.")

    environment = os.environ.copy()
    environment.update({
        "SUPABASE_URL": SUPABASE_URL, "SUPABASE_SERVICE_ROLE_KEY": service_key,
        "NEXT_PUBLIC_SUPABASE_URL": SUPABASE_URL, "NEXT_PUBLIC_SUPABASE_ANON_KEY": anon_key,
        "NEXT_PUBLIC_APP_URL": APP_URL, "SOCRA_BACKEND_URL": API_URL, "NEXT_PUBLIC_BACKEND_WS_URL": WEBSOCKET_URL,
        # Personal provider keys are unnecessary for the manual test. Avoid inheriting a deployment job secret.
        "SOCRA_JOB_ENCRYPTION_KEY": test.get("SOCRA_JOB_ENCRYPTION_KEY") or "",
    })
    if service == "frontend":
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY", "GROQ_API_KEY",
                     "NEXT_PUBLIC_GEMINI_API_KEY", "NEXT_PUBLIC_GOOGLE_API_KEY"):
            environment.pop(name, None)
        environment["SOCRA_MANUAL_TEST"] = "1"
        next_cli = FRONTEND / "node_modules" / "next" / "dist" / "bin" / "next"
        command = [node, str(next_cli), "dev", "--hostname", "127.0.0.1", "--port", "3001"]
        return command, FRONTEND, environment

    key_file = ROOT / ".socra-p2-gemini.env"
    key = dotenv_values(key_file).get("GEMINI_API_KEY") or ""
    if not key.strip():
        raise ValueError(f"Set GEMINI_API_KEY in {key_file.name} before starting the test backend or worker.")
    environment.update({
        "GEMINI_API_KEY": key.strip(), "GOOGLE_API_KEY": "", "GOOGLE_GENERATIVE_AI_API_KEY": "", "GROQ_API_KEY": "",
        "FRONTEND_URL": APP_URL, "BACKEND_PORT": "8001", "SOCRA_ENV": "development", "SOCRA_NODE_BIN": node,
        "CHAT_MODEL": MODEL, "SOCRA_EXPLAIN_REVIEW_MODEL": MODEL, "SOCRA_EXPLAIN_MODEL_LIMITS_JSON": local_model_limits(),
        "EXPLAIN_DOCUMENT_MODE": "true", "EXPLAIN_UNIT_PIPELINE": "true",
    })
    if service == "backend":
        # The signed-in frontend shares localhost cookies with this loopback WebSocket server.
        environment["WEBSOCKETS_MAX_LINE_LENGTH"] = "32768"
    command = [sys.executable, "-B", "-m", "worker"] if service == "worker" else [
        sys.executable, "-B", "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8001",
    ]
    return command, BACKEND, environment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=("backend", "worker", "frontend"))
    parser.add_argument("--check", action="store_true", help="Validate settings without starting a service.")
    args = parser.parse_args()
    try:
        command, directory, environment = service_configuration(args.service)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Socra {args.service}: isolated socra-test project. Website: {APP_URL}", flush=True)
    if args.check:
        return 0
    return subprocess.call(command, cwd=directory, env=environment)


if __name__ == "__main__":
    sys.exit(main())
