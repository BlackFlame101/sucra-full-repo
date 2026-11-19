"""Single source of truth for supported chat LLM providers."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import httpx
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnableLambda
from openai import APIConnectionError

from agents.metrics import ModelMetrics
from config import get_settings, resolve_google_model

logger = logging.getLogger(__name__)
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


def is_transient_provider_error(exc: BaseException) -> bool:
    """Recognize retryable provider status and transport failures, including SDK wrappers."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status_code", None) or getattr(current, "code", None)
        if status in (500, 502, 503, 504) or isinstance(current, (httpx.TransportError, APIConnectionError)):
            return True
        current = current.__cause__ or current.__context__
    return False


def provider_error_code(exc: BaseException) -> str | None:
    """Classify common API-key and provider access failures across wrapped errors."""
    seen: set[int] = set()
    current: BaseException | None = exc
    groq_json_output_rejected = False
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status_code", None) or getattr(current, "code", None) or getattr(current, "status", None)
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
        "PROVIDER_UNAVAILABLE": "The AI provider interrupted the response. Try again in a moment.",
        "GROQ_STRUCTURED_OUTPUT_FAILED": "Groq could not complete a valid structured response. The response may have reached its output limit. Try again with a narrower request or choose another model in Settings.",
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
        model=resolve_google_model(settings.chat_model),
        google_api_key=settings.gemini_api_key,
        temperature=temperature,
        streaming=streaming,
        max_retries=max_retries,
        timeout=45.0,
    )


class SingleDispatchGoogleTransport(httpx.BaseTransport, httpx.AsyncBaseTransport):
    """Use HTTPX for Gemini so each invocation owns exactly one dispatch."""

    def __init__(self):
        # The SDK shares client_args between its sync and async HTTPX clients.
        self.sync_transport = httpx.HTTPTransport(retries=0)
        self.async_transport = httpx.AsyncHTTPTransport(retries=0)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self.sync_transport.handle_request(request)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.async_transport.handle_async_request(request)

    def close(self) -> None:
        self.sync_transport.close()

    async def aclose(self) -> None:
        self.close()
        await self.async_transport.aclose()


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
    single_attempt: bool = False,
    agent: str = "unknown",
    request_id: str | None = None,
    google_transport: httpx.BaseTransport | None = None,
) -> Any:
    """Return the configured chat model (Gemini by default, or Groq).

    ``api_key`` and ``model`` are optional per-request overrides forwarded
    from the WebSocket payload (Settings dialog in the frontend). When both
    are absent we return a process-wide cached instance.

    ``max_retries`` is honored by both provider integrations for streaming
    and non-streaming calls. Use ``single_attempt`` when the caller owns the
    retry budget, including any fallback.
    """
    chosen_provider = (provider or "google").strip().lower()
    chosen_key = (api_key or "").strip() or None
    chosen_model = (model or "").strip() or None
    if single_attempt:
        # Gemini counts total attempts. OpenAI counts additional retries.
        max_retries = 0 if chosen_provider == "groq" else 1

    def monitor(llm, model_id: str):
        # Keep logged model IDs single-line and exclude credentials and prompt content.
        safe_model = "".join(c for c in model_id[:120] if c.isascii() and (c.isalnum() or c in "-_./:"))
        return llm.with_config(callbacks=[ModelMetrics(agent, chosen_provider, safe_model, request_id, max_retries)])

    if chosen_provider == "groq":
        settings = get_settings()
        chosen_key = chosen_key or settings.groq_api_key or None
        if not chosen_key:
            raise ValueError("A Groq API key is required when using Groq.")
        primary_model_id = chosen_model or settings.groq_model
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
            return monitor(groq_model.bind(response_format={"type": "json_object"}) if response_schema else groq_model, primary_model_id)

        primary = monitor(_groq_json_model(groq_model, primary_model_id, response_schema), primary_model_id)
        backup_model_id = settings.groq_backup_model
        if single_attempt or not backup_model_id or backup_model_id == primary_model_id:
            return primary
        # Retry only Groq's JSON generation failure with another generally
        # available text model. Do not mask key, quota, permission, or rate errors.
        backup_options: dict[str, Any] = {}
        if max_completion_tokens is not None:
            backup_options["max_tokens"] = max_completion_tokens
        if backup_model_id in GROQ_REASONING_MODELS:
            backup_options["reasoning_effort"] = "low"
        backup = monitor(_groq_json_model(ChatOpenAI(
            model=backup_model_id,
            api_key=chosen_key,
            base_url="https://api.groq.com/openai/v1",
            temperature=temperature,
            streaming=False,
            max_retries=max_retries,
            timeout=45.0,
            **backup_options,
        ), backup_model_id, response_schema), backup_model_id)

        async def invoke_with_json_backup(input: Any, config: Any = None) -> Any:
            try:
                return await primary.ainvoke(input, config=config)
            except Exception as exc:
                if not _is_groq_json_rejection(exc):
                    raise
                logger.warning(
                    "groq_structured_backup agent=%s request_id=%s", agent, request_id,
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

    if (chosen_key is None and chosen_model is None and max_completion_tokens is None
            and response_schema is None and google_transport is None):
        return monitor(_cached_default_llm(temperature, streaming, max_retries), resolve_google_model(get_settings().chat_model))

    settings = get_settings()
    google_model_id = resolve_google_model(chosen_model or settings.chat_model)
    google_model = ChatGoogleGenerativeAI(
        model=google_model_id,
        google_api_key=chosen_key or settings.gemini_api_key,
        max_output_tokens=max_completion_tokens,
        temperature=temperature,
        streaming=streaming,
        max_retries=max_retries,
        timeout=45.0,
        **({"client_args": {"transport": google_transport, "follow_redirects": False}} if google_transport else {}),
    )
    if streaming and response_schema:
        google_model = google_model.bind(response_mime_type="application/json", response_json_schema=response_schema)
    return monitor(google_model, google_model_id)


def visible_text(content: Any) -> str:
    """Project only public text from provider message blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block["text"] for block in content
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        )
    return ""
