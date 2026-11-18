import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from agents import explicateur
from agents.explain_budget import ExplainCallBudget, explain_budget
from agents.explain_planner import build_learning_plan
from agents.explain_unit_generation import generate_unit
from agents.explain_unit_review import _merge_repair, _parse_repair, review_units
from tests.test_explain_unit_generation import block, excerpt_rows, extract_pages, records_for


def fixture(*, text="0,55 − 0,12 = 0,43", coverage="explained", kind="worked_calculation", findings=(), gaps=()):
    source = {"page": 16, "start": 0, "end": len(text), "quote": text}
    unit = {"logical_id": "shapley", "kind": kind, "content_version": "v1", "start": [16, 0],
            "end": [16, len(text)]}
    draft = {"logical_id": "shapley", "content_version": "v1", "coverage": coverage,
             "sources": [source], "blocks": [{"block_id": "b1", "kind": "result", "provenance": "derived",
              "text": text, "claims": [], "hypothetical": False, "source_indexes": [1]}],
             "findings": list(findings), "unverifiable_source": list(gaps), "missing_item_ids": [],
             "interruptions": [], "verified_facts": []}
    record = {"checklist": [{"item_id": "arithmetic", "anchors": [source], "importance": "essential",
                            "facts": [], "text": text}]}
    plan = {"required_items": {"shapley": ["arithmetic"]}, "depth": "standard", "level": "beginner"}
    return draft, unit, record, plan


def review(findings=(), *, score=3, unit="shapley"):
    return json.dumps({"reviews": [{"unit_id": unit, "pedagogy_score": score, "findings": list(findings)}]})


class IndependentReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_grounded_textual_paraphrase_needs_qualified_reviewer_evidence(self):
        draft, unit, record, plan = fixture(text="Une conséquence expliquée avec ses propres mots.")
        draft.update(missing_item_ids=["arithmetic"], reviewable_items={"arithmetic": ["b1"]},
                     findings=[{"code": "missing_item", "severity": "missing", "item_id": "arithmetic"}])
        for quote, expected in [("own words not found", "partial"), (draft["blocks"][0]["text"], "explained")]:
            assessment = {"reviews": [{"unit_id": "shapley", "pedagogy_score": 3, "findings": [],
                                        "checklist_evidence": [{"item_id": 1, "block_id": "b1", "quote": quote}]}]}
            result, = await review_units([draft], [unit], {"shapley": record}, [], plan, [],
                                         AsyncMock(return_value=json.dumps(assessment)), allow_repair=False)
            self.assertEqual(result["coverage"], expected)
        draft["findings"].append({"code": "calculation_mismatch", "severity": "authoritative", "block_id": "b1"})
        result, = await review_units([draft], [unit], {"shapley": record}, [], plan, [],
                                     AsyncMock(return_value=json.dumps(assessment)), allow_repair=False)
        self.assertEqual(result["coverage"], "partial")

    async def test_review_rejects_complete_response_on_nested_or_literal_controls_without_retry(self):
        draft, unit, record, plan = fixture()
        retry = AsyncMock()
        for raw in (
            review() + "\x00",
            json.dumps({"reviews": [{"unit_id": "shapley", "pedagogy_score": 3, "findings": [],
                                     "ledger_updates": [{"quote": "nested\x81"}]}]}),
        ):
            with self.subTest(raw=repr(raw)):
                dispatch = AsyncMock(return_value=raw)
                result, = await review_units([draft], [unit], {"shapley": record}, [], plan, [], dispatch,
                                             retry_dispatch=retry)
                dispatch.assert_awaited_once()
                self.assertEqual(result["review_reason"], "review_provider_corruption")
                self.assertEqual(result["review_state"], "unreviewed")
                self.assertEqual(result["blocks"], draft["blocks"])
                self.assertNotIn("independent_review", result)
        retry.assert_not_awaited()

    async def test_review_maps_each_numeric_reference_back_to_its_unit_checklist(self):
        draft, unit, record, plan = fixture(text="A grounded paragraph teaches the two related principles.")
        first, second = "a" * 64, "b" * 64
        original, = record["checklist"]
        record["checklist"] = [original | {"item_id": first}, original | {"item_id": second}]
        plan["required_items"]["shapley"] = [first, second]
        draft.update(missing_item_ids=[first, second], reviewable_items={second: ["b1"]})
        quote = draft["blocks"][0]["text"]
        finding = {"kind": "missing", "item_id": 1, "block_id": "b1", "quote": quote, "detail": "First principle missing"}
        evidence = {"item_id": 2, "block_id": "b1", "quote": quote}
        response = {"reviews": [{"unit_id": "shapley", "pedagogy_score": 3,
                                 "findings": [finding, finding | {"item_id": 3}],
                                 "checklist_evidence": [evidence, evidence | {"item_id": 0}]}]}
        dispatch = AsyncMock(return_value=json.dumps(response))
        result, = await review_units([draft], [unit], {"shapley": record}, [], plan, [], dispatch, allow_repair=set())
        payload, = json.loads(dispatch.await_args.args[1][-1].content)
        self.assertEqual([item["item_id"] for item in payload["checklist"]], [1, 2])
        self.assertEqual(payload["reviewable_items"], [{"item_id": 2, "block_ids": ["b1"]}])
        self.assertNotIn(first, json.dumps(payload))
        self.assertNotIn(second, json.dumps(payload))
        assessment = result["independent_review"]
        self.assertEqual([f["item_id"] for f in assessment["findings"]], [first])
        self.assertEqual([i["item_id"] for i in assessment["checklist_evidence"]], [second])
        self.assertEqual(result["missing_item_ids"], [first])

    async def test_27_drafts_reviewed_in_two_batches_with_at_most_one_targeted_retry(self):
        original, unit, record, plan = fixture()
        ids = [f"unit-{i:02}" for i in range(27)]
        drafts = [original | {"logical_id": uid} for uid in ids]
        units = [unit | {"logical_id": uid} for uid in ids]
        records = dict.fromkeys(ids, record)
        plan["required_items"] = dict.fromkeys(ids, ["arithmetic"])
        for scenario in ("healthy", "failure", "retry", "oversized", "missing_and_duplicate", "token_budget"):
            with self.subTest(scenario=scenario):
                calls = []
                budget = ExplainCallBudget(learning_limit=3)

                async def provider(purpose, messages, schema, retry=False):
                    budget.reserve("learning", purpose, retry=retry)
                    selected = [row["unit_id"] for row in json.loads(messages[-1].content)]
                    calls.append(selected)
                    rows = [{"unit_id": uid, "pedagogy_score": 3, "findings": []} for uid in selected]
                    if selected == ids[24:] and not retry:
                        if scenario in {"failure", "retry"}:
                            raise ConnectionError("simulated transient failure")
                        if scenario == "oversized":
                            rows += [rows[0]] * 65
                        if scenario == "missing_and_duplicate":
                            rows = [rows[0], rows[0], rows[2]]
                    return json.dumps({"reviews": rows})

                async def retry(*args):
                    return await provider(*args, retry=True)

                result = await review_units(
                    drafts, units, records, [], plan, [], provider, allow_repair=False,
                    fits=lambda messages, schema, count: count <= 24 and not (scenario == "token_budget" and calls),
                    retry_dispatch=retry if scenario == "retry" else None,
                )
                self.assertEqual(calls[:2], [ids[:24]] if scenario == "token_budget" else [ids[:24], ids[24:]])
                self.assertEqual([draft["logical_id"] for draft in result], ids)
                self.assertTrue(all(d["review_state"] == "approved" for d in result[:24]))
                unreviewed = [d["logical_id"] for d in result if d["review_state"] == "unreviewed"]
                self.assertEqual(unreviewed, ids[24:] if scenario in {"failure", "oversized", "token_budget"}
                                 else ids[24:26] if scenario == "missing_and_duplicate" else [])
                self.assertTrue(all(d["coverage"] == "partial" for d in result if d["logical_id"] in unreviewed))
                self.assertEqual(len(calls), 3 if scenario == "retry" else 1 if scenario == "token_budget" else 2)
                if scenario == "token_budget":
                    self.assertTrue(all(d["review_reason"] == "review_token_budget" for d in result[24:]))
                if scenario == "retry":
                    self.assertEqual(calls[2], ids[24:])
                    self.assertEqual(budget.summary()["learning"]["retries"], 1)

    async def test_reviews_fit_current_budget_and_precede_repairs(self):
        draft, unit, record, plan = fixture()
        ids = ["first", "second", "third"]
        drafts = [draft | {"logical_id": uid} for uid in ids]
        units = [unit | {"logical_id": uid} for uid in ids]
        plan["required_items"] = dict.fromkeys(ids, ["arithmetic"])
        calls = []
        issue = {"kind": "pedagogy", "block_id": "b1", "quote": "0,43", "detail": "Explain the change."}

        async def provider(purpose, messages, schema):
            body = json.loads(messages[-1].content)
            if purpose == "repair":
                calls.append(("repair", [body["unit_id"]]))
                return '{"patches":[]}'
            batch = [row["unit_id"] for row in body]
            calls.append(("review", batch))
            return json.dumps({"reviews": [{"unit_id": uid, "pedagogy_score": 2,
                                            "findings": [issue] if uid == "first" else []} for uid in batch]})

        result = await review_units(
            drafts, units, dict.fromkeys(ids, record), [], plan, [], provider,
            fits=lambda messages, schema, count: count <= (2 if not calls else 1),
        )
        self.assertEqual(calls, [("review", ["first", "second"]), ("review", ["third"]), ("repair", ["first"])])
        self.assertEqual([d["review_state"] for d in result], ["rejected", "approved", "approved"])

    async def test_batched_review_preserves_valid_sibling_when_another_assessment_is_invalid(self):
        first, unit, record, plan = fixture()
        second = first | {"logical_id": "other"}
        other = unit | {"logical_id": "other"}
        plan["required_items"]["other"] = ["arithmetic"]
        dispatch = AsyncMock(return_value=json.dumps({"reviews": [
            {"unit_id": "shapley", "pedagogy_score": 3, "findings": []},
            {"unit_id": "other", "pedagogy_score": "invalid", "findings": []},
        ]}))
        yes, no = await review_units([first, second], [unit, other], {"shapley": record, "other": record},
                                     [], plan, [], dispatch)
        dispatch.assert_awaited_once()
        self.assertEqual((yes["verification"], no["verification"]), ("reviewed", "review_failed"))
        self.assertEqual(no["blocks"], second["blocks"])

    async def test_batched_review_repairs_only_the_flagged_unit(self):
        good, unit, record, plan = fixture()
        bad = good | {"logical_id": "other"}
        other = unit | {"logical_id": "other"}
        plan["required_items"]["other"] = ["arithmetic"]
        issue = {"kind": "pedagogy", "block_id": "b1", "quote": "0,43", "detail": "Explain the change."}
        stages = []

        async def dispatch(stage, messages, schema):
            stages.append(stage)
            payload = json.loads(messages[-1].content)
            if stage == "review":
                return json.dumps({"reviews": [
                    {"unit_id": "shapley", "pedagogy_score": 3, "findings": []},
                    {"unit_id": "other", "pedagogy_score": 1, "findings": [issue]},
                ]})
            self.assertEqual(payload["unit_id"], "other")
            return '{"patches":[]}'

        yes, no = await review_units([good, bad], [unit, other], {"shapley": record, "other": record},
                                     [], plan, [], dispatch)
        self.assertEqual(stages, ["review", "repair"])
        self.assertEqual(yes["coverage"], "explained")
        self.assertEqual(yes["blocks"], good["blocks"])
        self.assertIn("repair_rejection", no)
        self.assertEqual(no["coverage"], "partial")

    async def test_saved_page_16_responses_and_complete_control(self):
        pdf = os.environ.get("SOCRA_EXPLAINABILITY_FIXTURE")
        artifact = os.environ.get("SOCRA_P2_REPLAY")
        if not pdf or not artifact:
            self.skipTest("Page-16 PDF and saved live artifact are required")
        saved = json.loads(Path(artifact).read_text(encoding="utf-8"))
        pages = await extract_pages(Path(pdf).read_bytes(), layout=True, evidence=True)
        units, rows, records = records_for(pages)
        unit, = [u for u in units if u["start"][0] == u["end"][0] == 16]
        uid = unit["logical_id"]
        excerpts = excerpt_rows(unit, rows)
        plan = build_learning_plan([unit], "replay", "sans rien omettre", records, level="beginner")
        record = records[uid]
        historical = record | {"checklist": [item | {"anchors": [
            anchor for anchor in item["anchors"] if anchor in saved["draft"]["sources"]
        ]} for item in record["checklist"]]}

        async def generate(selected, provider):
            return await generate_unit(unit, selected, excerpts, plan, provider, fits=lambda _: True,
                                       continuity={}, language="French", unit_map=[unit])

        async def replay_generation(messages, count):
            payload = json.loads(messages[-1].content)
            self.assertEqual([{k: v for k, v in source.items() if k != "index"} for source in payload["sources"]],
                             saved["draft"]["sources"])
            return saved["responses"]["generate"][0], ""

        original = await generate(historical, replay_generation)
        codes = {finding["code"] for finding in original["findings"]}
        self.assertIn("split_claim_number", codes)
        self.assertIn("missing_claim_marker", codes)
        self.assertNotIn("calculation_mismatch", codes)
        self.assertEqual(original["coverage"], "partial")
        self.assertFalse(any(block["source_indexes"] for block in original["blocks"]))
        review_mock = AsyncMock(return_value=saved["responses"]["review"][0])
        verdict, = await review_units([original], [unit], records, excerpts, plan, [], review_mock)
        self.assertEqual(verdict["verification"], "review_failed")
        self.assertNotEqual(verdict["coverage"], "explained")

        raw_repair = saved["responses"]["repair"][0]
        canonical = json.dumps({"patches": json.loads(raw_repair)})
        self.assertEqual(_parse_repair(raw_repair), _parse_repair(canonical))
        targets = {b["block_id"] for b in original["blocks"]}
        for response in (raw_repair, canonical):
            with self.assertRaisesRegex(ValueError, "unverified provenance"):
                _merge_repair(original, response, targets, unit, record, excerpts,
                              plan["required_items"][uid], [unit], set(range(1, len(original["sources"]) + 1)))

        async def complete_control(messages, count):
            packet = json.loads(messages[-1].content)
            sources = packet["sources"]
            checklist = packet["checklist"]
            table = [item for item in checklist if item["type"] == "number_table"]
            table_text = "| Variables connues | v(S) = prédiction |\n" + "\n".join(
                f"| {item['facts'][0]['label_path'][0]} | {item['facts'][0]['value']} |" for item in table
            )

            def cited(kind, text, indexes, **fields):
                return {"kind": kind, "text": text, "provenance": "course",
                        "claims": [{"quote": text, "source_indexes": indexes}], **fields}

            blocks = [cited("given_values", table_text, list(dict.fromkeys(i for item in table for i in item["sources"])))]
            blocks[0]["provenance"] = "derived"
            worked = next(item for item in checklist if "Ordre 1" in item["text"])
            ordering = None
            for index in worked["sources"]:
                quote = sources[index - 1]["quote"]
                if quote.startswith("Ordre "):
                    ordering = cited("substitution", quote, [index])
                    blocks.append(ordering)
                    continue
                if quote.startswith(("montant :", "nuit :")) and ordering is not None:
                    ordering["text"] += "\n" + quote
                    ordering["claims"].append({"quote": quote, "source_indexes": [index]})
                    continue
                kind = "result" if quote.startswith("φ") else "substitution"
                fields = ({"calculation": {"expression": "(0.43 + 0.49) / 2", "expected": "0.46"}}
                          if quote.startswith("φ(montant)") else {})
                blocks.append(cited(kind, quote, [index], **fields))
            formula = "Comparer les deux ordres évite de mesurer une variable uniquement quand elle arrive en premier."
            meaning = "Les contributions positives indiquent que les deux variables relèvent la prédiction au-dessus de la moyenne."
            for item in checklist:
                if item in table or item == worked:
                    continue
                quote = sources[item["sources"][0] - 1]["quote"]
                if "Exemple pédagogique" in quote:
                    entry = cited("formula", quote, item["sources"])
                    entry["provenance"] = "derived"
                    entry["text"] += "\n" + formula
                    entry["claims"].append({"quote": formula, "source_indexes": worked["sources"]})
                    blocks.append(entry)
                else:
                    blocks.append(cited("interpretation", quote, item["sources"]))
            blocks.append(cited("interpretation", meaning, worked["sources"]) | {"provenance": "derived"})
            return json.dumps({"blocks": blocks}, ensure_ascii=False), ""

        complete = await generate(record, complete_control)
        self.assertEqual(complete["coverage"], "explained", complete["findings"])
        self.assertTrue(all(b["source_indexes"] for b in complete["blocks"]))
        self.assertIn("0,46", " ".join(b["text"] for b in complete["blocks"]))

        async def corrupt_efficiency(messages, count):
            raw, reason = await complete_control(messages, count)
            data = json.loads(raw)
            for entry in data["blocks"]:
                if entry["text"] == "0,12 + 0,46 + 0,31 = 0,89":
                    changed = "0,12 + 0,46 − 0,31 = 0,89"
                    entry.update(text=changed, provenance="derived")
                    entry["claims"][0]["quote"] = changed
            return json.dumps(data), reason

        corrupt = await generate(record, corrupt_efficiency)
        wrong, = [f for f in corrupt["findings"] if f["code"] == "displayed_equation_mismatch"]
        self.assertIn("0.27 ≠ 0.89", wrong["detail"])
        cited = next(b for b in corrupt["blocks"] if b["block_id"] == wrong["block_id"])
        self.assertEqual(cited["provenance"], "unverified")
        self.assertEqual([corrupt["sources"][index - 1] for index in cited["source_indexes"]], [wrong["source"]])
        self.assertTrue(corrupt["missing_item_ids"])
        self.assertEqual(corrupt["coverage"], "partial")

        async def omit_orders(messages, count):
            raw, reason = await complete_control(messages, count)
            response = json.loads(raw)
            response["blocks"] = [block for block in response["blocks"] if not block["text"].startswith("Ordre ")]
            return json.dumps(response), reason

        shallow = await generate(record, omit_orders)
        self.assertEqual(shallow["coverage"], "partial")
        self.assertTrue(shallow["missing_item_ids"])
        self.assertTrue(all(b["source_indexes"] for b in shallow["blocks"]))
        self.assertNotIn("calculation_mismatch", {f["code"] for f in shallow["findings"]})

        async def wrong_attribution(messages, count):
            raw, reason = await complete_control(messages, count)
            data = json.loads(raw.replace("= 0,31", "= 0,46"))
            for entry in data["blocks"]:
                if entry["text"].startswith("φ(nuit)"):
                    entry["provenance"] = "derived"
            return json.dumps(data), reason

        swapped = await generate(record, wrong_attribution)
        self.assertIn("label_value_mismatch", {f["code"] for f in swapped["findings"]})

        async def review_control(purpose, messages, schema):
            payload, = json.loads(messages[-1].content)
            self.assertTrue(payload["ordered_calculation"])
            self.assertIn("reproduce", " ".join(payload["teaching_rules"]))
            checks = {
                "first_order": "Ordre 1", "second_order": "Ordre 2", "averaging": "Comparer les deux ordres",
                "interpretation": "Les contributions positives", "reproducibility": "0,12 + 0,46 + 0,31",
            }
            evidence = []
            for criterion, prefix in checks.items():
                match = next(b for b in complete["blocks"] if prefix in b["text"])
                evidence.append({"criterion": criterion, "block_id": match["block_id"], "quote": match["text"]})
            return json.dumps({"reviews": [{"unit_id": uid, "pedagogy_score": 3, "findings": [],
                                            "teaching_evidence": evidence}]})

        verdict, = await review_units([complete], [unit], records, excerpts, plan, [], review_control)
        self.assertEqual((verdict["coverage"], verdict["verification"]), ("explained", "reviewed"))

    async def test_repair_reasons_and_both_valid_envelopes(self):
        inputs = fixture()
        draft, unit, record, plan = inputs
        original = draft["blocks"][0]
        original.update(provenance="course", claims=[{"start": 0, "end": len(original["text"]), "source_indexes": [1]}])
        issue = {"kind": "pedagogy", "block_id": "b1", "quote": "0,43", "detail": "Explain the marginal change."}
        repair = [{"replace": "b1", "block": {"kind": "result", "text": original["text"], "provenance": "course",
                  "claims": [{"quote": original["text"], "source_indexes": [1]}]}}]
        for response in (repair, {"patches": repair}):
            result, calls = await self.run_review(inputs, iter([review([issue], score=1), json.dumps(response)]), limit=2)
            self.assertEqual(calls, ["review", "repair"])
            self.assertTrue(result["repair_changes"])
        for replacement, provenance, source, reason in [
            ("other", "course", 1, "unauthorized"),
            ("b1", "made-up", 1, "Invalid repair schema"),
            ("b1", "course", 2, "outside its authorized evidence"),
        ]:
            invalid = [{"replace": replacement, "block": repair[0]["block"] | {
                "provenance": provenance, "claims": [{"quote": original["text"], "source_indexes": [source]}],
            }}]
            result, _ = await self.run_review(inputs, iter([review([issue], score=1), json.dumps(invalid)]), limit=2)
            self.assertIn(reason, result["repair_rejection"])
            self.assertEqual(result["blocks"], draft["blocks"])
        unsupported = "0,55 − 0,12 = 0,99"
        invalid = [{"replace": "b1", "block": repair[0]["block"] | {
            "text": unsupported, "claims": [{"start": 0, "end": len(unsupported), "source_indexes": [1]}],
        }}]
        result, _ = await self.run_review(inputs, iter([review([issue], score=1), json.dumps(invalid)]), limit=2)
        self.assertIn("unsupported_claim_number", result["repair_rejection"])
        self.assertEqual(result["blocks"], draft["blocks"])

    async def run_review(self, inputs, responses, limit=4):
        draft, unit, record, plan = inputs
        budget = ExplainCallBudget(learning_limit=limit)
        calls = []

        async def dispatch(purpose, messages, schema):
            budget.reserve("learning", purpose)
            calls.append(purpose)
            if purpose == "review":
                payload = json.loads(messages[-1].content)
                self.assertNotIn("coverage", payload[0])
                self.assertNotIn("verified_facts", payload[0])
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return response

        result, = await review_units([draft], [unit], {"shapley": record},
                                     [{"unit_id": "shapley", "page_number": 16,
                                       "content": draft["sources"][0]["quote"]}],
                                     plan, [], dispatch)
        return result, calls

    async def test_hand_written_good_shapley_needs_one_review_and_no_repair(self):
        inputs = fixture(text="Start at 0,12 with neither variable. If amount arrives first it adds "
                         "0,55 − 0,12 = 0,43, then night adds 0,89 − 0,55 = 0,34. In reverse order, "
                         "night adds 0,40 − 0,12 = 0,28 and amount adds 0,89 − 0,40 = 0,49. "
                         "Average each variable across orders: amount 0,46 and night 0,31. "
                         "The baseline and both contributions sum to the prediction, 0,89.")
        result, calls = await self.run_review(inputs, iter([review()]))
        self.assertEqual(calls, ["review"])
        self.assertEqual((result["coverage"], result["verification"], result["confidence"]),
                         ("explained", "reviewed", "high"))

    async def test_deterministic_errors_and_page_26_source_gap_cannot_be_approved(self):
        for findings, gaps in [
            ([{"code": "calculation_mismatch", "severity": "authoritative", "block_id": "b1"}], []),
            ([{"code": "label_value_mismatch", "severity": "authoritative", "block_id": "b1"}], []),
            ([], [{"page": 26, "status": "unverifiable_source"}]),
        ]:
            with self.subTest(findings=findings, gaps=gaps):
                result, _ = await self.run_review(fixture(findings=findings, gaps=gaps), iter([review(), "{}"]))
                self.assertEqual(result["coverage"], "partial")
                self.assertEqual(result["unverifiable_source"], gaps)
                self.assertFalse(result["verified_facts"])

    async def test_calibration_on_legacy_negative_controls(self):
        path = Path(__file__).parent / "fixtures/explicateur_depth/explainability_negative_controls.json"
        one, two = json.loads(path.read_text(encoding="utf-8"))["responses"]
        posthoc, comparison = one["sections"][2]["content"], two["sections"][0]["content"]
        for text, issue in [
            (posthoc, {"kind": "missing", "item_id": 1, "block_id": "b1",
                       "quote": "calcule une contribution équitable des variables",
                       "detail": "Intermediate coalition calculations absent"}),
            (comparison, {"kind": "pedagogy", "block_id": "b1", "quote": "Les mesures montrent",
                          "detail": "Fraud counts do not teach the labeled F1 comparison or trade-off"}),
        ]:
            result, calls = await self.run_review(fixture(text=text), iter([
                review([issue], score=1 if issue["kind"] == "pedagogy" else 2), "{}"
            ]), limit=2)
            self.assertEqual(calls, ["review", "repair"])
            self.assertEqual(result["coverage"], "partial")
            self.assertEqual(result["independent_review"]["findings"][0]["kind"], issue["kind"])

    async def test_unsupported_quotes_invalid_json_timeout_and_exhausted_budget_preserve_draft(self):
        bad = review([{"kind": "pedagogy", "block_id": "b1", "quote": "not present", "detail": "Unsupported"}], score=1)
        for responses, limit in [([bad], 1), (["not JSON"], 1), ([TimeoutError()], 1), ([], 0)]:
            inputs = fixture()
            result, calls = await self.run_review(inputs, iter(responses), limit=limit)
            self.assertEqual(result["blocks"], inputs[0]["blocks"])
            self.assertEqual(result["verification"], "review_failed")
            self.assertEqual(result["coverage"], "partial")
            self.assertEqual(len(calls), limit)

    async def test_unexplained_beginner_jargon_is_not_substantive_coverage(self):
        inputs = fixture(text="Apply the efficiency axiom and use marginal contribution.")
        issue = {"kind": "pedagogy", "block_id": "b1", "quote": "efficiency axiom",
                 "detail": "Define the axiom and illustrate it using the baseline and contributions."}
        result, calls = await self.run_review(inputs, iter([review([issue], score=1)]), limit=1)
        self.assertEqual(calls, ["review"])
        self.assertEqual(result["coverage"], "partial")
        self.assertEqual(result["independent_review"]["pedagogy_score"], 1)

    async def test_repair_appends_without_duplication_and_does_not_loop_when_budget_exhausts(self):
        text = "0,55 − 0,12 = 0,43. La contribution correspond à la différence des prédictions."
        inputs = fixture(text=text, coverage="partial")
        original = inputs[0]["blocks"][0]
        original["text"] = "0,55 − 0,12 = 0,43."
        original["provenance"] = "course"
        original["claims"] = [{"start": 0, "end": len(original["text"]), "source_indexes": [1]}]
        addition = "La contribution correspond à la différence des prédictions."
        payload = {"patches": [{"replace": None, "block": {"kind": "interpretation", "text": addition,
                   "provenance": "course", "claims": [{"start": 0, "end": len(addition), "source_indexes": [1]}]}}]}
        issue = {"kind": "pedagogy", "block_id": "b1", "quote": "0,43", "detail": "Explain the marginal change."}
        result, calls = await self.run_review(inputs, iter([review([issue], score=1), json.dumps(payload)]), limit=2)
        self.assertEqual(calls, ["review", "repair"])
        self.assertEqual(result["blocks"][0], original)
        self.assertEqual(result["blocks"][1]["text"], addition)
        self.assertEqual(result["verification"], "review_failed")
        self.assertEqual(result["coverage"], "partial")

    async def test_worker_dispatch_shares_generation_review_and_repair_budget(self):
        units, rows, records = records_for([{"text": "II.3 Calculer la contribution\nφ(montant) = (0,43 + 0,49) / 2 = 0,46"}])
        unit = units[0]
        plan = build_learning_plan(units, "map", "Teach exhaustively", records)
        metrics = explicateur._ExplainMetrics("test", call_budget=ExplainCallBudget(learning_limit=2))
        agents = []

        def model(**options):
            agent = options["agent"]
            agents.append(agent)
            self.assertTrue(options["single_attempt"])

            async def invoke(messages):
                data = json.loads(messages[-1].content)
                if agent == "explain_unit_generation":
                    raw = json.dumps({"blocks": [block("result", data["sources"][0]["quote"], [1])]})
                else:
                    self.assertNotIn("coverage", data[0])
                    raw = review(unit=unit["logical_id"])
                return SimpleNamespace(content=raw, response_metadata={})
            return SimpleNamespace(ainvoke=AsyncMock(side_effect=invoke))

        with patch.object(explicateur, "get_chat_llm", side_effect=model):
            result, = await explicateur._generate_course_units(
                {"provider": "google", "model": "gemini-3.5-flash-lite"}, metrics,
                explain_budget("google", "gemini-3.5-flash-lite"), units, records,
                excerpt_rows(unit, rows), plan, units, "English", overview=True, continuity=[], prior_facts=[],
            )
        self.assertEqual(agents, ["explain_unit_generation", "explain_unit_review"])
        self.assertEqual(metrics.call_budget.summary()["learning"]["by_purpose"], {"generate": 1, "review": 1})
        self.assertEqual(result["coverage"], "partial")
