"""Read/write chat messages tied to a session."""
from __future__ import annotations

from typing import Any, Literal

from db.supabase_client import get_supabase


Role = Literal["user", "assistant"]


def save_message(
    session_id: str,
    role: Role,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "session_id": session_id,
        "role": role,
        "content": content,
        "metadata": metadata or {},
    }
    res = get_supabase().table("messages").insert(payload).execute()
    return res.data[0] if res.data else {}


def save_message_metadata(message_id: str, metadata: dict[str, Any]) -> None:
    """Attach safe, client-visible mode data to its assistant message."""
    get_supabase().table("messages").update({"metadata": metadata}).eq("id", message_id).execute()


def merge_message_metadata(message_id: str, metadata: dict[str, Any]) -> None:
    """Merge mode snapshots into existing metadata without replacing it."""
    client = get_supabase()
    rows = client.table("messages").select("metadata").eq("id", message_id).limit(1).execute().data or []
    existing = rows[0].get("metadata") if rows else {}
    merged = {**(existing if isinstance(existing, dict) else {}), **metadata}
    save_message_metadata(message_id, merged)


def merge_latest_assistant_metadata(session_id: str, metadata: dict[str, Any]) -> None:
    rows = (
        get_supabase().table("messages").select("id, metadata")
        .eq("session_id", session_id).eq("role", "assistant")
        .order("created_at", desc=True).limit(1).execute().data or []
    )
    if rows:
        merge_message_metadata(str(rows[0]["id"]), metadata)


def load_messages(session_id: str) -> list[dict[str, Any]]:
    res = (
        get_supabase()
        .table("messages")
        .select("id, role, content, metadata, created_at")
        .eq("session_id", session_id)
        .order("created_at", desc=False)
        .execute()
    )
    return res.data or []


def touch_session(session_id: str) -> None:
    """Bump ``updated_at`` so the sidebar shows the most recent inquiry first."""
    from datetime import datetime, timezone

    get_supabase().table("sessions").update(
        {"updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", session_id).execute()


def set_default_session_title_from_prompt(session_id: str, prompt: str) -> None:
    """Name a new inquiry from its first prompt without overwriting a rename."""
    import re

    title = re.sub(r"\s+", " ", prompt).strip().strip("\"'`#*- ")
    if not title:
        return
    if len(title) > 64:
        shortened = title[:61].rsplit(" ", 1)[0].rstrip(" ,.;:-")
        title = f"{shortened or title[:61].rstrip()}…"

    get_supabase().table("sessions").update({"title": title}).eq(
        "id", session_id
    ).eq("title", "New Inquiry").execute()
