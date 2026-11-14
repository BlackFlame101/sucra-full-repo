from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage

from agents.exercise_generator import generate_verified_exercise
from agents.llm import _cached_default_llm, get_chat_llm
from agents.metrics import ModelMetrics, estimated_cost
from config import DEFAULT_GOOGLE_MODEL, Settings, resolve_google_model
from graph.state import bounded_history
from rag.embeddings import _embed_sync
from rag.retriever import fuse_rankings, retrieval_scope, retrieve_chunks, retrieve_summary_guided_chunks


def row(key: str, page: int = 1) -> dict:
    return {"id": key, "content": key, "document_id": "fixture", "page_number": page, "similarity": 0.7}


class RetrievalEfficiencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_simultaneous_queries_share_embedding_and_vector_read_only_in_this_scope(self):
        with patch("rag.retriever.embed_query", AsyncMock(return_value=[0.1])) as embed, \
             patch("rag.retriever._call_rpc", return_value=[row("semantic")]) as search:
            async with retrieval_scope():
                result = await asyncio.gather(retrieve_chunks("join", "course"), retrieve_chunks("join", "course"))
                self.assertEqual(result, [[row("semantic")], [row("semantic")]])
                await retrieve_chunks("join", "another course")
                self.assertEqual(embed.await_count, 1)
                self.assertEqual(search.call_count, 2)
            async with retrieval_scope():
                await retrieve_chunks("join", "course")
                self.assertEqual(embed.await_count, 2)

    async def test_summary_selection_keeps_lexical_and_semantic_fallback_pages(self):
        section = {"document_id": "fixture", "page_start": 4, "page_end": 5, "title": "Hash Join", "summary": "Database join"}
        with patch("rag.retriever.embed_query", AsyncMock(return_value=[0.1])), \
             patch("rag.retriever._call_rpc", return_value=[row("broad", 1), row("section", 4)]), \
             patch("rag.retriever.get_current_course_sections", AsyncMock(return_value=[section])), \
             patch("rag.retriever._match_terms", return_value=[row("section", 4), row("exact_term", 6)]):
            result = await retrieve_summary_guided_chunks("hash join", "course", k=3)
        self.assertEqual([item["id"] for item in result], ["section", "broad", "exact_term"])
        self.assertEqual([item["page_number"] for item in result], [4, 1, 6])

    async def test_hybrid_search_keeps_lexical_results_when_embedding_fails(self):
        with patch("rag.retriever.embed_query", AsyncMock(side_effect=TimeoutError)), \
             patch("rag.retriever._match_terms", return_value=[row("exact_term")]):
            self.assertEqual(await retrieve_chunks("join", "course", hybrid=True), [row("exact_term")])

    async def test_hybrid_retrieval_keeps_labeled_course_pages_and_ignores_other_courses(self):
        cases = [
            ("Which table holds sales measurements in a star schema?", "fact-table", 4),
            ("Pourquoi LEFT JOIN conserve les clients sans commande ?", "left-join", 12),
            ("What does group_scores do?", "group_scores", 15),
        ]
        for question, label, page in cases:
            with self.subTest(question=question):
                expected = row(label, page)
                vector_rows = [row("related-introduction", 1), expected]
                with patch("rag.retriever.embed_query", AsyncMock(return_value=[0.1])), \
                     patch("rag.retriever._call_rpc", return_value=vector_rows), \
                     patch("rag.retriever._match_terms", return_value=[expected]) as keyword, \
                     patch("rag.retriever.get_current_course_sections", AsyncMock(return_value=[])):
                    baseline = await retrieve_chunks(question, "owned-course", k=1)
                    hybrid = await retrieve_summary_guided_chunks(question, "owned-course", k=1)
                self.assertEqual(baseline[0]["page_number"], 1)
                self.assertEqual(hybrid[0]["page_number"], page)
                self.assertEqual(keyword.call_args.args[0], "owned-course")
                self.assertIn({"fact-table": "table", "left-join": "join", "group_scores": "group_scores"}[label],
                              keyword.call_args.args[1].casefold())

    async def test_structural_checks_alone_accept_a_wrong_course_fact(self):
        source = {**row("source", 4), "document_id": "00000000-0000-0000-0000-000000000021",
                  "filename": "fixture.pdf", "content": "A LEFT JOIN retains unmatched rows from the left table."}
        incorrect = {
            "exercise_type": "multiple_choice", "concept": "SQL LEFT JOIN", "difficulty": "beginner",
            "bloom_level": "remember", "prompt": "Which rows does a LEFT JOIN retain from the left table?",
            "citations": [{"source_index": 1}], "hints": ["Check the join keyword.", "Consider rows without a match."],
            "choices": [{"id": key, "text": value} for key, value in zip("ABCD", (
                "Only rows with a match", "Every left row", "Only right-side rows", "No rows"
            ))],
            "correct_choice": "A", "expected_answer": "Only rows with a match",
            "rubric": [{"criterion": "Selects the correct option", "points": 10}], "common_mistakes": [],
        }
        candidate = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps(incorrect))))
        verifier = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content=json.dumps(
            {"is_valid": False, "issues": ["The source retains every left row, including unmatched rows."]}
        ))))
        with patch("agents.exercise_generator.retrieve_summary_guided_chunks", AsyncMock(return_value=[source])), \
             patch("agents.exercise_generator.get_recent_exercise_prompts", return_value=[]), \
             patch("agents.exercise_generator._model_for", side_effect=lambda state, **kwargs:
                   verifier if kwargs.get("agent") == "exercise_verification" else candidate):
            with self.assertRaisesRegex(ValueError, "Independent verifier rejected"):
                await generate_verified_exercise({
                    "course_id": "course", "session_id": "session", "user_id": "owner",
                    "student_message": "Give me a QCM about LEFT JOIN.", "language": "en",
                })
        self.assertEqual(candidate.ainvoke.await_count, 2)
        self.assertEqual(verifier.ainvoke.await_count, 2)

    def test_fusion_deduplicates_and_prefers_consensus(self):
        result = fuse_rankings([row("a"), row("b")], [row("b"), row("c")], 3)
        self.assertEqual([item["id"] for item in result], ["b", "a", "c"])

    def test_history_budget_keeps_the_latest_contiguous_messages(self):
        history = [{"role": "assistant", "content": "x" * 50}, {"role": "user", "content": "newest"}]
        self.assertEqual(bounded_history(history, max_chars=10), history[-1:])

    async def test_metrics_report_usage_and_public_first_text_without_content(self):
        metrics = ModelMetrics("explain", "google", "fixture", "request", 2)
        run_id = uuid4()
        with patch("agents.metrics.configured_prices", return_value={"google:fixture": {"input": 1, "output": 2}}):
            self.assertEqual(estimated_cost("google", "fixture", 100, 20), 0.00014)
            await metrics.on_chat_model_start({}, [["private prompt"]], run_id=run_id)
            await metrics.on_llm_new_token([{"type": "reasoning", "text": "private thought"}], run_id=run_id)
            self.assertIsNone(metrics.calls[run_id][1])
            await metrics.on_llm_new_token("public text", run_id=run_id)
            await metrics.on_retry(None, run_id=run_id)
            result = SimpleNamespace(generations=[], llm_output={"token_usage": {"prompt_tokens": 100, "completion_tokens": 20}})
            with self.assertLogs("agents.metrics", level="INFO") as logs:
                await metrics.on_llm_end(result, run_id=run_id)
            output = logs.output[0]
            self.assertIn("input_tokens=100 output_tokens=20 retry_events=1", output)
            self.assertIn("estimated_usd=0.00014", output)
            self.assertNotIn("private", output)
            self.assertNotIn("public text", output)


class ModelPolicyTests(unittest.TestCase):
    def test_legacy_and_alias_models_resolve_to_the_pinned_default(self):
        for model in (
            "gemini-2.5-flash", "gemini-2.5-flash-lite", "  MODELS/GEMINI-2.5-FLASH-PREVIEW-09-2025  ",
            "models/gemini-2.5-flash-image", "gemini-flash-latest", "models/gemini-flash-lite-latest",
            "models/gemini-2%2E5-flash", "publishers/google/models/gemini-2.5-flash",
        ):
            with self.subTest(model=model), patch.dict("os.environ", {"CHAT_MODEL": model}):
                settings = Settings(supabase_url="http://example.test", supabase_service_role_key="test", gemini_api_key="test")
                self.assertEqual(settings.chat_model, DEFAULT_GOOGLE_MODEL)
                self.assertEqual(resolve_google_model(model), DEFAULT_GOOGLE_MODEL)
        self.assertEqual(resolve_google_model("models/gemini-3.8-flash"), "gemini-3.8-flash")
        self.assertEqual(resolve_google_model("gemini-2.5-pro"), "gemini-2.5-pro")

    def test_backend_factory_pins_model_for_default_override_and_worker_calls(self):
        settings = SimpleNamespace(chat_model="gemini-flash-latest", gemini_api_key="server-test-key")
        _cached_default_llm.cache_clear()
        self.addCleanup(_cached_default_llm.cache_clear)
        with patch("agents.llm.get_settings", return_value=settings), patch("agents.llm.ChatGoogleGenerativeAI") as google:
            get_chat_llm()
            get_chat_llm(agent="course_summary", api_key="personal-test-key")
            get_chat_llm(agent="explain", model="models/gemini-2.5-flash", streaming=True, response_schema={"type": "object"})
            get_chat_llm(agent="exercise_generation", model="gemini-3.8-flash")
            self.assertEqual([call.kwargs["model"] for call in google.call_args_list],
                             [DEFAULT_GOOGLE_MODEL] * 3 + ["gemini-3.8-flash"])
            self.assertEqual(google.call_args_list[1].kwargs["google_api_key"], "personal-test-key")

    def test_invalid_embedding_is_rejected_before_vector_search(self):
        settings = SimpleNamespace(embedding_model="gemini-embedding-001", embedding_dim=3)
        with patch("rag.embeddings.get_settings", return_value=settings), patch("rag.embeddings._client") as client:
            embed = client.return_value.models.embed_content
            for vector in ([0.1], [0.1, 0.2, float("nan")]):
                embed.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=vector)])
                with self.assertRaisesRegex(ValueError, "invalid vector"):
                    _embed_sync("hash join", task_type="RETRIEVAL_QUERY")
            self.assertEqual(embed.call_args.kwargs["config"].task_type, "RETRIEVAL_QUERY")
