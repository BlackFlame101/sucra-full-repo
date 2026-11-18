"""Document retry, checkpoint and mandatory review regressions. No provider traffic."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from email.utils import formatdate
from hashlib import sha256
import json
from time import time
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import httpx

from agents import explain_document as document
from agents.llm import provider_retry_after
from tests.test_educational_document import FixtureProvider, MemoryCheckpoint, generate, source

QUERY = "Solve Part 1 of this lab."


class FailureFixture(FixtureProvider):
    def __init__(self, **failures):
        super().__init__()
        self.failures = {stage: iter(sequence) for stage, sequence in failures.items()}
        self.attempts = []

    def model(self, **options):
        real = super().model(**options)
        stage = options["agent"].removeprefix("explain_document_")

        async def invoke(messages):
            serialized = json.dumps([options["model"], options["max_completion_tokens"], options["response_schema"],
                                     [m.content for m in messages]], ensure_ascii=False, separators=(",", ":"))
            self.attempts.append((stage, sha256(serialized.encode()).hexdigest()))
            fault = next(self.failures.get(stage, iter(())), None)
            if isinstance(fault, (int, tuple)):
                status, headers = fault if isinstance(fault, tuple) else (fault, {})
                request = httpx.Request("POST", "https://example.invalid/generate")
                raise httpx.HTTPStatusError("fixture", request=request,
                                            response=httpx.Response(status, headers=headers, request=request))
            if fault == "malformed":
                return SimpleNamespace(content="This response is not a JSON document.",
                                       response_metadata={"finish_reason": "STOP"})
            response = await real.ainvoke(messages)
            if fault == "invalid_citation":
                draft = json.loads(response.content)
                row = draft["sections"][0]
                citation = row["claims"][0]["citations"][0]
                row["markdown"] = row["markdown"].replace(citation, "invalid-citation")
                response.content = json.dumps(draft)
            return response

        return SimpleNamespace(ainvoke=invoke)


class RecoveryTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.bundle = source([{"text": "Part 1 – Model\nExercise A – Validation\nA reliable validation protocol."}])
        self.sleep = self.enterContext(patch.object(document.asyncio, "sleep", AsyncMock()))
        self.enterContext(patch.object(document, "uniform", return_value=.75))

    async def run_fixture(self, provider, checkpoint=None, query=QUERY):
        return await generate(self.bundle, query, provider, checkpoint=checkpoint)

    def assert_stages(self, provider, stages):
        self.assertEqual([stage for stage, _ in provider.attempts], stages)

    async def test_plan_503_and_generation_503_have_independent_retries(self):
        checkpoint = MemoryCheckpoint()
        provider = FailureFixture(plan=[503], generate=[503])
        result = await self.run_fixture(provider, checkpoint)
        self.assertEqual(result["state"], "approved", result["verification"])
        self.assert_stages(provider, ["plan", "plan", "generate", "generate", "review"])
        self.assertEqual([row["document_version"] for row in checkpoint.data["versions"]], ["outline", "sections"])
        reservations = [row for row in checkpoint.data["calls"] if "tokens" in row]
        self.assertEqual(len(reservations), 5)
        self.assertEqual([row["retry"] for row in reservations], [False, True, False, True, False])
        self.assertEqual(reservations[2]["tokens"], reservations[3]["tokens"])

    async def test_three_generation_attempts_are_byte_identical_with_exponential_backoff(self):
        checkpoint = MemoryCheckpoint()
        provider = FailureFixture(generate=[503, 502])
        result = await self.run_fixture(provider, checkpoint)
        self.assertEqual(result["state"], "approved", result["verification"])
        self.assert_stages(provider, ["plan", "generate", "generate", "generate", "review"])
        self.assertEqual(len({digest for stage, digest in provider.attempts if stage == "generate"}), 1)
        self.assertEqual(self.sleep.await_count, 2)
        self.assertAlmostEqual(self.sleep.await_args_list[0].args[0], .75, delta=.1)
        self.assertAlmostEqual(self.sleep.await_args_list[1].args[0], 1.5, delta=.1)
        self.assertEqual(sum(row.get("complete", False) for row in checkpoint.data["versions"]), 1)

    async def test_exhaustion_blocks_review_and_approval(self):
        checkpoint = MemoryCheckpoint()
        provider = FailureFixture(generate=[503, 503, 504, 503])
        result = await self.run_fixture(provider, checkpoint)
        self.assert_stages(provider, ["plan", "generate", "generate", "generate"])
        self.assertEqual(result["verification"]["findings"], ["generate_transport_exhausted"])
        self.assertEqual(result["state"], "draft")
        resumed = FailureFixture()
        result = await self.run_fixture(resumed, checkpoint)
        self.assert_stages(resumed, [])
        self.assertFalse(result["verification"]["passed"])

    async def test_confirmed_transient_restarts_from_plan_and_reuses_attempt_budget(self):
        checkpoint = MemoryCheckpoint()
        provider = FailureFixture(generate=[503])
        self.sleep.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.run_fixture(provider, checkpoint)
        # Simulate a new worker opening the reloaded checkpoint, without previous in-memory dispatch state.
        reloaded = MemoryCheckpoint()
        reloaded.data = json.loads(json.dumps(checkpoint.data))
        reloaded.document = deepcopy(checkpoint.document)
        self.sleep.side_effect = None
        resumed = FailureFixture(generate=[503])
        result = await self.run_fixture(resumed, reloaded)
        self.assertEqual(result["state"], "approved", result["verification"])
        self.assert_stages(resumed, ["generate", "generate", "review"])
        self.assertEqual(provider.attempts[-1][1], resumed.attempts[0][1])
        self.assertEqual([row["document_version"] for row in reloaded.data["versions"]], ["outline", "sections"])
        self.assertEqual(sum(row["purpose"] == "generate" and "tokens" in row for row in reloaded.data["calls"]), 3)

    async def test_malformed_or_invalid_success_never_retries_or_reviews_even_after_reload(self):
        for fault in ("malformed", "invalid_citation"):
            with self.subTest(fault=fault):
                checkpoint = MemoryCheckpoint()
                provider = FailureFixture(generate=[fault])
                result = await self.run_fixture(provider, checkpoint)
                self.assert_stages(provider, ["plan", "generate"])
                self.assertFalse(result["verification"]["passed"])
                resumed = FailureFixture()
                result = await self.run_fixture(resumed, checkpoint)
                self.assert_stages(resumed, [])
                self.assertFalse(result["verification"]["passed"])

    async def test_plan_binding_rejects_wrong_request_and_planner_version(self):
        checkpoint = MemoryCheckpoint()
        await self.run_fixture(FailureFixture(generate=["malformed"]), checkpoint)
        provider = FailureFixture()
        result = await self.run_fixture(provider, checkpoint, query="Solve Part 1 of this lab in detail.")
        self.assertEqual(result["verification"]["findings"], ["plan_checkpoint_incompatible"])
        with patch.object(document, "_PLAN", document._PLAN + " Changed planner prompt."):
            result = await self.run_fixture(provider, checkpoint)
        self.assertEqual(result["verification"]["findings"], ["plan_checkpoint_incompatible"])
        self.assert_stages(provider, [])

    async def test_plan_source_fence_and_duplicate_outline_rejected(self):
        checkpoint = MemoryCheckpoint()
        await self.run_fixture(FailureFixture(generate=["malformed"]), checkpoint)
        original = deepcopy(checkpoint.data["versions"][0])
        checkpoint.data["versions"][0]["source_hash"] = "invalid"
        provider = FailureFixture()
        result = await self.run_fixture(provider, checkpoint)
        self.assertEqual(result["verification"]["findings"], ["document_checkpoint_identity"])
        checkpoint.data["versions"] = [original, deepcopy(original)]
        result = await self.run_fixture(provider, checkpoint)
        self.assertEqual(result["verification"]["findings"], ["plan_checkpoint_incompatible"])
        self.assert_stages(provider, [])

    async def test_retry_after_is_honored_until_deadline_without_spending_an_attempt(self):
        provider = FailureFixture(generate=[(503, {"Retry-After": "5"})])
        result = await self.run_fixture(provider)
        self.assertEqual(result["state"], "approved", result["verification"])
        self.assertAlmostEqual(self.sleep.await_args.args[0], 5, delta=.1)
        self.sleep.reset_mock()
        provider = FailureFixture(generate=[(503, {"Retry-After": "120"})])
        result = await self.run_fixture(provider)
        self.assert_stages(provider, ["plan", "generate"])
        self.assertEqual(result["verification"]["findings"], ["generate_retry_deadline"])
        self.sleep.assert_not_awaited()
        wrapper = RuntimeError("wrapped")
        wrapper.__cause__ = RuntimeError("upstream")
        wrapper.__cause__.headers = {"Retry-After": formatdate(time() + 8, usegmt=True)}
        self.assertGreater(provider_retry_after(wrapper), 6)

    async def test_rate_limit_does_not_retry_and_quota_keeps_a_review_slot(self):
        provider = FailureFixture(generate=[(429, {"Retry-After": "2"})])
        result = await self.run_fixture(provider)
        self.assert_stages(provider, ["plan", "generate"])
        self.assertFalse(result["verification"]["passed"])
        actual = document.explain_budget("google", "gemini-3.5-flash-lite")
        low = replace(actual, model_limits=actual.model_limits.model_copy(update={"requests_per_day": 3}))
        provider = FailureFixture(generate=[503])
        with patch.object(document, "explain_budget", return_value=low), patch.object(
            document, "review_target", return_value=(actual.model_limits.model_id, low)
        ):
            result = await self.run_fixture(provider)
        self.assert_stages(provider, ["plan", "generate"])
        self.assertEqual(result["verification"]["findings"], ["generate_budget"])
