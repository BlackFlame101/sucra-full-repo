import unittest

from agents.explain_planner import build_learning_plan, has_explicit_scope, learning_progress


def unit(uid, label, page, *, kind="concept", parent="ii", title=None):
    return {"logical_id": uid, "content_version": "v1", "label": label, "kind": kind,
            "start": [page, 0], "end": [page, 30], "title": title or uid,
            "heading_path": [(parent, "", 1), (label.casefold(), "", 1)]}


class LearningPlannerTests(unittest.TestCase):
    def setUp(self):
        self.units = [unit("part2", "II", 11, kind="transition"), unit("shap", "II.1", 16),
                      unit("proof", "II.2", 17, kind="derivation"),
                      unit("part3", "III", 23, kind="transition", parent="iii"),
                      unit("f1", "III.1", 26, kind="comparison", parent="iii")]
        self.prepared = {"f1": {"content_version": "v1", "unresolved": [
            {"page": 26, "reason": "visual_details_unconfirmed", "status": "unverifiable_source"}
        ]}}

    def plan(self, prompt="Teach the entire course", **options):
        return build_learning_plan(self.units, "map", prompt, self.prepared, **options)

    def test_scope_and_ambiguity(self):
        plan = self.plan("Uniquement la partie II, sans les démonstrations")
        self.assertEqual(plan["order"], ["shap"])
        self.assertEqual(plan["scope"]["proof"]["reason"], "proof_excluded")
        self.assertEqual(plan["scope"]["f1"]["reason"], "outside_requested_part")
        ambiguous = self.plan("Teach only part IX")
        self.assertTrue(ambiguous["assumptions"])
        self.assertEqual(ambiguous["order"], ["shap", "proof", "f1"])

    def test_exercise_scope_also_excludes_child_questions(self):
        exercise = unit("question", "(a)", 20, kind="exercise")
        exercise["heading_path"].insert(1, ("exercice 3", "", 1))
        self.units.append(exercise)
        self.assertEqual(self.plan("Skip exercise 3")["scope"]["question"]["reason"], "exercise_excluded")

    def test_numbered_spark_step_enters_the_unit_pipeline_and_limits_scope(self):
        self.units.extend([
            unit("setup", "Étape 0", 1, kind="lab_step"),
            unit("next", "Étape 1", 2, kind="lab_step"),
        ])
        request = "Explique uniquement l’étape 0 (Vérifier l’environnement) du document TP4_Spark_MLlib.pdf en français."
        self.assertTrue(has_explicit_scope(request))
        plan = self.plan(request)
        self.assertEqual(plan["order"], ["setup"])
        self.assertEqual(plan["scope"]["next"]["reason"], "outside_requested_lab_steps")
        self.assertEqual(self.plan("Explain only step 7 of this lab")["order"], [])

    def test_prerequisite_order_depth_and_student_level(self):
        self.prepared["shap"] = {"content_version": "v1", "depends_on": ["proof"],
                                 "external_prereqs": ["Algebra", "Algebra"],
                                 "checklist": [{"item_id": key, "importance": key}
                                               for key in ("essential", "supporting", "optional")]}
        plan = self.plan("Teach everything without omitting details", level="beginner")
        self.assertEqual(plan["order"], ["proof", "shap", "f1"])
        self.assertEqual(plan["primer"], {"provenance": "supplementary", "prerequisites": ["Algebra"]})
        self.assertEqual(plan["required_items"]["shap"], ["essential", "supporting", "optional"])
        advanced = self.plan(level="advanced")
        self.assertEqual(advanced["prereqs_assumed"], ["Algebra"])
        self.assertIsNone(advanced["primer"])
        self.assertEqual(advanced["required_items"]["shap"], ["essential"])
        self.assertEqual(plan["fingerprint"], advanced["fingerprint"])

    def test_continue_ignores_partial_and_deepen_ranks_missing_essentials(self):
        self.prepared["shap"] = {"content_version": "v1", "checklist": [{"item_id": "minor", "importance": "optional"}]}
        self.prepared["proof"] = {"content_version": "v1", "checklist": [{"item_id": "key", "importance": "essential"}]}
        progress = {"shap": {"status": "partial", "content_version": "v1", "missing_item_ids": ["minor"]},
                    "proof": {"status": "partial", "content_version": "v1", "missing_item_ids": ["key"]}}
        plan = self.plan()
        state = learning_progress(plan, self.units, progress, "inquiry", prepared=self.prepared)
        self.assertEqual(state["remaining"], [{"logical_id": "f1", "title": "f1", "pages": [26, 26]}])
        self.assertEqual([(a["action"], a["logical_id"]) for a in state["next_actions"]],
                         [("continue_learning", "f1"), ("deepen_unit", "proof"), ("deepen_unit", "shap")])
        self.assertEqual(state, learning_progress(plan, self.units, progress, "inquiry", prepared=self.prepared))
        progress["f1"] = {"status": "covered", "content_version": "v1"}
        state = learning_progress(plan, self.units, progress, "inquiry")
        self.assertEqual(state["progress"]["f1"]["status"], "partial")
        self.assertTrue(state["progress"]["f1"]["unverifiable_source"])
        self.assertFalse(state["remaining"])
        self.assertTrue(all(a["action"] == "deepen_unit" for a in state["next_actions"]))

    def test_ledger_admits_only_current_reviewed_facts_without_source_gaps(self):
        facts = [{"unit_id": "shap", "content_version": version, "verification": verification, "value": value}
                 for version, verification, value in [("v1", "reviewed", "accepted"), ("v0", "reviewed", "stale"),
                                                      ("v1", "unchecked", "unverified")]]
        facts.append({"unit_id": "f1", "content_version": "v1", "verification": "reviewed"})
        progress = {uid: {"status": "covered", "content_version": "v1"} for uid in ("shap", "f1")}
        state = learning_progress(self.plan(), self.units, progress, "inquiry", verified_facts=facts)
        self.assertEqual([item["value"] for item in state["facts_ledger"]], ["accepted"])
