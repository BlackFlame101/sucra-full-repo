"""Unit checkpoints in the server-owned message metadata of an authenticated turn."""
import asyncio

from db.supabase_client import get_supabase

KEY = "explain_unit_checkpoint"


class CheckpointRejected(RuntimeError):
    """The current turn could not safely publish progress."""


def load_checkpoints(session_id, document_id):
    """Read all matching turns in stable order, including canceled requests."""
    checkpoints = []
    offset = 0
    while True:
        rows = (get_supabase().table("messages").select("metadata")
                .eq("session_id", session_id).eq("role", "user")
                .eq(f"metadata->{KEY}->>document_id", document_id)
                .order("created_at").order("id").range(offset, offset + 49).execute().data or [])
        for row in rows:
            checkpoint = row["metadata"][KEY]
            if not any(version.get("kind") == "educational_document" for version in checkpoint["versions"]):
                checkpoints.append(checkpoint)
        if len(rows) < 50:
            return checkpoints
        offset += len(rows)


def source_is_current(source, course_id, owner_id, *, client=None):
    client = client or get_supabase()
    return bool((client.table("documents").select("id,courses!inner(user_id)")
                 .eq("id", source["document_id"]).eq("course_id", course_id)
                 .eq("courses.user_id", owner_id).eq("content_hash", source["source_hash"])
                 .eq("index_generation", source["generation"]).eq("index_status", "ready")
                 .is_("index_stage", "null").limit(1).execute().data))


class TurnCheckpoint:
    def __init__(self, session_id, course_id, owner_id, request_id, prompt, *, lease):
        self.session_id = session_id
        self.course_id = course_id
        self.owner_id = owner_id
        self.request_id = request_id
        self.lease = lease
        self.prompt = prompt.copy()
        self.document = None
        self.data = None

    async def open(self, document):
        source = {"document_id": str(document["id"]), "source_hash": document["content_hash"],
                  "generation": document["index_generation"]}
        saved = self.prompt["metadata"].get(KEY)
        if saved and any(saved.get(key) != value for key, value in source.items()):
            raise ValueError("The PDF was reindexed during this request. Start a new explanation.")
        self.document = source
        self.data = saved or source | {"request_id": self.request_id, "versions": [], "calls": []}
        return await asyncio.to_thread(load_checkpoints, self.session_id, source["document_id"])

    def _persist(self, *, version=None, call=None, final=None):
        source = self.document
        params = {
            "p_inquiry": self.session_id, "p_course": self.course_id, "p_owner": self.owner_id,
            "p_lease": self.lease, "p_document": source["document_id"], "p_generation": source["generation"],
            "p_source_hash": source["source_hash"], "p_message": self.prompt["id"], "p_request": self.request_id,
            "p_expected_revision": self.data.get("revision"), "p_version": version, "p_call": call,
            "p_final": final,
        }
        try:
            return get_supabase().rpc("append_explain_checkpoint", params).retry(False).execute().data
        except Exception as exc:
            raise CheckpointRejected("Could not confirm the unit checkpoint.") from exc

    def _write(self, version, call):
        if self._persist(version=version, call=call) is not True:
            raise CheckpointRejected("The inquiry lease, source, or checkpoint revision changed.")

    async def finalize(self, content, metadata):
        saved = await asyncio.to_thread(self._persist, final={"content": content, "metadata": metadata})
        if not isinstance(saved, dict) or not saved.get("id"):
            raise CheckpointRejected("The inquiry lease, source, or checkpoint revision changed.")
        return saved

    async def save(self, *, version=None, purpose=None, tokens=0, retry=False, batch_hash=None, retry_at=None):
        # Await any in-flight write when canceled so the inquiry lease spans the commit.
        data = self.data.copy()
        data["revision"] = data.get("revision", 0) + 1
        if version is not None:
            data["versions"] = [*data["versions"], version]
        call = None
        if purpose:
            call = {"purpose": purpose}
            if batch_hash is not None:
                call["batch_hash"] = batch_hash
            if retry_at is None:
                call["tokens"] = tokens
            else:
                call["retry_at"] = retry_at
            if retry:
                call["retry"] = True
            data["calls"] = [*data["calls"], call]
        write = asyncio.create_task(asyncio.to_thread(self._write, version, call))
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError:
            await write
            raise
        self.data = data
