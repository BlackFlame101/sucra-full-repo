"""Offline integration controls for the source-specific Spark Step 0 approval gate."""

from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from agents import explicateur
from agents.explain_budget import ExplainCallBudget, ReviewConfigurationError, explain_budget, review_target
from agents.explain_lab_verification import CHECK_IDS, COMMANDS, NO_COMMAND, PEDAGOGY, RUNTIME, deterministic_passed, lab_approval_passed
from agents.explain_lifecycle import latest_outputs, version_for
from agents.explain_planner import _BEESWARM_VERSION, build_learning_plan
from agents.explain_tagged_output import TaggedLayout, parse_tagged_units
from agents.explain_unit_generation import generate_unit
from agents.explain_unit_review import LAB_REVIEW_SCHEMA, lab_provider_response, review_units
from tests.run_explain_scorecard import generate_replay, load_spark_fixture, prepare_spark, structural_tagged


GENERATOR = "gemini-3.5-flash-lite"
REVIEWER = "gemini-3.5-flash"
_EVIDENCE_SLOTS = (0, 2, 3, 4, 8, 12, 15, 14, 16, 19)


def spark_inputs():
    annotation, pages, indexed = load_spark_fixture()
    units, by_id, records, plan, excerpts = prepare_spark(annotation, pages, indexed)
    uid = annotation["units"][0]["unit_id"]
    return by_id[uid], units, records, plan, excerpts[uid]


def lab_review_row(draft):
    return {"unit_id": draft["logical_id"], "pedagogy_score": 2, "findings": [], "lab_evidence": [
        {"criterion": criterion, "item_id": group + 1, "block_id": draft["blocks"][offset]["block_id"],
         "quote": draft["blocks"][offset]["text"]}
        for (criterion, group, _), offset in zip(PEDAGOGY, _EVIDENCE_SLOTS, strict=True)
    ]}


def review_json(row):
    return json.dumps({"reviews": [row]}, ensure_ascii=False)


def corrected_spark_response(payload):
    """Separate offline control for the runtime line and grounded local-mode teaching."""
    return structural_tagged(payload).replace(
        RUNTIME["French"] + " Le numéro", RUNTIME["French"] + "\nLe numéro",
    ).replace(
        "Une session locale rend possible un essai reproductible sur le poste de travail.",
        "Attendez-vous à ce que le travail soit exécuté avec deux threads sur un seul poste. "
        "Cet essai ne permet pas de déduire les performances d’un cluster distribué.",
    )


class SparkApprovalTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.unit, cls.units, cls.records, cls.plan, cls.excerpts = spark_inputs()

    async def generate(self, transform=lambda raw: raw):
        return await generate_replay(self.unit, self.units, self.records, self.plan, self.excerpts,
                                     lambda payload, _: (transform(structural_tagged(payload)), ""))

    async def review(self, draft, dispatch, *, fits=None):
        result, = await review_units([draft], self.units, self.records, self.excerpts, self.plan, [],
                                     dispatch, allow_repair=set(), fits=fits)
        return result

    async def test_exact_operations_and_distinct_grounded_blocks(self):
        packets, draft = await self.generate()
        self.assertEqual(len(packets), 1)
        self.assertEqual(len(draft["blocks"]), 20)
        self.assertEqual(len(draft["sources"]), 5)
        self.assertEqual(list(draft["lab_verification"]["checks"]), list(CHECK_IDS))
        self.assertTrue(deterministic_passed(draft))
        self.assertEqual(draft["verification"], "deterministic_only")
        self.assertIn("import os, sys", draft["blocks"][1]["text"])
        self.assertEqual(version_for("offline", "ready", draft)["stage"], "draft")

    async def test_runtime_and_local_provenance_instructions_match_the_packet(self):
        packets, draft = await generate_replay(
            self.unit, self.units, self.records, self.plan, self.excerpts,
            lambda payload, _: (corrected_spark_response(payload), ""),
        )
        packet = packets[0].payload
        contract = packet["lab_command_contract"]
        self.assertEqual(packet["language"], "French")
        self.assertEqual(len(contract["groups"]), 5)
        runtime_group, local_group = contract["groups"][-2:]
        self.assertEqual(runtime_group["expected_result_must_include"], RUNTIME["French"])
        for phrase in ("In expected_result", "on its own plain-text line", "capitalization, accents",
                       "lowercase", "installed in the runtime environment", "Do not give a fixed version"):
            self.assertIn(phrase, runtime_group["expected_result_instruction"])
        self.assertIn(RUNTIME["French"], draft["blocks"][14]["text"].splitlines())
        self.assertEqual(local_group["derived_sources"], packet["checklist"][4]["sources"])
        self.assertIn("For action, expected_result and checkpoint, use derived provenance", local_group["local_mode_instruction"])
        self.assertIn("Only the no-command placeholder is supplementary", local_group["local_mode_instruction"])
        local_source, = (source for source in packet["sources"] if source["index"] in local_group["derived_sources"])
        self.assertIn("deux threads sur la machine", local_source["quote"])
        self.assertIn("performances d’un cluster distribué", local_source["quote"])
        local_blocks = draft["blocks"][16:]
        self.assertEqual([b["provenance"] for b in local_blocks], ["derived", "supplementary", "derived", "derived"])
        self.assertEqual(local_blocks[1]["text"], NO_COMMAND["French"])
        self.assertFalse(local_blocks[1]["source_indexes"])
        for block in (local_blocks[0], *local_blocks[2:]):
            self.assertEqual(block["source_indexes"], local_group["derived_sources"])
        result = local_blocks[2]["text"]
        self.assertIn("deux threads sur un seul poste", result)
        self.assertIn("ne permet pas de déduire les performances d’un cluster distribué", result)
        self.assertNotIn("En mode local[2], Spark utilise deux threads sur la machine.", result)
        self.assertEqual(tuple(draft["lab_verification"]["checks"]), CHECK_IDS)
        self.assertTrue(deterministic_passed(draft))
        self.assertEqual(version_for("offline", "ready", draft)["stage"], "draft")

    async def test_lowercase_runtime_continuation_is_rejected_without_rewriting(self):
        sentence = RUNTIME["French"]
        continuation = "Les avertissements restent visibles et " + sentence[0].lower() + sentence[1:]
        _, draft = await self.generate(lambda raw: raw.replace(sentence, continuation))
        self.assertIn(continuation, draft["blocks"][14]["text"])
        self.assertEqual([key for key, passed in draft["lab_verification"]["checks"].items() if not passed],
                         ["runtime_qualification"])
        self.assertFalse(lab_approval_passed(draft))

    async def test_only_no_command_placeholder_can_be_supplementary(self):
        for kind in ("action", "expected_result", "checkpoint"):
            for provenance, indexes in (("supplementary", "-"), ("derived", "-"),
                                        ("derived", "1"), ("derived", "99")):
                with self.subTest(kind=kind, provenance=provenance, indexes=indexes):
                    old = f"kind={kind} provenance=derived sources=5 items=5"
                    new = f"kind={kind} provenance={provenance} sources={indexes} items=5"
                    _, draft = await self.generate(lambda raw: raw.replace(old, new, 1))
                    self.assertFalse(draft["lab_verification"]["checks"]["source_grounding"])
                    self.assertFalse(deterministic_passed(draft))
                    self.assertEqual(version_for("offline", "ready", draft)["stage"], "draft")

    async def test_command_and_runtime_mutations_fail(self):
        settings = COMMANDS[0][1:3]
        imports = COMMANDS[0][3:6]
        builder, session, warn, version = COMMANDS[0][-1], *COMMANDS[3]
        tests = [
            ("missing import os/sys", "import os, sys\n", "", "python_executable"),
            ("missing runtime interpreter", settings[0] + "\n", "", "python_executable"),
            ("missing driver interpreter", settings[1] + "\n", "", "driver_executable"),
            ("wrong SQL import", imports[0], "from pyspark.sql import functions as F", "spark_imports"),
            ("wrong app name", "TP3_MLlib_VersionB", "TP4_MLlib_VersionB", "application_name"),
            ("wrong local master", 'local[2]', 'local[4]', "local_master"),
            ("wrong session config", builder, "spark = (SparkSession", "session_creation"),
            ("missing WARN step", warn + "\n", "", "warn_logging"),
            ("missing runtime version command", version + "\n", "", "runtime_version_command"),
            ("reversed env order", "\n".join(settings), "\n".join(reversed(settings)), "complete_execution_order"),
            ("swapped imports", "\n".join(imports), "\n".join(reversed(imports)), "complete_execution_order"),
            ("session builder before configuration", "\n".join(COMMANDS[0]),
             "\n".join((builder, *COMMANDS[0][:-1])), "complete_execution_order"),
            ("logging before session", session + "\n" + warn, warn + "\n" + session, "complete_execution_order"),
            ("version before session", session + "\n" + warn + "\n" + version,
             version + "\n" + warn + "\n" + session, "complete_execution_order"),
            ("duplicate operation", imports[0], imports[0] + "\n" + imports[0], "spark_imports"),
            ("invalid Python indentation", "import os, sys", "    import os, sys", "python_cell_syntax"),
            ("invented fixed version", "Le numéro dépend du moteur", "La version Spark est 3.5.1. Le numéro dépend du moteur",
             "runtime_qualification"),
            ("unqualified version", "est relevée à l’exécution.", "est inscrite dans le document.", "runtime_qualification"),
            ("command mentioned only in prose", "```python\n" + COMMANDS[1][0] + "\n```",
             "Le réglage est " + COMMANDS[1][0] + ".", "local_master"),
            ("expected result omitted", "kind=expected_result", "kind=missing_result", "separate_blocks"),
            ("checkpoint omitted", "kind=checkpoint", "kind=missing_checkpoint", "separate_blocks"),
            ("code in action block", "Les deux réglages", "```python\na = 1\n```\nLes deux réglages", "separate_blocks"),
            ("wrong source", "sources=1 items=1", "sources=2 items=1", "source_grounding"),
            ("forbidden control", "@@UNIT", "\x1f@@UNIT", "control_characters"),
        ]
        for name, old, new, failed_check in tests:
            with self.subTest(name=name):
                _, draft = await self.generate(lambda raw: raw.replace(old, new, 1))
                self.assertIs(draft["lab_verification"]["checks"][failed_check], False)
                self.assertFalse(deterministic_passed(draft))
                self.assertEqual(version_for("offline", "ready", draft)["stage"], "draft")

    async def test_json_compatibility_splits_the_same_ordered_contract(self):
        async def run_split(*, cite_full_packet_index):
            packets = []

            async def send(messages, _count):
                payload = json.loads(messages[-1].content)
                uid = payload["unit_id"]
                packets.append(payload)
                raw, reason = parse_tagged_units(
                    structural_tagged(payload), {uid: TaggedLayout.from_packet(payload)},
                )[uid]
                if cite_full_packet_index and len(packets) == 2:
                    response = json.loads(raw)
                    local_action = next(
                        block for block in response["blocks"]
                        if block["kind"] == "action" and block["candidate_items"] == [3]
                    )
                    local_action["claims"][0]["source_indexes"] = [5]
                    raw = json.dumps(response, ensure_ascii=False)
                return raw, reason

            with patch.dict(os.environ, {"EXPLAIN_GENERATION_FORMAT": "json"}):
                draft = await generate_unit(self.unit, self.records[self.unit["logical_id"]], self.excerpts,
                                            self.plan, send, fits=lambda _: True, continuity={}, language="French",
                                            unit_map=self.units)
            self.assertEqual([len(p["checklist"]) for p in packets], [2, 3])
            local_group = packets[1]["lab_command_contract"]["groups"][-1]
            self.assertEqual((local_group["item_id"], local_group["derived_sources"]), (3, [3]))
            return draft

        draft = await run_split(cite_full_packet_index=False)
        self.assertTrue(deterministic_passed(draft))
        self.assertEqual(draft["blocks"][16]["source_indexes"], [5])
        invalid = await run_split(cite_full_packet_index=True)
        self.assertIn("invalid_claim_index", invalid["interruptions"])
        self.assertFalse(invalid["lab_verification"]["checks"]["source_grounding"])
        self.assertEqual(version_for("offline", "ready", invalid)["stage"], "draft")

    async def test_missing_skipped_or_tampered_checks_prevent_review_and_ready(self):
        _, valid = await self.generate()
        for manipulation in (
            lambda draft: draft.pop("lab_verification"),
            lambda draft: draft["lab_verification"]["checks"].pop("driver_executable"),
            lambda draft: draft["blocks"][1].update(text="unverified command"),
        ):
            draft = deepcopy(valid)
            manipulation(draft)
            sent = AsyncMock()
            verdict = await self.review(draft, sent)
            sent.assert_not_awaited()
            self.assertEqual(verdict["review_reason"], "lab_deterministic_incomplete")
            self.assertEqual(version_for("offline", "ready", verdict)["stage"], "draft")

    async def test_score_two_and_complete_evidence_are_eligible_but_plain_mocks_cannot_approve(self):
        _, draft = await self.generate()
        row = lab_review_row(draft)
        request = []

        async def send(_purpose, messages, schema):
            request.append(json.loads(messages[-1].content)[0])
            self.assertIs(schema, LAB_REVIEW_SCHEMA)
            return review_json(row)

        mocked = await self.review(draft, send)
        self.assertEqual(mocked["review_state"], "incomplete")
        self.assertEqual(mocked["review_reason"], "lab_review_transport_unverified")
        self.assertEqual(len(mocked["independent_review"]["lab_evidence"]), 10)
        self.assertEqual(mocked["independent_review"]["checklist_evidence"], [])
        self.assertEqual(version_for("offline", "ready", mocked)["stage"], "draft")
        self.assertEqual(len(request), 1)
        self.assertEqual({c["criterion"] for c in request[0]["lab_criteria"]}, {c for c, _, _ in PEDAGOGY})
        self.assertTrue(all(b["kind"] != "command_or_ui" for b in request[0]["blocks"]))
        # Synthetic receipt exercises the positive gate in memory only, without writing an approved artifact.
        response = lab_provider_response(review_json(row), REVIEWER, {"finish_reason": "STOP", "model_name": REVIEWER})
        eligible = await self.review(draft, AsyncMock(return_value=response))
        self.assertTrue(lab_approval_passed(eligible))
        self.assertEqual(eligible["review_state"], "approved")
        serialized = version_for("test-only", "ready", eligible)
        self.assertEqual(serialized["stage"], "ready")
        self.assertTrue(lab_approval_passed(serialized["output"]))

    async def test_review_evidence_shape_score_and_dispatch_fail_closed(self):
        _, draft = await self.generate()
        complete = lab_review_row(draft)
        mutations = {
            "missing collection": lambda row: row.pop("lab_evidence"),
            "empty collection": lambda row: row.update(lab_evidence=[]),
            "incomplete collection": lambda row: row["lab_evidence"].pop(),
            "wrong original id": lambda row: row["lab_evidence"][0].update(item_id=2),
            "wrong explanatory block": lambda row: row["lab_evidence"][0].update(block_id=draft["blocks"][4]["block_id"]),
            "command block": lambda row: row["lab_evidence"][0].update(block_id=draft["blocks"][1]["block_id"],
                                                                   quote=draft["blocks"][1]["text"]),
            "wrong quote": lambda row: row["lab_evidence"][0].update(quote="Cette phrase ne figure pas dans le brouillon."),
            "below threshold": lambda row: row.update(pedagogy_score=1),
        }
        for name, change in mutations.items():
            with self.subTest(name=name):
                row = deepcopy(complete)
                change(row)
                wrapped = lab_provider_response(review_json(row), REVIEWER, {"finish_reason": "STOP", "model_name": REVIEWER})
                verdict = await self.review(draft, AsyncMock(return_value=wrapped))
                self.assertNotEqual(verdict["review_state"], "approved")
                self.assertFalse(lab_approval_passed(verdict))
                self.assertEqual(version_for("offline", "ready", verdict)["stage"], "draft")
        invalid = await self.review(draft, AsyncMock(return_value='{"reviews":'))
        self.assertEqual(invalid["review_reason"], "invalid_review_response")
        missing = AsyncMock()
        unreviewed = await self.review(draft, missing, fits=lambda *_: False)
        missing.assert_not_awaited()
        self.assertEqual(unreviewed["review_reason"], "review_token_budget")
        self.assertEqual(version_for("offline", "ready", unreviewed)["stage"], "draft")

    async def test_copy_and_incorrect_pedagogy_are_separate_from_command_exactness(self):
        cases = [
            ("Dans ce mode le traitement utilise deux fils d’exécution sur la même machine.",
             "En mode local[2], Spark utilise deux threads sur la machine.", 16, "copied"),
            ("Dans ce mode le traitement utilise deux fils d’exécution sur la même machine.",
             "Dans ce mode le traitement utilise huit fils d’exécution sur la même machine.", 16, "incorrect"),
            ("Un essai sur un seul poste ne mesure ni la répartition du travail ni les performances d’un cluster.",
             "La configuration locale garantit les mêmes performances sur un cluster.", 19, "unsupported"),
            ("Les deux réglages donnent aux processus PySpark le même interpréteur que le notebook.",
             "Configurez ces options dans le notebook en suivant le code.", 0, "pedagogy"),
        ]
        for old, new, index, kind in cases:
            with self.subTest(kind=kind):
                _, draft = await self.generate(lambda raw: raw.replace(old, new))
                self.assertTrue(deterministic_passed(draft))
                row = lab_review_row(draft)
                if kind != "copied":
                    row["findings"] = [{"kind": kind, "block_id": draft["blocks"][index]["block_id"],
                                       "quote": new, "detail": "La justification pédagogique est insuffisante."}]
                result = await self.review(draft, AsyncMock(return_value=review_json(row)))
                self.assertFalse(lab_approval_passed(result))
                self.assertEqual(version_for("offline", "ready", result)["stage"], "draft")
                if kind == "copied":
                    self.assertEqual(result["review_reason"], "lab_pedagogy_evidence_invalid")
                else:
                    self.assertEqual(result["review_state"], "rejected")

    async def test_incomplete_saved_lab_versions_are_not_ready_outputs(self):
        _, draft = await self.generate()
        marked = draft | {"verification": "reviewed", "review_state": "approved"}
        self.assertEqual(latest_outputs([{"stage": "ready", "output": marked}]), {})
        saved = version_for("offline", "ready", marked)
        self.assertEqual(saved["stage"], "draft")
        self.assertEqual(saved["output"]["review_state"], "incomplete")

    async def test_configured_reviewer_reaches_the_production_dispatch(self):
        base = json.loads(Path(__file__).resolve().parents[1].joinpath("explain_model_limits.json").read_text())
        base["models"].append(base["models"][0] | {"model_id": REVIEWER})
        seen = []

        def model(**options):
            seen.append(options)

            async def invoke(messages):
                packet = json.loads(messages[-1].content)
                text = structural_tagged(packet) if options["agent"] == "explain_unit_generation" else '{"reviews":[]}'
                return SimpleNamespace(content=text, response_metadata={})
            return SimpleNamespace(ainvoke=invoke)

        checkpoint = SimpleNamespace(data={"calls": [], "document_id": "spark", "generation": 1,
                                            "source_hash": "fixture"}, save=AsyncMock())
        event = AsyncMock()
        state = {"provider": "google", "model": GENERATOR, "explain_checkpoint": checkpoint, "explain_unit_event": event}
        env = {"SOCRA_EXPLAIN_REVIEW_MODEL": REVIEWER, "SOCRA_EXPLAIN_MODEL_LIMITS_JSON": json.dumps(base),
               "EXPLAIN_GENERATION_FORMAT": "tagged"}
        with patch.dict(os.environ, env), patch.object(explicateur, "get_chat_llm", side_effect=model):
            metrics = explicateur._ExplainMetrics("test", call_budget=ExplainCallBudget(2))
            result, = await explicateur._generate_course_units(
                state, metrics, explain_budget("google", GENERATOR), [self.unit], self.records, self.excerpts,
                self.plan, self.units, "French", overview=False, continuity=[], prior_facts=[])
        self.assertEqual([options["model"] for options in seen], [GENERATOR, REVIEWER])
        self.assertTrue(all(options["single_attempt"] for options in seen))
        self.assertIs(seen[1]["response_schema"], LAB_REVIEW_SCHEMA)
        self.assertTrue(seen[1]["bind_response_schema"])
        self.assertEqual(seen[1]["max_completion_tokens"], 1800)
        self.assertEqual(result["review_state"], "unreviewed")
        self.assertEqual(version_for("offline", "ready", result)["stage"], "draft")
        versions = [call.kwargs["version"] for call in checkpoint.save.await_args_list if "version" in call.kwargs]
        self.assertEqual([row["stage"] for row in versions], ["draft", "draft"])
        self.assertNotIn("unit_ready", [call.args[0] for call in event.await_args_list])


class LabContractTests(unittest.TestCase):
    def test_preferred_reviewer_needs_a_verified_local_model_budget(self):
        budget = explain_budget("google", GENERATOR)
        with patch.dict(os.environ):
            os.environ.pop("SOCRA_EXPLAIN_MODEL_LIMITS_JSON", None)
            for model in (None, "", REVIEWER, "not-a-configured-model", "models/" + GENERATOR):
                with self.subTest(model=model), self.assertRaises(ReviewConfigurationError):
                    review_target("google", GENERATOR, budget, model, required=True)
            self.assertEqual(review_target("google", GENERATOR, budget, GENERATOR, required=True)[0], GENERATOR)
        for metadata in ({}, {"model_name": REVIEWER, "finish_reason": "MAX_TOKENS"},
                         {"model_name": GENERATOR, "finish_reason": "STOP"}):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                lab_provider_response("{}", REVIEWER, metadata)

    def test_two_beeswarm_gaps_are_in_scope_without_text_or_offsets(self):
        uid = "beeswarm"
        unit = {"logical_id": uid, "kind": "figure_walkthrough", "content_version": _BEESWARM_VERSION,
                "start": [18, 0], "end": [18, 558], "title": "SHAP global", "label": "II.5"}
        record = {"content_version": _BEESWARM_VERSION,
                  "checklist": [{"item_id": "text-point", "importance": "essential"}],
                  "unresolved": [{"page": 18, "kind": "figure", "reason": "visual_details_unconfirmed",
                                  "status": "unverifiable_source"}]}
        plan = build_learning_plan([unit], "offline", "Teach", {uid: record})
        self.assertIn(uid, plan["order"])
        self.assertEqual(plan["required_items"][uid], ["text-point"])
        gaps = plan["unverifiable_source"][uid]
        self.assertEqual([gap["id"] for gap in gaps], ["chapter6-01-labels", "chapter6-01-axis"])
        self.assertTrue(all(g["status"] == "unverifiable_source" and "span" not in g and "value" not in g for g in gaps))
