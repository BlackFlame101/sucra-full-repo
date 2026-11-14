"""Service-role access to the durable PDF queue."""
from __future__ import annotations

import asyncio
from typing import Any

from db.supabase_client import get_supabase


async def rpc(name: str, params: dict[str, Any]) -> Any:
    return await asyncio.to_thread(lambda: get_supabase().rpc(name, params).retry(False).execute().data)


async def claim_job(kind: str) -> dict[str, Any] | None:
    rows = await rpc("claim_processing_job", {"job_kind": kind})
    return (rows or [None])[0]


async def job_rpc(job: dict, name: str, **fields: Any) -> Any:
    return await rpc(name, {"job_id": job["id"], "lease": job["lease_token"], **fields})
