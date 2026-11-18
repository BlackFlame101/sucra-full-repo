"""Local planning estimates for Explain evidence and structured generation."""
from __future__ import annotations

import json
import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from math import ceil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, PositiveInt

from config import DEFAULT_GOOGLE_MODEL, resolve_google_model

logger = logging.getLogger(__name__)

BudgetType = Literal["preparation", "learning"]
CallPurpose = Literal["plan", "vision", "enrich", "generate", "review", "repair"]


class ExplainCallLimit(ValueError):
    def __init__(self, budget_type: BudgetType):
        super().__init__(f"The explanation reached its {budget_type} call limit. Ask for a smaller section.")


class ReviewConfigurationError(ValueError):
    pass


def review_target(provider, generation_model, generation_budget, configured, *, required=False):
    if configured is None and not required:
        return generation_model, generation_budget
    model = (configured or "").strip()
    selected_provider = (provider or "google").strip().lower()
    if (not model or (required and selected_provider != "google")
            or (selected_provider == "google" and resolve_google_model(model) != model)):
        raise ReviewConfigurationError("An explicit supported reviewer model is required.")
    limits = explain_budget(selected_provider, model)
    if limits is None:
        raise ReviewConfigurationError("The reviewer model has no verified local quota configuration.")
    return model, limits


@dataclass
class ExplainCallBudget:
    """Request-local call ceilings. Reserve at dispatch, including every retry."""

    learning_limit: int
    preparation_limit: int = 0
    _calls: Counter[tuple[BudgetType, CallPurpose]] = field(default_factory=Counter, init=False)
    _retries: Counter[BudgetType] = field(default_factory=Counter, init=False)

    def _used(self, budget_type: BudgetType) -> int:
        return sum(count for (kind, _), count in self._calls.items() if kind == budget_type)

    def reserve(self, budget_type: BudgetType, purpose: CallPurpose, *, retry: bool = False) -> None:
        limit = self.learning_limit if budget_type == "learning" else self.preparation_limit
        if self._used(budget_type) >= limit:
            raise ExplainCallLimit(budget_type)
        self._calls[budget_type, purpose] += 1
        if retry:
            self._retries[budget_type] += 1

    def summary(self) -> dict:
        return {
            kind: {
                "limit": limit,
                "used": self._used(kind),
                "by_purpose": {purpose: count for (bucket, purpose), count in self._calls.items() if bucket == kind},
                "retries": self._retries[kind],
            }
            for kind, limit in (("preparation", self.preparation_limit), ("learning", self.learning_limit))
        }


class ModelLimits(BaseModel):
    provider: str
    model_id: str
    context_tokens: PositiveInt | None
    max_output_tokens: PositiveInt | None
    tokens_per_minute: PositiveInt | None
    requests_per_minute: PositiveInt | None = None
    requests_per_day: PositiveInt | None = None
    tokens_per_day: PositiveInt | None = None
    checked_on: str


class BudgetPolicy(BaseModel):
    concurrency_reserve_percent: int = Field(ge=0, lt=100)
    framing_reserve_tokens: PositiveInt
    retry_prompt_reserve_tokens: PositiveInt
    max_output_tokens: PositiveInt
    min_output_tokens: PositiveInt
    max_added_evidence_chunks: int = Field(ge=0, le=20)
    estimate_utf8_bytes_per_token: float = Field(ge=1, le=4)


class LimitsConfig(BaseModel):
    models: list[ModelLimits]
    policy: BudgetPolicy


@lru_cache(maxsize=4)
def _limits_config(override: str | None) -> LimitsConfig | None:
    try:
        payload = override if override is not None else Path(__file__).resolve().parents[1].joinpath(
            "explain_model_limits.json"
        ).read_text(encoding="utf-8")
        return LimitsConfig.model_validate_json(payload)
    except (OSError, ValueError):
        logger.warning("explain_model_limits_unavailable")
        return None


@dataclass(frozen=True)
class ExplainBudget:
    policy: BudgetPolicy
    capacity: int
    max_output_tokens: int
    minute_share: int
    model_limits: ModelLimits

    def prompt_tokens(self, messages, response_schema) -> int:
        payload = json.dumps(
            {"messages": [{"role": message.type, "content": message.content} for message in messages],
             "schema": response_schema}, ensure_ascii=False, separators=(",", ":"),
        )
        size = len(payload.encode("utf-8", errors="replace"))
        return ceil(size / self.policy.estimate_utf8_bytes_per_token) + self.policy.framing_reserve_tokens

    def fits(self, messages, schema, *, reserve_retry: bool = True) -> bool:
        reserve = self.policy.retry_prompt_reserve_tokens if reserve_retry else 0
        return (self.max_output_tokens >= self.policy.min_output_tokens
                and self.prompt_tokens(messages, schema) + self.max_output_tokens + reserve <= self.capacity)


def explain_budget(provider: str | None, model: str | None) -> ExplainBudget | None:
    config = _limits_config(os.getenv("SOCRA_EXPLAIN_MODEL_LIMITS_JSON"))
    if config is None:
        return None
    provider = (provider or "google").strip().lower()
    model = (model or "").strip()
    if provider == "google":
        model = resolve_google_model(model or os.getenv("CHAT_MODEL", DEFAULT_GOOGLE_MODEL))
    elif provider == "groq":
        model = model or os.getenv("GROQ_CHAT_MODEL", "openai/gpt-oss-120b")
    limits = next((entry for entry in config.models if (entry.provider, entry.model_id) == (provider, model)), None)
    if limits is None or None in (limits.context_tokens, limits.tokens_per_minute, limits.max_output_tokens):
        return None
    policy = config.policy
    minute_share = limits.tokens_per_minute * (100 - policy.concurrency_reserve_percent) // 100
    capacity = min(limits.context_tokens, minute_share)
    # Leave room for input even where the model advertises much more output than the minute quota.
    output = min(limits.max_output_tokens, policy.max_output_tokens, capacity // 3)
    return ExplainBudget(policy, capacity, output, minute_share, limits)
