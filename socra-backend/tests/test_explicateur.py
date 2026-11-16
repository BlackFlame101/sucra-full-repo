from __future__ import annotations

import asyncio
import json
import re
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from google.genai.errors import ClientError
from langchain_core.messages import AIMessageChunk
from openai import BadRequestError, RateLimitError

from agents import explicateur
from agents import llm
from agents.explicateur import _bind_sources, _normalize_explanation_payload
from agents.explain_tasks import classify_explain_task, task_prompt
from models.schemas import GeneratedExplanation

SOURCE = {
    "id": "chunk-0001",
    "document_id": "00000000-0000-0000-0000-000000000001",
    "filename": "Course.pdf",
    "page_number": 4,
    "content": "A project manager coordinates work toward the project objectives.",
}
OUTLINE = "Partie 1 Install the tools.\nQuestion 1 Describe results.\n1. Start the program.\n2. Run the job."
TP_REQUEST = (
    "I want you to detail everything of what i need to do to complete this tp in my laptop "
    "with every install of any application and every code that i need and every command i need to run "
    "and everything i need to do for each screen shot detailed at the end of the file as well"
)


class ExplainTaskTests(unittest.TestCase):
    def profile(self, message, language="fr", explicit=False):
        return classify_explain_task(message, language, explicit, False, [], False)

    def test_classifies_complementary_subjects_and_guidance(self):
        for message, intent in (
            (TP_REQUEST, "lab_walkthrough"),
            ("Explain every major concept", "concept_explanation"),
            ("Give hints for Questions 1-6", "exercise_guidance"),
            ("Set up my complete Python project with every command", "coding_guide"),
            ("Explain the maths proof", "math_explanation"),
            ("Help with this grammar exercise", "language_lesson"),
            ("Explain this research methodology", "research_analysis"),
            ("Compare the values in this table", "data_table_analysis"),
            ("Explique toutes les étapes du TP", "lab_walkthrough"),
            ("اشرح كل خطوات التثبيت", "lab_walkthrough"),
        ):
            with self.subTest(message=message):
                self.assertEqual(self.profile(message).intent, intent)
        lab = self.profile(TP_REQUEST)
        self.assertEqual(lab.detail_level, "exhaustive")
        self.assertNotIn("complete runnable code", task_prompt(lab))
        self.assertIn("complete runnable code", task_prompt(self.profile("Explain this Python script")))
        self.assertIn("Do not give ready-made answers", task_prompt(self.profile("Give hints for Questions 1-6")))

    def test_response_language_precedence(self):
        self.assertEqual(self.profile("Explain this concept").language, "English")
        self.assertEqual(self.profile("Explain this concept", explicit=True).language, "French")
        self.assertEqual(self.profile("Explain this concept. Answer in French.", "en", True).language, "French")
        self.assertEqual(self.profile("اشرح هذه المعادلة").language, "Arabic")
        self.assertEqual(self.profile("Explain this concept. Answer in Arabic.", "fr", True).language, "Arabic")

    def test_brevity_variants_and_detailed_requests(self):
        for request in (
            "give me a short summary", "Give me a quick overview", "Explain overfitting briefly.",
            "Summarize this in three bullets.", "En bref, explique la validation croisee.",
            "Explain it in a single sentence.", "Explique en une seule phrase.", "اشرح في جملة واحدة.",
            "Donne un resume court.", "اشرح الانحدار باختصار",
        ):
            with self.subTest(request=request):
                task = self.profile(request)
                self.assertEqual((task.intent, task.detail_level), ("short_summary", "brief"))
                self.assertEqual(explicateur._request_style(request)[0], "short summary")
        for request in ("Explain it in a single sentence.", "Explique en une seule phrase.", "اشرح في جملة واحدة."):
            task = self.profile(request)
            self.assertTrue(task.single_sentence)
            self.assertIn("exactly one direct sentence", explicateur.task_prompt(task))
        for request in (
            TP_REQUEST, "Give a brief summary first, then explain the lab in detail.",
            "Do not summarize briefly. Explain the methodology.",
        ):
            with self.subTest(request=request):
                self.assertNotEqual(self.profile(request).intent, "short_summary")

    def test_flags_default_off_and_enable_in_development(self):
        with patch.dict(explicateur.os.environ, {}, clear=True):
            self.assertFalse(explicateur.explain_flag("EXPLAIN_TASK_MODES"))
            with patch.dict(explicateur.os.environ, {"SOCRA_ENV": "development", "EXPLAIN_MULTI_EXERCISE_BATCHING": "0"}):
                self.assertTrue(explicateur.explain_flag("EXPLAIN_TASK_MODES"))
                self.assertFalse(explicateur.explain_flag("EXPLAIN_MULTI_EXERCISE_BATCHING"))

    def test_lab_normalizer_keeps_fences_and_inline_rows_in_order(self):
        fence = chr(96) * 3
        content = f"Open the app.\n{fence}powershell\nWrite-Output ready\n{fence}\nClick Run.\n{fence}bash\necho done\n{fence}\n" + chr(96) + "run" + chr(96) + ": Executes."
        payload = {"sections": [{"heading": "Setup", "content": content}]}
        lab = _normalize_explanation_payload(payload, "lab_walkthrough")["sections"][0]
        self.assertEqual(lab["content"], content)
        self.assertEqual(lab["code"], "")
        self.assertEqual(lab["walkthrough"], [])
        coding = _normalize_explanation_payload({"sections": [
            {"heading": "Setup", "content": content.split("Click Run.")[0]},
        ]}, "coding_guide")
        self.assertEqual(coding["sections"][0]["code"], "")
        self.assertEqual(coding["sections"][0]["content"], content.split("Click Run.")[0])
        default = _normalize_explanation_payload(payload)["sections"][0]
        self.assertEqual(default["content"], content)
        self.assertEqual(default["walkthrough"], [])


def response(citations):
    return SimpleNamespace(response_metadata={}, content=json.dumps({
        "definition": "A sample definition.",
        "intuition": "A sample intuition.",
        "sections": [{"heading": "Sample section", "content": "A sample explanation."}],
        "citations": citations,
    }))


class ExplainAdapterTests(unittest.TestCase):
    def test_single_attempt_disables_sdk_retries_and_configured_groq_backup(self):
        settings = SimpleNamespace(
            groq_api_key="fake", groq_model="primary", groq_backup_model="backup",
            chat_model="gemini-3.5-flash-lite", gemini_api_key="fake",
        )
        with patch.object(llm, "get_settings", return_value=settings), \
                patch.object(llm, "ChatOpenAI") as groq, \
                patch.object(llm, "ChatGoogleGenerativeAI") as gemini:
            for stream in (True, False):
                groq.reset_mock()
                gemini.reset_mock()
                llm.get_chat_llm(provider="groq", streaming=stream, single_attempt=True, max_completion_tokens=16_000)
                llm.get_chat_llm(provider="google", streaming=stream, single_attempt=True, max_completion_tokens=16_000)
                groq.assert_called_once()
                gemini.assert_called_once()
                self.assertEqual(groq.call_args.kwargs["max_retries"], 0)
                self.assertEqual(gemini.call_args.kwargs["max_retries"], 1)


class ExplanationCitationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = [SOURCE.copy()]

    def test_binds_source_index_to_retrieved_citation(self) -> None:
        bound = _bind_sources({"citations": [{"source_index": 1}]}, self.chunks)
        self.assertEqual(bound["citations"][0]["page_number"], 4)
        self.assertEqual(bound["citations"][0]["filename"], "Course.pdf")

    def test_accepts_metadata_only_when_it_matches_retrieved_source(self) -> None:
        bound = _bind_sources({"citations": [{"page_number": 4, "filename": "Course.pdf"}]}, self.chunks)
        self.assertEqual(bound["citations"][0]["document_id"], self.chunks[0]["document_id"])

    def test_rejects_unmatched_source(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not match"):
            _bind_sources({"citations": [{"source_index": 8}]}, self.chunks)

    def test_drops_invalid_citations_and_deduplicates_by_document_and_page(self):
        self.chunks.extend([
            {**SOURCE, "id": "same-page"},
            {**SOURCE, "document_id": "bad-id"},
            {**SOURCE, "page_number": 5, "content": "Too short"},
            {**SOURCE, "page_number": None},
            {**SOURCE, "document_id": "00000000-0000-0000-0000-000000000002"},
        ])
        drops = Counter()
        bound = _bind_sources({
            "citations": [99, True, 1.0, "1", {}, 3, 4, 5, 1, 2, 6],
        }, self.chunks, drops)
        self.assertEqual([cit["document_id"] for cit in bound["citations"]],
                         [self.chunks[0]["document_id"], self.chunks[5]["document_id"]])
        self.assertEqual(drops, {
            "invalid_index": 1, "malformed_value": 4, "invalid_source_metadata": 2,
            "short_excerpt": 1, "duplicate_page": 1,
        })

    def test_bad_index_cannot_fall_back_to_matching_echoed_metadata(self):
        for index in (0, 8, None):
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "does not match"):
                _bind_sources({"citations": [
                    {"source_index": index, "page_number": 4, "filename": "Course.pdf"},
                ]}, self.chunks)

    def test_metadata_from_unretrieved_document_and_ambiguous_pages_are_rejected(self):
        self.chunks.append({**SOURCE, "document_id": "00000000-0000-0000-0000-000000000002"})
        for reference in (
            {"page_number": 4, "filename": "Course.pdf"},
            {"page_number": 4, "filename": "Course.pdf", "document_id": "00000000-0000-0000-0000-000000000003"},
            {"page_number": 99, "document_id": SOURCE["document_id"]},
        ):
            with self.subTest(reference=reference), self.assertRaisesRegex(ValueError, "does not match"):
                _bind_sources({"citations": [reference]}, self.chunks)

    def test_bound_citations_respect_the_existing_card_limit(self):
        chunks = [{**SOURCE, "page_number": page} for page in range(1, 11)]
        bound = _bind_sources({"citations": list(range(1, 11))}, chunks)
        self.assertEqual([cit["page_number"] for cit in bound["citations"]], list(range(1, 9)))

    def test_normalizes_string_pitfalls_to_a_list(self) -> None:
        payload = _normalize_explanation_payload({
            "common_pitfalls": "Failing to launch the program.",
            "sections": [{"heading": "Run", "content": "Run the program from its folder."}],
            "citations": [1],
        })
        self.assertEqual(payload["common_pitfalls"], ["Failing to launch the program."])

    def test_normalizes_string_section_and_citation_shapes(self) -> None:
        payload = _normalize_explanation_payload({
            "sections": ["A detailed section explaining the concept."],
            "citations": "1",
        })
        self.assertEqual(payload["sections"][0]["heading"], "Section 1")
        self.assertEqual(payload["citations"], ["1"])

    def test_splits_inline_code_explanations_into_walkthrough_rows(self) -> None:
        payload = _normalize_explanation_payload({
            "sections": [{
                "heading": "Line by line",
                "content": "Intro\n- `import sys` : Imports arguments support [4].\n- `sc.stop()` : Stops Spark [4].",
            }],
        })
        section = payload["sections"][0]
        self.assertEqual(section["content"], "Intro")
        self.assertEqual(len(section["walkthrough"]), 2)
        self.assertEqual(section["walkthrough"][0]["code"], "import sys")


class SectionCitationTests(unittest.TestCase):
    def test_section_indexes_bind_independently_of_legacy_global_limit(self):
        chunks = [{**SOURCE, "page_number": page} for page in range(1, 11)]
        second_pdf = {**SOURCE, "document_id": "00000000-0000-0000-0000-000000000002",
                      "filename": "Other.pdf", "page_number": 1}
        chunks.extend([second_pdf, {**SOURCE, "page_number": 1}, {**SOURCE, "page_number": 0}])
        payload = _normalize_explanation_payload({
            "definition": "", "intuition": "", "citations": list(range(1, 11)),
            "sections": [
                {"heading": "Setup", "content": "Open the app.", "citations": [second_pdf],
                 "source_indexes": [False, 0, -1, "2", {"source_index": 2}, 99, 13, *range(1, 13)],
                 "covers": ["question:1", " Question 2 ", "question:1", 99, "", "x" * 181]},
                {"heading": "Continue", "source_indexes": [0, 100], "citations": [second_pdf]},
                {"heading": "Screenshot checkpoint", "source_indexes": "2"},
            ],
        })
        bound = _bind_sources(payload, chunks)
        card = GeneratedExplanation.model_validate(bound).model_dump(mode="json", exclude_none=True)
        self.assertEqual(len(card["citations"]), 8)
        setup = card["sections"][0]
        self.assertEqual([citation["page_number"] for citation in setup["citations"]], [*range(1, 11), 1])
        self.assertEqual(setup["citations"][-1]["document_id"], second_pdf["document_id"])
        self.assertEqual(setup["citations"][-1]["excerpt"], second_pdf["content"])
        self.assertEqual(setup["covers"], ["question:1", "Question 2"])
        for section in card["sections"]:
            self.assertNotIn("source_indexes", section)
        for section in card["sections"][1:]:
            self.assertNotIn("citations", section)

    def test_legacy_card_still_validates_without_new_fields(self):
        old = {"definition": "Previously saved definition.", "intuition": "Previously saved intuition.",
               "sections": [{"heading": "Old solution", "code": "print(1)", "code_language": "python"}],
               "citations": [{"document_id": SOURCE["document_id"], "filename": SOURCE["filename"],
                              "page_number": SOURCE["page_number"], "excerpt": SOURCE["content"]}]}
        card = GeneratedExplanation.model_validate_json(json.dumps(old))
        self.assertEqual(card.sections[0].code, "print(1)")
        self.assertIsNone(card.sections[0].citations)
        self.assertIsNone(card.sections[0].covers)
        self.assertEqual(card.citations[0].page_number, 4)

    def test_preview_keeps_content_and_omits_nested_unbound_data(self):
        from agents.explanation_preview import explanation_preview

        raw = json.dumps({"sections": [{
            "heading": "Setup", "content": "Open the app.\n\n" + chr(96) * 3 + "bash\necho first\n" + chr(96) * 3 + "\n\nClick Run.",
            "source_indexes": [1], "covers": ["question:1"], "code_language": "powershell",
            "code": "Write-Output second", "walkthrough": [{"code": "Write-Output second", "explanation": "Writes the output."}],
            "citations": [{"content": "untrusted preview text"}],
        }]})
        preview = explanation_preview(raw)
        self.assertLess(preview.index("echo first"), preview.index("Click Run"))
        self.assertLess(preview.index("Click Run"), preview.index("powershell"))
        self.assertEqual(preview.count("Write-Output second"), 1)
        self.assertIn("Writes the output.", preview)
        self.assertNotIn("untrusted preview text", preview)
        self.assertNotIn("question:1", preview)
        for cutoff in range(1, len(raw) + 1):
            self.assertTrue(preview.startswith(explanation_preview(raw[:cutoff])))


class ExplanationRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch.dict(explicateur.os.environ, {
            "EXPLAIN_TASK_MODES": "0", "EXPLAIN_MULTI_EXERCISE_BATCHING": "0",
        }))
        self.retrieve = AsyncMock(return_value=[{**SOURCE, "content": OUTLINE}])
        self.invoke = AsyncMock(return_value=response([1]))
        for name, mock in (
            ("retrieve_summary_guided_chunks", self.retrieve),
            ("retrieve_chunks", AsyncMock(return_value=[])),
            ("get_chat_llm", lambda *args, **kwargs: SimpleNamespace(ainvoke=self.invoke)),
        ):
            self.enterContext(patch.object(explicateur, name, mock))

    async def explain(self, message):
        return await explicateur.run_explicateur({
            "course_id": "course-1", "student_message": message, "request_id": "req-1",
            "api_key": "private-fixture-key", "profile": {"mastered_concepts": ["private-profile-entry"]},
        })

    async def test_adaptive_lab_uses_one_generation_and_ordered_content(self):
        self.retrieve.return_value = [{**SOURCE, "content": OUTLINE + "\nExercise 1 Analyze data.\nExercise 2 Check results."}]
        with patch.dict(explicateur.os.environ, {
            "EXPLAIN_TASK_MODES": "1", "EXPLAIN_MULTI_EXERCISE_BATCHING": "1",
            "EXPLAIN_DOCUMENT_INVENTORY": "0", "EXPLAIN_COVERAGE_CHECK": "0",
        }), self.assertLogs("agents.explicateur", level="INFO") as captured:
            await self.explain(TP_REQUEST)
        self.invoke.assert_awaited_once()
        system = self.invoke.call_args.args[0][0].content
        self.assertIn("lab walkthrough", system)
        self.assertIn("fenced Markdown blocks inside section.content", system)
        self.assertIn("Do not give ready-made answers", system)
        self.assertIn("section.source_indexes", system)
        self.assertIn("Address each mandatory question individually", system)
        event = json.loads(captured.records[-1].getMessage().removeprefix("explain_request "))
        self.assertEqual(event["style"], "detailed teaching explanation")
        self.assertEqual(event["intent"], "lab_walkthrough")
        self.assertEqual(event["detail_level"], "exhaustive")
        self.assertTrue(event["task_modes_enabled"])
        self.assertFalse(event["coverage_check_enabled"])

    async def test_adaptive_named_exercise_uses_original_number(self):
        self.retrieve.return_value = [{**SOURCE, "content": "Exercise 1 Analyze data.\nExercise 3 Check results."}]
        with patch.dict(explicateur.os.environ, {"EXPLAIN_TASK_MODES": "1", "EXPLAIN_MULTI_EXERCISE_BATCHING": "1"}):
            await self.explain("Solve Exercise 3 only")
        self.invoke.assert_awaited_once()
        self.assertIn("this exercise only: Exercise 3", self.invoke.call_args.args[0][-1].content)

    async def test_batch_groups_narrow_context_and_rebind_local_citation_indexes(self):
        self.retrieve.return_value = [
            {**SOURCE, "id": str(i), "page_number": i, "content": f"Exercise {i} Analyze the supplied model."}
            for i in range(1, 9)
        ]
        async def invoke(prompt):
            source_json = json.loads(prompt[1].content.split("Course excerpts: ", 1)[1])
            scope = prompt[-1].content
            self.assertIn("Do not solve exercises outside this group", scope)
            selected = [int(num) for num in re.findall(r"Exercise (\d+)", scope)]
            actual = next(source for source in source_json if source["page_number"] == selected[0])
            raw = json.loads(response([actual["source_index"]]).content)
            raw["sections"] = [{"heading": f"Exercise {i}", "content": "A valid solution."} for i in selected]
            raw["sections"].append({"heading": "Shared example", "content": "A duplicate shared example."})
            return SimpleNamespace(content=json.dumps(raw), response_metadata={})

        self.invoke.side_effect = invoke
        with patch.dict(explicateur.os.environ, {
            "EXPLAIN_TASK_MODES": "1", "EXPLAIN_MULTI_EXERCISE_BATCHING": "1",
            "SOCRA_EXPLAIN_EXERCISES_PER_BATCH": "3", "SOCRA_EXPLAIN_MAX_BATCH_GROUPS": "3",
        }):
            result = (await self.explain("Solve all exercises"))["explanation"]
        self.assertEqual(self.invoke.await_count, 3)
        self.assertEqual([c["page_number"] for c in result["citations"]], [1, 4, 7])
        self.assertEqual([s["heading"] for s in result["sections"] if s["heading"].startswith("Exercise")],
                         [f"Exercise {i}" for i in range(1, 9)])
        self.assertEqual(sum(s["heading"] == "Shared example" for s in result["sections"]), 1)
        for args in self.invoke.await_args_list:
            self.assertLess(len(json.loads(args.args[0][1].content.split("Course excerpts: ", 1)[1])), 8)

    async def test_batch_flag_off_keeps_legacy_per_target_calls_and_cap(self):
        self.retrieve.return_value = [{
            **SOURCE, "content": "\n".join(f"Exercise {i} Analyze the supplied model." for i in range(1, 7)),
        }]
        with patch.dict(explicateur.os.environ, {
            "EXPLAIN_TASK_MODES": "1", "EXPLAIN_MULTI_EXERCISE_BATCHING": "0",
            "SOCRA_EXPLAIN_MAX_EXERCISE_CALLS": "2",
        }):
            result = (await self.explain("Solve all exercises"))["explanation"]
        self.assertEqual(self.invoke.await_count, 2)
        self.assertIn("Exercise 3", result["sections"][-1]["content"])

    async def test_excluded_number_does_not_become_a_target(self):
        self.retrieve.return_value = [{**SOURCE, "content": "Exercise 1 Analyze data.\nExercise 2 Check results."}]
        with patch.dict(explicateur.os.environ, {"EXPLAIN_TASK_MODES": "1", "EXPLAIN_MULTI_EXERCISE_BATCHING": "1"}):
            await self.explain("Solve all exercises except Exercise 2")
        self.invoke.assert_awaited_once()
        self.assertEqual(len(self.invoke.call_args.args[0]), 2)

    async def test_batched_truncation_salvages_a_section_and_lists_remaining_group(self):
        self.retrieve.return_value = [{
            **SOURCE, "content": "\n".join(f"Exercise {i} Analyze the supplied model." for i in range(1, 7)),
        }]
        self.invoke.return_value = SimpleNamespace(
            content='{"citations":[1],"sections":[{"heading":"Exercise 1","content":"An independent solution."},'
                    '{"heading":"Exercise 2","content":"Half finished',
            response_metadata={"finish_reason": "length"},
        )
        with patch.dict(explicateur.os.environ, {
            "EXPLAIN_TASK_MODES": "1", "EXPLAIN_MULTI_EXERCISE_BATCHING": "1",
            "SOCRA_EXPLAIN_EXERCISES_PER_BATCH": "3", "SOCRA_EXPLAIN_MAX_BATCH_GROUPS": "2",
        }):
            result = (await self.explain("Solve all exercises"))["explanation"]
        self.invoke.assert_awaited_once()
        self.assertEqual(result["sections"][0]["heading"], "Exercise 1")
        self.assertIn("cut off", result["sections"][1]["content"])
        self.assertIn("Exercise 4, Exercise 5, Exercise 6", result["sections"][-1]["content"])

    async def test_numbered_assignment_and_explicit_request_without_exercises_generate_once(self):
        for message in ("Work through the assignment", "Solve all exercises"):
            with self.subTest(message=message):
                self.invoke.reset_mock()
                await self.explain(message)
                self.invoke.assert_awaited_once()
                self.assertEqual(len(self.invoke.call_args.args[0]), 2)

    async def test_labelled_exercises_require_explicit_solving_request(self):
        self.retrieve.return_value = [{**SOURCE, "content": "Exercise 1 Analyze the data.\nExercise 2 Compare the models."}]
        for message in ("Explain all exercises", "Don't solve the exercises", "Give hints to solve all exercises"):
            with self.subTest(message=message):
                self.invoke.reset_mock()
                await self.explain(message)
                self.invoke.assert_awaited_once()
                self.assertEqual(len(self.invoke.call_args.args[0]), 2)

    async def test_named_exercise_scopes_by_exact_original_number(self):
        self.retrieve.return_value = [{
            **SOURCE, "content": f"{OUTLINE}\nExercise 2: Sample A\n**Exercice 3.1** Sample B\nExercice 3.10 Sample C",
        }]
        await self.explain("Résous l’exercice 3.1")
        self.invoke.assert_awaited_once()
        scoped = self.invoke.call_args.args[0][-1].content
        self.assertIn("this exercise only: Exercice 3.1", scoped)
        self.assertIn("Preserve the original number", scoped)
        self.assertNotIn("3.10", scoped)

    async def test_retry_keeps_each_target_prompt_isolated(self):
        self.retrieve.return_value = [{**SOURCE, "content": "Exercise 1 Analyze the data.\nExercise 2 Compare the models."}]
        self.invoke.side_effect = [response([88]), response([1]), response([1])]
        await self.explain("Solve the exercises")
        first, retry, second = [args.args[0] for args in self.invoke.await_args_list]
        self.assertEqual([len(prompt) for prompt in (first, retry, second)], [3, 4, 3])
        self.assertIn("this exercise only: Exercise 1", first[-1].content)
        self.assertIn("this exercise only: Exercise 2", second[-1].content)

    async def test_transport_and_format_failures_share_one_request_retry(self):
        failure = httpx.RemoteProtocolError("Connection closed")
        self.invoke.side_effect = [failure, response([88]), response([1])]
        with patch.object(explicateur.asyncio, "sleep", AsyncMock()) as sleep:
            with self.assertRaisesRegex(ValueError, "within the retry budget"):
                await self.explain("Explain the course")
        self.assertEqual(self.invoke.await_count, 2)
        sleep.assert_awaited_once()

    async def test_provider_json_rejection_can_use_the_same_format_retry(self):
        request = httpx.Request("POST", "https://provider.invalid/v1")
        self.invoke.side_effect = [
            BadRequestError("json_validate_failed", response=httpx.Response(400, request=request), body={}),
            response([1]),
        ]
        await self.explain("Explain the course")
        self.assertEqual(self.invoke.await_count, 2)
        self.assertIn("previous response did not match", self.invoke.call_args.args[0][-1].content)

    async def test_one_format_repair_is_shared_across_targets(self):
        self.retrieve.return_value = [{**SOURCE, "content": "Exercise 1 Analyze the data.\nExercise 2 Compare the models."}]
        self.invoke.side_effect = [response([88]), response([1]), response([88]), response([1])]
        with self.assertRaisesRegex(ValueError, "within the retry budget"):
            await self.explain("Solve the exercises")
        self.assertEqual(self.invoke.await_count, 3)

    async def test_rate_limit_before_output_honors_retry_after_or_jitter(self):
        request = httpx.Request("POST", "https://provider.invalid/v1")
        for headers, delay in (({"Retry-After": "3"}, 3), ({}, 0.75)):
            with self.subTest(headers=headers):
                self.invoke.reset_mock()
                self.invoke.side_effect = [
                    RateLimitError("Too many requests", response=httpx.Response(429, request=request, headers=headers), body={}),
                    response([1]),
                ]
                with patch.object(explicateur.asyncio, "sleep", AsyncMock()) as sleep, \
                        patch.object(explicateur, "uniform", return_value=0.75):
                    await self.explain("Explain the course")
                sleep.assert_awaited_once_with(delay)
                self.assertEqual(self.invoke.await_count, 2)

    async def test_retry_after_longer_than_deadline_is_not_shortened(self):
        request = httpx.Request("POST", "https://provider.invalid/v1")
        self.invoke.side_effect = RateLimitError(
            "Too many requests",
            response=httpx.Response(429, request=request, headers={"Retry-After": "120"}),
            body={},
        )
        with patch.object(explicateur.asyncio, "sleep", AsyncMock()) as sleep:
            with self.assertRaises(RateLimitError):
                await self.explain("Explain the course")
        sleep.assert_not_awaited()
        self.invoke.assert_awaited_once()

    async def test_gemini_temporary_429_retries_before_stream_output(self):
        attempts = 0
        preview = AsyncMock()

        async def stream(_):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Try again briefly."}})
            yield AIMessageChunk(content=response([1]).content)

        with patch.object(explicateur, "get_chat_llm", return_value=SimpleNamespace(astream=stream)), \
                patch.object(explicateur.asyncio, "sleep", AsyncMock()) as sleep:
            result = await explicateur.run_explicateur({
                "student_message": "Explain modeling", "course_id": "course-1", "preview": preview,
            })
        self.assertEqual(attempts, 2)
        sleep.assert_awaited_once()
        self.assertTrue(result["explanation"]["sections"])
        self.assertTrue(all(call.args[0] is not None for call in preview.await_args_list))

    async def test_expired_wall_clock_budget_prevents_model_start(self):
        budget = explicateur._GenerationBudget(deadline=0)
        with patch.object(explicateur, "_GenerationBudget", return_value=budget):
            with self.assertRaisesRegex(ValueError, "took too long"):
                await self.explain("Explain the course")
        self.invoke.assert_not_awaited()

    async def test_wall_clock_budget_cancels_an_inflight_invocation(self):
        cancelled = asyncio.Event()

        async def stalled(_):
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        self.invoke.side_effect = stalled
        budget = explicateur._GenerationBudget(deadline=explicateur.monotonic() + 0.05)
        with patch.object(explicateur, "_GenerationBudget", return_value=budget):
            with self.assertRaisesRegex(ValueError, "took too long"):
                await self.explain("Explain the course")
        self.invoke.assert_awaited_once()
        self.assertTrue(cancelled.is_set())

    async def test_incomplete_section_and_missing_citations_do_not_trigger_regeneration(self):
        for raw in ('{"citations":[1],"sections":[{"heading":"Visible but incomplete","content":"Preview only',
                    '{"sections":[{"heading":"Complete","content":"No citation indexes emitted."}],"citations":[1'):
            with self.subTest(raw=raw):
                self.invoke.reset_mock()
                self.invoke.return_value = SimpleNamespace(content=raw, response_metadata={"finish_reason": "MAX_TOKENS"})
                with self.assertRaisesRegex(ValueError, "without a recoverable course-grounded section"):
                    await self.explain("Explain the course")
                self.invoke.assert_awaited_once()

    async def test_default_cap_stops_at_four_and_logs_only_target_labels(self):
        self.retrieve.return_value = [{
            **SOURCE, "content": "\n".join(f"Exercise {n}: Private exercise details." for n in range(1, 7)),
        }]
        with patch.dict(explicateur.os.environ):
            explicateur.os.environ.pop("SOCRA_EXPLAIN_MAX_EXERCISE_CALLS", None)
            with self.assertLogs(explicateur.logger, "INFO") as captured:
                output = await self.explain("Solve all exercises")
        self.assertEqual(self.invoke.await_count, 4)
        self.assertIn("Exercise 5, Exercise 6", output["explanation"]["sections"][-1]["content"])
        event = json.loads(captured.records[-1].getMessage().removeprefix("explain_request "))
        self.assertEqual(event["outcome"], "incomplete")
        self.assertEqual(event["target_count"], 6)
        self.assertEqual(event["target_labels"], [f"Exercise {n}" for n in range(1, 7)])
        self.assertEqual(event["omitted_target_count"], 2)
        self.assertNotIn("Private exercise details", captured.output[0])

    async def test_mixed_citations_keep_the_valid_source_without_regeneration(self):
        self.invoke.return_value = response([99, 1])
        with self.assertLogs(explicateur.logger, "INFO") as captured:
            result = await self.explain("Work through the assignment, private prompt contents")
        self.invoke.assert_awaited_once()
        self.assertEqual(GeneratedExplanation.model_validate(result["explanation"]).citations[0].page_number, 4)
        event = json.loads(captured.records[-1].getMessage().removeprefix("explain_request "))
        self.assertEqual(event["request_id"], "req-1")
        self.assertEqual(event["style"], "detailed teaching explanation")
        self.assertTrue(event["assignment_mode"])
        self.assertEqual(event["chunk_count"], 1)
        self.assertEqual(event["chunk_ids"], ["chunk-0001"])
        self.assertEqual(event["estimated_retrieved_tokens"], (len(OUTLINE) + 3) // 4)
        self.assertEqual(event["document_pages"], [[SOURCE["document_id"], 4]])
        self.assertEqual(event["target_count"], 0)
        self.assertEqual(event["target_labels"], [])
        self.assertEqual(event["model_attempts"], 1)
        self.assertEqual(event["retry_reasons"], {})
        self.assertEqual(event["citation_drop_count"], 1)
        self.assertEqual(event["citation_drop_reasons"], {"invalid_index": 1})
        self.assertEqual(set(event["elapsed_ms"]), {"retrieval", "generation", "parsing", "citation_binding"})
        self.assertTrue(all(ms >= 0 for ms in event["elapsed_ms"].values()))
        for private in ("private-fixture-key", "private-profile-entry", "private prompt contents", "Start the program.", "Course.pdf"):
            self.assertNotIn(private, captured.output[0])

    async def test_all_citations_invalid_uses_existing_safe_failure(self):
        self.invoke.return_value = response([99, True])
        with self.assertLogs(explicateur.logger, "INFO") as captured:
            with self.assertRaisesRegex(ValueError, "Could not prepare a valid course-grounded explanation"):
                await self.explain("Explain the course")
        self.assertEqual(self.invoke.await_count, 2)
        event = json.loads(captured.records[-1].getMessage().removeprefix("explain_request "))
        self.assertEqual(event["outcome"], "failed")
        self.assertEqual(event["model_attempts"], 2)
        self.assertEqual(event["retry_reasons"], {"invalid_citations": 1})

    async def test_existing_subject_fixtures_keep_one_generation_call(self):
        scenarios = Path(__file__).with_name("scenarios")
        for name in ("sql_joins", "entropy", "isolated_system", "data_warehouse"):
            with self.subTest(name=name):
                case = json.loads((scenarios / f"scenario_{name}.json").read_text(encoding="utf-8"))
                self.invoke.reset_mock()
                await self.explain(case["turns"][0])
                self.invoke.assert_awaited_once()
                self.assertEqual(self.retrieve.call_args.kwargs["k"], 20)


if __name__ == "__main__":
    unittest.main()
