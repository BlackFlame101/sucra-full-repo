"""End-to-end WebSocket smoke test.

Assumes uvicorn is already running on ``ws://127.0.0.1:8000``::

    # In one terminal:
    uv run uvicorn main:app --port 8000

    # In another:
    uv run python scripts/smoke_ws.py

Sends 2 turns through ``/ws/chat/{session_id}``:
  • Turn 1 — first message: triggers Diagnostiqueur + Tuteur (no eval).
  • Turn 2 — substantive answer: triggers Tuteur + Évaluateur + Mémoire.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


SESSION_ID = "5fb1fc22-ca22-42f3-8a9b-ffac78705509"  # fresh session, no prior history
COURSE_ID = "a5159856-5479-4699-9f1b-b76ae04fb818"
WS_URL = f"ws://127.0.0.1:8000/ws/chat/{SESSION_ID}"

TURN_1 = "I want to understand star schemas in data warehousing."
TURN_2 = (
    "I think a star schema has one big central fact table that stores measurable events "
    "like sales, surrounded by smaller dimension tables for context such as time, "
    "product, customer. The fact table holds foreign keys to each dimension."
)


def _truncate(s: str, n: int = 80) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


async def _drain_until_done(ws) -> dict:
    """Read frames until a {type:done} arrives. Returns a summary dict."""
    full_text: list[str] = []
    diagnostic = None
    context = None
    error = None
    token_count = 0
    async for raw in ws:
        msg = json.loads(raw)
        kind = msg.get("type")
        if kind == "token":
            tok = msg.get("content", "")
            full_text.append(tok)
            token_count += 1
            print(tok, end="", flush=True)
        elif kind == "diagnostic":
            diagnostic = msg.get("content")
            print(f"\n[diagnostic received] {_truncate(json.dumps(diagnostic), 200)}")
        elif kind == "context":
            context = msg.get("content")
            print(f"\n[context received] {_truncate(json.dumps(context), 200)}")
        elif kind == "error":
            error = msg.get("content")
            print(f"\n[error] {error}")
            break
        elif kind == "done":
            print("\n[done]")
            break
    return {
        "full_text": "".join(full_text),
        "tokens": token_count,
        "diagnostic": diagnostic,
        "context": context,
        "error": error,
    }


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"Connecting to {WS_URL} ...")
    async with websockets.connect(WS_URL, max_size=2**24) as ws:
        print("Connected.\n")

        # ---------------- TURN 1 ----------------
        print("=" * 70)
        print("TURN 1 (first message)")
        print("=" * 70)
        print(f"> {TURN_1}\n")
        await ws.send(json.dumps({
            "message": TURN_1,
            "courseId": COURSE_ID,
            "sessionId": SESSION_ID,
        }))
        result1 = await _drain_until_done(ws)
        print(
            f"\n[turn 1 summary] tokens={result1['tokens']} "
            f"chars={len(result1['full_text'])} "
            f"diagnostic={'yes' if result1['diagnostic'] else 'no'} "
            f"context={'yes' if result1['context'] else 'no'}"
        )

        # ---------------- TURN 2 ----------------
        print("\n" + "=" * 70)
        print("TURN 2 (substantive answer — should trigger Évaluateur + Mémoire)")
        print("=" * 70)
        print(f"> {TURN_2}\n")
        await ws.send(json.dumps({
            "message": TURN_2,
            "courseId": COURSE_ID,
            "sessionId": SESSION_ID,
        }))
        result2 = await _drain_until_done(ws)
        print(
            f"\n[turn 2 summary] tokens={result2['tokens']} "
            f"chars={len(result2['full_text'])} "
            f"context={'yes' if result2['context'] else 'no'}"
        )
        if result2["context"]:
            print("[context.key_terms]:", result2["context"].get("key_terms"))
            print("[context.score]:    ", result2["context"].get("comprehension_score"))
            print("[context.misconceptions]:", result2["context"].get("misconceptions"))
            print("[context.suggested_readings count]:", len(result2["context"].get("suggested_readings") or []))


if __name__ == "__main__":
    asyncio.run(main())
