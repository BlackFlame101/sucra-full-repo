"""Single source of truth for supported chat LLM providers."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnableLambda

from config import get_settings

logger = logging.getLogger(__name__)
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
GROQ_STRICT_JSON_MODELS = {
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "meta-models/muse-spark-open",
}
GROQ_REASONING_MODELS = set(GROQ_STRICT_JSON_MODELS)


def _is_groq_json_rejection(exc: BaseException) -> bool:
    """True only for Groq's JSON generation/validation 400 response."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        body = getattr(current, "body", None)
        text = f"{current} {body}".lower()
        if "json_validate_failed" in text:
            return True
        # Follow explicit wrapper causes only. The backup call runs inside the
        # first failure's exception handler, so __context__ can be the original
        # JSON 400 even when the backup itself failed for a different reason
        # (for example, a 413 TPM rate limit).
        current = current.__cause__
    return False


def _groq_json_model(model: ChatOpenAI, model_id: str, schema: dict[str, Any] | None = None):
    if schema and model_id in GROQ_STRICT_JSON_MODELS:
        return model.bind(response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "socra_structured_response",
                "strict": True,
                "schema": schema,
            },
        })
    return model.bind(response_format={"type": "json_object"})


class GroqJsonOutputError(RuntimeError):
    """Raised when both selected and backup models fail structured generation."""


def provider_error_code(exc: BaseException) -> str | None:
    """Classify common API-key and provider access failures across wrapped errors."""
    seen: set[int] = set()
    current: BaseException | None = exc
    groq_json_output_rejected = False
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status_code", None) or getattr(current, "status", None)
        body = getattr(current, "body", None)
        text = f"{current} {body}".lower()
        if "groqjsonoutputerror" in text or "json_validate_failed" in text:
            groq_json_output_rejected = True
        if any(marker in text for marker in (
            "insufficient_quota", "resource_exhausted", "quota exceeded",
        )):
            return "API_KEY_QUOTA_EXCEEDED"
        if status == 429 or any(marker in text for marker in (
            "rate_limit_exceeded", "rate limit", "too many requests",
        )):
            return "API_RATE_LIMITED"
        if status == 401 or any(marker in text for marker in (
            "invalid_api_key", "invalid api key", "incorrect api key",
            "authentication error", "unauthorized",
        )):
            return "API_KEY_INVALID"
        if status == 403 or any(marker in text for marker in (
            "permission denied", "insufficient permission", "not authorized to access",
        )):
            return "API_KEY_ACCESS_DENIED"
        current = current.__cause__ or current.__context__
    if groq_json_output_rejected:
        return "GROQ_STRUCTURED_OUTPUT_FAILED"
    return None


def provider_error_message(code: str) -> str:
    return {
        "API_KEY_QUOTA_EXCEEDED": "Your selected AI API key has reached its usage limit. Open Settings and add or select another API key, then try again.",
        "API_KEY_INVALID": "Your AI API key was rejected. Open Settings and replace it with a valid key, then try again.",
        "API_KEY_ACCESS_DENIED": "This AI API key does not have access to the selected model. Check your key and model in Settings.",
        "API_RATE_LIMITED": "The AI provider is temporarily rate-limiting requests. Wait a moment and retry, or switch to another key in Settings.",
        "GROQ_STRUCTURED_OUTPUT_FAILED": "Groq could not complete a valid structured response with the selected or backup model. The response may have reached its output limit. Try again with a narrower request or choose another model in Settings.",
    }.get(code, "The AI provider could not complete the request. Check your API key and model in Settings, then try again.")


def is_provider_quota_error(exc: BaseException) -> bool:
    return provider_error_code(exc) == "API_KEY_QUOTA_EXCEEDED"


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
    response_schema: dict[str, Any] | None = None,
    max_completion_tokens: int | None = None,
) -> Any:
    """Return the configured chat model (Gemini by default, or Groq).

    ``api_key`` and ``model`` are optional per-request overrides forwarded
    from the WebSocket payload (Settings dialog in the frontend). When both
    are absent we return a process-wide cached instance.

    ``max_retries`` is honored by both provider integrations for streaming
    and non-streaming calls.
    """
    chosen_provider = (provider or "google").strip().lower()
    chosen_key = (api_key or "").strip() or None
    chosen_model = (model or "").strip() or None

    if chosen_provider == "groq":
        settings = get_settings()
        chosen_key = chosen_key or settings.groq_api_key or None
        if not chosen_key:
            raise ValueError("A Groq API key is required when using Groq.")
        primary_model_id = chosen_model or GROQ_DEFAULT_MODEL
        groq_options: dict[str, Any] = {}
        if max_completion_tokens is not None:
            # ChatOpenAI maps its max_tokens option to Groq's current
            # max_completion_tokens request field.
            groq_options["max_tokens"] = max_completion_tokens
        if primary_model_id in GROQ_REASONING_MODELS:
            groq_options["reasoning_effort"] = "low"
        groq_model = ChatOpenAI(
            model=primary_model_id,
            api_key=chosen_key,
            base_url="https://api.groq.com/openai/v1",
            temperature=temperature,
            streaming=streaming,
            max_retries=max_retries,
            timeout=45.0,
            **groq_options,
        )
        # Every non-streaming Groq call in Socra expects a structured JSON
        # payload. Keep the Socratic tutor's streaming free-text path untouched.
        # Groq JSON Object Mode is supported across its chat models; individual
        # agents still validate their own schemas and retry/fallback as needed.
        if streaming:
            return groq_model

        primary = _groq_json_model(groq_model, primary_model_id, response_schema)
        # Retry only Groq's JSON generation failure with another generally
        # available text model. Do not mask key, quota, permission, or rate errors.
        backup_model_id = (
            "openai/gpt-oss-20b"
            if primary_model_id == GROQ_DEFAULT_MODEL
            else GROQ_DEFAULT_MODEL
        )
        backup_options: dict[str, Any] = {}
        if max_completion_tokens is not None:
            backup_options["max_tokens"] = max_completion_tokens
        if backup_model_id in GROQ_REASONING_MODELS:
            backup_options["reasoning_effort"] = "low"
        backup = _groq_json_model(ChatOpenAI(
            model=backup_model_id,
            api_key=chosen_key,
            base_url="https://api.groq.com/openai/v1",
            temperature=temperature,
            streaming=False,
            max_retries=max_retries,
            timeout=45.0,
            **backup_options,
        ), backup_model_id, response_schema)

        async def invoke_with_json_backup(input: Any, config: Any = None) -> Any:
            try:
                return await primary.ainvoke(input, config=config)
            except Exception as exc:
                if not _is_groq_json_rejection(exc):
                    raise
                logger.warning(
                    "Groq model %s rejected a structured response; retrying once with %s",
                    primary_model_id,
                    backup_model_id,
                )
                try:
                    backup_input = input
                    if isinstance(input, list):
                        backup_input = [
                            *input,
                            HumanMessage(content=(
                                "The previous attempt was rejected by the provider's JSON validator. "
                                "Return one complete JSON object that follows the requested fields exactly. "
                                "Escape quotes and newlines inside strings, do not use markdown fences, and "
                                "avoid unrelated exercises or repeated explanations. Shorten the answer "
                                "substantially, group related code lines into a few logical walkthrough "
                                "blocks, and preserve only the exercise the student requested."
                            )),
                        ]
                    return await backup.ainvoke(backup_input, config=config)
                except Exception as backup_exc:
                    if _is_groq_json_rejection(backup_exc):
                        raise GroqJsonOutputError(
                            "Groq could not produce a response in the required format using the selected "
                            "or backup model. Try again or choose another model in Settings."
                        ) from backup_exc
                    raise

        return RunnableLambda(invoke_with_json_backup)
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
