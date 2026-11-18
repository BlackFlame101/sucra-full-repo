from hashlib import sha256
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from langchain_core.messages import HumanMessage

from agents import llm
from agents.explain_lifecycle import UnitOutput
from agents.explain_unit_generation import generate_unit, linked_evidence
from agents.explain_unit_review import CHECKLIST_REVIEW_SCHEMA, REVIEW_SCHEMA, UnitReview, review_units
from tests.test_explain_tagged_generation import ANSWER, FIXTURES, LIVE_DIGEST, cv_source
from tests.test_explain_unit_review import fixture


REVIEW_DIGEST = "4ec5d92e611343019d10439b78928c09c4667c0a6d30739b839545d898d6e00b"


def saved_text(name, expected_hash):
    data = (FIXTURES / name).read_bytes()
    if sha256(data).hexdigest() != expected_hash:
        raise AssertionError("Historical provider fixture changed")
    candidate, = json.loads(data)["candidates"]
    return candidate["content"]["parts"][0]["text"]


class ReviewSchemaBindingTests(unittest.TestCase):
    def test_gemini_http_body_binds_the_required_evidence_schema(self):
        factory = llm.ChatGoogleGenerativeAI
        bodies = []

        def respond(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
                "role": "model", "parts": [{"text": '{"reviews":[]}'}],
            }}]})

        def local_model(**options):
            return factory(**options, vertexai=False, client_args={"transport": httpx.MockTransport(respond)})

        settings = SimpleNamespace(chat_model="gemini-3.5-flash-lite", gemini_api_key="offline-fixture")
        with patch.object(llm, "ChatGoogleGenerativeAI", side_effect=local_model), \
                patch.object(llm, "get_settings", return_value=settings):
            for schema, bind in ((CHECKLIST_REVIEW_SCHEMA, False), (REVIEW_SCHEMA, True),
                                 (CHECKLIST_REVIEW_SCHEMA, True)):
                model = llm.get_chat_llm(agent="explain_unit_review", provider="google", single_attempt=True,
                                         response_schema=schema, bind_response_schema=bind)
                model.invoke([HumanMessage(content="Offline transport fixture")])
        self.assertEqual(len(bodies), 3)
        self.assertNotIn("responseJsonSchema", bodies[0]["generationConfig"])
        for body, required in zip(bodies[1:], (False, True), strict=True):
            config = body["generationConfig"]
            self.assertEqual(config["responseMimeType"], "application/json")
            unit = config["responseJsonSchema"]["$defs"]["UnitReview"]
            self.assertEqual("checklist_evidence" in unit["required"], required)
            self.assertEqual(unit["properties"]["checklist_evidence"]["items"]["$ref"],
                             "#/$defs/ChecklistReviewEvidence")
            if required:
                self.assertNotIn("default", unit["properties"]["checklist_evidence"])
                item = config["responseJsonSchema"]["$defs"]["ChecklistReviewEvidence"]
                self.assertEqual(set(item["required"]), {"item_id", "block_id", "quote"})


class ChecklistReviewContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.dict("os.environ", {"EXPLAIN_GENERATION_FORMAT": "tagged"}))
        pages = json.loads((FIXTURES / "cv-indexed-pages.json").read_bytes())
        self.units, self.records, self.plan, excerpts = cv_source(pages)
        self.unit = next(u for u in self.units if u["logical_id"] == ANSWER)
        self.excerpts = excerpts[ANSWER]
        self.related = linked_evidence(self.unit, self.units, self.records, excerpts)
        raw = saved_text("cv-answer-1-live-tagged-response.json", LIVE_DIGEST)
        self.draft = await generate_unit(
            self.unit, self.records[ANSWER], self.excerpts, self.plan, AsyncMock(return_value=(raw, "")),
            fits=lambda _: True, continuity={}, language="French", unit_map=self.units, related=self.related,
        )
        self.ids = self.plan["required_items"][ANSWER]
        self.evidence = [{"item_id": i, "block_id": block["block_id"], "quote": block["text"]}
                         for i, block in enumerate(self.draft["blocks"][::4], 1)]

    def response(self, evidence):
        return json.dumps({"reviews": [{"unit_id": ANSWER, "pedagogy_score": 3, "findings": [],
                                        "checklist_evidence": evidence}]})

    async def run_review(self, wire, *, draft=None, peer=None):
        dispatch, retry = AsyncMock(return_value=wire), AsyncMock()
        verdict, *_ = await review_units(
            [draft or self.draft, *([peer] if peer else [])], self.units, self.records, self.excerpts,
            self.plan, [], dispatch, allow_repair=set(), retry_dispatch=retry, related={ANSWER: self.related},
        )
        dispatch.assert_awaited_once()
        retry.assert_not_awaited()
        return verdict, dispatch.await_args.args

    async def test_exact_saved_review_reports_omission_and_remains_incomplete(self):
        wire = saved_text("cv-answer-1-live-review-response.json", REVIEW_DIGEST)
        parsed, = json.loads(wire)["reviews"]
        self.assertNotIn("checklist_evidence", UnitReview.model_validate(parsed).model_fields_set)
        result, _ = await self.run_review(wire)
        self.assertEqual(result["independent_review"]["pedagogy_score"], 3)
        self.assertEqual(result["independent_review"]["findings"], [])
        self.assertEqual(result["review_reason"], "review_checklist_evidence_missing")
        self.assertEqual((result["verification"], result["review_state"]), ("reviewed", "incomplete"))
        self.assertEqual(result["semantic_coverage_item_ids"], [])
        self.assertEqual(set(result["missing_item_ids"]), set(self.ids))
        self.assertEqual(result["blocks"], self.draft["blocks"])
        self.assertEqual(len(UnitOutput.model_validate(result).blocks), 24)

    async def test_mocked_complete_review_confirms_six_items_with_original_ids(self):
        result, (_, messages, schema) = await self.run_review(self.response(self.evidence))
        self.assertIs(schema, CHECKLIST_REVIEW_SCHEMA)
        packet, = json.loads(messages[-1].content)
        self.assertEqual(len(packet["blocks"]), 24)
        self.assertEqual([i["item_id"] for i in packet["reviewable_items"]], list(range(1, 7)))
        self.assertIn("Assess every number", messages[0].content)
        self.assertIn("exactly one entry", messages[0].content)
        self.assertEqual((result["coverage"], result["review_state"]), ("explained", "approved"))
        self.assertEqual([e["item_id"] for e in result["independent_review"]["checklist_evidence"]], self.ids)
        self.assertEqual(set(result["semantic_coverage_item_ids"]), set(self.ids))
        self.assertEqual(result["missing_item_ids"], [])

    async def test_missing_duplicate_unknown_and_unsupported_evidence_cannot_approve(self):
        first, *others = self.evidence
        cases = (
            ("missing item", others, "incomplete", set(self.ids[1:])),
            ("empty list", [], "incomplete", set()),
            ("duplicate item", [first, first | {"quote": first["quote"].split(". ", 1)[0] + "."}, *others],
             "invalid", set(self.ids[1:])),
            ("unknown item", [first, *others, first | {"item_id": 7}], "invalid", set(self.ids)),
            ("wrong block", [first | {"block_id": others[0]["block_id"]}, *others], "invalid", set(self.ids[1:])),
            ("unsupported quote", [first | {"quote": "Une citation complète est absente de la réponse."}, *others],
             "invalid", set(self.ids[1:])),
            ("heading words only", [first | {"quote": "présentation trop chargée"}, *others],
             "invalid", set(self.ids[1:])),
        )
        for label, evidence, reason, confirmed in cases:
            with self.subTest(label=label):
                result, _ = await self.run_review(self.response(evidence))
                self.assertEqual(result["review_state"], "incomplete")
                self.assertEqual(result["review_reason"], "review_checklist_evidence_" + reason)
                self.assertEqual(set(result["semantic_coverage_item_ids"]), confirmed)

    async def test_exact_full_heading_quote_is_not_substantive_evidence(self):
        first, *others = self.evidence
        heading = "Une présentation claire et lisible pour le recrutement."
        block = self.draft["blocks"][0] | {"text": f"## {heading}\n" + self.draft["blocks"][0]["text"]}
        draft = self.draft | {"blocks": [block, *self.draft["blocks"][1:]]}
        result, _ = await self.run_review(self.response([first | {"quote": heading}, *others]), draft=draft)
        self.assertEqual(result["review_reason"], "review_checklist_evidence_invalid")
        self.assertNotIn(self.ids[0], result["semantic_coverage_item_ids"])

    async def test_evidence_cannot_cite_a_block_from_another_reviewed_unit(self):
        first, *others = self.evidence
        uid = next(u["logical_id"] for u in self.units if u["label"] == "Question 1")
        foreign = {"block_id": f"{uid}:1", "text": first["quote"], "provenance": "derived", "source_indexes": [1]}
        peer = self.draft | {"logical_id": uid, "blocks": [foreign], "reviewable_items": {}}
        wire = json.loads(self.response([first | {"block_id": foreign["block_id"]}, *others]))
        wire["reviews"].append({"unit_id": uid, "pedagogy_score": 3, "findings": []})
        result, _ = await self.run_review(json.dumps(wire), peer=peer)
        self.assertEqual(result["review_reason"], "review_checklist_evidence_invalid")
        self.assertNotIn(self.ids[0], result["semantic_coverage_item_ids"])

    async def test_without_reviewable_items_preserves_optional_field_and_numeric_ledger(self):
        draft, unit, record, plan = fixture(text="Précision : 0,46.")
        draft["verified_facts"] = [{"label_path": ["Précision"], "value": "0,46"}]
        wire = {"reviews": [{"unit_id": "shapley", "pedagogy_score": 3, "findings": [], "ledger_updates": [
            {"kind": "result", "block_id": "b1", "quote": "Précision : 0,46."},
        ]}]}
        dispatch = AsyncMock(return_value=json.dumps(wire))
        result, = await review_units([draft], [unit], {"shapley": record}, [], plan, [], dispatch, allow_repair=set())
        self.assertIs(dispatch.await_args.args[2], REVIEW_SCHEMA)
        self.assertEqual(result["review_state"], "approved")
        self.assertNotIn("review_reason", result)
        self.assertEqual(result["verified_facts"], [{
            "label_path": ["Précision"], "value": "0,46", "verification": "reviewed", "quote": "Précision : 0,46.",
        }])
