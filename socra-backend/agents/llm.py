"""Single source of truth for supported chat LLM providers."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from config import get_settings


@lru_cache(maxsize=8)
def _cached_default_llm(
    temperature: float,
    streaming: bool,
    max_retries: int,
) -> ChatGoogleGenerativeAI:
    """Cached factory for the *server-side default* LLM (no per-user key)."""
    settings = get_settings()
    return ChatGoogleGenerativeAI(
        model=settings.chat_model,
        google_api_key=settings.gemini_api_key,
        temperature=temperature,
        streaming=streaming,
        retries=max_retries,
        request_timeout=45.0,
    )


def get_chat_llm(
    temperature: float = 0.4,
    *,
    streaming: bool = False,
    max_retries: int = 4,
    api_key: str | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> Any:
    """Return the configured chat model (Gemini by default, or xAI Grok).

    ``api_key`` and ``model`` are optional per-request overrides forwarded
    from the WebSocket payload (Settings dialog in the frontend). When both
    are absent we return a process-wide cached instance.

    ``max_retries`` is honored by both provider integrations for streaming
    and non-streaming calls.
    """
    chosen_provider = (provider or "google").strip().lower()
    chosen_key = (api_key or "").strip() or None
    chosen_model = (model or "").strip() or None

    if chosen_provider in {"xai", "grok"}:
        settings = get_settings()
        chosen_key = chosen_key or settings.xai_api_key or None
        if not chosen_key:
            raise ValueError("An xAI API key is required when using Grok.")
        return ChatOpenAI(
            model=chosen_model or "grok-4.7",
            api_key=chosen_key,
            base_url="https://api.x.ai/v1",
            temperature=temperature,
            streaming=streaming,
            max_retries=max_retries,
            timeout=45.0,
        )
    if chosen_provider != "google":
        raise ValueError(f"Unsupported chat provider: {chosen_provider}")

    if chosen_key is None and chosen_model is None:
        return _cached_default_llm(temperature, streaming, max_retries)

    settings = get_settings()
    return ChatGoogleGenerativeAI(
        model=chosen_model or settings.chat_model,
        google_api_key=chosen_key or settings.gemini_api_key,
        temperature=temperature,
        streaming=streaming,
        retries=max_retries,
        request_timeout=45.0,
    )
