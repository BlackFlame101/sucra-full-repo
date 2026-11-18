import json
import os
from hashlib import sha256
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from uuid import uuid4

from agents.explain_budget import ExplainCallBudget
from agents.explain_unit_generation import (
    BATCH_SCHEMA, DraftBlock, DraftUnit, SCHEMA, generate_unit, generation_packet, legacy_projection, linked_evidence,
    plan_generation_batch, resolve_claims, systemic_generation_failure, teaching_findings, unpack_generation_batch,
)
from agents.explain_unit_review import REPAIR_SCHEMA
from agents.explain_verifier import Anchor, Block
from agents.structured_output import CONTROL, gemini_response_schema
from pydantic import ValidationError
from agents.explain_planner import build_learning_plan
from rag.explain_preparation import prepare_units
from rag.unit_map import bind_chunks, build_unit_map
from worker import chunk_pages, extract_pages
from agents.explain_course import unit_excerpts
from agents import explicateur
from agents.explain_budget import explain_budget


def records_for(pages):
    units = build_unit_map("course", pages)["units"]
    rows = [row | {"filename": "Course.pdf"} for row in chunk_pages([p["text"] for p in pages], positions=True)]
    bind_chunks(units, rows)
    evidence = prepare_units(units, pages, rows, rows, source_hash="fixture")
    return units, rows, evidence


def excerpt_rows(unit, rows):
    return list(unit_excerpts([{"id": unit["logical_id"], "evidence_spans": unit["evidence_spans"]}], rows))


def block(kind, text, indexes, **extra):
    return {"kind": kind, "text": text, "provenance": "course",
            "claims": [{"start": 0, "end": len(text), "source_indexes": indexes}]} | extra


class UnitGenerationTests(unittest.IsolatedAsyncioTestCase):
    def test_quote_only_gemini_contract_keeps_local_legacy_support_and_resolves_whitespace(self):
        for schema in (SCHEMA, BATCH_SCHEMA, REPAIR_SCHEMA):
            claim = gemini_response_schema(schema)["$defs"]["DraftClaim"]
            self.assertEqual(set(claim["properties"]), {"output_quote", "source_indexes"})
            self.assertEqual(set(claim["required"]), {"output_quote", "source_indexes"})
            self.assertNotIn("maxItems", claim["properties"]["source_indexes"])
        original = "Prédiction\n0,46"
        anchor = Anchor(16, 0, len(original), original)
        source = {"kind": "result", "text": original, "provenance": "course"}
        quoted = {"quote": "Prédiction 0,46", "source_indexes": [1]}
        draft = DraftBlock.model_validate(source | {"claims": [quoted]})
        marker, = resolve_claims(draft, [anchor], {1: 1})
        self.assertEqual(original[marker.start:marker.end], original)
        legacy = DraftBlock.model_validate(source | {"claims": [{"start": 0, "end": len(original), "source_indexes": [1]}]})
        self.assertEqual(resolve_claims(legacy, [anchor], {1: 1}), (marker,))
        damaged = "spécialité Intellige nce et profil ambitie use"
        readable = "spécialité Intelligence et profil ambitieuse"
        corrected = DraftBlock.model_validate(source | {"text": readable, "claims": [
            {"output_quote": damaged, "source_indexes": [1]}]})
        repaired_marker, = resolve_claims(corrected, [Anchor(1, 0, len(damaged), damaged)], {1: 1})
        self.assertEqual(readable[repaired_marker.start:repaired_marker.end], readable)
        with self.assertRaisesRegex(ValidationError, "claim_quote_not_found"):
            DraftBlock.model_validate(source | {"text": "une spécialité", "claims": [
                {"output_quote": "une spécia lité", "source_indexes": [1]}]})
        for selector, error in ((quoted | {"start": 0, "end": len(original)}, "mixed_claim_marker"),
                                (quoted | {"quote": "Invented text"}, "claim_quote_not_found")):
            with self.assertRaisesRegex(ValidationError, error):
                DraftBlock.model_validate(source | {"claims": [selector]})
        with self.assertRaisesRegex(ValidationError, "ambiguous_claim_quote"):
            DraftBlock.model_validate(source | {"text": original + " " + original, "claims": [quoted]})
        fabricated = DraftBlock.model_validate(source | {"text": "Prédiction 0,99",
                    "claims": [{"quote": "Prédiction 0,99", "source_indexes": [1]}]})
        with self.assertRaisesRegex(ValueError, "differs from the cited source"):
            resolve_claims(fabricated, [anchor], {1: 1})
        foreign = DraftBlock.model_validate(source | {"claims": [quoted | {"source_indexes": [2]}]})
        with self.assertRaisesRegex(ValueError, "outside its authorized evidence"):
            resolve_claims(foreign, [anchor], {1: 1})

    def test_case_restatement_english_reasoning_and_unqualified_qcm_answers_are_flagged(self):
        copied = "Une présentation trop chargée nuit à la lisibilité."
        case = {"logical_id": "case", "heading_path": [("étude de cas", "cas", 1)]}
        findings = teaching_findings(case, [Block("b", "explanation", copied, "course")],
                                     [Anchor(1, 0, len(copied), copied)], "French")
        self.assertEqual({f.code for f in findings}, {"case_reasoning_missing"})
        question = case | {"label": "Question 1"}
        consequence = Block("b", "explanation", "La lecture ralentit parce que les rubriques se confondent.", "derived")
        self.assertEqual({f.code for f in teaching_findings(question, [consequence], [], "French")},
                         {"case_action_missing"})
        action = Block("a", "final_answer", "Yassmina devrait séparer les rubriques.", "derived")
        self.assertFalse(teaching_findings(question, [consequence, action], [], "French"))
        qcm = {"logical_id": "q", "label": "Q1"}
        choices = [Anchor(1, i, i + 4, f"{label}. x") for i, label in enumerate("ABCD")]
        text = "The correct choices are A and C because they are the options that support this result."
        final = Block("b", "final_answer", text, "derived")
        self.assertEqual({f.code for f in teaching_findings(qcm, [final], choices, "French")},
                         {"language_mismatch", "qcm_answer_uncertainty_missing"})
        qualified = Block("b", "final_answer", "Réponse raisonnée. A et C sont les choix pertinents.", "derived")
        self.assertFalse(teaching_findings(qcm, [qualified], choices, "French"))

    async def test_saved_live_cv_and_qcm_batches_fail_explicitly_and_stop_before_next_dispatch(self):
        folder = os.getenv("SOCRA_P2_STAGE1_FIXTURES")
        directory = os.getenv("SOCRA_FOUR_PDF_DIR")
        if not folder or not directory:
            self.skipTest("Stage 1 responses and source PDFs are required")
        from rag.unit_map import build_unit_map

        raw_by_doc = {}
        for name in ("cv", "revision"):
            saved = json.loads((Path(folder) / f"socra-p2-stage1-{name}-responses.json").read_text(encoding="utf-8"))
            raw_by_doc[name] = saved[0]["output"]
            for batch in saved:
                parsed = unpack_generation_batch(batch["output"], batch["unit_ids"])
                self.assertTrue(all(not reason for _, reason in parsed.values()))
            prior = json.loads((Path(folder) / f"socra-p2-stage1-{name}-live-result.json").read_text(encoding="utf-8"))
            self.assertEqual(systemic_generation_failure(prior["drafts"], {}),
                             "zero_retained_blocks" if name == "cv" else "no_usable_provenance")

        pdf = next(Path(directory).glob("TD*ANALYSE CV.pdf"))
        pages = await extract_pages(pdf.read_bytes(), layout=True, evidence=True)
        units = build_unit_map("cv", pages)["units"]
        rows = chunk_pages([p["text"] for p in pages], positions=True)
        bind_chunks(units, rows)
        records = prepare_units(units, pages, rows, chunk_pages(await extract_pages(pdf.read_bytes())), source_hash="fixture")
        plan = build_learning_plan(units, "map", "Explique en détail sans rien omettre", records)
        selected = [u for u in units if u["logical_id"] in plan["order"] and plan["required_items"][u["logical_id"]]]
        # A subsequent source group is queued here only to prove the first batch blocks a second dispatch.
        later = selected[-1] | {"logical_id": "later", "heading_path": (("different", "different", 1),)}
        old_id = selected[-1]["logical_id"]
        records["later"] = records[old_id]
        plan["required_items"]["later"] = plan["required_items"][old_id]
        assert len(selected) == 5
        metrics = explicateur._ExplainMetrics("stage1-offline", call_budget=ExplainCallBudget(learning_limit=9))
        invoke = AsyncMock(return_value=SimpleNamespace(content=raw_by_doc["cv"], response_metadata={}))
        with patch.object(explicateur, "get_chat_llm", return_value=SimpleNamespace(ainvoke=invoke)):
            drafts = await explicateur._generate_course_units(
                {"model": "gemini-3.5-flash-lite", "provider": "google"}, metrics,
                explain_budget("google", "gemini-3.5-flash-lite"), [*selected, later], records,
                [row for u in selected for row in excerpt_rows(u, rows)]
                + [row | {"unit_id": "later"} for row in excerpt_rows(selected[-1], rows)],
                plan, [*units, later], "French",
                overview=True, continuity=[], prior_facts=[],
            )
        invoke.assert_awaited_once()
        self.assertEqual(metrics.retrieval["systemic_generation_failure"], "zero_retained_blocks")
        self.assertTrue(all("mixed_claim_marker" in d["interruptions"] and not d["blocks"] for d in drafts[:5]))
        self.assertEqual(drafts[-1]["interruptions"], ["systemic_generation_failure"])

    async def test_real_cv_links_only_the_case_and_corresponding_answer_and_replays_quote_only_response(self):
        folder = os.getenv("SOCRA_P2_STAGE1_FIXTURES")
        directory = os.getenv("SOCRA_FOUR_PDF_DIR")
        if not folder or not directory:
            self.skipTest("CV PDF and saved quote-only response are required")
        from rag.unit_map import build_unit_map

        pdf = next(Path(directory).glob("TD*ANALYSE CV.pdf"))
        pages = await extract_pages(pdf.read_bytes(), layout=True, evidence=True)
        units = build_unit_map("cv", pages)["units"]
        rows = chunk_pages([p["text"] for p in pages], positions=True)
        bind_chunks(units, rows)
        records = prepare_units(units, pages, rows, chunk_pages(await extract_pages(pdf.read_bytes())), source_hash="fixture")
        excerpts = {u["logical_id"]: excerpt_rows(u, rows) for u in units}
        by_label = {u["label"]: u for u in units}
        for number in (1, 2):
            q = by_label[f"Question {number}"]
            a = by_label[f"Réponse {number}"]
            sources = linked_evidence(q, units, records, excerpts)
            self.assertEqual({s["label"] for s in sources.values()}, {"Étude de cas", f"Réponse {number}"})
            self.assertEqual({s["label"] for s in linked_evidence(a, units, records, excerpts).values()},
                             {"Étude de cas", f"Question {number}"})
            self.assertLessEqual(len(sources), 24)
            self.assertTrue(all(anchor.quote == pages[anchor.page - 1]["text"][anchor.start:anchor.end]
                                for anchor in sources))
        q = by_label["Question 1"]
        a = by_label["Réponse 1"]
        foreign = a | {"document_id": "foreign"}
        self.assertNotIn("Réponse 1", {s["label"] for s in linked_evidence(
            q, [foreign if unit == a else unit for unit in units], records, excerpts).values()})
        report = json.loads((Path(folder) / "socra-p2-resume-cv-generation-responses.json").read_text(encoding="utf-8"))
        batch, = report
        prior = unpack_generation_batch(batch["output"], batch["unit_ids"])
        self.assertTrue(all(reason != "mixed_claim_marker" for _, reason in prior.values()))
        plan = build_learning_plan(units, "map", "Explique en détail sans rien omettre", records)
        results = []
        for u in units:
            uid = u["logical_id"]
            if uid in prior:
                results.append(await generate_unit(
                    u, records[uid], excerpts[uid], plan, AsyncMock(), fits=lambda _: True, continuity={},
                    language="French", unit_map=units, batch_response=prior[uid],
                    related=linked_evidence(u, units, records, excerpts),
                ))
        self.assertTrue(any(f["code"] == "deferred_required_answer" for draft in results for f in draft["findings"]))
        self.assertTrue(all(draft["coverage"] != "explained" for draft in results))

        qid = q["logical_id"]
        context = linked_evidence(q, units, records, excerpts)
        _, packet, _ = generation_packet(q, records[qid], excerpts[qid], plan, {}, "French", context)
        action = next(s for s in packet["sources"] if s.get("label") == "Réponse 1" and "chargée" in s["quote"].casefold())
        original = next(s for s in packet["sources"] if s.get("label") == "Étude de cas")
        text = "Présenter les réalisations clairement permet de rendre le profil plus lisible pour le recruteur."
        payload = {"blocks": [{"kind": "working", "text": text, "provenance": "derived", "claims": [
            {"output_quote": text, "source_indexes": [original["index"], action["index"]]}]}]}
        result = await generate_unit(q, records[qid], excerpts[qid], plan, AsyncMock(), fits=lambda _: True,
                                     continuity={}, language="French", unit_map=units,
                                     batch_response=(json.dumps(payload), ""), related=context)
        self.assertEqual(result["blocks"][0]["source_indexes"], [original["index"], action["index"]])
        self.assertFalse(any(f["code"] == "invalid_claim_anchor" for f in result["findings"]))

    def test_batch_envelope_isolates_invalid_duplicate_missing_and_foreign_units(self):
        good = block("explanation", "Grounded text", [1])
        rows = [{"unit_id": "one", "blocks": [good]}, {"unit_id": "duplicate", "blocks": [good]},
                {"unit_id": "duplicate", "blocks": [good]}, {"unit_id": "foreign", "blocks": [good]},
                {"unit_id": "invalid", "blocks": {"block": good}},
                {"unit_id": "mixed", "blocks": [False, good]}]
        ids = ["one", "duplicate", "missing", "invalid", "mixed"]
        parsed = unpack_generation_batch(json.dumps({"units": rows}), ids)
        self.assertEqual(set(parsed), set(ids))
        self.assertEqual(json.loads(parsed["one"][0]), {"blocks": [good]})
        self.assertEqual([parsed[uid][1] for uid in ids[1:]],
                         ["duplicate_batch_unit", "missing_batch_unit", "invalid_batch_unit", ""])
        self.assertEqual(json.loads(parsed["mixed"][0]), {"blocks": [False, good]})
        partial = unpack_generation_batch('{"units":[' + json.dumps(rows[0]) + ',{"unit_id":', ids, "provider_failure")
        self.assertEqual(partial["one"], parsed["one"])
        self.assertEqual(partial["missing"], ("", "provider_failure"))

    async def test_corrupted_or_malformed_blocks_keep_a_valid_sibling(self):
        units, rows, records = records_for([{"text": "Question 1: Read the example\nThis is grounded evidence."}])
        unit = units[0]
        uid = unit["logical_id"]
        plan = build_learning_plan(units, "map", "Teach all details", records)
        snippets = excerpt_rows(unit, rows)
        _, packet, _ = generation_packet(unit, records[uid], snippets, plan, {}, "English")
        source = packet["sources"][0]
        good = block("problem", source["quote"], [source["index"]])
        quote = {"output_quote": good["text"] + "\x81", "source_indexes": [1]}
        invalid = [False, good | {"text": "d\x00amaged"}, good | {"claims": [quote]},
                   good | {"claims": [{"quote": "bad\x7f", "source_indexes": [1]}]}]
        raw = json.dumps({"units": [{"unit_id": uid, "blocks": [*invalid, good]}]})
        result = await generate_unit(
            unit, records[uid], snippets, plan, AsyncMock(), fits=lambda _: True, continuity={},
            language="English", unit_map=units, batch_response=unpack_generation_batch(raw, [uid])[uid],
        )
        self.assertEqual([b["text"] for b in result["blocks"]], [good["text"]])
        self.assertEqual(result["dropped_block_counts"], {"invalid_draft_block": 1, "provider_text_corruption": 3})
        self.assertEqual(systemic_generation_failure([result], {}), "provider_text_corruption")
        tied = result | {"dropped_block_counts": {"invalid_draft_block": 3, "provider_text_corruption": 3}}
        self.assertIsNone(systemic_generation_failure([tied], {}))
        controls = [*range(9), 11, 12, *range(14, 32), *range(127, 160)]
        self.assertTrue(all(CONTROL.fullmatch(chr(code)) for code in controls))
        self.assertFalse(any(CONTROL.search(char) for char in "\t\r\nÉà"))

    async def test_exact_raw_cv_response_rejects_all_five_units(self):
        fixtures = Path(__file__).parent / "fixtures/explicateur_depth"
        path = fixtures / "cv-raw-gemini-response.json"
        original = path.read_bytes()
        self.assertEqual(sha256(original).hexdigest(), "d284d7b2a907b53b3f0663943477bc0dd883fa05f9a3413d7cc45d6bbc8e083d")
        raw = json.loads(original)["candidates"][0]["content"]["parts"][0]["text"]
        self.assertEqual(raw.count("\x00"), 0)
        self.assertGreater(raw.count(r"\u0000"), 200)
        parsed = json.loads(raw)
        self.assertEqual([row["unit_id"] for row in parsed["units"]], [
            "68289b854590095af0381cf2", "60b3bff0f917644f30d42989", "c1d1bea95ce64f12e43d7776",
            "7c8d7c9c6d747737a13d2d67", "64f50c3294dcad6ee61bb205",
        ])
        pages = json.loads((fixtures / "cv-indexed-pages.json").read_bytes())
        units = build_unit_map("cv", pages)["units"]
        rows = chunk_pages([page["text"] for page in pages], positions=True)
        bind_chunks(units, rows)
        records = prepare_units(units, pages, rows, rows, source_hash="fixture")
        plan = build_learning_plan(units, "map", "Explique en détail sans rien omettre", records)
        selected = [u for u in units if plan["required_items"].get(u["logical_id"])]
        invoke = AsyncMock(return_value=SimpleNamespace(content=raw, response_metadata={}))
        metrics = explicateur._ExplainMetrics("cv-offline", call_budget=ExplainCallBudget(learning_limit=9))
        with patch.object(explicateur, "get_chat_llm", return_value=SimpleNamespace(ainvoke=invoke)):
            drafts = await explicateur._generate_course_units(
                {"model": "gemini-3.5-flash-lite", "provider": "google"}, metrics,
                explain_budget("google", "gemini-3.5-flash-lite"), selected, records,
                [row for u in selected for row in excerpt_rows(u, rows)], plan, units,
                "French", overview=True, continuity=[], prior_facts=[],
            )
        invoke.assert_awaited_once()
        self.assertEqual([d["logical_id"] for d in drafts], [row["unit_id"] for row in parsed["units"]])
        self.assertEqual(metrics.retrieval["systemic_generation_failure"], "provider_text_corruption")
        for draft, row in zip(drafts, parsed["units"]):
            self.assertEqual(draft["coverage"], "not_generated")
            self.assertIn("provider_text_corruption", draft["interruptions"])
            self.assertEqual(draft["dropped_block_counts"], {"provider_text_corruption": len(row["blocks"])})
            self.assertFalse(draft["blocks"])
        self.assertEqual(path.read_bytes(), original)

    async def test_number_one_maps_to_the_current_packet_for_facts_and_reviewable_items(self):
        value = "Précision : 0,46."
        statement = "Le seuil ajuste le filtrage des résultats peu fiables."
        source_text = value + "\n" + statement
        uid = "packet-scope"
        unit = {"logical_id": uid, "content_version": "v1", "title": "Filtrage", "kind": "exercise",
                "heading_path": [("exercise", "Filtrage", 1)], "start": [1, 0], "end": [1, len(source_text)]}
        ids = ["a" * 64, "b" * 64]
        anchors = [{"page": 1, "start": 0, "end": len(value), "quote": value},
                   {"page": 1, "start": len(value) + 1, "end": len(source_text), "quote": statement}]
        facts = [{"label_path": ["Précision"], "value": "0,46", "anchor": anchors[0]}]
        record = {"checklist": [
            {"item_id": ids[0], "anchors": [anchors[0]], "text": value, "facts": facts,
             "importance": "essential", "type": "numeric_result"},
            {"item_id": ids[1], "anchors": [anchors[1]], "text": statement, "facts": [],
             "importance": "essential", "type": "definition"},
        ]}
        plan = {"required_items": {uid: ids}, "level": "beginner", "depth": "standard"}
        packets = []

        async def dispatch(messages, _source_count):
            raw_packet = messages[-1].content
            self.assertTrue(all(item_id not in raw_packet for item_id in ids))
            item, = json.loads(raw_packet)["checklist"]
            self.assertEqual(item["id"], 1)
            packets.append(item["text"])
            text = value if item["text"] == value else "Ce réglage aide à écarter les résultats incertains."
            candidate = block("working", text, [1], provenance="derived", candidate_items=[1, 99])
            return json.dumps({"blocks": [candidate]}), ""

        output = await generate_unit(
            unit, record, [{"page_number": 1, "content": source_text}], plan, dispatch,
            fits=lambda messages: len(json.loads(messages[-1].content)["checklist"]) == 1,
            continuity={}, language="French", unit_map=[unit],
        )
        self.assertEqual(packets, [value, statement])
        self.assertEqual([f["value"] for f in output["verified_facts"]], ["0,46"])
        self.assertEqual(output["reviewable_items"], {ids[1]: [output["blocks"][1]["block_id"]]})
        self.assertIn("invalid_checklist_reference", output["interruptions"])

    async def test_multi_unit_pipeline_batches_generation_and_review_and_keeps_citations_local(self):
        units, rows, records = records_for([
            {"text": "Exercice 1: Practice\nQ1. First calculation?\nOne plus one equals two.\n"
                     "Q2. Second calculation?\nTwo plus two equals four.\nQ3. Third calculation?\n"
                     "Three plus three equals six.\nQ4. Fourth calculation?\nFour plus four equals eight."}
        ])
        selected = units[1:]
        plan = build_learning_plan(selected, "map", "Teach the questions", records)
        budget = explain_budget("google", "gemini-3.5-flash-lite")
        metrics = explicateur._ExplainMetrics("batch-test", call_budget=ExplainCallBudget(learning_limit=2))
        calls = []

        def model(**options):
            async def invoke(messages):
                payload = json.loads(messages[-1].content)
                calls.append(options["agent"])
                if options["agent"] == "explain_unit_generation":
                    self.assertIs(options["response_schema"], BATCH_SCHEMA)
                    self.assertLessEqual(options["max_completion_tokens"], budget.max_output_tokens)
                    generated = []
                    for index, entry in enumerate(payload["units"]):
                        if index == 2:
                            continue
                        source = entry["sources"][0]["quote"]
                        candidate = block("problem", source, [999 if index == 1 else 1])
                        generated.append({"unit_id": entry["unit_id"], "blocks": [candidate]})
                    response = {"units": generated}
                else:
                    self.assertEqual([entry["unit_id"] for entry in payload],
                                     [selected[index]["logical_id"] for index in (0, 3)])
                    response = {"reviews": [{"unit_id": entry["unit_id"], "pedagogy_score": 2, "findings": []}
                                            for entry in payload]}
                return SimpleNamespace(content=json.dumps(response), response_metadata={})
            return SimpleNamespace(ainvoke=invoke)

        excerpts = [row for unit in selected for row in excerpt_rows(unit, rows)]
        with patch.object(explicateur, "get_chat_llm", side_effect=model):
            result = await explicateur._generate_course_units(
                {"provider": "google", "model": "gemini-3.5-flash-lite"}, metrics, budget,
                selected, records, excerpts, plan, units, "English", overview=True, continuity=[], prior_facts=[],
            )
        self.assertEqual(calls, ["explain_unit_generation", "explain_unit_review"])
        self.assertEqual([draft["logical_id"] for draft in result], [unit["logical_id"] for unit in selected])
        self.assertTrue(result[0]["blocks"][0]["source_indexes"])
        self.assertEqual(result[0]["verification"], "reviewed")
        self.assertEqual(result[1]["coverage"], "not_generated")
        self.assertIn("invalid_marker", result[1]["interruptions"])
        self.assertIn("missing_batch_unit", result[2]["interruptions"])
        self.assertEqual(result[3]["verification"], "reviewed")

    def test_batch_planner_splits_when_output_estimate_will_not_fit(self):
        from dataclasses import replace
        units, rows, records = records_for([{"text": "Question 1: A substantive exercise\nPay attention to the input."}])
        unit = units[0]
        plan = build_learning_plan(units, "map", "Teach", records)
        packet = generation_packet(unit, records[unit["logical_id"]], excerpt_rows(unit, rows), plan, {}, "English")
        budget = replace(explain_budget("google", "gemini-3.5-flash-lite"), max_output_tokens=packet[2] * 2)
        size, messages, output, _ = plan_generation_batch([packet, packet, packet], budget)
        self.assertEqual(size, 2)
        self.assertEqual(len(json.loads(messages[-1].content)["units"]), 2)
        self.assertLessEqual(output, budget.max_output_tokens)
        self.assertIsNone(plan_generation_batch([packet, packet], budget, output_scale=1.25))

    async def test_batched_equations_are_verified_independently(self):
        units, rows, records = records_for([
            {"text": "II.1 Calculer la somme\n0,12 + 0,46 + 0,31 = 0,89"},
            {"text": "II.2 Calculer la différence\n0,89 − 0,46 = 0,43"},
        ])
        plan = build_learning_plan(units, "map", "Teach all arithmetic", records)
        corrupt = "0,12 + 0,46 − 0,31 = 0,89"
        correct = "0,89 − 0,46 = 0,43"
        ids = [unit["logical_id"] for unit in units]
        batch = unpack_generation_batch(json.dumps({"units": [
            {"unit_id": ids[0], "blocks": [block("result", corrupt, [1])]},
            {"unit_id": ids[1], "blocks": [block("result", correct, [1])]},
        ]}), ids)
        dispatch = AsyncMock()
        results = []
        for unit in units:
            uid = unit["logical_id"]
            results.append(await generate_unit(
                unit, records[uid], excerpt_rows(unit, rows), plan, dispatch, fits=lambda _: True,
                continuity={}, language="French", unit_map=units, batch_response=batch[uid],
            ))
        dispatch.assert_not_awaited()
        first, second = results
        self.assertIn("displayed_equation_mismatch", {f["code"] for f in first["findings"]})
        self.assertTrue(first["missing_item_ids"])
        self.assertNotIn("displayed_equation_mismatch", {f["code"] for f in second["findings"]})
        self.assertFalse(second["missing_item_ids"])
        self.assertEqual(second["sources"][0]["page"], 2)

    def test_gemini_schema_avoids_nested_array_constraint_expansion(self):
        original = json.dumps(SCHEMA, sort_keys=True)
        provider = gemini_response_schema(SCHEMA)
        self.assertIn('"maxItems"', original)
        self.assertNotIn('"maxItems"', json.dumps(provider))
        self.assertEqual(provider["required"], ["blocks"])
        self.assertEqual(provider["properties"]["blocks"]["items"], {"$ref": "#/$defs/DraftBlock"})
        self.assertEqual(provider["$defs"]["DraftBlock"]["required"], ["kind", "text", "provenance"])
        self.assertEqual(json.dumps(SCHEMA, sort_keys=True), original)
        draft_block = {"kind": "result", "text": "Example", "provenance": "derived"}
        with self.assertRaises(ValidationError):
            DraftUnit.model_validate({"blocks": [draft_block] * 17})
        with self.assertRaises(ValidationError):
            DraftUnit.model_validate({"blocks": [draft_block | {
                "claims": [{"start": 0, "end": 1, "source_indexes": list(range(13))}],
            }]})

    async def draft(self, unit, evidence, rows, units, dispatch, *, topic="Teach this unit", level="advanced"):
        plan = build_learning_plan(units, "map", topic, evidence, level=level)
        return await generate_unit(unit, evidence[unit["logical_id"]], excerpt_rows(unit, rows), plan, dispatch,
                                   fits=lambda _: True, continuity={"recent_units": ["Prior unit"]},
                                   language="French", unit_map=units)

    async def test_dense_exhaustive_unit_uses_two_calls_and_preserves_prefix_after_provider_failure(self):
        lines = [f"Source requirement number {n} is documented." for n in range(1, 17)]
        units, rows, evidence = records_for([{"text": "II.1 Source methods\n" + "\n".join(lines)}])
        unit = units[0]
        sent = []

        async def provider(messages, count):
            payload = json.loads(messages[-1].content)
            sent.append(payload)
            first = payload["sources"][0]
            content = block("explanation", first["quote"], [1])
            if len(sent) == 2:
                return '{"blocks":[' + json.dumps(content) + ',{"kind":', "provider_failure"
            return json.dumps({"blocks": [content]}), ""

        draft = await self.draft(unit, evidence, rows, units, provider,
                                 topic="Teach exhaustively without omitting anything", level="beginner")
        self.assertEqual(len(sent), 2)
        self.assertEqual({p["level"] for p in sent}, {"beginner"})
        self.assertEqual({p["depth"] for p in sent}, {"exhaustive"})
        self.assertEqual(sum(len(p["checklist"]) for p in sent), 16)
        self.assertEqual(len(draft["blocks"]), 2)
        self.assertEqual(draft["coverage"], "partial")
        self.assertIn("truncated", draft["interruptions"])
        self.assertTrue(draft["missing_item_ids"])

    async def test_call_budget_exhaustion_preserves_first_packet(self):
        units, rows, evidence = records_for([{"text": "II.1 Context\n" + "\n".join(
            f"Documented finding number {n} needs an explanation." for n in range(24))}])
        budget = ExplainCallBudget(learning_limit=1)
        async def provider(messages, count):
            budget.reserve("learning", "generate")
            source = json.loads(messages[-1].content)["sources"][0]["quote"]
            return json.dumps({"blocks": [block("explanation", source, [1])]}), ""
        draft = await self.draft(units[0], evidence, rows, units, provider,
                                 topic="Teach exhaustively without omitting anything")
        self.assertEqual(budget.summary()["learning"]["used"], 1)
        self.assertEqual(len(draft["blocks"]), 1)
        self.assertIn("call_budget", draft["interruptions"])

    async def test_missing_visual_values_are_unverified_not_promoted(self):
        units, rows, evidence = records_for([{"text": "III.3 Performance ou interprétabilité ?\nComparer les mesures sur le même jeu de test."}])
        uid = units[0]["logical_id"]
        evidence[uid]["unresolved"] = [{"page": 1, "kind": "table", "status": "unverifiable_source"}]
        evidence[uid]["figures"] = [{"page": 1, "vision_observation": {"value": "0,9999"}}]

        async def provider(messages, count):
            self.assertNotIn("0,9999", messages[-1].content)
            return json.dumps({"blocks": [block("criteria", "Comparer les mesures sur le même jeu de test.", [1]),
                                          block("table", "Le F1 vaut 0,9999.", [1])]}), ""

        draft = await self.draft(units[0], evidence, rows, units, provider)
        self.assertEqual(draft["blocks"][1]["provenance"], "unverified")
        self.assertFalse(draft["blocks"][1]["source_indexes"])
        self.assertEqual(draft["coverage"], "partial")
        self.assertFalse(draft["verified_facts"])
        self.assertEqual(draft["unverifiable_source"][0]["kind"], "table")
        card = legacy_projection([draft], excerpt_rows(units[0], rows), "document", "French")
        self.assertEqual(card["schema_version"], 2)
        self.assertTrue(card["sections"][0]["citations"])
        self.assertIn("Non vérifié", card["sections"][1]["content"])

    async def test_summary_sends_essential_items_and_scope_without_extra_call(self):
        units, rows, evidence = records_for([{"text": "II.1 Model comparison\nThe model compares the results.\nThere were 12 trials."}])
        unit = units[0]
        plan = build_learning_plan(units, "map", "Summarize", evidence, level="advanced", summary=True)
        async def provider(messages, count):
            payload = json.loads(messages[-1].content)
            self.assertEqual((payload["depth"], payload["level"]), ("summary", "advanced"))
            self.assertTrue(all(item["importance"] == "essential" for item in payload["checklist"]))
            self.assertNotIn("12 trials", messages[-1].content)
            return '{"blocks":[]}', ""
        dispatch = AsyncMock(side_effect=provider)
        await generate_unit(unit, evidence[unit["logical_id"]], excerpt_rows(unit, rows), plan, dispatch,
                            fits=lambda _: True, continuity={}, language="English", unit_map=units)
        dispatch.assert_awaited_once()

    async def test_actual_course_unit_prompts_and_shapley_recomputation(self):
        path = os.getenv("SOCRA_EXPLAINABILITY_FIXTURE")
        if not path:
            self.skipTest("SOCRA_EXPLAINABILITY_FIXTURE unavailable")
        pages = await extract_pages(Path(path).read_bytes(), layout=True, evidence=True)
        units, rows, evidence = records_for(pages)
        targets = {u["start"][0]: u for u in units if u["start"][0] in {12, 14, 16, 19, 26}}
        for page, keyword in [(12, "permutation"), (14, "fuite"), (16, "0,46"), (19, "Pondérer"), (26, "source_gaps")]:
            with self.subTest(page=page):
                async def provider(messages, count):
                    payload = json.loads(messages[-1].content)
                    self.assertIn(keyword, messages[-1].content)
                    self.assertTrue(all(src["page"] in range(targets[page]["start"][0], targets[page]["end"][0] + 1)
                                        for src in payload["sources"]))
                    if page != 16:
                        first = payload["sources"][0]
                        return json.dumps({"blocks": [block(payload["required_blocks"][0], first["quote"], [1])]}), ""
                    steps = []
                    for key, expression, value in [
                        ("= 0,43", "0.55-0.12", "0,43"), ("= 0,34", "0.89-0.55", "0,34"),
                        ("= 0,28", "0.40-0.12", "0,28"), ("= 0,49", "0.89-0.40", "0,49"),
                        ("φ(montant) =", "(0.43+0.49)/2", "0,46"),
                        ("φ(nuit) =", "(0.34+0.28)/2", "0,31"),
                        ("0,12 + 0,46 + 0,31", "0.12+0.46+0.31", "0,89"),
                    ]:
                        source = next(src for src in payload["sources"] if key in src["quote"])
                        steps.append(block("result" if value == "0,89" else "substitution", source["quote"],
                                           [source["index"]], provenance="derived",
                                           calculation={"expression": expression, "expected": value}))
                    return json.dumps({"blocks": steps}), ""
                mock = AsyncMock(side_effect=provider)
                draft = await self.draft(targets[page], evidence, rows, units, mock)
                mock.assert_awaited_once()
                self.assertTrue(draft["blocks"])
                if page == 16:
                    codes = {f["code"] for f in draft["findings"]}
                    self.assertNotIn("calculation_mismatch", codes)
                    self.assertNotIn("missing_calculation", codes)
                    self.assertEqual(len(draft["blocks"]), 7)
                    self.assertTrue(all(block["provenance"] == "derived" for block in draft["blocks"]))
                    self.assertEqual([fact["value"] for fact in draft["verified_facts"]], ["0,89"])

    async def test_dependent_exercises_keep_distinct_subquestions_and_scope(self):
        path = Path(__file__).parent / "fixtures/explicateur_depth/dependent_exercise_sheet.txt"
        units, rows, evidence = records_for([{"text": path.read_text(encoding="utf-8")}])
        plan = build_learning_plan(units, "map", "Solve exercise 2", evidence, requested_exercises=("2",))
        by_id = {unit["logical_id"]: unit for unit in units}
        selected = [by_id[uid] for uid in plan["order"]]
        self.assertEqual([unit["label"] for unit in selected], ["Exercice 2", "(a)", "(b)"])
        unit = selected[1]
        self.assertTrue(evidence[unit["logical_id"]]["depends_on"])

        async def provider(messages, count):
            payload = json.loads(messages[-1].content)
            self.assertIn("Exercice 1(b)".casefold(), messages[-1].content.casefold())
            self.assertIn("verification", " ".join(payload["teaching_rules"]))
            self.assertNotIn("checkpoint", " ".join(payload["teaching_rules"]))
            self.assertIn("final_answer", payload["required_blocks"])
            return json.dumps({"blocks": [block("problem", payload["sources"][0]["quote"], [1])]}), ""

        mock = AsyncMock(side_effect=provider)
        draft = await self.draft(unit, evidence, rows, units, mock)
        mock.assert_awaited_once()
        self.assertTrue(draft["blocks"])
        self.assertEqual(draft["coverage"], "partial")

    async def test_actual_knime_lab_supplies_steps_and_checkpoint_contract(self):
        path = os.getenv("SOCRA_ORANGE_KNIME_FIXTURE")
        if not path:
            self.skipTest("SOCRA_ORANGE_KNIME_FIXTURE unavailable")
        pages = await extract_pages(Path(path).read_bytes(), layout=True, evidence=True)
        units, rows, evidence = records_for(pages)
        unit = next(unit for unit in units if unit["kind"] == "lab_step"
                    and any("knime" in item["text"].casefold() for item in evidence[unit["logical_id"]]["checklist"]))

        async def provider(messages, count):
            payload = json.loads(messages[-1].content)
            self.assertIn("expected_result", payload["required_blocks"])
            self.assertIn("checkpoint", payload["required_blocks"])
            self.assertTrue(any(item["type"] == "command" for item in payload["checklist"]))
            return json.dumps({"blocks": [block("action", payload["sources"][0]["quote"], [1])]}), ""

        mock = AsyncMock(side_effect=provider)
        draft = await self.draft(unit, evidence, rows, units, mock)
        self.assertTrue(draft["blocks"])
        mock.assert_awaited_once()

    async def test_stream_error_keeps_completed_v2_block_under_shared_dispatch_budget(self):
        units, rows, evidence = records_for([{"text": "II.1 Source methods\nA concrete source statement needs explanation."}])
        unit = units[0]
        plan = build_learning_plan(units, "map", "Teach the course", evidence)
        preview = AsyncMock()
        metrics = explicateur._ExplainMetrics("test", call_budget=ExplainCallBudget(learning_limit=1))

        async def stream(messages):
            source = json.loads(messages[-1].content)["sources"][0]["quote"]
            draft = block("explanation", source, [1])
            yield SimpleNamespace(content='{"blocks":[' + json.dumps(draft) + ",", response_metadata={})
            raise ConnectionError("synthetic interrupted provider stream")

        with patch.object(explicateur, "get_chat_llm", return_value=SimpleNamespace(astream=stream)) as model:
            drafts = await explicateur._generate_course_units(
                {"preview": preview, "model": "gemini-3.5-flash-lite", "provider": "google"},
                metrics, explain_budget("google", "gemini-3.5-flash-lite"),
                units, evidence, excerpt_rows(unit, rows), plan, units, "English",
                overview=True, continuity=[], prior_facts=[],
            )
        self.assertEqual(metrics.call_budget.summary()["learning"]["used"], 1)
        self.assertTrue(model.call_args.kwargs["single_attempt"])
        self.assertEqual(len(drafts[0]["blocks"]), 1)
        self.assertIn("provider_failure", drafts[0]["interruptions"])
        self.assertIn("Provisional", preview.await_args.args[0])

    async def test_flagged_prepared_course_uses_unit_schema_and_legacy_projection(self):
        units, rows, evidence = records_for([{"text": "II.1 Source methods\nA concrete source statement needs explanation."}])
        identifier = str(uuid4())
        rows = [row | {"id": str(uuid4()), "document_id": identifier, "similarity": 0.0} for row in rows]
        document = {"id": identifier, "filename": "Course.pdf", "page_count": 1, "index_generation": 1}

        async def invoke(messages):
            payload = json.loads(messages[-1].content)
            if isinstance(payload, list):
                reviewed = {"reviews": [{"unit_id": payload[0]["unit_id"], "pedagogy_score": 2, "findings": []}]}
                return SimpleNamespace(content=json.dumps(reviewed), response_metadata={})
            source = payload["sources"][0]["quote"]
            return SimpleNamespace(content=json.dumps({"blocks": [block("explanation", source, [1])]}),
                                   response_metadata={})

        mock = AsyncMock(side_effect=invoke)
        with patch.dict(os.environ, {"EXPLAIN_UNIT_PIPELINE": "true", "EXPLAIN_INTENT_PLANS": "true",
                                     "SOCRA_EXPLAIN_UNIT_MAX_LEARNING_CALLS": "2"}), \
             patch.object(explicateur, "retrieve_summary_guided_chunks", AsyncMock(return_value=rows)), \
             patch.object(explicateur, "course_documents", AsyncMock(return_value=[document])), \
             patch.object(explicateur, "document_inventory_chunks", AsyncMock(return_value=(rows, "full_document"))), \
             patch.object(explicateur, "load_or_queue_unit_map", AsyncMock(return_value={"text_hash": "map", "units": units})), \
             patch.object(explicateur, "load_prepared_evidence", AsyncMock(return_value=evidence)), \
             patch.object(explicateur, "queue_unit_evidence", AsyncMock()), \
             patch.object(explicateur, "get_chat_llm", return_value=SimpleNamespace(ainvoke=mock)):
            returned = await explicateur.run_explicateur({
                "course_id": "course", "user_id": "owner", "explain_document_id": identifier,
                "student_message": "Teach me the entire course, all chapters in order.",
                "model": "gemini-3.5-flash-lite", "provider": "google", "request_id": str(uuid4()),
            })
        self.assertEqual(mock.await_count, 2)
        card = returned["explanation"]
        self.assertEqual(card["schema_version"], 2)
        self.assertEqual(card["sections"][0]["citations"][0]["page_number"], 1)
        self.assertEqual(card["units"][0]["logical_id"], units[0]["logical_id"])
        self.assertEqual(card["units"][0]["verification"], "reviewed")
        self.assertEqual(card["course_progress"]["sections"][0]["status"], "partial")
