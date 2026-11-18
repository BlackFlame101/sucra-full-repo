"""Offline plumbing checks. The depth golden set is a separate manual review."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessageChunk

from agents import explicateur
from agents.explain_budget import ExplainCallBudget, ExplainCallLimit
from tests.test_explicateur import SOURCE, response


class ExplainCallBudgetTests(unittest.TestCase):
    def test_preparation_and_learning_have_separate_ceilings(self):
        budget = ExplainCallBudget(learning_limit=2, preparation_limit=1)
        budget.reserve("preparation", "plan")
        budget.reserve("learning", "generate")
        budget.reserve("learning", "generate", retry=True)
        with self.assertRaises(ExplainCallLimit):
            budget.reserve("learning", "review")
        with self.assertRaises(ExplainCallLimit):
            budget.reserve("preparation", "vision")
        self.assertEqual(budget.summary(), {
            "preparation": {"limit": 1, "used": 1, "by_purpose": {"plan": 1}, "retries": 0},
            "learning": {"limit": 2, "used": 2, "by_purpose": {"generate": 2}, "retries": 1},
        })


class ExplainPhaseZeroTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = {
            "SOCRA_ENV": "development",
            "EXPLAIN_UNIT_PIPELINE": "true",
            "SOCRA_EXPLAIN_UNIT_MAX_LEARNING_CALLS": "12",
            "EXPLAIN_TASK_MODES": "0",
            "EXPLAIN_INTENT_PLANS": "0",
            "EXPLAIN_DOCUMENT_INVENTORY": "0",
            "EXPLAIN_MULTI_EXERCISE_BATCHING": "0",
            "EXPLAIN_COVERAGE_CHECK": "0",
        }
        self.enterContext(patch.dict(explicateur.os.environ, self.env, clear=True))
        self.answer = response([1])
        self.answer.usage_metadata = {"input_tokens": 65, "output_tokens": 22}
        self.invoke = AsyncMock(return_value=self.answer)
        self.model = SimpleNamespace(ainvoke=self.invoke)
        self.retrieve = AsyncMock(return_value=[SOURCE])
        self.enterContext(patch.object(explicateur, "retrieve_summary_guided_chunks", self.retrieve))
        self.enterContext(patch.object(explicateur, "retrieve_chunks", AsyncMock(return_value=[])))
        factory = self.enterContext(patch.object(explicateur, "get_chat_llm"))
        factory.return_value = self.model

    async def explain(self, topic="Explain modeling", **state):
        return await explicateur.run_explicateur({"course_id": "fixture", "student_message": topic, **state})

    @staticmethod
    def request_log(captured):
        return json.loads(captured.records[-1].getMessage().removeprefix("explain_request "))

    async def test_flag_is_off_even_in_development_until_explicitly_enabled(self):
        explicateur.os.environ.pop("EXPLAIN_UNIT_PIPELINE")
        explicateur.os.environ["SOCRA_EXPLAIN_UNIT_MAX_LEARNING_CALLS"] = "1"
        self.invoke.side_effect = [SimpleNamespace(content="invalid", response_metadata={}), self.answer]
        with self.assertLogs(explicateur.logger, "INFO") as captured:
            await self.explain()
        self.assertEqual(self.invoke.await_count, 2)
        self.assertNotIn("call_budget", self.request_log(captured))

    async def test_retry_is_metered_and_has_its_own_usage(self):
        self.invoke.side_effect = [
            SimpleNamespace(content="invalid", response_metadata={}, usage_metadata={"input_tokens": 20, "output_tokens": 1}),
            self.answer,
        ]
        with self.assertLogs(explicateur.logger, "INFO") as captured:
            await self.explain()
        event = self.request_log(captured)
        self.assertEqual(event["call_budget"]["learning"], {
            "limit": 2, "used": 2, "by_purpose": {"generate": 2}, "retries": 1,
        })
        self.assertEqual([(a["retry"], a["input_tokens"], a["output_tokens"])
                          for a in event["generation_attempts"]], [(False, 20, 1), (True, 65, 22)])

    async def test_ceiling_prevents_retry_from_reaching_model(self):
        explicateur.os.environ["SOCRA_EXPLAIN_UNIT_MAX_LEARNING_CALLS"] = "1"
        self.invoke.return_value = SimpleNamespace(content="invalid", response_metadata={})
        with self.assertLogs(explicateur.logger, "INFO") as captured:
            with self.assertRaises(ExplainCallLimit):
                await self.explain()
        self.invoke.assert_awaited_once()
        event = self.request_log(captured)
        self.assertEqual(event["call_budget"]["learning"]["retries"], 0)
        self.assertIsNone(event["generation_attempts"][0]["input_tokens"])

    async def test_stream_usage_aggregates_deltas(self):
        async def stream(_):
            yield AIMessageChunk(content=self.answer.content, usage_metadata={
                "input_tokens": 22, "output_tokens": 4, "total_tokens": 26,
            })
            yield AIMessageChunk(content="", usage_metadata={
                "input_tokens": 0, "output_tokens": 5, "total_tokens": 5,
            })

        self.model.astream = stream
        with self.assertLogs(explicateur.logger, "INFO") as captured:
            await self.explain(preview=AsyncMock())
        attempt, = self.request_log(captured)["generation_attempts"]
        self.assertEqual((attempt["input_tokens"], attempt["output_tokens"]), (22, 9))
        self.assertEqual((attempt["chunks_sent"], attempt["chunks_dropped"]), (1, 0))

    async def test_course_scoping_reports_the_evidence_in_the_prompt(self):
        explicateur.os.environ["EXPLAIN_INTENT_PLANS"] = "1"
        document = {"id": SOURCE["document_id"], "filename": SOURCE["filename"], "page_count": 7}
        chunks = [
            {**SOURCE, "id": str(page), "page_number": page, "content": f"Private passage on page {page}."}
            for page in range(1, 8)
        ]
        maps = [
            {"document_id": document["id"], "title": f"Concept {page}", "page_start": page, "page_end": page}
            for page in range(1, 8)
        ]
        self.retrieve.return_value = chunks
        with (
            patch.object(explicateur, "course_documents", AsyncMock(return_value=[document])),
            patch.object(explicateur, "document_inventory_chunks", AsyncMock(return_value=(chunks, "full_document"))),
            patch.object(explicateur, "get_current_course_sections", AsyncMock(return_value=maps)),
            self.assertLogs(explicateur.logger, "INFO") as captured,
        ):
            await self.explain("Explain the whole course", user_id="fixture")
        context = self.invoke.call_args.args[0][-1].content
        self.assertIn("Private passage on page 1.", context)
        self.assertNotIn("Private passage on page 7.", context)
        attempt, = self.request_log(captured)["generation_attempts"]
        self.assertEqual((attempt["chunks_sent"], attempt["chunks_dropped"]), (5, 2))
        self.assertNotIn("Private passage", "\n".join(captured.output))
