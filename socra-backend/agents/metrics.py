"""Content-free model metrics shared by streaming and structured agents."""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from math import isfinite
from time import monotonic

from langchain_core.callbacks import AsyncCallbackHandler

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def configured_prices() -> dict:
    """USD per million input and output tokens, supplied by the operator."""
    try:
        prices = json.loads(os.getenv("SOCRA_MODEL_PRICES_JSON", "{}"))
        return prices if isinstance(prices, dict) else {}
    except ValueError:
        logger.warning("model_pricing_config_invalid")
        return {}


def estimated_cost(provider: str, model: str, input_tokens, output_tokens) -> float | None:
    price = configured_prices().get(f"{provider}:{model}")
    if not isinstance(price, dict) or not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None
    rates = (price.get("input"), price.get("output"))
    if not all(isinstance(rate, (int, float)) and isfinite(rate) and rate >= 0 for rate in rates):
        return None
    return (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000


class ModelMetrics(AsyncCallbackHandler):
    def __init__(self, agent: str, provider: str, model: str, request_id: str | None, retry_budget: int):
        self.agent, self.provider, self.model = agent, provider, model
        self.request_id, self.retry_budget = request_id, retry_budget
        self.calls: dict = {}

    async def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self.calls[run_id] = [monotonic(), None, 0]

    async def on_llm_new_token(self, token, *, run_id, chunk=None, **kwargs):
        call = self.calls.get(run_id)
        if call is not None and call[1] is None:
            content = getattr(getattr(chunk, "message", None), "content", token)
            if (isinstance(content, str) and content) or (
                isinstance(content, list) and any(isinstance(x, dict) and x.get("type") == "text" and x.get("text") for x in content)
            ):
                call[1] = monotonic()

    async def on_retry(self, retry_state, *, run_id, **kwargs):
        if run_id in self.calls:
            self.calls[run_id][2] += 1

    async def on_llm_end(self, response, *, run_id, **kwargs):
        usage = next(
            (usage for group in response.generations for item in group
             if (usage := getattr(getattr(item, "message", None), "usage_metadata", None))),
            None,
        )
        if not usage:
            raw = (response.llm_output or {}).get("token_usage") or {}
            usage = {"input_tokens": raw.get("prompt_tokens"), "output_tokens": raw.get("completion_tokens")}
        self._log(run_id, "ok", usage)

    async def on_llm_error(self, error, *, run_id, **kwargs):
        self._log(run_id, type(error).__name__, {})

    def _log(self, run_id, status: str, usage: dict):
        call = self.calls.pop(run_id, None)
        if call is None:
            return
        started, first, retries = call
        input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
        logger.info(
            "model_call request_id=%s agent=%s provider=%s model=%s status=%s total_ms=%d first_text_ms=%s "
            "input_tokens=%s output_tokens=%s retry_events=%d retry_budget=%d estimated_usd=%s",
            self.request_id, self.agent, self.provider, self.model, status, (monotonic() - started) * 1000,
            round((first - started) * 1000) if first is not None else None, input_tokens, output_tokens,
            retries, self.retry_budget, estimated_cost(self.provider, self.model, input_tokens, output_tokens),
        )


def structured_failure(agent: str, state: dict, attempt: int, error: Exception) -> None:
    logger.warning("structured_output_rejected request_id=%s agent=%s attempt=%d error_type=%s",
                   state.get("model_request_id") or state.get("request_id"), agent, attempt, type(error).__name__)
