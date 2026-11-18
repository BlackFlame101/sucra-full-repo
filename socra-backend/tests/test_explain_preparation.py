from hashlib import sha256
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.explain_verifier import Anchor
from rag.explain_preparation import VisionBudget, prepare_units, resolve_visuals, validate_dependencies, verify_prepared_unit
from rag.unit_map import build_unit_map
from rag.explain_vision import configured_visual_services
from worker import chunk_pages, extract_pages
import worker


def prepare(pages, *, indexed_override=None):
    skeleton = build_unit_map("fixture", pages)
    chunks = chunk_pages([page["text"] for page in pages], positions=True)
    indexed = chunks if indexed_override is None else indexed_override
    return skeleton, prepare_units(skeleton["units"], pages, chunks, indexed, source_hash="fixture")


class PreparationTests(unittest.TestCase):
    def test_exercise_checklist_identity_and_source_validation(self):
        text = (Path(__file__).parent / "fixtures/explicateur_depth/dependent_exercise_sheet.txt").read_text(encoding="utf-8")
        pages = [{"text": text}]
        skeleton, records = prepare(pages)
        self.assertEqual(records, prepare(pages)[1])
        exercises = [records[unit["logical_id"]] for unit in skeleton["units"] if unit["kind"] == "exercise"]
        self.assertEqual(len(exercises), 8)
        self.assertTrue(any(item["type"] == "question" for record in exercises for item in record["checklist"]))
        # Exercise 2(a) explicitly uses the result of Exercise 1(b).
        self.assertEqual(exercises[5]["depends_on"], [exercises[2]["unit_id"]])
        for record in exercises:
            for item in record["checklist"]:
                for anchor in item["anchors"]:
                    self.assertEqual(text[anchor["start"]:anchor["end"]], anchor["quote"])
        _, unresolved = prepare(pages, indexed_override=[])
        self.assertTrue(any(record["unresolved"] for record in unresolved.values()))
        self.assertFalse(any(record["checklist"] for record in unresolved.values()))

    def test_prerequisites_use_explicit_source_and_reject_bad_edges(self):
        text = ["II.1 Data foundations\nDefinitions and context.",
                "II.2 Apply the method\nPrérequis : basic algebra\nVoir II.1 pour les données.\nVoir II.9 pour les cas limites."]
        skeleton, records = prepare([{"text": value} for value in text])
        first, second = [unit["logical_id"] for unit in skeleton["units"]]
        self.assertEqual(records[second]["depends_on"], [first])
        self.assertEqual(records[second]["external_prereqs"], ["basic algebra"])
        self.assertIn("II.9", [item.get("label") for item in records[second]["unresolved"]])
        records[first]["depends_on"] = [second, "missing"]
        validate_dependencies(records, {first, second})
        self.assertEqual(records[first]["depends_on"], [second])
        self.assertEqual(records[second]["depends_on"], [])

    def test_indexed_evidence_feeds_phase_two_verifier(self):
        text = "II.3 Calculer la contribution\nφ(montant) = (0,43 + 0,49) / 2 = 0,46"
        skeleton, records = prepare([{"text": text}])
        unit = skeleton["units"][0]
        record = records[unit["logical_id"]]
        findings = verify_prepared_unit(unit, [], record, pages={1: text}, sources=(Anchor(1, 0, len(text)),))
        self.assertTrue(any(f.code == "missing_calculation" for f in findings))
        self.assertTrue(any(f.code == "missing_item" and f.item_id for f in findings))
        self.assertTrue(any(formula["text"].endswith("0,46") for formula in record["math"]))


class VisualTests(unittest.IsolatedAsyncioTestCase):
    async def test_configured_vision_renders_only_pinned_page_and_disables_provider_retries(self):
        data = b"pinned PDF fixture"
        env = {"SOCRA_EXPLAIN_VISION_API_KEY": "offline-fixture",
               "SOCRA_EXPLAIN_VISION_DOCUMENT_SHA256": sha256(data).hexdigest()}
        invocation = AsyncMock(return_value=SimpleNamespace(content='{"table":{"columns":["Model","F1"],"rows":[["A","0,8"]]}}'))
        with patch.dict(os.environ, env), \
             patch("rag.explain_vision.render_pdf_region", return_value=b"PNG") as renderer, \
             patch("rag.explain_vision.get_chat_llm", return_value=SimpleNamespace(ainvoke=invocation)) as client:
            render, describe, _, budget = configured_visual_services()
            asset = {"page": 26, "bbox": [0, 0, 100, 100]}
            self.assertEqual(await render(data, asset | {"page": 25}), b"")
            self.assertEqual(await render(b"wrong document", asset), b"")
            self.assertEqual(await render(data, asset), b"PNG")
            renderer.assert_called_once_with(data, asset)
            self.assertEqual((await describe(b"PNG"))["table"]["rows"], [["A", "0,8"]])
            self.assertEqual(budget.limit, 1)
            self.assertTrue(client.call_args.kwargs["single_attempt"])
            invocation.assert_awaited_once()

    async def test_visually_read_table_keeps_all_five_rows_out_of_indexed_facts(self):
        figure = {"figure_id": "comparison-image", "page": 26, "confidence": "unresolved",
                  "asset": {"page": 26, "bbox": [40, 122, 587, 425]}}
        record = {"unit_id": "comparison", "figures": [figure], "checklist": [],
                  "unresolved": [{"id": "comparison-image", "kind": "table_or_figure", "page": 26,
                                  "status": "unverifiable_source"}]}
        rows = [["Forêt aléatoire", "0,8669"], ["Logistique brute", "0,7407"],
                ["Logistique log", "0,8593"], ["Arbre profondeur 3", "0,5737"],
                ["Arbre sans limite", "0,7556"]]
        vision = AsyncMock(return_value={"table": {"columns": ["Modèle", "F1"], "rows": rows}})
        used = await resolve_visuals({"comparison": record}, AsyncMock(return_value=b"fixture crop"),
                                     vision, {}, budget=VisionBudget(limit=1))
        self.assertEqual(used, 1)
        self.assertEqual(figure["vision_observation"]["table"]["rows"], rows)
        self.assertEqual(figure["confidence"], "vision_unconfirmed")
        self.assertEqual(record["checklist"], [])

    async def test_unreadable_math_routes_to_optional_visual_extraction(self):
        text = "II.3 Calculer à la main\nφ(montant) = � = 0,46"
        _, records = prepare([{"text": text}])
        record = next(iter(records.values()))
        missing, = [item for item in record["unresolved"] if item["kind"] == "math"]
        vision = AsyncMock(return_value={"plain": "φ(montant) = 0,46", "latex": r"\phi(m)=0.46"})
        await resolve_visuals(records, AsyncMock(return_value=b"formula crop"), vision, {}, budget=VisionBudget(limit=1))
        self.assertEqual(missing["vision_observation"]["plain"], "φ(montant) = 0,46")
        self.assertEqual(record["math"], [])

    async def test_vision_disabled_cache_limits_and_approximate_values(self):
        def records():
            return {str(i): {"unit_id": str(i), "unresolved": [], "figures": [
                {"figure_id": f"{i}-{j}", "page": i, "confidence": "unresolved", "asset": {"page": i, "bbox": [j]}}
                for j in range(5)]} for i in range(5)}
        render = AsyncMock(side_effect=lambda asset: repr(asset).encode())
        vision = AsyncMock(return_value={"title": "Chart", "key_values": [
            {"label": "Printed", "value": "0,46", "printed": True}, {"label": "Read", "value": "0,45"}]})
        cache = {}
        budget = VisionBudget()
        self.assertEqual(await resolve_visuals(records(), render, None, cache, budget=budget), 0)
        render.assert_not_awaited()
        prepared = records()
        self.assertEqual(await resolve_visuals(prepared, render, vision, cache, budget=budget), 12)
        self.assertEqual(vision.await_count, 12)
        values = prepared["0"]["figures"][0]["vision_observation"]["key_values"]
        self.assertEqual([value["approximate"] for value in values], [False, True])
        self.assertEqual(sum(f["confidence"] == "vision_unconfirmed" for f in prepared["0"]["figures"]), 3)
        await resolve_visuals({"0": prepared["0"]}, render, vision, cache, budget=budget)
        self.assertEqual(vision.await_count, 12)
        repeated = records()
        self.assertEqual(await resolve_visuals({"0": repeated["0"]}, render, vision, cache,
                                               budget=VisionBudget(limit=1)), 1)
        self.assertEqual(vision.await_count, 13)

    async def test_worker_checkpoints_only_claimed_units(self):
        data = b"synthetic PDF fixture"
        digest = sha256(data).hexdigest()
        pages = [{"text": "II.1 Source examples\nA measurable source statement."},
                 {"text": "II.2 Procedure\nA second indexed source statement."}]
        skeleton = build_unit_map("doc", pages)
        unit = skeleton["units"][1]
        job = {"id": 1, "lease_token": "test-lease", "document_id": "doc", "generation": 1,
               "source_hash": digest, "unit_id": unit["logical_id"], "content_version": unit["content_version"]}
        client = MagicMock()
        docs, maps = MagicMock(), MagicMock()
        client.table.side_effect = {"documents": docs, "explain_unit_maps": maps}.__getitem__
        for query, result in [(docs, {"id": "doc", "course_id": "course", "courses": {"user_id": "owner"}}),
                              (maps, {"units": skeleton["units"]})]:
            query.select.return_value = query
            query.eq.return_value = query
            query.single.return_value = query
            query.execute.return_value = SimpleNamespace(data=result)
        indexed = chunk_pages([page["text"] for page in pages])
        with patch.object(worker, "get_supabase", return_value=client), \
             patch.object(worker, "download_document", AsyncMock(return_value=data)), \
             patch.object(worker, "extract_pages", AsyncMock(return_value=pages)), \
             patch.object(worker, "document_inventory_chunks", AsyncMock(return_value=(indexed, "full_document"))), \
             patch.object(worker, "job_rpc", AsyncMock(return_value=True)) as rpc:
            await worker.prepare_claimed_batch([job])
        heartbeat, finish = rpc.await_args_list
        self.assertIsNone(heartbeat.kwargs["evidence"])
        self.assertEqual(finish.kwargs["evidence"]["unit_id"], job["unit_id"])
        self.assertTrue(finish.kwargs["evidence"]["checklist"])


class RealPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def extracted(self, variable):
        path = os.environ.get(variable)
        if not path:
            self.skipTest(f"{variable} was not supplied")
        pdf = Path(path).expanduser().read_bytes()
        pages = await extract_pages(pdf, layout=True, evidence=True)
        baseline = await extract_pages(pdf, layout=True)
        unit_map = build_unit_map("fixture", baseline)
        skeleton = build_unit_map("fixture", pages)
        self.assertEqual(unit_map, skeleton)
        text = [page["text"] for page in pages]
        evidence = prepare_units(skeleton["units"], pages, chunk_pages(text, positions=True),
                                 chunk_pages(await extract_pages(pdf)), source_hash=sha256(pdf).hexdigest())
        return pages, evidence

    async def test_explainability_pdf_sensitive_pages(self):
        pages, records = await self.extracted("SOCRA_EXPLAINABILITY_FIXTURE")
        self.assertEqual(len(pages), 35)
        self.assertEqual(len(records), 33)
        figures = [item for record in records.values() for item in record["figures"]]
        math = [item for record in records.values() for item in record["math"]]
        tables = [item for record in records.values() for item in record["tables"]]
        self.assertTrue(any(item["anchor"]["page"] == 16 and "0,46" in item["text"] for item in math))
        sampled = {page: [item for record in records.values() for item in record["checklist"]
                          if item["anchors"][0]["page"] == page] for page in (16, 17, 18, 19, 26)}
        calculation, = [item for item in sampled[16] if item["type"] == "worked_calc"
                        and "φ(montant)" in item["text"]]
        self.assertIn("φ(nuit)", calculation["text"])
        self.assertIn("0,12 + 0,46 + 0,31 = 0,89", calculation["text"])
        self.assertGreaterEqual(len(calculation["anchors"]), 7)
        self.assertFalse(any(item["text"] in {"montant seul 0,55", "Comment lire", "Comment choisir"}
                             for items in sampled.values() for item in items))
        for value in ("0,116", "0,924"):
            self.assertTrue(any(value in item["text"] and item["importance"] == "essential" for item in sampled[17]))
        self.assertLess(sum(map(len, sampled.values())), 76)
        print("Phase 3 audited checklist by page:", {page: len(items) for page, items in sampled.items()})
        coalition_table, = [record for record in tables if record["page"] == 16]
        self.assertEqual([(row[0]["text"], row[1]["text"]) for row in coalition_table["rows"]],
                         [("aucune (moyenne du modèle)", "0,12"), ("montant seul", "0,55"),
                          ("nuit seule", "0,40"), ("montant et nuit", "0,89")])
        for page in (17, 18, 19, 25, 26):
            self.assertTrue(any(item["page"] == page and item["asset"]["bbox"] for item in figures), page)
        commands = [item["text"] for record in records.values() for item in record["checklist"]
                    if item["type"] == "command" and item["anchors"][0]["page"] == 19]
        self.assertTrue(all(any(line.startswith(word) for line in commands)
                            for word in ("Perturber", "Prédire", "Pondérer", "Ajuster", "Lire")))
        tree_table, = [record for record in tables if record["page"] == 25]
        self.assertEqual(tree_table["columns"], ["Profondeur", "Feuilles", "F1 test"])
        self.assertEqual([(row[0]["text"], row[2]["text"]) for row in tree_table["rows"]],
                         [("2", "0,2293"), ("3", "0,5737"), ("4", "0,6063"),
                          ("6", "0,7510"), ("sans limite", "0,7556")])
        self.assertFalse(any(item["page"] == 26 for item in tables))
        self.assertTrue(any(item.get("page") == 26 and item["kind"] == "table_or_figure"
                            for record in records.values() for item in record["unresolved"]))
        print("Phase 3 course:", _totals(records))

    async def test_orange_knime_pdf_retains_procedures_and_figures(self):
        pages, records = await self.extracted("SOCRA_ORANGE_KNIME_FIXTURE")
        self.assertEqual(len(pages), 15)
        items = [item for record in records.values() for item in record["checklist"]]
        self.assertTrue(any("Orange" in item["text"] and item["type"] == "command" for item in items))
        self.assertTrue(any("KNIME" in item["text"] for item in items))
        self.assertTrue(any(record["figures"] for record in records.values()))
        print("Phase 3 Orange/KNIME:", _totals(records))


def _totals(records):
    return {key: sum(len(record[key]) for record in records.values())
            for key in ("checklist", "tables", "figures", "math", "unresolved", "depends_on")}
