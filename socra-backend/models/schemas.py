"""Pydantic models used by the FastAPI / WebSocket layer."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    agents: list[str] = Field(
        default_factory=lambda: [
            "diagnostiqueur",
            "tuteur_socratique",
            "evaluateur",
            "memoire",
        ]
    )


class ChatRequest(BaseModel):
    message: str
    course_id: str
    session_id: str


class ContextRequest(BaseModel):
    session_id: str
    course_id: str


class WSMessage(BaseModel):
    type: Literal["token", "context", "diagnostic", "done", "error"]
    content: Any | None = None
