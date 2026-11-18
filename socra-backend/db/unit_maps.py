"""Owner-scoped access to the current Explain Unit Map."""
import asyncio

from db.jobs import rpc
from db.supabase_client import get_supabase
from rag.unit_map import EXTRACTOR_VERSION
from rag.explain_preparation import PREPARATION_VERSION


async def load_prepared_evidence(course_id: str, owner_id: str, document: dict) -> dict:
    generation = document.get("index_generation")
    source = document.get("content_hash")
    if not course_id or not owner_id or type(generation) is not int or not source:
        return {}

    def read():
        rows = (get_supabase().table("explain_preparation_jobs")
                .select("unit_id,result,documents!inner(courses!inner(user_id))")
                .eq("document_id", str(document["id"])).eq("generation", generation)
                .eq("source_hash", source).eq("state", "done").eq("prompt_version", PREPARATION_VERSION)
                .eq("documents.course_id", course_id).eq("documents.courses.user_id", owner_id)
                .eq("documents.index_generation", generation).eq("documents.content_hash", source)
                .eq("documents.index_status", "ready").is_("documents.index_stage", "null")
                .order("id").limit(1000).execute().data)
        return {row["unit_id"]: row["result"] for row in rows if isinstance(row["result"], dict)}

    return await asyncio.to_thread(read)


async def queue_unit_evidence(owner_id: str, document: dict, identifiers: list[str]) -> None:
    if owner_id and type(document.get("index_generation")) is int and identifiers:
        await rpc("request_explain_preparation", {
            "doc_id": str(document["id"]), "owner_id": owner_id,
            "expected_generation": document["index_generation"], "unit_ids": identifiers[:5],
            "version": PREPARATION_VERSION,
        })


async def load_or_queue_unit_map(course_id: str, owner_id: str, document: dict) -> dict | None:
    generation = document.get("index_generation")
    if not course_id or not owner_id or type(generation) is not int or document.get("index_stage") is not None:
        return None
    source = document.get("content_hash")
    if not source:
        return None

    def read():
        return (get_supabase().table("explain_unit_maps")
                .select("units,text_hash,documents!inner(courses!inner(user_id))")
                .eq("document_id", str(document["id"])).eq("generation", generation)
                .eq("source_hash", source).eq("extractor_version", EXTRACTOR_VERSION)
                .eq("documents.course_id", course_id).eq("documents.courses.user_id", owner_id)
                .eq("documents.index_generation", generation).eq("documents.content_hash", source)
                .eq("documents.index_status", "ready").is_("documents.index_stage", "null")
                .limit(1).execute().data)

    rows = await asyncio.to_thread(read)
    if rows:
        return rows[0]
    await rpc("queue_explain_unit_map", {
        "doc_id": str(document["id"]), "expected_generation": generation, "owner_id": owner_id,
        "extractor_version": EXTRACTOR_VERSION,
    })
    return None
