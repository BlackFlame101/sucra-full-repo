"""Single source of truth for the chat LLM (Gemini)."""
from __future__ import annotations

from functools import lru_cache

from langchain_google_genai import ChatGoogleGenerativeAI

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
        max_retries=max_retries,
    )


def get_chat_llm(
    temperature: float = 0.4,
    *,
    streaming: bool = False,
    max_retries: int = 4,
    api_key: str | None = None,
    model: str | None = None,
) -> ChatGoogleGenerativeAI:
    """Return a Gemini chat model.

    ``api_key`` and ``model`` are optional per-request overrides forwarded
    from the WebSocket payload (Settings dialog in the frontend). When both
    are absent we return a process-wide cached instance.

    ``max_retries`` is honoured by ``langchain-google-genai`` for both
    streaming and non-streaming calls and protects us against the 503/429s
    that the public Gemini endpoint occasionally returns under load.
    """
    chosen_key = (api_key or "").strip() or None
    chosen_model = (model or "").strip() or None

    if chosen_key is None and chosen_model is None:
        return _cached_default_llm(temperature, streaming, max_retries)

    settings = get_settings()
    return ChatGoogleGenerativeAI(
        model=chosen_model or settings.chat_model,
        google_api_key=chosen_key or settings.gemini_api_key,
        temperature=temperature,
        streaming=streaming,
        max_retries=max_retries,
    )
