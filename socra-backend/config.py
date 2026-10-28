"""Centralized configuration loaded from environment variables."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, Field


load_dotenv()


class Settings(BaseModel):
    supabase_url: str = Field(default_factory=lambda: os.environ["SUPABASE_URL"])
    supabase_service_role_key: str = Field(
        default_factory=lambda: os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    )
    gemini_api_key: str = Field(default_factory=lambda: os.environ["GEMINI_API_KEY"])
    xai_api_key: str = Field(default_factory=lambda: os.environ.get("XAI_API_KEY", ""))

    backend_port: int = Field(
        default_factory=lambda: int(os.environ.get("BACKEND_PORT", "8000"))
    )
    frontend_url: str = Field(
        default_factory=lambda: os.environ.get("FRONTEND_URL", "http://localhost:3000")
    )
    log_level: str = Field(
        default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO")
    )

    # Model configuration.
    # The default can be overridden per request from the Settings dialog.
    chat_model: str = Field(
        default_factory=lambda: os.environ.get("CHAT_MODEL", "gemini-3.5-flash-lite")
    )
    # text-embedding-004 was retired April 2026. We use gemini-embedding-001
    # truncated to 768 dims (Matryoshka) so it lines up with the vector(768)
    # column in public.embeddings. Existing chunks need re-embedding to fully
    # benefit from this; until then RAG similarity is degraded but functional.
    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
