"""Portable CV and Spark acceptance and end-to-end offline failure controls."""

from copy import deepcopy
from dataclasses import replace
import json
import unittest

from agents.explain_planner import build_learning_plan
from tests.explain_scorecard import aggregate, score_unit
from tests.run_explain_scorecard import (
    FIXTURES, HISTORICAL, MOCKED, SCOPE, TWO_PACKET_OUTPUT_LIMIT, generate_replay, load_spark_fixture, prepare_spark, replay_cv,
    review_reference_probe, structural_tagged,
)


class SourceAnnotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.annotation, cls.pages, indexed = load_spark_fixture()
        cls.units, cls.by_id, cls.records, cls.plan, cls.excerpts = prepare_spark(cls.annotation, cls.pages, indexed)

    def test_source_spans_and_unit_map(self):
        self.assertEqual(len(self.pages), 9)
        self.assertEqual([u["label"] for u in self.units if u["kind"] == "lab_step"],
                         [f"Étape {i}" for i in range(11)])
        for scope in self.annotation["units"]:
            unit = self.by_id[scope["unit_id"]]
            self.assertEqual((unit["start"], unit["end"]), (scope["unit_map_start"], scope["unit_map_end"]))
            ids = [r["id"] for r in scope["requirements"]]
            self.assertEqual(len(ids), len(set(ids)))
            for requirement in scope["requirements"]:
                for source in requirement["evidence"]:
                    self.assertIn(source["page"], scope["actual_source_pages"])
                    self.assertEqual(source["quote"], self.pages[source["page"] - 1]["text"][source["start"]:source["end"]])

    def test_margin_transition_and_redundant_objective_are_audited_exclusions(self):
        expected = [
            (1, 9, {"supporting_objective": 1, "running_header": 2, "running_footer": 2, "section_transition": 2}),
            (2, 17, {"supporting_objective": 2, "running_header": 3, "running_footer": 3}),
        ]
        for scope, (first, candidates, locations) in zip(self.annotation["units"], expected, strict=True):
            uid = scope["unit_id"]
            record = {r["item_id"]: r for r in self.records[uid]["checklist"]}
            ledger = {r["item_id"]: r for r in self.records[uid]["checklist_exclusions"]}
            self.assertEqual(len(record) + len(ledger), candidates)
            self.assertEqual(set(ledger), {r["candidate_id"] for r in scope["non_requirement_candidates"]})
            self.assertEqual(scope["actual_source_pages"][0], first)
            for entry in scope["non_requirement_candidates"]:
                row = ledger[entry["candidate_id"]]
                self.assertEqual(row["text"], entry["text"])
                self.assertEqual(row["anchors"], entry["evidence"])
                self.assertEqual(row["anchors"][0]["page"], locations[entry["classification"]])
                self.assertEqual((row["type"], row["importance"]), ("command", "essential"))
                reason = entry["classification"]
                self.assertEqual(row["reason"], "redundant_objective" if reason == "supporting_objective" else reason)
                self.assertTrue(row["detection"]["rule"])
                self.assertNotIn(row["item_id"], record)
                self.assertNotIn(row["item_id"], self.plan["required_items"][uid])
                for source in row["detection"].get("supporting_anchors", ()):
                    self.assertIn(source, [a for candidate in record.values() for a in candidate["anchors"]])


class ScorecardTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.annotation, cls.pages, indexed = load_spark_fixture()
        cls.units, cls.by_id, cls.records, cls.plan, cls.excerpts = prepare_spark(cls.annotation, cls.pages, indexed)

    async def replay(self, scope_index, response=None, *, historical=False, two_packets=False):
        self.scope = self.annotation["units"][scope_index] | {
            "expected_packet_count": 2 if historical or two_packets else 1,
        }
        uid = self.scope["unit_id"]
        self.replay_records, self.replay_plan = self.records, self.plan
        if historical:
            fixture = json.loads((FIXTURES / "spark-step-2-historical-candidates.json").read_text(encoding="utf-8"))
            self.assertEqual((fixture["unit_id"], fixture["source_sha256"]), (uid, self.annotation["sha256"]))
            self.replay_records = self.records | {
                uid: self.records[uid] | {"checklist": fixture["checklist"], "checklist_exclusions": []},
            }
            self.replay_plan = build_learning_plan(self.units, "spark-scorecard", SCOPE, self.replay_records)
        self.candidates = self.replay_records[uid]["checklist"]
        self.requested = self.replay_plan["required_items"][uid]
        self.packets, self.draft = await generate_replay(
            self.by_id[uid], self.units, self.replay_records, self.replay_plan, self.excerpts[uid],
            response or (lambda payload, _: (structural_tagged(payload), "")),
            output_limit=TWO_PACKET_OUTPUT_LIMIT if two_packets else None,
        )

    def score(self, **overrides):
        values = dict(annotation=self.scope, pages=self.pages, candidates=self.candidates,
                      requested_ids=self.requested, packets=self.packets, draft=self.draft, evidence_kind=MOCKED,
                      exclusions=self.replay_records[self.scope["unit_id"]]["checklist_exclusions"])
        return score_unit(**(values | overrides))

    def assert_issue(self, report, code, *, packet=None):
        self.assertIn(code, [r["code"] for r in report["failures"] if packet is None or r.get("packet") == packet])

    async def probe(self):
        return await review_reference_probe(
            self.draft, self.packets, self.candidates, self.units, self.replay_records,
            self.excerpts[self.scope["unit_id"]], self.replay_plan,
        )

    async def test_cv_shared_result_matches_accepted_control(self):
        report = await replay_cv()
        self.assertEqual(report["evidence_kind"], HISTORICAL)
        source, packet, merged, review = report["source"], report["packets"][0], report["merged"], report["review"]
        self.assertEqual((source["ground_truth_requirements"], source["extracted_candidates"],
                          source["accepted_candidates"], source["correct_requirements"]), (6, 6, 6, 6))
        self.assertEqual(len(report["packets"]), 1)
        self.assertEqual(packet["groups_complete"]["count"], 6)
        self.assertEqual(packet["required_kind_coverage"]["count"], 24)
        self.assertEqual(merged["parsed_to_merged_retention"]["count"], 24)
        self.assertEqual(report["citations"]["resolved_anchors"]["count"], 20)
        self.assertEqual((review["evidence_completeness"]["count"], review["pedagogy_score"],
                          review["verdict"], review["ready_stage"]), (6, 3, "approved", "ready"))
        self.assertEqual(merged["final_coverage"], "explained")
        self.assertEqual(report["failures"], [])

    async def test_step_zero_single_packet_with_clean_checklist(self):
        await self.replay(0)
        review_packet, refs = await self.probe()
        report = self.score(review_packet=review_packet, reference_rows=refs)
        source, packet = report["source"], report["packets"][0]
        self.assertEqual((source["ground_truth_requirements"], source["correct_requirements"],
                          source["extracted_candidates"], source["correct_candidates"]), (9, 9, 5, 5))
        self.assertEqual(source["pre_filter_candidates"], 9)
        self.assertEqual(source["exact_exclusion_anchors"]["count"], 4)
        self.assertEqual(source["false_positive_candidates"], [])
        self.assertEqual((report["assignment"]["actual_packets"], packet["groups_complete"]["count"],
                          report["merged"]["actual_blocks"]), (1, 5, 20))
        self.assertEqual(report["review"]["mapping_probe"]["count"], 5)
        self.assertEqual(report["review"]["status"], "not_evaluated")
        self.assertIsNone(report["review"]["verdict"])
        self.assertEqual(report["failures"], [])

    async def test_step_two_union_order_local_id_collisions_and_review_mapping(self):
        # Retain the historical 68-block/17-anchor control with the old planning inputs.
        await self.replay(1, historical=True)
        review_packet, refs = await self.probe()
        report = self.score(review_packet=review_packet, reference_rows=refs)
        first, second = report["packets"]
        self.assertEqual([len(first["assigned_original_ids"]), len(second["assigned_original_ids"])], [8, 9])
        self.assertNotEqual(first["numeric_to_original_id"][1], second["numeric_to_original_id"][1])
        self.assertEqual(report["review"]["numeric_to_original_id"][1], first["numeric_to_original_id"][1])
        self.assertEqual(report["review"]["numeric_to_original_id"][9], second["numeric_to_original_id"][1])
        self.assertEqual(report["review"]["mapping_probe"]["count"], 17)
        self.assertEqual(report["source"]["ground_truth_requirements"], 16)
        self.assertEqual(report["assignment"]["genuine_source_missing"], [])
        self.assertEqual(len(report["source"]["false_positive_candidates"]), 2)
        self.assertEqual(report["assignment"]["duplicate_original_ids"], {})
        self.assertTrue(report["merged"]["ordered_blocks_match"])
        self.assertEqual(report["merged"]["source_requirements_with_all_linked_groups_retained"]["count"], 16)
        self.assertEqual(report["merged"]["parsed_to_merged_retention"]["count"], 68)
        self.assertEqual(report["citations"]["resolved_anchors"]["count"], 17)
        self.assertEqual(report["citations"]["cross_packet_evidence"], [])
        self.assertEqual(set(aggregate([report])), {MOCKED})
        self.assert_issue(report, "running_margin_false_positive")

    async def test_step_two_corrected_production_planning(self):
        await self.replay(1)
        review_packet, refs = await self.probe()
        report = self.score(review_packet=review_packet, reference_rows=refs)
        self.assertEqual(report["source"]["pre_filter_candidates"], 17)
        self.assertEqual(report["source"]["accepted_candidates"], 14)
        self.assertEqual(report["source"]["accepted_requirements"], 16)
        self.assertEqual(report["source"]["exact_exclusion_anchors"]["count"], 3)
        self.assertEqual(report["assignment"]["actual_packets"], 1)
        self.assertEqual(report["merged"]["parsed_to_merged_retention"]["count"], 56)
        self.assertEqual(report["citations"]["resolved_anchors"]["count"], 14)
        self.assertEqual(report["review"]["mapping_probe"]["count"], 14)
        self.assertEqual(report["failures"], [])

    async def test_step_two_dedicated_split_with_genuine_requirements_only(self):
        await self.replay(1, two_packets=True)
        review_packet, refs = await self.probe()
        report = self.score(review_packet=review_packet, reference_rows=refs)
        left, right = report["packets"]
        self.assertEqual([len(p["assigned_original_ids"]) for p in (left, right)], [7, 7])
        self.assertNotEqual(left["numeric_to_original_id"][1], right["numeric_to_original_id"][1])
        self.assertEqual(report["review"]["numeric_to_original_id"][1], left["numeric_to_original_id"][1])
        self.assertEqual(report["review"]["numeric_to_original_id"][8], right["numeric_to_original_id"][1])
        self.assertEqual(report["review"]["mapping_probe"]["count"], 14)
        self.assertEqual(report["assignment"]["invalid_assignments"], [])
        self.assertEqual(report["assignment"]["duplicate_original_ids"], {})
        self.assertEqual(report["merged"]["source_requirements_with_all_linked_groups_retained"]["count"], 16)
        self.assertEqual(report["merged"]["parsed_to_merged_retention"]["count"], 56)
        self.assertTrue(report["merged"]["ordered_blocks_match"])
        self.assertEqual(report["citations"]["resolved_anchors"]["count"], 14)
        self.assertEqual(report["citations"]["resolved_claim_anchor_references"]["count"], 28)
        self.assertEqual(report["citations"]["supplementary_blocks_without_claims"], 28)
        self.assertEqual(report["citations"]["merged_cross_packet_evidence"], [])
        self.assertEqual(report["failures"], [])

    async def test_missing_and_duplicate_packets(self):
        await self.replay(1, lambda _payload, _: ("", "provider_failure"), two_packets=True)
        missing = self.score()
        self.assert_issue(missing, "missing_packet")
        self.assert_issue(missing, "missing_packet_assignments")
        self.assert_issue(missing, "source_requirements_missing_from_packet_union")
        await self.replay(1, two_packets=True)
        repeated = self.score(packets=[*self.packets, self.packets[0]])
        self.assert_issue(repeated, "extra_packet")
        self.assert_issue(repeated, "duplicate_packet_assignments")

    async def test_missing_and_duplicate_source_checklist_items(self):
        await self.replay(1)
        first_genuine = next(r for r in self.candidates if r["item_id"] == self.scope["requirements"][0]["candidate_ids"][0])
        missing = self.score(candidates=[r for r in self.candidates if r != first_genuine])
        self.assert_issue(missing, "missing_genuine_source_requirement")
        self.assertIn(self.scope["requirements"][0]["id"], missing["source"]["missing_requirements"])
        duplicate = self.score(candidates=[*self.candidates, first_genuine])
        self.assert_issue(duplicate, "duplicate_checklist_item")

    async def test_packet_parser_failures_are_actionable(self):
        cases = [
            ("missing group", 2, lambda raw: raw.rsplit("@@BLOCK kind=action", 1)[0], "",
             "missing_generated_group"),
            ("wrong local item", 2, lambda raw: raw.replace(" items=1\n", " items=2\n", 1), "",
             "invalid_tagged_skeleton"),
            ("invalid item", 2, lambda raw: raw.replace(" items=1\n", " items=99\n", 1), "",
             "invalid_checklist_reference"),
            ("invalid source", 2, lambda raw: raw.replace(" sources=1 ", " sources=99 ", 1), "",
             "invalid_claim_index"),
            ("truncated first", 1, lambda raw: raw[:len(raw) // 3], "max_tokens", "max_tokens"),
            ("truncated second", 2, lambda raw: raw[:len(raw) // 3], "max_tokens", "max_tokens"),
            ("malformed", 2, lambda raw: raw.replace("@@BLOCK", "@@WRONG", 1), "", "malformed_tagged_output"),
            ("duplicate group", 2, lambda raw: raw + "\n" + raw.split("\n", 1)[1], "", "duplicate_block_group"),
        ]
        for title, packet, mutate, reason, code in cases:
            with self.subTest(title=title):
                def dispatch(payload, ordinal):
                    raw = structural_tagged(payload)
                    return (mutate(raw), reason) if packet == ordinal else (raw, "")
                await self.replay(1, dispatch, two_packets=True)
                report = self.score()
                self.assert_issue(report, code, packet=packet)
                self.assertEqual(report["review"]["status"], "not_evaluated")
                if reason:
                    self.assertTrue(report["packets"][packet - 1]["truncated"])

    async def test_merge_detects_order_and_cross_packet_evidence_leakage(self):
        await self.replay(1, two_packets=True)
        modified = deepcopy(self.draft)
        boundary = len(self.packets[0].payload["checklist"]) * len(self.packets[0].payload["required_blocks"])
        modified["blocks"][0], modified["blocks"][boundary] = modified["blocks"][boundary], modified["blocks"][0]
        self.assert_issue(self.score(draft=modified), "incorrect_merged_order")
        modified = deepcopy(self.draft)
        leaked_index = modified["blocks"][boundary]["claims"][0]["source_indexes"][0]
        claim = modified["blocks"][0]["claims"][0]
        claim["source_indexes"] = [leaked_index]
        modified["blocks"][0]["source_indexes"] = [leaked_index]
        report = self.score(draft=modified)
        self.assert_issue(report, "merged_block_or_evidence_mismatch")
        self.assert_issue(report, "cross_packet_evidence_leakage")
        packet = self.packets[0]
        leaked = replace(packet, raw=packet.raw.replace(" sources=1 ", " sources=9 ", 1))
        self.assertEqual(self.score(packets=[leaked, self.packets[1]])["citations"]["cross_packet_evidence"], [1])

    async def test_incorrect_review_mapping_is_detected(self):
        await self.replay(1, two_packets=True)
        review_packet, refs = await self.probe()
        boundary = len(self.packets[0].payload["checklist"])
        refs[boundary]["production_remapped_original_id"] = refs[0]["production_remapped_original_id"]
        report = self.score(review_packet=review_packet, reference_rows=refs)
        self.assert_issue(report, "incorrect_review_item_or_block_mapping")
        self.assertEqual(report["review"]["mapping_probe"]["count"], 13)
