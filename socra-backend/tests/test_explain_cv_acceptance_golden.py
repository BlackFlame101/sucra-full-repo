from hashlib import sha256
import json
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from agents.explain_lifecycle import ExplanationV2, attach_contract, version_for
from agents.explain_planner import build_learning_plan, learning_progress
from agents.explain_unit_generation import generate_unit, legacy_projection, linked_evidence
from agents.explain_unit_review import CHECKLIST_REVIEW_SCHEMA, review_units
from agents.structured_output import has_control_characters
from tests.test_explain_review_contract import saved_text
from tests.test_explain_tagged_generation import ANSWER, FIXTURES, LIVE_DIGEST, LIVE_TEACHING_EVIDENCE, cv_source
from worker import extract_pages


QUESTION = "60b3bff0f917644f30d42989"
CASE = "68289b854590095af0381cf2"
PDF_DIGEST = "c76516b0d55f71b0b4683796cee4d086a0799c9b07edf5e54888333ac3b2f3c2"
PAGES_DIGEST = "1e8831ff0a4e1d63abb475c02d50d02ca0888890194fbfa7fa92cc595f4dcf2d"
REVIEW_DIGEST = "6ee2d6d3da1028cc752582b90078932ea656f8148f7f87cc30421f1aa056dc5f"
CONTENT_VERSION = "6e8b97859668114c0fa96864d665a66962772f957cdf869f6fbb92d237f9b170"
ITEM_IDS = (
    "e0d8fe3c84b978350e88c427ac7556a9a8b88b009fdb342d5b9b2120ba10113e",
    "7dc1a18bfcfc7b175a19c3e1d016d4c423ef819d26499c5a23a29386ac6e104c",
    "3a754529dae7ea55ea8a3d80a083d5a6e62d0569f9528a4fa50dea461acc3f2d",
    "6664f102bb27fb4ae4f865eda704360eb22f1a4f38100b9b83be556a1e72f379",
    "5b29d36f6c72de4dc7f013459d4b50ed223d98b1b870194961b120f51eff2153",
    "9b76de918e788216d9efc9b9484ce7cdda17b7d2cf53b2be2085775d38bba8f9",
)
ATS_OVERCLAIM = ("Cette correction garantit que le contenu textuel sera extrait et lu sans erreur "
                 "par les outils de recrutement.")


class AcceptedCVGoldenTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.dict(os.environ, {"EXPLAIN_GENERATION_FORMAT": "tagged"}))
        indexed = (FIXTURES / "cv-indexed-pages.json").read_bytes()
        self.assertEqual(sha256(indexed).hexdigest(), PAGES_DIGEST)
        self.pages = json.loads(indexed)
        self.units, self.records, self.plan, self.excerpts = cv_source(self.pages)
        self.answer = next(unit for unit in self.units if unit["logical_id"] == ANSWER)
        self.related = linked_evidence(self.answer, self.units, self.records, self.excerpts)
        self.response = saved_text("cv-answer-1-positive-live-review.json", REVIEW_DIGEST)
        raw = saved_text("cv-answer-1-live-tagged-response.json", LIVE_DIGEST)
        self.draft = await generate_unit(
            self.answer, self.records[ANSWER], self.excerpts[ANSWER], self.plan, AsyncMock(return_value=(raw, "")),
            fits=lambda _: True, continuity={}, language="French", unit_map=self.units, related=self.related,
        )

    async def replay_review(self, raw):
        dispatch = AsyncMock(return_value=raw)
        verdict, = await review_units(
            [self.draft], self.units, self.records, self.excerpts[ANSWER], self.plan, [], dispatch,
            allow_repair=set(), related={ANSWER: self.related},
        )
        dispatch.assert_awaited_once()
        purpose, messages, schema = dispatch.await_args.args
        self.assertEqual(purpose, "review")
        self.assertIs(schema, CHECKLIST_REVIEW_SCHEMA)
        packet, = json.loads(messages[-1].content)
        self.assertEqual([entry["item_id"] for entry in packet["reviewable_items"]], list(range(1, 7)))
        self.assertEqual([entry["text"] for entry in packet["blocks"]], [b["text"] for b in self.draft["blocks"]])
        return verdict

    async def test_accepted_provider_responses_replay_to_ready_with_all_original_evidence(self):
        self.assertEqual(
            [(unit["logical_id"], unit["kind"], unit["start"][0], unit["end"][0]) for unit in self.units],
            [
                ("92b34a03ff9d35791ba0e29b", "front_matter", 1, 1),
                (CASE, "exercise", 1, 1),
                (QUESTION, "exercise", 1, 1),
                ("c1d1bea95ce64f12e43d7776", "exercise", 1, 1),
                ("9bb67ed3e91cedc23cb41114", "non_teaching", 2, 2),
                (ANSWER, "concept", 2, 2),
                ("64f50c3294dcad6ee61bb205", "concept", 2, 2),
            ],
        )
        self.assertEqual(self.answer["label"], "Réponse 1")
        self.assertEqual(self.answer["content_version"], CONTENT_VERSION)
        self.assertEqual(self.records[ANSWER]["depends_on"], [QUESTION])
        self.assertEqual({row["unit_id"] for row in self.related.values()}, {QUESTION, CASE})
        self.assertEqual(tuple(self.plan["required_items"][ANSWER]), ITEM_IDS)
        self.assertEqual(len(self.draft["blocks"]), 24)
        self.assertEqual(len(self.draft["sources"]), 20)
        self.assertEqual([b["kind"] for b in self.draft["blocks"]],
                         ["explanation", "intuition", "source_example", "takeaway"] * 6)
        for paragraph, parts in zip(self.draft["blocks"][::4], LIVE_TEACHING_EVIDENCE, strict=True):
            self.assertTrue(all(part in paragraph["text"] for part in parts))
        for source in self.draft["sources"]:
            self.assertEqual(self.pages[source["page"] - 1]["text"][source["start"]:source["end"]], source["quote"])
        self.assertFalse(has_control_characters(self.draft))
        self.assertFalse(self.draft["interruptions"])
        verdict = await self.replay_review(self.response)
        self.assertEqual((verdict["review_state"], verdict["verification"], verdict["coverage"]),
                         ("approved", "reviewed", "explained"))
        self.assertEqual(verdict["independent_review"]["pedagogy_score"], 3)
        self.assertEqual(verdict["independent_review"]["findings"], [])
        self.assertEqual(tuple(e["item_id"] for e in verdict["independent_review"]["checklist_evidence"]), ITEM_IDS)
        self.assertEqual(verdict["blocks"], self.draft["blocks"])
        self.assertEqual(verdict["sources"], self.draft["sources"])
        self.assertEqual(verdict["missing_item_ids"], [])

        plan = build_learning_plan([self.answer], "cv-golden", "Explique sans rien omettre", self.records)
        version = version_for("accepted-cv-fixture", "ready", verdict)
        card = legacy_projection([verdict], self.excerpts[ANSWER], "cv", "French")
        learning = learning_progress(
            plan, [self.answer], {ANSWER: {"content_version": verdict["content_version"], "status": verdict["coverage"]}},
            "accepted-cv-fixture", verified_facts=verdict["verified_facts"], prepared=self.records,
        )
        prepared = attach_contract(card, plan, [self.answer], [version], [version], learning, self.records)
        saved = ExplanationV2.model_validate_json(json.dumps(prepared, ensure_ascii=False))
        self.assertEqual(saved.versions[0].stage, "ready")
        self.assertEqual(saved.versions[0].output.model_dump(mode="json"), version["output"])
        self.assertEqual(saved.learning_state.progress[0].status, "explained")
        self.assertTrue(saved.coverage_ledger["document_complete"])

        # The permanent replay runs with extracted pages even when the original local PDF is unavailable.
        if directory := os.getenv("SOCRA_FOUR_PDF_DIR"):
            data = (Path(directory) / "TD N° 3 ANALYSE CV.pdf").read_bytes()
            self.assertEqual(sha256(data).hexdigest(), PDF_DIGEST)
            extracted = await extract_pages(data, layout=True, evidence=True)
            self.assertEqual([page["text"] for page in extracted], [page["text"] for page in self.pages])

    async def test_exact_ats_overclaim_can_block_approval_as_reviewed_unsupported(self):
        draft_block = self.draft["blocks"][0]
        self.assertIn(ATS_OVERCLAIM, draft_block["text"])
        anchors = [self.draft["sources"][i - 1]["quote"] for i in draft_block["source_indexes"]]
        self.assertTrue(any("compatible avec les logiciels ATS" in quote for quote in anchors))
        self.assertTrue(all("sans erreur" not in quote and "garantit" not in quote for quote in anchors))
        mock = json.loads(self.response)
        mock["reviews"][0]["findings"] = [{
            "kind": "unsupported", "item_id": 1, "block_id": draft_block["block_id"], "quote": ATS_OVERCLAIM,
            "detail": "La source recommande un format compatible ATS sans promettre une extraction sans erreur.",
        }]
        verdict = await self.replay_review(json.dumps(mock, ensure_ascii=False))
        self.assertEqual(verdict["review_state"], "rejected")
        self.assertIn(ITEM_IDS[0], verdict["missing_item_ids"])
        self.assertNotIn(ITEM_IDS[0], verdict["semantic_coverage_item_ids"])
        self.assertEqual(verdict["independent_review"]["findings"][0]["quote"], ATS_OVERCLAIM)
