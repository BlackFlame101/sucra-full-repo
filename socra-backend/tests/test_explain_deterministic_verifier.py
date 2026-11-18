import json
from pathlib import Path
import unittest

from agents.explain_arithmetic import arithmetic, displayed_equations, numeric_array
from agents.explain_verifier import (
    Anchor, Block, Calculation, ChecklistItem, Claim, Fact, decimal_value, verify_unit,
)


def unit(kind, page, source, identifier="unit"):
    return {"kind": kind, "logical_id": identifier, "start": [page, 0], "end": [page, len(source)]}


def evidence(page, text):
    return Anchor(page, 0, len(text), text)


def block(text, kind="explanation", provenance="course", *, indexes=(1,), **fields):
    return Block("block", kind, text, provenance, (Claim(0, len(text), indexes),), **fields)


class ArithmeticTests(unittest.TestCase):
    def test_whitelisted_operations(self):
        self.assertEqual(arithmetic("round((sqrt(16) + abs(-2)) ** 2 / 3, 2)"), 12)
        self.assertEqual(arithmetic("max(3, 5) // 2 + min(7, 3) % 2"), 3)
        self.assertAlmostEqual(arithmetic("log(exp(2))"), 2)
        self.assertEqual(numeric_array("mean", ([1, 2, 3],)), 2)
        self.assertEqual(numeric_array("dot", ([1, 2], [3, 4])), 11)
        self.assertEqual(numeric_array("matmul", ([[1, 2]], [[3], [4]])), [[11]])

    def test_rejects_non_numeric_syntax_and_bounds(self):
        for expression in ("x", "x.attr", "sqrt(x=4)", "[1,2]", "True", "1/0", "2**100",
                           "10**20", "1e999", "(-1)**0.5", "1+" * 62 + "1", "(" * 300):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                arithmetic(expression)
        with self.assertRaises(ValueError):
            arithmetic("1+1", timeout=0)
        with self.assertRaises(ValueError):
            numeric_array("matmul", ([[1, 2]], [[3], [4, 5]]))


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.source = "Modèle | F1 | AUC\nLogistique brute | 0,7407 | 0,60\nLogistique log | 0,8593 | 0,80"
        self.anchor = evidence(24, self.source)
        self.unit = unit("comparison", 24, self.source, "logistic")
        self.facts = (
            Fact(("Logistique brute", "F1"), "0,7407", self.anchor),
            Fact(("Logistique log", "F1"), "0,8593", self.anchor),
        )
        self.item = ChecklistItem("labeled-f1", (self.anchor,), facts=self.facts)

    def verify(self, blocks, **changes):
        return verify_unit(self.unit, blocks, **({"pages": {24: self.source},
                            "sources": (self.anchor,), "checklist": (self.item,)} | changes))

    def test_locale_and_table_bindings_detect_swaps_without_using_the_auc_column(self):
        good = "Modèle | F1 | AUC\nLogistique brute | 0.7407 | 0.60\nLogistique log | 0.8593 | 0.80"
        findings = self.verify([block(good, "table")])
        self.assertEqual({finding.code for finding in findings}, {"missing_block"})
        self.assertEqual(decimal_value("0,8593"), decimal_value("0.8593"))
        self.assertEqual(decimal_value("1 506"), decimal_value("1506"))
        swapped = good.replace("0.7407", "swap").replace("0.8593", "0.7407").replace("swap", "0.8593")
        findings = self.verify([block(swapped, "table")])
        mismatches = [finding for finding in findings if finding.code == "label_value_mismatch"]
        self.assertEqual(len(mismatches), 2)
        self.assertIn("missing_item", {finding.code for finding in findings})
        for finding in mismatches:
            self.assertEqual((finding.severity, finding.unit_id, finding.block_id, finding.source),
                             ("authoritative", "logistic", "block", self.anchor))
            self.assertIn("Logistique", swapped[slice(*finding.output_span)])

    def test_wrong_direction_is_heuristic_only(self):
        claim = "Le F1 augmente de 0,8593 à 0,7407."
        findings = self.verify([block(claim, "interpretation")], checklist=())
        direction, = [finding for finding in findings if finding.code == "direction_conflict"]
        self.assertEqual(direction.severity, "heuristic")
        self.assertFalse(any(finding.severity == "authoritative" for finding in findings))

    def test_numeric_comparison_binds_each_model_to_the_shared_metric(self):
        swapped = "F1 de Logistique brute : 0,8593 contre Logistique log : 0,7407."
        findings = self.verify([block(swapped, "interpretation")])
        self.assertEqual([f.item_id for f in findings if f.code == "label_value_mismatch"],
                         ["labeled-f1", "labeled-f1"])

    def test_valid_page_with_unrelated_claim_is_not_coverage(self):
        findings = self.verify([block("Logistique log, F1 : 0,9999", "table")])
        self.assertTrue({"unsupported_claim_number", "label_value_mismatch", "missing_item"}
                        <= {finding.code for finding in findings})
        for indexes, code in [((), "missing_claim_marker"), ((2,), "invalid_claim_anchor"),
                              ((True,), "invalid_claim_anchor")]:
            with self.subTest(indexes=indexes):
                result = self.verify([block(self.source, "table", indexes=indexes)])
                self.assertIn(code, {finding.code for finding in result})
        other = evidence(25, self.source)
        findings = self.verify([block(self.source, "table")], pages={24: self.source, 25: self.source}, sources=(other,))
        self.assertIn("invalid_claim_anchor", {finding.code for finding in findings})

    def test_cross_unit_ledger_and_supplementary_or_unverified(self):
        source = "Mme Benali : 0,924"
        fact = Fact(("Mme Benali",), "0,924", evidence(17, source))
        pages = {17: source, 24: self.source}
        for text, hypothetical, code in [
            ("Imaginons Mme Benali : 0,123", True, "label_value_mismatch"),
            ("Autre résultat : 0,123", False, "unmarked_hypothetical"),
        ]:
            findings = self.verify([block(text, provenance="supplementary", hypothetical=hypothetical)],
                                   pages=pages, facts=(fact,))
            self.assertIn(code, {finding.code for finding in findings})
        findings = self.verify([block(self.source, "table", "unverified")])
        self.assertIn("missing_item", {finding.code for finding in findings})

    def test_missing_and_incorrect_worked_calculation(self):
        source = "Base 0,12. Contributions 0,46 et 0,31."
        anchor = evidence(16, source)
        lesson = unit("worked_calculation", 16, source, "shapley")
        findings = verify_unit(lesson, [], pages={16: source}, sources=(anchor,))
        self.assertIn("missing_calculation", {finding.code for finding in findings})
        self.assertEqual(len([f for f in findings if f.code == "missing_block"]), 5)
        for expected in ("0,89", "0,91"):
            with self.subTest(expected=expected):
                result = block(f"Le résultat est {expected}.", "result", "derived",
                               calculation=Calculation(expected, "0.12 + 0.46 + 0.31"))
                findings = verify_unit(lesson, [result], pages={16: source}, sources=(anchor,))
                codes = {finding.code for finding in findings}
                self.assertEqual("calculation_mismatch" in codes, expected == "0,91")
                self.assertEqual("missing_calculation" in codes, expected == "0,91")
        invented = block("Le résultat est 0,89.", "result", "derived",
                          calculation=Calculation("0,89", "0.77 + 0.12"))
        findings = verify_unit(lesson, [invented], pages={16: source}, sources=(anchor,))
        self.assertIn("unsupported_calculation_operand", {finding.code for finding in findings})

    def test_each_displayed_equation_is_checked_with_its_own_span(self):
        source = "0,12 + 0,46 + 0,31 = 0,89"
        anchor = evidence(16, source)
        lesson = unit("worked_calculation", 16, source, "shapley")
        item = ChecklistItem("efficiency", (anchor,), phrases=(source,))
        for equation in (
            "0,12 + 0,46 − 0,31 = 0,89",
            "0,12 × 0,46 + 0,31 = 0,89",
            "0,12 + 0,46 + 0,32 = 0,89",
            "0,12 + 0,46 + 0,31 = 0,88",
        ):
            with self.subTest(equation=equation):
                displayed = f"Autre calcul | 0,12 + 0,46 = 0,58 |\nEfficacité | {equation} |"
                result = block(displayed, "result", "derived", calculation=Calculation("0,58", "0.12 + 0.46"))
                findings = verify_unit(lesson, [result], pages={16: source}, sources=(anchor,), checklist=(item,))
                contradiction, = [f for f in findings if f.code == "displayed_equation_mismatch"]
                self.assertEqual(contradiction.severity, "authoritative")
                self.assertEqual((contradiction.unit_id, contradiction.block_id, contradiction.source),
                                 ("shapley", "block", anchor))
                self.assertEqual(displayed[slice(*contradiction.output_span)], equation)
                self.assertIn("efficiency", [f.item_id for f in findings if f.code == "missing_item"])
                if "−" in equation:
                    self.assertIn("0.27 ≠ 0.89", contradiction.detail)

    def test_displayed_notation_and_unsupported_syntax(self):
        accepted = (
            "0,12 + 0,46 + 0,31 = 0,89", "(0,43 + 0,49) ÷ 2 = 0,46",
            "(-3 + 1) × 2 = −4", "3 000 / 2 = 1 500", "2**3 = 2 × 4 = 8",
            "max(3, 5) // 2 = 2", "1 + 1 = 2, 2 + 2 = 4",
            "1 + 1 = 2 et 2 + 2 = 4", "2 + 2 = 4. Puis on continue.",
            "round((sqrt(16) + abs(-2)) ** 2 / 3, 2) = 12",
        )
        for text in accepted:
            with self.subTest(text=text):
                self.assertEqual(len(list(displayed_equations(text))), 2 if "2 + 2" in text and "1 + 1" in text else 1)
                self.assertFalse(any(f.code in {"displayed_equation_mismatch", "unverifiable_equation"}
                                     for f in self.verify([block(text, "table")], legacy=True)))
        for text in ("2 ^ 3 = 8", "√4 = 2", "1 / 0 = 5", "unknown(4) = 2"):
            with self.subTest(text=text):
                finding, = [f for f in self.verify([block(text, "table")], legacy=True)
                            if f.code == "unverifiable_equation"]
                self.assertEqual(finding.severity, "source")

    def test_equation_checklist_does_not_match_a_different_valid_operator(self):
        source = "2 + 2 = 4"
        anchor = evidence(16, source)
        lesson = unit("worked_calculation", 16, source, "operators")
        item = ChecklistItem("addition", (anchor,), phrases=(source,))
        findings = verify_unit(lesson, [block("2 × 2 = 4", "result")],
                               pages={16: source}, sources=(anchor,), checklist=(item,))
        self.assertIn("addition", [f.item_id for f in findings if f.code == "missing_item"])
        self.assertNotIn("displayed_equation_mismatch", {f.code for f in findings})


class SavedAnswerReplayTests(unittest.TestCase):
    def test_observable_defects_in_saved_explanations(self):
        fixture = Path(__file__).parent / "fixtures/explicateur_depth/explainability_negative_controls.json"
        first, second = json.loads(fixture.read_text(encoding="utf-8"))["responses"]
        # Manually transcribed evidence from the Phase 0 golden scenarios. Legacy cards have page
        # numbers but no claim markers or source excerpts, so the replay checks observable gaps.
        examples = {
            16: ("coalitions", "0,12 0,55 0,40 0,89 0,46 0,31"),
            17: ("waterfall-reading", "valeur de base 0,116 et prédiction 0,924"),
            18: ("beeswarm-reading", "400 transactions de test"),
        }
        part1 = Block("post-hoc", "explanation", first["sections"][2]["content"], "legacy")
        gaps = []
        for page, (item, source) in examples.items():
            checklist = ChecklistItem(item, (evidence(page, source),), phrases=(source,))
            gaps.extend(verify_unit(unit("concept", page, source, f"page-{page}"), [part1],
                                    pages={page: source}, sources=(), checklist=(checklist,), legacy=True))
        self.assertEqual({finding.item_id for finding in gaps if finding.code == "missing_item"},
                         {"coalitions", "waterfall-reading", "beeswarm-reading"})

        source = "F1\nForêt aléatoire 0,8669\nLogistique brute 0,7407\nLogistique log 0,8593\n"
        source += "Arbre profondeur 3 0,5737\nArbre sans limite 0,7556"
        scores = ("0,8669", "0,7407", "0,8593", "0,5737", "0,7556")
        names = ("Forêt aléatoire", "Logistique brute", "Logistique log", "Arbre profondeur 3", "Arbre sans limite")
        anchor = evidence(26, source)
        checklist = [ChecklistItem(f"f1-{i}", (anchor,), facts=(Fact((name, "F1"), value, anchor),))
                     for i, (name, value) in enumerate(zip(names, scores), 1)]
        unit_map = [
            unit("transition", page, title, label) | {"label": label, "title": title}
            for label, page, title in [("II", 11, "Expliquer un modèle après coup"),
                                      ("III", 23, "Des modèles interprétables par nature")]
        ]
        blocks = [Block(f"section-{i}", "explanation", section["content"], "legacy")
                  for i, section in enumerate(second["sections"][:2], 1)]
        findings = verify_unit(unit("comparison", 26, source, "III.3"), blocks,
                               pages={26: source}, sources=(), checklist=checklist, unit_map=unit_map, legacy=True)
        self.assertEqual(len([finding for finding in findings if finding.code == "incorrect_part"]), 2)
        self.assertEqual(len([finding for finding in findings if finding.code == "missing_item"]), 5)
