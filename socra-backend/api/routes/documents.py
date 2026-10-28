"""PDF summary processing endpoint used by the frontend upload pipeline."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agents.course_summarizer import summarize_document
from db.supabase_client import get_supabase
from graph.state import SocraState

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)


class SummarizeRequest(BaseModel):
    pages: list[str] = Field(min_length=1)
    course_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    google_api_key: str | None = None


def _write_summaries(document_id: str, course_id: str, version: str, rows: list[dict[str, Any]]) -> None:
    client = get_supabase()
    client.table("document_summaries").delete().eq("document_id", document_id).execute()
    if rows:
        client.table("document_summaries").insert([
            {**row, "document_id": document_id, "course_id": course_id, "document_version": version}
            for row in rows
        ]).execute()


@router.post("/{document_id}/summarize")
async def process_summaries(document_id: UUID, request: SummarizeRequest) -> dict[str, str]:
    client = get_supabase()
    doc = await asyncio.to_thread(lambda: client.table("documents").select("id,course_id,content_hash").eq("id", str(document_id)).single().execute().data)
    if not doc or str(doc["course_id"]) != str(request.course_id):
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.get("content_hash") != request.content_hash:
        raise HTTPException(status_code=409, detail="Document version changed during processing")
    state: SocraState = {"course_id": str(request.course_id)}
    if request.google_api_key:
        state["api_key"] = request.google_api_key
    try:
        payload = await summarize_document(state, request.pages)
        for index, row in enumerate(payload["sections"]):
            row["section_index"] = index
        rows = ([payload["document"]] if payload["document"] else []) + payload["sections"]
        await asyncio.to_thread(_write_summaries, str(document_id), str(request.course_id), request.content_hash, rows)
        return {"status": "ready"}
    except Exception as exc:
        logger.warning("Summary processing failed for %s: %s", document_id, exc)
        await asyncio.to_thread(lambda: client.table("document_summaries").delete().eq("document_id", str(document_id)).execute())
        raise HTTPException(status_code=503, detail="Could not summarize course pages; retry processing") from exc
