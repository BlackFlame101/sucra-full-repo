"""Reproducible offline comparison with fixed synthetic service delays."""
from __future__ import annotations

import asyncio
import logging
from statistics import median
from time import perf_counter
from unittest.mock import patch

from rag.retriever import retrieval_scope, retrieve_summary_guided_chunks, retrieve_chunks
from tests.offline_windows import OfflinePolicy

ROW = {"id": "spark", "content": "Spark supports window functions.", "document_id": "doc", "page_number": 3,
       "chunk_index": 0, "filename": "fixture.pdf", "similarity": 0.8}
SECTION = {"document_id": "doc", "title": "Spark windows", "summary": "Window functions",
           "page_start": 8, "page_end": 8}


async def embed(_query):
    await asyncio.sleep(0.04)
    return [0.1]


async def sections(_course):
    await asyncio.sleep(0.03)
    return [SECTION]


def vector(*_args):
    from time import sleep
    sleep(0.02)
    return [ROW]


async def old_search():
    await sections("course")
    v = await embed("Spark window")
    await asyncio.to_thread(vector, v, "course", 60)
    # The guide had no candidate in its section. The old path searched again.
    await retrieve_chunks("Spark window", "course", k=6)


async def new_search():
    async with retrieval_scope():
        await retrieve_summary_guided_chunks("Spark window", "course", k=6)


async def exam_generation(parallelism):
    limit = asyncio.Semaphore(parallelism)
    async def candidate():
        async with limit:
            await asyncio.sleep(0.03)  # candidate generation
            await asyncio.sleep(0.02)  # independent verification
    await asyncio.gather(*(candidate() for _ in range(6)))


async def measure(fn):
    samples = []
    for _ in range(15):
        start = perf_counter()
        await fn()
        samples.append((perf_counter() - start) * 1000)
    return f"p50={median(samples):.1f} ms, p95={max(samples):.1f} ms"


async def run():
    logging.disable(logging.WARNING)
    with patch("rag.retriever.embed_query", side_effect=embed), patch("rag.retriever._call_rpc", side_effect=vector), \
         patch("rag.retriever.get_current_course_sections", side_effect=sections), \
         patch("rag.retriever._match_terms", return_value=[]):
        print("Retrieval fallback before:", await measure(old_search))
        print("Retrieval fallback after: ", await measure(new_search))
    print("Six exam slots, sequential: ", await measure(lambda: exam_generation(1)))
    print("Six exam slots, two workers:", await measure(lambda: exam_generation(2)))


if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(OfflinePolicy())
    asyncio.run(run())
