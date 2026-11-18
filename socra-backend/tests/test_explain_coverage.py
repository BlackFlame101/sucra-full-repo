from __future__ import annotations

import json
import unittest
from dataclasses import replace
from itertools import product
from types import SimpleNamespace
from unittest.mock import patch

from agents import explicateur
from agents.explain_coverage import evaluate_coverage, missing_requirements, relevant_requirements
from models.schemas import ExplanationSection, GeneratedExplanation
from rag.document_inventory import Requirement, build_inventory
from tests import test_explain_phase2 as fixtures


def part(heading, content, citations=(1,), stop=""):
    return SimpleNamespace(content=json.dumps({
        "definition": "A source-based explanation.",
        "intuition": "A source-based intuition.",
        "sections": [{"heading": heading, "content": content}],
        "citations": list(citations),
    }), response_metadata={"finish_reason": stop})


class CoverageLogicTests(unittest.TestCase):
    def test_translated_nested_requirement_headings_keep_their_evidence(self):
        row = fixtures.chunk(7, "To do\nCapture 1: Matrice de confusion.\nAnnexe A: script transactions.csv")
        items = [item for item in build_inventory([row]).requirements if item.kind in {"screenshot", "appendix"}]
        self.assertEqual(len(items), 2)
        sections = [ExplanationSection(heading="Evaluation", content=(
            "## Screenshot checkpoint: Capture 1\n### Actions\n"
            "After training, open the scorer and show the confusion matrix. Save it in the report.\n"
            "## Appendix A\n### Python script\nRun this script to generate transactions.csv.\n"
            "~~~python\nwith open('transactions.csv', 'w') as file:\n    file.write('amount\\n')\n~~~"
        ))]
        self.assertEqual([entry.status for entry in evaluate_coverage(items, sections, {row["id"]}, lab=True)],
                         ["covered", "covered"])
        translated = sections[0].model_copy(update={"content": sections[0].content.replace(
            "Screenshot checkpoint: Capture 1", "لقطة الشاشة الأولى").replace("Appendix A", "Annexe A")})
        self.assertEqual([entry.status for entry in evaluate_coverage(items, [translated], {row["id"]}, lab=True)],
                         ["covered", "covered"])

    def test_expected_outputs_and_recovery_use_source_text_and_procedure(self):
        row = fixtures.chunk(4, "Step 1: Run the classifier\nExpected result\n\n500 rows, 50 positives\n\n"
                                "Troubleshooting\nIf the import fails, choose the CSV reader.\n\nStep 2: Export")
        items = build_inventory([row]).requirements
        step = next(item for item in items if item.id == "step:1")
        results = [item for item in items if item.kind in {"expected_result", "troubleshooting"}]
        self.assertTrue(any("500 rows, 50 positives" in item.evidence_anchor for item in results))
        self.assertTrue(any("choose the CSV reader" in item.evidence_anchor for item in results))
        self.assertTrue(all(item.parent_key == step.key and item.status == "supporting" for item in results))

    def test_coverage_diagnostics_distinguish_partial_missing_and_unavailable(self):
        row = fixtures.chunk(7, "Part IV: Mandatory assessment\nCapture 1: Matrice de confusion.\nCapture 2: Other output.")
        items = relevant_requirements(build_inventory([row]), "Explain the whole document", broad=True)
        self.assertEqual([item.id for item in items], ["screenshot:1", "screenshot:2"])
        section = ExplanationSection(heading="Screenshot 1", content="Open the viewer and show the confusion matrix.")
        self.assertEqual([(result.status, result.reason) for result in
                          evaluate_coverage(items, [section], {row["id"]}, lab=True)],
                         [("partial", "INSUFFICIENT_DETAIL"), ("missing", "NOT_MENTIONED")])
        full = section.model_copy(update={"content": "After training, open the viewer, capture the confusion matrix and save it in the report."})
        self.assertEqual(evaluate_coverage(items[:1], [full], {row["id"]}, lab=True)[0].status, "covered")
        checkpoint = full.model_copy(update={"heading": "Screenshot checkpoint 1"})
        self.assertEqual(evaluate_coverage(items[:1], [checkpoint], {row["id"]}, lab=True)[0].status, "covered")
        self.assertEqual(evaluate_coverage(items[:1], [full], set(), lab=True)[0].reason, "SOURCE_UNAVAILABLE")
        self.assertIsNotNone(evaluate_coverage(items[:1], [section], {row["id"]}, lab=True)[0].diagnostic)

    def test_tp_handwritten_good_and_synthetic_bad(self):
        screenshots = ["Orange scoring", "confusion matrix", "Orange workflow", "KNIME execution", "performance metrics"]
        questions = ["accuracy metrics", "random seeds", "fraud errors", "target column", "workflow differences", "model evaluation"]
        rows = [
            fixtures.chunk(7, "To do\n" + "\n".join(f"Capture {i}: {name}" for i, name in enumerate(screenshots, 1))),
            fixtures.chunk(13, "Required Questions\n" + "\n".join(f"Question {i}: {name}" for i, name in enumerate(questions, 1))),
            fixtures.chunk(14, "Otherwise use Annex A.\nAnnexe A: generate transactions.csv"),
        ]
        inventory = build_inventory(rows, "full_document")
        required = relevant_requirements(inventory, "Explain the entire PDF", broad=True, source_chunks=rows)
        self.assertEqual(len(required), 12)
        good = [ExplanationSection(heading=f"Screenshot {i}", content=f"After running the model, show the {name} and save the image in your report.") for i, name in enumerate(screenshots, 1)]
        good += [ExplanationSection(heading=f"Question {i}", content=f"Compare {name} and explain the relevant evidence from your workflow.") for i, name in enumerate(questions, 1)]
        good += [ExplanationSection(heading="Appendix A", content="To generate transactions.csv, run the source script locally.")]
        evidence = {row["id"] for row in rows}
        self.assertEqual(missing_requirements(required, good, evidence), [])
        bad = [ExplanationSection(heading="Capture 2", content="After running, show the result, save it, and include everything in the report. " * 15)]
        self.assertEqual(len(missing_requirements(required, bad, evidence)), 12)
        self.assertEqual(len(missing_requirements(required, good, {rows[0]["id"], rows[1]["id"]})), 1)
        self.assertFalse(missing_requirements(required[:1], good[:1], evidence))

    def test_exhaustive_blocks_reject_question_restating_and_partial_captures(self):
        row = fixtures.chunk(7, "To do\nCapture 1: Confusion matrix.\nRequired Questions\nQuestion 6: Compare model evaluation.")
        items = [item for item in build_inventory([row]).requirements if item.kind in {"screenshot", "question"}]
        overview = [
            ExplanationSection(heading="Question 6", content="Compare model evaluation and discuss which model works best."),
            ExplanationSection(heading="Capture 1", content="After running, show the confusion matrix and save it in the report."),
        ]
        self.assertEqual(missing_requirements(items, overview, {row["id"]}, lab=True), items)
        structured = ExplanationSection(heading="Evaluation", content=(
            "### Capture 1\nAfter execution, open the scorer. Show the confusion matrix and save it in the report.\n"
            "### Question 6\nInspect the model evaluation results. Compare the same metric across runs "
            "and record the evidence for your recommendation."
        ))
        self.assertEqual(missing_requirements(items, [structured], {row["id"]}, lab=True), [])
        list_guide = structured.model_copy(update={"content": structured.content.replace(
            "### Question 6\n", "6. **Question 6**: ")})
        self.assertEqual(missing_requirements(items, [list_guide], {row["id"]}, lab=True), [])

    def test_installation_paraphrase_still_needs_grounded_action(self):
        row = fixtures.chunk(1, "Étape 0.2 : Installer Orange Data Mining")
        item = next(item for item in build_inventory([row]).requirements if item.kind == "installation")
        good = ExplanationSection(heading="Set up Orange Data Mining",
                                  content="Download the Orange Data Mining installer and run the wizard.")
        bare = good.model_copy(update={"content": "Orange Data Mining is a good tool to consider."})
        self.assertEqual(missing_requirements([item], [good], {row["id"]}), [])
        self.assertEqual(missing_requirements([item], [bare], {row["id"]}), [item])

    def test_same_root_file_paths_must_match_unambiguous_source_path(self):
        anchor = "Save the file to project/data/transactions.csv."
        item = Requirement("file:transactions.csv", "file-key", "file", "doc", 1, "chunk",
                           anchor, anchor, "required", "line", None)
        good = ExplanationSection(heading="Save transactions.csv", content=anchor)
        wrong = good.model_copy(update={"content": "Save the file to project/transactions.csv."})
        ambiguous = replace(item, evidence_anchor=anchor + " Or save it to project/transactions.csv.")
        self.assertEqual(missing_requirements([item], [good], {"chunk"}), [])
        self.assertEqual(missing_requirements([item], [wrong], {"chunk"}), [item])
        self.assertEqual(missing_requirements([ambiguous], [wrong], {"chunk"}), [])

    def test_short_equation_and_empty_covers_hint(self):
        row = fixtures.chunk(1, "Required tasks\nEquation 1: x=2")
        items = list(build_inventory([row]).requirements)
        good = ExplanationSection(heading="Equation 1", content="From 2x=4, x=2. Verify: 4=4.")
        tagged = ExplanationSection.model_validate({"heading": "Equation 1", "covers": ["formula:1"]})
        self.assertEqual(missing_requirements(items, [good], {row["id"]}), [])
        self.assertEqual(missing_requirements(items, [tagged], {row["id"]}), items)
        self.assertEqual(relevant_requirements(build_inventory([row]), "Explain Question 5", broad=False), [])


class CoverageFlowTests(unittest.IsolatedAsyncioTestCase):
    run_explain = fixtures.Phase2ExplainTests.run_explain

    def setUp(self):
        fixtures.Phase2ExplainTests.setUp(self)
        self.enterContext(patch.dict(explicateur.os.environ, {"EXPLAIN_COVERAGE_CHECK": "1"}))
        self.rows[1]["content"] = "Question 5: Inspect confusion matrix.\nQuestion 6: Compare accuracy metrics."
        self.covered = part("Question 1", "Explain the setup, record observations, and report your conclusions with evidence.")
        self.invoke.return_value = self.covered

    async def test_exhaustive_checklist_and_large_gap_skip(self):
        self.rows[0]["content"] = "Required Questions\n" + "\n".join(
            f"Question {i}: Compare fraud metrics." for i in range(1, 7))
        self.rows[1]["content"] = "To do\n" + "\n".join(
            f"Capture {i}: Confusion matrix." for i in range(1, 6))
        self.invoke.return_value = part("Checklist overview", "Questions 1 to 6 and captures 1 to 5.")
        with self.assertLogs("agents.explicateur", level="INFO") as logs:
            output = (await self.run_explain())["explanation"]
        self.invoke.assert_awaited_once()
        system, user = self.invoke.await_args.args[0]
        checklist = user.content.split("excerpt supplied): ", 1)[1].split("\nDetected exercise", 1)[0]
        entries = json.loads(checklist)
        self.assertEqual([(item["id"], item["source_index"]) for item in entries], [
            *((f"question:{i}", 1) for i in range(1, 7)),
            *((f"screenshot:{i}", 2) for i in range(1, 6)),
        ])
        self.assertIn("each capture its own", system.content)
        self.assertIn("complete source script", system.content)
        self.assertIn("where to look, how to reason and what to write", system.content)
        self.assertTrue(all(item["placement"] == "separate_section" for item in entries))
        schema = self.model.call_args.kwargs["response_schema"]
        self.assertEqual(set(schema["properties"]), {"citations", "sections"})
        self.assertNotIn("code", schema["properties"]["sections"]["items"]["properties"])
        event = json.loads(logs.records[-1].getMessage().removeprefix("explain_request "))
        self.assertEqual(event["coverage_missing"], 11)
        self.assertEqual(event["coverage_repair_skip_reason"], "too_many_missing")
        self.assertEqual(event["outcome"], "incomplete")
        self.assertIn("Question 6", output["sections"][-1]["content"])

    async def test_short_summary_has_a_compact_generation_contract_with_both_flag_settings(self):
        body = "Visual pipelines let you prepare data, train models and compare results with a held-out dataset."
        for task_modes, intent_plans in product(("0", "1"), repeat=2):
            flags = {"EXPLAIN_TASK_MODES": task_modes, "EXPLAIN_INTENT_PLANS": intent_plans}
            with self.subTest(**flags), patch.dict(explicateur.os.environ, flags):
                self.invoke.reset_mock()
                self.invoke.return_value = SimpleNamespace(content=json.dumps({
                    "citations": [1], "sections": [{"heading": "Summary", "content": body}],
                }), response_metadata={})
                output = (await self.run_explain("give me a short summary"))["explanation"]
                self.invoke.assert_awaited_once()
                system, user = self.invoke.await_args.args[0]
                self.assertIn("one short section", system.content)
                self.assertIn("up to four short bullet points", system.content)
                self.assertNotIn("Request-relevant checklist", user.content)
                self.assertNotIn("Write content and code_language", system.content)
                schema = self.model.call_args.kwargs["response_schema"]
                self.assertEqual(set(schema["properties"]), {"citations", "sections"})
                self.assertEqual(schema["properties"]["sections"]["maxItems"], 1)
                self.assertEqual(self.model.call_args.kwargs["max_completion_tokens"], 1200)
                self.assertEqual([section["content"] for section in output["sections"]], [body])
                self.assertEqual(output["check_question"], "")
                self.assertEqual(output["common_pitfalls"], [])
                self.assertEqual(output["course_example"], "")
        self.catalog.assert_not_awaited()
        self.assertTrue(all(call.kwargs["k"] == 6 for call in self.retrieval.await_args_list))

    async def test_complete_script_survives_exhaustive_generation(self):
        fence = chr(96) * 3
        body = f"Run the dependency setup first.\n\n{fence}python\nimport csv\nwith open('data/example.csv', 'w') as file:\n    csv.writer(file).writerow(['example'])\n{fence}\n\nVerify the CSV."
        filler = f"{fence}python\n# Configured through the graphical interface.\n{fence}"
        self.invoke.return_value = SimpleNamespace(content=json.dumps({
            "citations": [1], "sections": [
                {"heading": "Appendix A", "content": body},
                {"heading": "Interface", "content": "Open the GUI.\n\n" + filler,
                 "code": "# No CLI command required.", "code_language": "powershell"},
            ],
        }), response_metadata={})
        with patch.dict(explicateur.os.environ, {"EXPLAIN_COVERAGE_CHECK": "0"}):
            output = (await self.run_explain())["explanation"]
        self.invoke.assert_awaited_once()
        self.assertEqual(output["sections"][0]["content"], body)
        self.assertEqual(output["definition"], "")
        self.assertEqual(output["sections"][1]["code"], "")
        self.assertIn("Configured through the graphical interface.", output["sections"][1]["content"])
        self.assertNotIn(fence, output["sections"][1]["content"])

    async def test_source_locators_and_advisory_table_lint(self):
        source_table = "Model\tPrecision\tRecall\nAlpha\t0.91\t0.82\nBeta\t0.88\t0.73"
        self.rows[0]["content"] = (
            "Step 1: Fit the classifier\nExpected result\n" + source_table
            + "\nTroubleshooting: Select the target column."
        )
        self.rows[1]["content"] = "Section II: Setup notes\nExpected result: Unassigned reference."
        self.retrieval.return_value = self.rows
        self.invoke.return_value = part("Step 1: Fit the classifier", source_table)
        with self.assertLogs("agents.explicateur", level="INFO") as logs:
            answer = (await self.run_explain())["explanation"]
        self.invoke.assert_awaited_once()
        system, user = self.invoke.await_args.args[0]
        self.assertIn("source reference results and troubleshooting beside the procedure", system.content)
        self.assertIn("one meaningful action per ordered Markdown item", system.content)
        self.assertIn("source indexes only in the structured citation fields", system.content)
        self.assertIn("unchecked Markdown tasks", system.content)
        self.assertIn("Markdown tables with header and separator rows", system.content)
        self.assertIn("label any calculation and its inputs", system.content)
        self.assertIn("student's own measurements", system.content)
        self.assertIn("general guidance", system.content)
        entries = json.loads(user.content.split("check each procedure match): ", 1)[1].split("\n", 1)[0])
        self.assertEqual([entry.get("procedure") for entry in entries], [
            {"source_index": 1, "label": "Step 1: Fit the classifier"},
            {"source_index": 1, "label": "Step 1: Fit the classifier"},
            None,
        ])
        self.assertEqual(answer["sections"][0]["content"], source_table)
        event = json.loads(logs.records[-1].getMessage().removeprefix("explain_request "))
        self.assertEqual(event["flattened_metric_table_sections"], 1)
        lint = explicateur._has_flattened_metric_table
        self.assertFalse(lint("~~~text\n" + source_table + "\n~~~"))
        self.assertFalse(lint("| Model | Precision | Recall |\n| --- | --- | --- |\n| Alpha | 0.91 | 0.82 |"))

    async def test_full_card_notices_preserve_the_last_script(self):
        self.rows[1]["content"] = "Required files: config/a.py"
        script = "~~~python\n" + "print('content')\n" * 174 + "~~~"
        self.invoke.return_value = SimpleNamespace(content=json.dumps({
            "citations": [1], "sections": [
                *[{"heading": f"Step {i}", "content": "Open the app."} for i in range(29)],
                {"heading": "Script", "content": script},
            ],
        }), response_metadata={})
        with patch.object(explicateur, "explain_budget", return_value=None):
            answer = (await self.run_explain())["explanation"]
        self.invoke.assert_awaited_once()
        restored = GeneratedExplanation.model_validate(answer)
        self.assertEqual(restored.sections[-1].content, script)
        self.assertIn("Insufficiently covered requirements", restored.course_example)
        self.assertIn("Requirements with evidence outside the supplied excerpts", restored.course_example)

        raw = json.loads(self.invoke.return_value.content)
        raw["course_example"] = "x" * 3000
        self.invoke.return_value.content = json.dumps(raw)
        with patch.object(explicateur, "explain_budget", return_value=None):
            overflow = (await self.run_explain())["explanation"]
        self.assertEqual(overflow["sections"][-1]["content"], script)
        self.assertEqual(overflow["course_example"], raw["course_example"])
        self.assertTrue(overflow["coverage_notices"])

    async def test_one_targeted_repair_and_persisted_missing_notice(self):
        fix = part("Question 5", "Inspect the confusion matrix, compare the counts and explain their significance.", (99, 1))
        self.invoke.side_effect = [self.covered, fix]
        output = (await self.run_explain())["explanation"]
        self.assertEqual(self.invoke.await_count, 2)
        prompt = self.invoke.await_args.args[0][-1].content
        self.assertNotIn("Requested topic", prompt)
        self.assertNotIn("Question 1: Explain the setup", prompt)
        restored = GeneratedExplanation.model_validate_json(json.dumps(output))
        self.assertEqual([s.heading for s in restored.sections][:2], ["Question 1", "Question 5"])
        self.assertIn("Question 6", restored.sections[-1].content)
        self.assertEqual([c.page_number for c in restored.citations], [1, 2])

    async def test_truncation_continues_once_without_restarting(self):
        fix = part("Question 5", "Inspect the confusion matrix, compare the counts and explain their significance.")
        self.invoke.side_effect = [part("Question 1", "Inspect the setup logs, record the configuration, and report your conclusions with evidence.", stop="length"), fix]
        output = (await self.run_explain())["explanation"]
        self.assertEqual(self.invoke.await_count, 2)
        self.assertIn("Question 5", [s["heading"] for s in output["sections"]])
        self.assertIn("Question 6", output["sections"][-1]["content"])

    async def test_retrieved_only_is_labeled_and_repair_gets_no_format_retry(self):
        self.index.return_value = (self.rows, "retrieved_only")
        self.invoke.side_effect = [self.covered, part("Question 5", "Insufficient evidence.", (99,))]
        output = (await self.run_explain())["explanation"]
        self.assertEqual(self.invoke.await_count, 2)
        self.assertIn("Checked against retrieved excerpts only.", output["sections"][-1]["content"])

    async def test_flag_off_preserves_original_card(self):
        with patch.dict(explicateur.os.environ, {"EXPLAIN_COVERAGE_CHECK": "0"}):
            output = (await self.run_explain())["explanation"]
        self.invoke.assert_awaited_once()
        self.assertEqual(len(output["sections"]), 1)

    async def test_complete_answer_spends_no_repair_call(self):
        self.rows[1]["content"] = "Appendix A: Optional reference."
        output = (await self.run_explain())["explanation"]
        self.invoke.assert_awaited_once()
        self.assertEqual([s["heading"] for s in output["sections"]], ["Question 1"])

    async def test_unconfigured_budget_retains_notice_without_repair(self):
        with patch.object(explicateur, "explain_budget", return_value=None):
            output = (await self.run_explain())["explanation"]
        self.invoke.assert_awaited_once()
        self.assertIn("Question 5", output["sections"][-1]["content"])
