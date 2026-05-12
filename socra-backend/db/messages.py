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
