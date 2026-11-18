from copy import deepcopy
import unittest

from agents.explain_verifier import Anchor, Block, Claim
from rag.explain_checklist import lab_transition, page_furniture
from rag.explain_preparation import prepare_units, verify_prepared_unit
from tests.run_explain_scorecard import load_spark_fixture, prepare_spark
from worker import chunk_pages


def positioned_page(rows):
    lines, runs, offset = [], [], 0
    for text, baseline, size in rows:
        lines.append(text)
        runs.append([offset, baseline, size, "font"])
        offset += len(text.encode("utf-16-le")) // 2 + 1
    return {"text": "\n".join(lines), "height": 800, "runs": runs}


def step(pages):
    return {"logical_id": "lab", "content_version": "source-version", "heading_path": [("étape 0", "", 1)],
            "label": "Étape 0", "title": "Atelier", "kind": "lab_step",
            "start": [1, 0], "end": [len(pages), len(pages[-1]["text"])]}


def prepare(pages, unit):
    texts = [page["text"] for page in pages]
    return prepare_units([unit], pages, chunk_pages(texts, positions=True), chunk_pages(texts),
                         source_hash="fixture")[unit["logical_id"]]


class ChecklistFilteringTests(unittest.TestCase):
    def test_original_character_offsets_after_multiple_exclusions_and_across_pages(self):
        header, footer, quote = "Atelier des données · Département", "Licence informatique · Département", "Répéter la mesure étalon."
        first = positioned_page([("Résumé 🧪 initial.", 700, 11), (header, 765, 8), (quote, 635, 11), (footer, 36, 8)])
        second = positioned_page([(header, 765, 8), (footer, 36, 8), (quote, 635, 11),
                                  ("Une procédure détaillée explique", 610, 11), ("comment vérifier l’étalon.", 590, 11)])
        third = positioned_page([("Rappel sur le calcul.", 700, 11), (header, 640, 11)])
        pages = [first, second, third]
        original = deepcopy(pages)
        unit = step(pages)
        record = prepare(pages, unit)
        self.assertEqual(pages, original)
        self.assertEqual([(row["reason"], row["anchors"][0]["page"]) for row in record["checklist_exclusions"]],
                         [("running_header", 1), ("running_footer", 1), ("running_header", 2), ("running_footer", 2)])
        for row in record["checklist"] + record["checklist_exclusions"]:
            for source in row["anchors"]:
                self.assertEqual(original[source["page"] - 1]["text"][source["start"]:source["end"]], source["quote"])
        repeated = next(row for row in record["checklist"] if row["text"] == quote)
        self.assertEqual([(a["page"], a["start"]) for a in repeated["anchors"]],
                         [(1, first["text"].index(quote)), (2, second["text"].index(quote))])
        self.assertIn({"page": 3, "start": third["text"].index(header), "end": len(third["text"]), "quote": header},
                      [a for row in record["checklist"] for a in row["anchors"]])
        multiline = "Une procédure détaillée explique\ncomment vérifier l’étalon."
        self.assertTrue(any(a["quote"] == multiline for row in record["checklist"] for a in row["anchors"]))

        source_anchors = [Anchor(**a) for a in repeated["anchors"]]
        additional = "Remarque générale"
        blocks = [Block("derived", "action", quote, "derived", (Claim(0, len(quote), (2,)),)),
                  Block("supplementary", "checkpoint", additional, "supplementary")]
        findings = verify_prepared_unit(unit, blocks, record,
            pages={i: page["text"] for i, page in enumerate(original, 1)}, sources=source_anchors)
        self.assertEqual(blocks[1].claims, ())
        self.assertFalse([f for f in findings if f.severity in {"source", "authoritative"}])

    def test_sequential_page_numbers_are_audited_without_removing_bottom_instructions(self):
        instruction = "Rendre le notebook corrigé"
        pages = [positioned_page([("Corps du document", 500, 11), (instruction, 48, 9),
                                  (f"Page {number} / 2", 28, 8)]) for number in (1, 2)]
        record = prepare(pages, step(pages))
        self.assertEqual([e["reason"] for e in record["checklist_exclusions"]], ["page_number", "page_number"])
        self.assertEqual([e["text"] for e in record["checklist_exclusions"]], ["Page 1 / 2", "Page 2 / 2"])
        accepted = next(row for row in record["checklist"] if row["text"] == instruction)
        self.assertEqual([a["page"] for a in accepted["anchors"]], [1, 2])
        # Even at the outermost margin, a recurring instruction isn't document metadata.
        for required_text in (instruction, "Le rapport doit présenter les deux mesures"):
            pages = [positioned_page([("Corps du document", 500, 11), (required_text, 20, 9)]) for _ in range(2)]
            self.assertFalse(page_furniture(pages, set()))
            self.assertIn(required_text, [r["text"] for r in prepare(pages, step(pages))["checklist"]])

    def test_uncertain_or_body_only_repetition_stays_in_scope(self):
        title = "Lire le résultat intermédiaire"
        pages = [positioned_page([(title, 610, 12), ("Application à un exemple", 500, 10),
                                  ("Mention unique au bas de la deuxième page", 32, 9)]),
                 {"text": title + "\nAutre application sans géométrie"}]
        record = prepare(pages, step(pages))
        self.assertEqual(record["checklist_exclusions"], [])
        self.assertIn("Mention unique au bas de la deuxième page", [row["text"] for row in record["checklist"]])
        self.assertEqual([a["page"] for row in record["checklist"] if row["text"] == title for a in row["anchors"]],
                         [1, 2])
        pages = [positioned_page([(title, 765, 11), ("Application à un exemple", 580, 11)]) for _ in range(2)]
        self.assertFalse(page_furniture(pages, set()))

    def test_numbered_institutional_footer_requires_a_recurring_template(self):
        label = "Département des données · Analyse"
        pages = [positioned_page([("Protocole expérimental", 530, 11), (f"{label} {number}", 18, 8)])
                 for number in (1, 2)]
        exclusions = prepare(pages, step(pages))["checklist_exclusions"]
        self.assertEqual([(row["text"], row["reason"]) for row in exclusions],
                         [(f"{label} 1", "running_footer"), (f"{label} 2", "running_footer")])
        self.assertTrue(all(row["detection"]["matching_pages"] == [1, 2] for row in exclusions))

    def test_part_title_with_a_required_operation_stays_in_scope(self):
        first = positioned_page([("Instructions initiales", 700, 11)])
        for title in ("PARTIE 1 – Rendre le tableau et justifier le résultat",
                      "PARTIE 1 – Classification de données puis produire un tableau"):
            with self.subTest(title=title):
                second = positioned_page([(title, 730, 16), ("Étape 1 – Mesures", 680, 12),
                                          ("Mesures suivantes", 620, 11)])
                pages = [first, second]
                unit = step(pages) | {"end": [2, len(title) + 1]}
                following = step(pages) | {"start": unit["end"], "logical_id": "next"}
                texts = [p["text"] for p in pages]
                self.assertIsNone(lab_transition(unit, following, pages))
                record = prepare_units([unit, following], pages, chunk_pages(texts, positions=True), chunk_pages(texts),
                                       source_hash="fixture")["lab"]
                self.assertIn(title, [row["text"] for row in record["checklist"]])

    def test_objective_requires_complete_support_and_no_new_obligation(self):
        annotation, pages, indexed = load_spark_fixture()
        scope = annotation["units"][0]
        for before, after in [
            ("spark.version)", "spark.feature)"),
            ("vérifier la version utilisée.", "vérifier la version utilisée et enregistrer son numéro."),
        ]:
            with self.subTest(before=before):
                altered_pages = deepcopy(pages)
                altered_indexed = indexed.copy()
                altered_pages[0]["text"] = altered_pages[0]["text"].replace(before, after, 1)
                altered_indexed[0] = altered_indexed[0].replace(before, after, 1)
                # The longer synthetic line invalidates its later PDF.js offsets.
                if len(before) != len(after):
                    altered_pages[0].pop("runs")
                    altered_pages[0].pop("evidence")
                _, _, records, _, _ = prepare_spark(annotation, altered_pages, altered_indexed)
                record = records[scope["unit_id"]]
                self.assertNotIn("redundant_objective", {row["reason"] for row in record["checklist_exclusions"]})
                self.assertTrue(any(row["text"].startswith("Objectif : démarrer") for row in record["checklist"]))
