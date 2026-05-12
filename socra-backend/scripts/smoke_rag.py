"""Manual smoke test for the RAG layer.

Usage::

    uv run python scripts/smoke_rag.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.retriever import retrieve_chunks  # noqa: E402


COURSE_ID = "a5159856-5479-4699-9f1b-b76ae04fb818"
QUERY = "What is a star schema in data warehousing?"


async def main() -> None:
    chunks = await retrieve_chunks(QUERY, COURSE_ID, k=3)
    print(f"Retrieved {len(chunks)} chunks")
    for i, c in enumerate(chunks, start=1):
        sim = c.get("similarity", 0.0)
        fname = c.get("filename") or "?"
        page = c.get("page_number")
        preview = (c.get("content") or "")[:120].replace("\n", " ")
        print(f"#{i} sim={sim:.3f} | {fname} p.{page} | {preview!r}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(main())
