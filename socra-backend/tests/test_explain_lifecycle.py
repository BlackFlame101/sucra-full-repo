"""Offline Phase 7 lifecycle, using real planning and mocked model and storage calls."""
import asyncio
import json
import os
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from agents import explicateur
from agents.explain_lifecycle import ExplanationV2, attach_contract, rebind_version, version_for
from db.explain_progress import KEY, TurnCheckpoint
from tests.test_explain_unit_generation import block, records_for


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.storage = {}
        self.calls = []
        self.events = []
        self.session = str(uuid4())
        self.document = {"id": str(uuid4()), "filename": "Course.pdf", "page_count": 3,
                         "index_generation": 4, "content_hash": "hash-four"}
        self.units, rows, records = records_for([
            {"text": "II.1 SHAP calculation\nShapley averages the marginal contributions across variable orders."},
            {"text": "II.2 LIME procedure\nLIME weights the nearby perturbations and fits a local model."},
            {"text": "III.3 Performance ou interprétabilité ?\nComparer les mesures du même jeu de test."},
        ])
        self.ids = [unit["logical_id"] for unit in self.units]
        records[self.ids[2]]["unresolved"] = [{"page": 3, "reason": "unreadable_table",
                                               "status": "unverifiable_source"}]
        rows = [row | {"id": str(uuid4()), "document_id": self.document["id"], "similarity": 0}
                for row in rows]
        self.enterContext(patch.dict(os.environ, {"EXPLAIN_UNIT_PIPELINE": "true", "EXPLAIN_INTENT_PLANS": "true",
                                                  "SOCRA_EXPLAIN_UNIT_MAX_LEARNING_CALLS": "1"}))
        self.enterContext(patch("db.explain_progress.load_checkpoints",
                                side_effect=lambda *args: deepcopy(list(self.storage.values()))))
        def persist(turn, version, call):
            data = deepcopy(turn.data)
            data["revision"] = data.get("revision", 0) + 1
            if version:
                data["versions"].append(version)
            if call:
                data["calls"].append(call)
            self.storage[turn.request_id] = data

        self.enterContext(patch.object(TurnCheckpoint, "_write", autospec=True, side_effect=persist))
        for name, result in {"retrieve_summary_guided_chunks": rows, "course_documents": [self.document],
                             "document_inventory_chunks": (rows, "full_document"),
                             "load_or_queue_unit_map": {"text_hash": "map", "units": self.units},
                             "load_prepared_evidence": records, "queue_unit_evidence": None}.items():
            self.enterContext(patch.object(explicateur, name, AsyncMock(return_value=result)))
        self.enterContext(patch.object(explicateur, "get_chat_llm", side_effect=self.model))

    def model(self, *, agent, **_):
        async def invoke(messages):
            self.calls.append(agent)
            content = json.loads(messages[-1].content)
            self.assertEqual(agent, "explain_unit_generation")
            extra = content["prior_learning"].get("deepen")
            quote = content["sources"][0]["quote"]
            text = quote + (" This is the deeper explanation." if extra else "")
            return SimpleNamespace(content=json.dumps({"blocks": [block("explanation", text, [1])]}),
                                   response_metadata={})
        return SimpleNamespace(ainvoke=invoke)

    def state(self, request=None, **changes):
        request = request or str(uuid4())
        prompt = {"id": request, "metadata": {KEY: deepcopy(self.storage[request])}
                  if request in self.storage else {}}
        checkpoint = TurnCheckpoint(self.session, "course", "owner", request, prompt, lease=str(uuid4()))

        async def event(kind, row):
            self.events.append((kind, row))

        return {"course_id": "course", "user_id": "owner", "session_id": self.session, "request_id": request,
                "student_message": "Teach me the entire course, all chapters in order.",
                "explain_document_id": self.document["id"], "model": "gemini-3.5-flash-lite", "provider": "google",
                "explain_checkpoint": checkpoint, "explain_unit_event": event, **changes}

    async def run_state(self, state):
        result = await explicateur.run_explicateur(state)
        return ExplanationV2.model_validate(result["explanation"]).model_dump(mode="json")

    async def test_continue_advances_past_partial_and_deepen_preserves_the_old_block(self):
        first = await self.run_state(self.state())
        self.assertEqual(first["units"][0]["coverage"], "partial")
        self.assertTrue(first["sections"][0]["citations"])
        self.assertEqual(first["sections"][0]["content"], first["sections"][0]["markdown"])
        actions = first["learning_state"]["next_actions"]
        advance = next(action for action in actions if action["action"] == "continue_learning")
        self.assertEqual(advance["logical_id"], self.ids[1])
        second = await self.run_state(self.state(advance["request_id"], explain_course_prior=first["course_progress"],
                                                explain_unit_action=advance["action"], explain_target_unit=self.ids[1]))
        self.assertEqual([unit["logical_id"] for unit in second["units"]], self.ids[1:2])
        self.assertEqual(second["learning_state"]["progress"][0]["status"], "partial")
        deepen = next(action for action in actions
                      if action["action"] == "deepen_unit" and action["logical_id"] == self.ids[0])
        version = await self.run_state(self.state(deepen["request_id"], explain_course_prior=first["course_progress"],
                                                  explain_unit_action=deepen["action"], explain_target_unit=self.ids[0]))
        revised = version["units"][0]
        self.assertEqual(revised["logical_id"], self.ids[0])
        self.assertEqual(revised["blocks"][0], first["units"][0]["blocks"][0])
        self.assertIn("deeper explanation", revised["blocks"][1]["text"])
        self.assertEqual(len(self.calls), 3)

    async def test_cancel_after_first_ready_then_retry_replays_without_more_model_calls(self):
        pending = self.state()
        async def event(kind, row):
            if kind == "unit_ready":
                raise asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.run_state(pending | {"explain_unit_event": event})
        checkpoint = self.storage[pending["request_id"]]
        self.assertEqual([row["stage"] for row in checkpoint["versions"]], ["draft", "ready"])
        resumed = await self.run_state(self.state(pending["request_id"]))
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(any(kind == "unit_ready" and value.get("replayed") for kind, value in self.events))
        self.assertEqual(resumed["units"][0], checkpoint["versions"][1]["output"])
        self.assertEqual(resumed["coverage_ledger"]["low_fidelity_pages"], [3])
        self.document.update(index_generation=5, content_hash="hash-five")
        with self.assertRaisesRegex(ValueError, "reindexed"):
            await self.run_state(self.state(pending["request_id"]))

    async def test_batch_checkpoints_each_unit_and_resumes_saved_sibling_without_regeneration(self):
        parent = ("ii", "shared topic", 1)
        for unit in self.units[:2]:
            unit["heading_path"] = (parent, *unit["heading_path"])

        async def invoke(messages):
            self.calls.append("batch")
            payload = json.loads(messages[-1].content)["units"]
            self.assertEqual([row["unit_id"] for row in payload], self.ids[:2])
            return SimpleNamespace(content=json.dumps({"units": [
                {"unit_id": row["unit_id"], "blocks": [block("explanation", row["sources"][0]["quote"], [1])]}
                for row in payload]}), response_metadata={})

        pending = self.state()

        async def event(kind, row):
            if kind == "unit_ready":
                raise asyncio.CancelledError

        with patch.object(explicateur, "get_chat_llm", return_value=SimpleNamespace(ainvoke=invoke)):
            with self.assertRaises(asyncio.CancelledError):
                await self.run_state(pending | {"explain_unit_event": event})
            stored = self.storage[pending["request_id"]]
            self.assertEqual([row["output"]["logical_id"] for row in stored["versions"] if row["stage"] == "draft"],
                             self.ids[:2])
            resumed = await self.run_state(self.state(pending["request_id"]))
        self.assertEqual(self.calls, ["batch"])
        self.assertTrue(all(unit["blocks"] for unit in resumed["units"][:2]))

    async def test_later_request_reviews_budget_deferred_draft_without_regenerating_it(self):
        first = await self.run_state(self.state())
        original = first["units"][0]
        self.assertEqual(original["review_reason"], "review_call_budget")
        action = next(a for a in first["learning_state"]["next_actions"]
                      if a["action"] == "deepen_unit" and a["logical_id"] == self.ids[0])
        calls = []

        def model(*, agent, **_):
            async def invoke(messages):
                calls.append(agent)
                if agent == "explain_unit_review":
                    response = {"reviews": [{"unit_id": self.ids[0], "pedagogy_score": 2, "findings": []}]}
                elif agent == "explain_unit_repair":
                    response = {"patches": []}
                else:
                    raise AssertionError("The saved text must not be regenerated")
                return SimpleNamespace(content=json.dumps(response), response_metadata={})
            return SimpleNamespace(ainvoke=invoke)

        with patch.dict(os.environ, {"SOCRA_EXPLAIN_UNIT_MAX_LEARNING_CALLS": "2"}), \
             patch.object(explicateur, "get_chat_llm", side_effect=model):
            revised = await self.run_state(self.state(
                action["request_id"], explain_course_prior=first["course_progress"],
                explain_unit_action=action["action"], explain_target_unit=action["logical_id"],
            ))
        self.assertEqual(calls, ["explain_unit_review", "explain_unit_repair"])
        self.assertEqual(revised["units"][0]["blocks"], original["blocks"])
        self.assertEqual(revised["units"][0]["verification"], "reviewed")

    def test_reindex_rebind_requires_unambiguous_current_evidence(self):
        quote = "Source text"
        old = {"page": 1, "start": 0, "end": len(quote), "quote": quote}
        moved = old | {"page": 2}
        row = {"required_item_ids": ["item"], "output": {"blocks": [{"text": quote}], "sources": [old],
               "unverifiable_source": [], "verified_facts": [{"anchor": old}]}}
        rebound = rebind_version(row, [moved], ["item"], [])
        self.assertEqual(rebound["output"]["verified_facts"][0]["anchor"], moved)
        self.assertIsNone(rebind_version(row, [moved, old], ["item"], []))
        self.assertIsNone(rebind_version(row, [moved], ["changed-item"], []))

    def test_document_status_requires_review_for_each_required_unit(self):
        units = self.units[:2]
        ids = self.ids[:2]
        plan = {"scope": {uid: {"in_scope": True, "reason": "requested"} for uid in ids},
                "order": ids, "required_items": {}, "unverifiable_source": {}}
        common = {"coverage": "explained", "confidence": "high", "missing_item_ids": [],
                  "unverifiable_source": [], "verified_facts": [], "sources": [],
                  "blocks": [{"block_id": "b1", "kind": "explanation", "text": "Teaching text",
                              "provenance": "course", "source_indexes": []}]}
        outputs = [common | {"logical_id": unit["logical_id"], "title": unit["title"],
                             "content_version": unit["content_version"], "verification": verification}
                   for unit, verification in zip(units, ("reviewed", "deterministic_only"))]
        versions = [version_for("request", "ready", output) for output in outputs]
        card = {"schema_version": 2, "language": "English", "units": outputs, "sections": []}
        result = attach_contract(card, plan, units, versions, versions, {"facts_ledger": [], "next_actions": []}, {})
        ledger = result["coverage_ledger"]
        self.assertFalse(ledger["document_complete"])
        self.assertEqual(ledger["document_status"], "partial")
        self.assertEqual(ledger["review_counts"], {"generated": 2, "reviewed": 1, "approved": 1, "rejected": 0,
                                                   "incomplete": 1, "unreviewed": 1, "not_generated": 0})
