"""Offline tests of the document-first Explain entry point and source guarantees."""
from __future__ import annotations

import ast
from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import get_args
import unittest
from unittest.mock import AsyncMock, patch

from agents import explain_document as document
from agents.explain_document_scope import ScopeClarification, Target, classify_document_request
from agents.explain_document_validation import DraftSection, check_section
from models.educational_document import EducationalDocument, ReviewCriterion
from rag.explain_document_source import prepare_document_scope
from tests.fixtures.spark_part_one_worked import CLAIMS, EXERCISE_CODE, EXERCISE_INTERPRETATION, LESSONS
from tests.test_explain_intent import FRENCH_CASES
from worker import chunk_pages, extract_pages


BENCHMARKS = {
    "spark": ("TP4_Spark_MLlib.pdf", "3203a05e7a063c3a4e9d04894e035cca7541342b694dafa2fb4c73b4d7ed4fe8"),
    "orange": ("TP_Complementaire_Orange_KNIME.pdf", "ae7807e7dcf7cc6e0f83c0aa76c39a73dfd0dc433bd269d484168f4fa90efd95"),
    "chapter": ("Cours_Chapitre6_Explicabilite_Auditabilite.pdf", "692f6333ee7686e92304f7670e046eb1032125a0dc6d23964d4f9e2d03f4bf2b"),
}
REQUEST = "Résous la Partie 1 du TD Spark en détail."
STATE = {"request_id": "mock-turn", "session_id": "mock-inquiry", "course_id": "mock-course",
         "user_id": "mock-owner", "provider": "google", "model": "gemini-3.5-flash-lite"}

SPARK_ANSWERS = [
    "Cette partie construit une classification binaire sur des transactions synthétiques.",
    "La graine fixe rend la génération reproductible tant que le fichier est créé dans les mêmes conditions.",
    "Le schéma explicite stabilise le type de chaque champ avant les contrôles de qualité.",
    "JSON Lines stocke un objet par ligne. Un tableau multiligne demande l’option multiLine. Le schéma fixe les types et la cible est fraude. Les variables explicatives sont le montant, l’heure, le pays différent et le nombre de tentatives.",
    "Le filtrage SQL retire les observations invalides puis répartit les lignes entre trois jeux distincts.",
    "Vérifiez les deux classes dans chaque jeu pour que l’apprentissage et les métriques aient un sens. randomSplit ne garantit pas des proportions exactes. Avec des dates, entraînez sur l’ancien et validez puis testez sur des périodes ultérieures.",
    "VectorAssembler rassemble les variables et le normaliseur applique la transformation apprise sur l’entraînement.",
    "L’identifiant de ligne ne mesure aucun comportement et peut introduire un artefact. Ajuster le normaliseur sur train évite la fuite. Un Pipeline décrit les étapes; un PipelineModel contient les transformations et le classifieur ajustés.",
    "Les modèles s’ajustent sur train et se comparent sur valid avant toute évaluation finale.",
    "Un rappel élevé réduit les fraudes manquées mais peut augmenter les alertes injustifiées. La précision mesure la fiabilité des alertes. Le test reste indépendant de la sélection sur validation.",
    "Le CSV conserve la classe réelle, la prédiction et la distribution binaire pour chaque observation exportée.",
    "toLocalIterator évite de réunir toute la partition de résultats en une liste sur le pilote. L’export centralisé reste coûteux en flux et temps à grande échelle. Chaque probabilité correspond à une classe du vecteur.",
    "Conservez les partitions du document. Ajustez chaque configuration sur train, comparez F1 pondéré, accuracy et AUC sur valid, puis retenez la meilleure configuration avant une seule évaluation sur test.",
]

SPARK_HEADINGS = [
    "Classification de transactions bancaires", "Générer le fichier de transactions", "Imposer le schéma des données",
    "Pourquoi JSON Lines et un schéma explicite ?", "Nettoyer et répartir les observations",
    "Classes et partitions temporelles", "Ajuster le pipeline de classification",
    "Variables explicatives et fuite de données", "Comparer les classifieurs",
    "Précision, rappel et indépendance du test", "Exporter les prédictions",
    "Lire le fichier et interpréter les probabilités", "Régler l’arbre et la forêt",
]

EXERCISE_A = """from pyspark.ml.classification import DecisionTreeClassifier, RandomForestClassifier
from pyspark.ml import Pipeline
from pyspark.ml.evaluation import MulticlassClassificationEvaluator, BinaryClassificationEvaluator

f1 = MulticlassClassificationEvaluator(labelCol="fraude", predictionCol="prediction", metricName="f1")
accuracy = MulticlassClassificationEvaluator(labelCol="fraude", predictionCol="prediction", metricName="accuracy")
auc = BinaryClassificationEvaluator(labelCol="fraude", rawPredictionCol="rawPrediction", metricName="areaUnderROC")
configurations = [
    ("Arbre", {"maxDepth": profondeur}, DecisionTreeClassifier(labelCol="fraude", maxDepth=profondeur, seed=73))
    for profondeur in (3, 8)
]
configurations += [
    ("Forêt", {"numTrees": arbres, "maxDepth": profondeur},
     RandomForestClassifier(labelCol="fraude", numTrees=arbres, maxDepth=profondeur, seed=73))
    for arbres in (15, 60) for profondeur in (4, 8)
]
comparaison = []
for nom, parametres, classifieur in configurations:
    modele = Pipeline(stages=[assembleur_tx, normaliseur_tx, classifieur]).fit(train_tx)
    validation = modele.transform(valid_tx)
    comparaison.append((nom, parametres, f1.evaluate(validation), accuracy.evaluate(validation), auc.evaluate(validation), modele))
print("Algorithme | Paramètres | F1 | Accuracy | AUC")
for nom, parametres, score, exactitude, aire, _ in comparaison:
    print(nom, parametres, score, exactitude, aire, sep=" | ")
meilleur = max(comparaison, key=lambda ligne: ligne[2])
predictions_finales = meilleur[-1].transform(test_tx)
print("F1 final :", f1.evaluate(predictions_finales))"""


class FixtureProvider:
    def __init__(self, answers=None, *, failure=None, worked=False, quality_issue=None):
        self.answers = iter(answers or ())
        self.calls = []
        self.failure = failure
        self.last_drafts = {}
        self.spark = answers is SPARK_ANSWERS
        self.worked = worked
        self.quality_issue = quality_issue
        self.requests = []

    def model(self, **options):
        async def invoke(messages):
            action = options["agent"].removeprefix("explain_document_")
            self.calls.append(action)
            value = json.loads(messages[-1].content)
            assert options["bind_response_schema"] and options["single_attempt"]
            limits = document.explain_budget(options["provider"], options["model"])
            self.requests.append({"stage": action, "model": options["model"],
                                  "input_estimate": limits.prompt_tokens(messages, options["response_schema"]),
                                  "max_output": options["max_completion_tokens"], "packet": value})
            if self.failure == action:
                raise RuntimeError("mocked provider outage")
            if action == "plan":
                result = {"title": "Classification de transactions avec Spark MLlib" if self.spark else "Document pédagogique",
                          "summary": "Présentation de la démarche.",
                          "sections": [{"section_id": row["section_id"], "title": row["label"][:95],
                                        "goal": "Présenter le raisonnement et le résultat."}
                                       for row in value["ordered_sections"]]}
            elif action == "generate":
                rows = []
                for item in value["selected_sections"]:
                    sid = item["section_id"]
                    quote = next(self.answers, "La méthode distingue les observations utiles et explique leur rôle concret.")
                    cid = item["source"][0]["id"]
                    text = f"{quote} [[{cid}]]"
                    position = SPARK_ANSWERS.index(quote) if self.spark else None
                    if self.worked and not (self.quality_issue in {"missing_mechanism", "recover_mechanism"} and position == 6):
                        quote = CLAIMS[position]
                        text = LESSONS[position].replace(quote, f"{quote} [[{cid}]]", 1)
                    if item["cells"]:
                        text += "\n\n" + "\n\n".join("{{cell:" + cell["id"] + "}}" for cell in item["cells"])
                    for cell in item["cells"]:
                        if cell["id"] in item["source_code_diagnostics"]:
                            fixed = cell["code"].replace('    labelCol="fraude", rawPredictionCol="rawPrediction",\n',
                                                         '    rawPredictionCol="rawPrediction",\n', 1)
                            text += ("\n\n**Cellule corrigée à exécuter.** Retirez le premier argument `labelCol` "
                                     "répété et gardez `rawPrediction` pour le calcul de l’AUC. Exécutez cette "
                                     "cellule à la place de l’originale ; elle définit `pred_test_tx` pour l’export."
                                     "\n\n~~~python corrects:" + cell["id"] + "\n" + fixed + "\n~~~")
                    outputs = []
                    if position == len(SPARK_ANSWERS) - 1 or quote == SPARK_ANSWERS[-1]:
                        code = EXERCISE_CODE if self.worked else EXERCISE_A
                        if self.quality_issue == "fragmented":
                            code = "for candidat in candidats:"
                        if self.quality_issue != "missing_solution":
                            text += "\n\n~~~python\n" + code + "\n~~~"
                        if self.worked and self.quality_issue != "incomplete_interpretation":
                            text += "\n\n" + EXERCISE_INTERPRETATION
                            outputs.append({"text": "**Lecture attendue.** Le tableau de validation contient une ligne par configuration.",
                                            "status": "expected"})
                        if self.quality_issue == "unsupported_execution":
                            text += "\n\nNous avons exécuté le code dans Spark."
                    title = SPARK_HEADINGS[position] if self.spark else "Démarche"
                    rows.append({"section_id": sid, "title": title, "markdown": text,
                                 "claims": [{"quote": quote, "citations": [cid]}], "outputs": outputs})
                    self.last_drafts[sid] = quote
                result = {"sections": rows}
            elif action == "repair":
                result = {"sections": value["sections"]}
                if self.quality_issue == "recover_mechanism":
                    result["sections"][0]["markdown"] += "\n\n" + LESSONS[6]
            else:
                findings = []
                if self.failure == "review_repair" and self.calls.count("review") == 1:
                    findings = [value["requirements"][-1]["section_id"] + ": verify answer"]
                rows = value["requirements"]
                sections = {"scope_completeness": 0, "technical_correctness": 6, "pedagogical_depth": 6,
                            "reasoning": 7, "solution_completeness": 12, "code_quality": 8,
                            "revision_usefulness": 12, "source_grounding": 2}
                rubric = []
                for criterion in get_args(ReviewCriterion):
                    row = rows[min(sections[criterion], len(rows) - 1)]
                    sid = row["section_id"]
                    score, reason = 3, "Fixture receipt for the scoped passage and its course evidence."
                    evidence = self.last_drafts[sid]
                    if self.spark and self.worked:
                        passage, reason = {
                            "scope_completeness": ("On contrôle d’abord ce qui entre dans le modèle, puis on apprend les transformations et les coefficients sur l’entraînement.",
                                                   "Les six étapes et les analyses sont suivies par le réglage demandé dans l’exercice."),
                            "technical_correctness": ("Avec `withMean=False` la moyenne n’est pas soustraite",
                                                      "Distingue la mise à l’échelle du centrage et utilise les statistiques d’entraînement."),
                            "pedagogical_depth": ("L’assembleur est un transformateur : il applique cette règle sans apprendre de paramètres.",
                                                  "Relie le vecteur d’entrée à la distinction entre transformation et apprentissage."),
                            "reasoning": ("Cette fuite peut rendre l’évaluation trop optimiste.",
                                          "Justifie l’ajustement sur train et le réemploi des mêmes statistiques."),
                            "solution_completeness": ("le modèle choisi transforme une seule fois `test_tx`", "Décrit le choix de configuration, l’évaluation et la lecture des erreurs."),
                            "code_quality": ("elle définit `pred_test_tx` pour l’export.", "La correction complète est distincte du code source et crée l’entrée de l’étape 6."),
                            "revision_usefulness": ("prenez les décisions sur validation et utilisez le test pour rendre compte de la performance finale.",
                                                    "Synthétise le protocole et explique comment lire un écart de performance."),
                            "source_grounding": (CLAIMS[2], "Le passage lie le schéma et ses types aux colonnes déclarées dans le PDF."),
                        }[criterion]
                        if passage in value["markdown"]:
                            evidence = passage
                    if criterion == "pedagogical_depth" and (self.quality_issue in {"shallow", "missing_mechanism"}
                            or self.quality_issue == "recover_mechanism" and self.calls.count("review") == 1):
                        score, evidence = 1, self.last_drafts[sid]
                        reason = "Expliquer comment `fit` ajuste le normaliseur sur train et réutilise ses statistiques."
                    if criterion == "solution_completeness" and self.quality_issue == "incomplete_interpretation":
                        score, evidence = 1, ""
                        reason = "Interpréter le F1 final, la matrice de confusion et les faux négatifs."
                    rubric.append({"criterion": criterion, "section_id": sid, "score": score,
                                   "reason": reason, "evidence": evidence})
                result = {"draft_hash": value["draft_hash"], "rubric": rubric, "findings": findings,
                          "evidence": [{"requirement_id": row["requirement_id"], "quote": self.last_drafts[row["section_id"]]}
                                       for row in value["requirements"] if row["requirement_id"]]}
                if self.failure == "review_wrong_hash":
                    result["draft_hash"] = "stale"
                if self.failure == "review_forged_quote":
                    rubric[0]["evidence"] = "Ce passage plausible est absent du document effectivement revu."
                if self.failure == "review_missing_criterion":
                    rubric[-1] = rubric[0]
            return SimpleNamespace(content=json.dumps(result), response_metadata={"finish_reason": "STOP"})

        return SimpleNamespace(ainvoke=invoke)


class MemoryCheckpoint:
    def __init__(self):
        self.data = {"versions": [], "calls": []}
        self.document = None

    async def open(self, doc):
        source = {"document_id": doc["id"], "source_hash": doc["content_hash"], "generation": doc["index_generation"]}
        if self.document and self.document != source:
            raise ValueError("Stale source version.")
        self.document = source

    async def save(self, *, version=None, purpose=None, tokens=0, retry=False, batch_hash=None, retry_at=None):
        if version:
            self.data["versions"].append(version)
        else:
            row = {"purpose": purpose, "tokens": tokens, "retry": retry} if retry_at is None else {
                "purpose": purpose, "retry_at": retry_at}
            if batch_hash is not None:
                row["batch_hash"] = batch_hash
            self.data["calls"].append(row)


def source(pages, filename="Spark.pdf", digest=None):
    chunks = chunk_pages([page["text"] for page in pages], positions=True)
    doc = {"id": "280de0bf-9b17-4192-8c94-ee07cbef18b6", "filename": filename, "index_generation": 2,
           "content_hash": digest or "mock-sha-256", "page_count": len(pages)}
    ranked = [{"page_number": row["page_number"], "document_id": doc["id"]} for row in chunks]
    return doc, pages, chunks, chunks, ranked


async def generate(bundle, query, provider, *, checkpoint=None, event=None):
    with patch.object(document, "_load_source", AsyncMock(return_value=bundle)), \
            patch.object(document, "get_chat_llm", provider.model), \
            patch.dict(os.environ, {"SOCRA_EXPLAIN_REVIEW_MODEL": "gemini-3.5-flash-lite"}, clear=False):
        result = await document.run_educational_document(
            STATE | {"student_message": query, "explain_checkpoint": checkpoint, "explain_document_event": event}
        )
    return result["explanation"]


class DocumentTests(unittest.IsolatedAsyncioTestCase):
    def test_intent_and_exclusions_are_independent(self):
        wanted = classify_document_request(REQUEST)
        self.assertEqual((wanted.action, wanted.document_type, wanted.scope, wanted.targets),
                         ("solve", "practical_lab", "part", (Target("part", "1"),)))
        wanted = classify_document_request("Guide me through Part II without solving Exercise A")
        self.assertEqual((wanted.action, wanted.targets, wanted.exclusions),
                         ("guide", (Target("part", "2"),), (Target("exercise", "a"),)))
        self.assertEqual(classify_document_request("Corrige mon code Spark.").action, "correct")
        assign = classify_document_request("Aide-moi à résoudre le TD.")
        self.assertEqual((assign.action, assign.scope), ("solve", "whole_document"))
        self.assertEqual(classify_document_request("Donne-moi la solution complète.").action, "solve")
        self.assertEqual(classify_document_request("Guide me through the complete lab.").action, "guide")

    def test_citation_integrity_and_unfinished_fences(self):
        page = {"text": "Partie 1 — Exemple\nLe cours propose une approche fondée sur une séparation mesurable."}
        doc, pages, positioned, indexed, _ = source([page])
        intent = classify_document_request("Explique la Partie 1.")
        planned, _ = prepare_document_scope(doc["id"], pages, positioned, indexed, intent)
        ref = planned[0].citations[0].citation_id
        quote = "La séparation rend la validation plus facile à interpréter."
        raw = {"section_id": planned[0].section.section_id, "title": "Exemple",
               "markdown": f"{quote} [[{ref}]]", "claims": [{"quote": quote, "citations": [ref]}]}
        check_section(DraftSection.model_validate(raw), planned[0], {1: page["text"]})
        for markup in (f"{quote} [[unknown]]", f"{quote} [[{ref}]]\n\n~~~python\nx = 1",
                       f"{quote} [[{ref}]]\n\nNous avons exécuté le code.",
                       f"{quote} [[{ref}]]\n\n~~~python\npass\n~~~"):
            with self.subTest(markup=markup), self.assertRaises(ValueError):
                check_section(DraftSection.model_validate(raw | {"markdown": markup}), planned[0], {1: page["text"]})
        with self.assertRaises(ValueError):
            check_section(DraftSection.model_validate(raw | {"claims": [{"quote": quote, "citations": [ref, ref]}]}),
                          planned[0], {1: page["text"]})

    async def test_unknown_scope_asks_before_dispatch(self):
        bundle = source([{"text": "Partie I — Un titre\nLa source décrit la validation."}])
        provider = FixtureProvider()
        with self.assertRaises(ScopeClarification):
            await generate(bundle, "Résous la Partie 2 du TD Spark.", provider)
        self.assertEqual(provider.calls, [])

    async def test_split_heading_and_roman_scope_with_prerequisite(self):
        pages = [{"text": "Step 0 – Setup\nExpected setup.\nPart I"},
                 {"text": "A documented exercise\nStep 1 – Build a model\nSource evidence.\nExercise A – Compare\nCompare the methods."},
                 {"text": "Part II – Other material\nStep 2 – Separate topic\nOut of scope."}]
        result = await generate(source(pages), "Solve Part I of this lab.", FixtureProvider())
        self.assertEqual(result["state"], "approved", result["verification"])
        self.assertEqual(result["intent"]["targets"], [{"kind": "part", "number": "1"}])
        self.assertEqual(len(result["prerequisites"]), 1)
        self.assertNotIn(3, [ref["span"]["page"] for ref in result["citations"]])
        self.assertIn("Exercise A", result["document_markdown"])

    async def test_progress_retry_reuses_scope_and_completed_sections(self):
        bundle = source([{"text": "Part 1 – Model\nExercise A – Validation\nA reliable validation protocol."}])
        checkpoint = MemoryCheckpoint()
        event = AsyncMock()
        first = FixtureProvider(failure="review")
        result = await generate(bundle, "Solve Part 1 of this lab.", first, checkpoint=checkpoint, event=event)
        self.assertEqual(result["state"], "review_pending")
        self.assertEqual(first.calls, ["plan", "generate", "review"])
        self.assertTrue(any(call.args[1]["sections"] for call in event.await_args_list))
        second = FixtureProvider()
        second.last_drafts.update(first.last_drafts)
        retried = await generate(bundle, "Solve Part 1 of this lab.", second, checkpoint=checkpoint)
        self.assertEqual(second.calls, ["review"])
        self.assertEqual(retried["state"], "approved")
        self.assertEqual(result["revision_id"], retried["revision_id"])
        self.assertEqual(result["document_markdown"], retried["document_markdown"])
        stale = (bundle[0] | {"index_generation": 3}, *bundle[1:])
        with self.assertRaisesRegex(ValueError, "Stale source version"):
            await generate(stale, "Solve Part 1 of this lab.", FixtureProvider(), checkpoint=checkpoint)

    async def test_review_repairs_once_and_binds_latest_revision(self):
        bundle = source([{"text": "Part 1 – Model\nExercise A – Validation\nA reliable validation protocol."}])
        provider = FixtureProvider(failure="review_repair")
        result = await generate(bundle, "Solve Part 1 of this lab.", provider)
        self.assertEqual(provider.calls, ["plan", "generate", "review", "repair", "review"])
        self.assertEqual(result["state"], "approved", result["verification"])
        self.assertTrue(result["parent_revision_id"])
        self.assertEqual(result["verification"]["reviewer"]["draft_hash"], result["verification"]["draft_hash"])

    async def test_generation_failure_does_not_approve_or_review(self):
        bundle = source([{"text": "Part 1 – Model\nExercise A – Validation\nA reliable validation protocol."}])
        provider = FixtureProvider(failure="generate")
        result = await generate(bundle, "Solve Part 1 of this lab.", provider)
        self.assertEqual(provider.calls, ["plan", "generate"])
        self.assertEqual(result["state"], "draft")
        self.assertFalse(result["sections"])
        self.assertTrue(result["remaining"])

    async def test_review_receipt_cannot_approve_with_wrong_hash_forged_evidence_or_duplicate_criterion(self):
        bundle = source([{"text": "Partie 1 – Protocole\nLa source décrit le contrôle de validation."}])
        for failure in ("review_wrong_hash", "review_forged_quote", "review_missing_criterion"):
            with self.subTest(failure=failure):
                provider = FixtureProvider(failure=failure)
                result = await generate(bundle, "Explique la Partie 1.", provider)
                self.assertEqual(provider.calls, ["plan", "generate", "review"])
                self.assertEqual(result["state"], "review_pending")
                self.assertFalse(result["verification"]["passed"])


class RealPDFTests(unittest.IsolatedAsyncioTestCase):
    async def bundle(self, key):
        name, expected = BENCHMARKS[key]
        default = Path.home() / "Downloads"
        root = Path(os.getenv("SOCRA_PHASE7_PDF_DIR", default))
        pdf = root / name
        if not pdf.is_file() and key == "chapter":
            pdf = root / "Cours_Chapitre6_Explicabilite_Auditabilite(1).pdf"
        if not pdf.is_file():
            self.skipTest(f"Original benchmark file unavailable: {pdf}")
        content = pdf.read_bytes()
        self.assertEqual(sha256(content).hexdigest(), expected)
        return source(await extract_pages(content, layout=True, evidence=True), name, expected)

    async def test_spark_part_one_scope_code_and_document(self):
        bundle = await self.bundle("spark")
        doc, pages, positioned, indexed, _ = bundle
        for request, action, count in (
            (REQUEST, "solve", 13), ("Explique-moi la Partie 1 du TD Spark.", "explain", 13),
            ("Guide-moi dans la Partie 1 du TD Spark.", "guide", 13),
            ("Explique l’étape 0 du TP Spark.", "explain", 1), ("Résous l’exercice A du TP Spark.", "solve", 1),
        ):
            with self.subTest(request=request):
                intent = classify_document_request(request, source_name=doc["filename"])
                self.assertEqual(intent.action, action)
                planned, _ = prepare_document_scope(doc["id"], pages, positioned, indexed, intent)
                self.assertEqual(len(planned), count)
                if count == 13:
                    self.assertEqual({c.span.page for row in planned for c in row.citations}, {2, 3, 4, 5})
                    self.assertEqual(sum(row.section.title.startswith("À analyser") for row in planned), 5)
                    cells = [cell for row in planned for cell in row.cells]
                    self.assertEqual(len(cells), 6)
                    self.assertEqual([sorted({s.page for s in cell.source_spans}) for cell in cells],
                                     [[2], [2], [3], [3, 4], [4, 5], [5]])
                    for cell in cells:
                        self.assertEqual([line.strip() for line in cell.code.splitlines() if line.strip()],
                                         [pages[s.page - 1]["text"][s.start:s.end] for s in cell.source_spans])
                        ast.parse(cell.code)
        provider = FixtureProvider(SPARK_ANSWERS, worked=True)
        checkpoint = MemoryCheckpoint()
        result = await generate(bundle, REQUEST, provider, checkpoint=checkpoint)
        self.assertEqual(provider.calls, ["plan", "generate", "review"])
        self.assertEqual(result["state"], "approved", result["verification"])
        self.assertEqual(result["schema_version"], 3)
        self.assertEqual(len(result["code_cells"]), 8)
        self.assertEqual(len(result["coverage"]), 13)
        self.assertTrue(all(row["state"] == "reviewed" for row in result["coverage"]))
        self.assertEqual(len(result["verification"]["reviewer"]["rubric"]), 8)
        original = next(cell for cell in result["code_cells"] if cell["cell_id"] in {
            row["corrects_cell_id"] for row in result["code_cells"] if row["corrects_cell_id"]})
        correction = next(cell for cell in result["code_cells"] if cell["corrects_cell_id"] == original["cell_id"])
        self.assertEqual((original["origin"], correction["origin"]), ("source", "generated"))
        with self.assertRaises(SyntaxError):
            compile(original["code"], "<pdf>", "exec")
        compile(correction["code"], "<corrected>", "exec")
        compile(result["code_cells"][-1]["code"], "<exercise>", "exec")
        self.assertEqual([row["page"] for row in result["prerequisites"]], [1])
        self.assertTrue(all(c["span"]["page"] in {2, 3, 4, 5} for c in result["citations"]))
        self.assertEqual(sum(line.startswith("# ") for line in result["document_markdown"].splitlines()), 1)
        self.assertTrue(any(line.startswith("## Étape 4") for line in result["document_markdown"].splitlines()))
        self.assertTrue(any(line.startswith("### Variables explicatives") for line in result["document_markdown"].splitlines()))
        exercise = "Résous l’exercice A du TP Spark."
        omitted = await generate(bundle, exercise, FixtureProvider())
        self.assertNotEqual(omitted["state"], "approved")
        self.assertIn("requires a complete solution cell", " ".join(omitted["verification"]["findings"]))
        solved_exercise = await generate(bundle, exercise, FixtureProvider([SPARK_ANSWERS[-1]]))
        self.assertEqual(solved_exercise["state"], "approved", solved_exercise["verification"])
        self.assertEqual([cell["origin"] for cell in solved_exercise["code_cells"]], ["generated"])
        EducationalDocument.model_validate_json(json.dumps(result))
        if out := os.getenv("SOCRA_PHASE7_OUTPUT_DIR"):
            Path(out, "spark-part-one-worked-offline.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                                               encoding="utf-8")
            records = []
            for row in provider.requests:
                data = row["packet"]
                packet_key = {"plan": "source", "generate": "selected_sections", "review": "requirements"}[row["stage"]]
                packet = json.dumps(data[packet_key], ensure_ascii=False, separators=(",", ":"))
                records.append({key: value for key, value in row.items() if key != "packet"} | {
                    "source_packet_estimated_utf8_bytes": len(packet.encode()), "source_packet_sha256": sha256(packet.encode()).hexdigest(),
                })
            Path(out, "spark-offline-dispatch.json").write_text(json.dumps(records, indent=2), encoding="utf-8")

    async def test_offline_spark_quality_controls_and_targeted_repair(self):
        bundle = await self.bundle("spark")
        for fault, expected in (("shallow", "pedagogical_depth"), ("missing_mechanism", "pedagogical_depth"),
                                ("incomplete_interpretation", "solution_completeness"),
                                ("missing_solution", "requires a complete solution cell"),
                                ("fragmented", "incomplete or invalid"),
                                ("unsupported_execution", "unverified execution claim")):
            with self.subTest(fault=fault):
                provider = FixtureProvider(SPARK_ANSWERS, worked=fault != "shallow", quality_issue=fault)
                result = await generate(bundle, REQUEST, provider)
                self.assertEqual(result["state"], "partial")
                self.assertTrue(any(expected in issue for issue in result["verification"]["findings"]))
                if fault in {"shallow", "missing_mechanism", "incomplete_interpretation"}:
                    self.assertEqual(provider.calls, ["plan", "generate", "review", "repair", "review"])
                    self.assertEqual(min(r["score"] for r in result["verification"]["reviewer"]["rubric"]), 1)
                else:
                    self.assertEqual(provider.calls, ["plan", "generate"])
        checkpoint = MemoryCheckpoint()
        provider = FixtureProvider(SPARK_ANSWERS, worked=True, quality_issue="recover_mechanism")
        event = AsyncMock()
        result = await generate(bundle, REQUEST, provider, checkpoint=checkpoint, event=event)
        self.assertEqual(result["state"], "approved", result["verification"])
        self.assertEqual(provider.calls, ["plan", "generate", "review", "repair", "review"])
        drafts = [row["payload"] for row in checkpoint.data["versions"] if row["document_version"] == "sections"][0]
        repaired = [row["payload"] for row in checkpoint.data["versions"] if row["document_version"] == "repair"][0]["sections"]
        self.assertEqual([row["section_id"] for row in repaired], [drafts[6]["section_id"]])
        self.assertNotEqual(repaired[0]["markdown"], drafts[6]["markdown"])
        before = next(call.args[1] for call in event.await_args_list if call.args[1]["state"] == "review_pending")

        def content_by_id(doc):
            return {row["section_id"]: doc["document_markdown"][row["markdown_start"]:row["markdown_end"]]
                    for row in doc["sections"] if row["section_id"] != drafts[6]["section_id"]}

        self.assertEqual(content_by_id(before), content_by_id(result))
        if out := os.getenv("SOCRA_PHASE7_OUTPUT_DIR"):
            records = [{key: value for key, value in row.items() if key != "packet"} for row in provider.requests]
            Path(out, "spark-offline-repair-dispatch.json").write_text(json.dumps(records, indent=2), encoding="utf-8")

    async def test_orange_original_workflow_and_fallback(self):
        bundle = await self.bundle("orange")
        doc, pages, positioned, indexed, _ = bundle
        intent = classify_document_request("Résous ce TP Orange et KNIME.", source_name=doc["filename"])
        planned, _ = prepare_document_scope(doc["id"], pages, positioned, indexed, intent)
        self.assertEqual([row.section.target.number for row in planned
                          if row.section.target and row.section.target.kind == "question"], list("123456"))
        self.assertEqual(sum(row.section.title.startswith("Capture ") for row in planned), 5)
        appendix = next(row for row in planned if row.section.title.startswith("Annexe A"))
        self.assertEqual([cell.language for cell in appendix.cells], ["python", "powershell"])
        self.assertIn("df.to_csv('data/transactions.csv', index=False)", appendix.cells[0].code)
        self.assertIn("python donnees.py", appendix.cells[1].code)
        self.assertFalse(any(row.source_issues for row in planned))
        solve = FixtureProvider()
        guide = FixtureProvider()
        result = await generate(bundle, "Résous ce TP Orange et KNIME.", solve)
        guided = await generate(bundle, "Guide-moi dans ce TP Orange et KNIME.", guide)
        self.assertEqual(result["intent"]["action"], "solve")
        self.assertEqual(guided["intent"]["action"], "guide")
        self.assertEqual(result["state"], "approved", result["verification"])
        self.assertEqual(guided["state"], "approved", guided["verification"])
        self.assertEqual(solve.calls, ["plan", "generate", "generate", "review"])
        self.assertEqual(guide.calls, solve.calls)

    async def test_chapter_scenario_uses_distinct_intent_and_course_source(self):
        bundle = await self.bundle("chapter")
        for (prompt, label), expected in zip(FRENCH_CASES, ("summarize", "explain", "explain", "explain", "revise")):
            with self.subTest(label=label):
                profile = classify_document_request(prompt)
                self.assertEqual(profile.action, expected)
                self.assertEqual(profile.language, "French")
                if label == "beginner":
                    self.assertEqual(profile.audience, "beginner")
                if label == "full_course":
                    self.assertEqual(profile.scope, "whole_document")
                result = await generate(bundle, prompt, FixtureProvider())
                self.assertNotEqual(result["state"], "draft", result["verification"])
                self.assertTrue(result["citations"])
                if label == "full_course":
                    # The actual source keeps the hand-worked Shapley example and audit chapters.
                    self.assertIn(16, {c["span"]["page"] for c in result["citations"]})
                    self.assertIn(30, {c["span"]["page"] for c in result["citations"]})
