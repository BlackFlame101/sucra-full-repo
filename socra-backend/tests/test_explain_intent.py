import unittest
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

from agents import explicateur
from agents.explicateur import _bind_sources, _normalize_explanation_payload
from agents.explain_intent import adaptive_prompt, classify_intent
from agents.explain_course import exercise_reference_batches
from agents.explain_tasks import resolve_explain_request
from rag.explain_documents import ExplainSourceError, resolve_explain_sources


FRENCH_CASES = [
    ("Donne-moi un résumé court de ce cours en français. Présente uniquement les idées essentielles en quelques phrases et au maximum quatre points clés. Ne développe pas chaque chapitre.", "summary"),
    ("Explique-moi les notions principales de ce cours en français, comme si j'étais un étudiant qui découvre le sujet. Pour chaque notion importante, donne une définition claire, une explication intuitive et un exemple tiré du document lorsque c'est possible. Organise la réponse de manière progressive, sans entrer dans tous les détails secondaires.", "standard"),
    ("Je veux apprendre et maîtriser l'intégralité de ce cours. Explique-moi tous les chapitres et toutes les sections dans l'ordre du document, sans omettre les notions importantes. Détaille les définitions, les mécanismes, les formules, les démonstrations, les tableaux et les exemples présents dans le PDF. Pour chaque concept, explique pourquoi il est important, comment il fonctionne et comment l'utiliser. Respecte fidèlement le contenu du cours, cite les pages correspondantes et distingue les informations du document de tes explications complémentaires. Si tu ne peux pas tout couvrir dans une seule réponse, indique précisément ce qu'il reste à expliquer au lieu de prétendre que le cours est terminé.", "full_course"),
    ("Je n'ai aucune connaissance préalable de ce domaine. Explique-moi les bases indispensables de ce cours avec des mots très simples, des analogies et des exemples concrets. Introduis les termes techniques progressivement et vérifie que les notions fondamentales sont comprises avant de passer aux notions avancées.", "beginner"),
    ("Prépare-moi une fiche de révision de ce cours pour un examen. Identifie les définitions, concepts, formules, distinctions et mécanismes essentiels présents dans le document. Organise-les par thème et ajoute des questions de révision sans inventer le contenu de l'examen.", "revision_sheet"),
]


class ExplainIntentTests(unittest.TestCase):
    def test_spark_references_are_per_item_and_exclude_weak_front_matter(self):
        pages = ["Étape 1 – Pipeline Spark\nLe VectorAssembler compose les variables.\n"
                 "À analyser – Pourquoi séparer validation et test ?\n"
                 "Étape 2 – Évaluer les prédictions\nPrécision rappel classification.\n"
                 "Exercice A – Régler les classifieurs\nCrossValidator optimise la validation."]
        manifest = {"parts": [{"page_start": 1, "page_end": 1}]}
        course = [
            (1, "Spark MLlib\nPipeline VectorAssembler validation prédictions classifieurs"),
            (2, "Plan du cours\nPipeline VectorAssembler validation prédictions classifieurs"),
            (5, "Construire un pipeline\nVectorAssembler compose les variables."),
            (5, "Construire un pipeline\nVectorAssembler compose les variables dans Spark."),
            (8, "Validation et test\nCrossValidator optimise les classifieurs."),
            (10, "Évaluer les prédictions\nPrécision rappel classification."),
        ]
        references = [{"id": str(index), "document_id": "course", "page_number": page,
                       "filename": "Course.pdf", "content": text} for index, (page, text) in enumerate(course)]
        batches = exercise_reference_batches(pages, manifest, "part", references)
        self.assertEqual([batch["label"] for batch in batches], ["Étape 1", "Analyse 1", "Étape 2", "Exercice A"])
        for batch in batches:
            excerpts = batch["excerpts"]
            self.assertTrue(excerpts)
            numbers = [item["page_number"] for item in excerpts]
            self.assertEqual(numbers, sorted(set(numbers)))
            self.assertNotIn(1, numbers)
            self.assertNotIn(2, numbers)
            self.assertTrue(all(item["snippet"] for item in excerpts))

    def test_selected_source_defaults_and_prompt_overrides(self):
        td = {"id": "td", "filename": "Spark TD.pdf"}
        course = {"id": "course", "filename": "Spark Cours.pdf"}
        other = {"id": "other", "filename": "Autre cours.pdf"}
        documents = [td, course, other]
        defaults = resolve_explain_sources(documents, "Résous la Partie 1 du TD Spark.", "td")
        self.assertEqual(defaults.task_source, td)
        self.assertEqual(defaults.reference_sources, (course, other))
        override = resolve_explain_sources(documents, "Résous Spark TD.pdf en utilisant Spark Cours.pdf.", "other")
        self.assertEqual((override.task_source, override.reference_sources), (td, (course,)))
        excluded = resolve_explain_sources(documents, "Résous le TD sans utiliser d’autres références.", "td")
        self.assertEqual(excluded.reference_sources, ())
        with self.assertRaises(ExplainSourceError):
            resolve_explain_sources(documents, "Résous le TD en utilisant Missing.pdf.", "td")

    def test_shared_action_depth_and_scope(self):
        for prompt, expected in (
            ("Résous les 20 questions du QCM.", ("solve", "standard", "qcm", None)),
            ("Explique le chapitre 6 en détail", ("explain", "detailed", "chapter", 6)),
            ("Résous la Partie 1 du TD Spark en détail", ("solve", "detailed", "part", 1)),
        ):
            with self.subTest(prompt=prompt):
                request = resolve_explain_request(prompt)
                self.assertEqual((request.action, request.depth, request.scope, request.target), expected)

    def test_five_lecture_requests(self):
        for request, intent in FRENCH_CASES:
            with self.subTest(intent=intent):
                profile = classify_intent(request, "en", False, ["Cours_Chapitre6_Explicabilite_Audit.pdf"])
                self.assertEqual(profile.intent, intent)
                self.assertEqual(profile.language, "French")
                self.assertEqual(profile.document_kind, "lecture")
                self.assertIn("Do not add lab checkpoints", adaptive_prompt(profile))
        self.assertEqual(classify_intent(FRENCH_CASES[0][0]).max_points, 4)

    def test_independent_document_kind_and_intent(self):
        cases = [
            ("Give me a short summary", "TP06.pdf", "summary", "lab"),
            ("Explain from scratch", "Research paper.pdf", "beginner", "research_paper"),
            ("Explain the equation step by step", "Course.pdf", "standard", "lecture"),
            ("Explain the methodology in this research paper", "Research paper.pdf", "standard", "research_paper"),
            ("Do not summarize. Explain the proof.", "Course.pdf", "standard", "lecture"),
            ("Aide-moi à résoudre l'exercice 2", "TD02.pdf", "exercise_help", "exercise_sheet"),
            ("Walk me through this lab step by step", "Lab.pdf", "lab_walkthrough", "lab"),
            ("لخص هذا الدرس", "", "summary", "unknown"),
        ]
        for prompt, name, intent, kind in cases:
            with self.subTest(prompt=prompt):
                result = classify_intent(prompt, source_names=[name])
                self.assertEqual((result.intent, result.document_kind), (intent, kind))

    def test_one_sentence(self):
        result = classify_intent("Explain it in one sentence")
        self.assertEqual((result.intent, result.max_sentences), ("summary", 1))
        answer = _normalize_explanation_payload({"sections": [
            {"heading": "Summary", "content": "A model simplifies reality. This is a second sentence."},
        ]}, "short_summary", max_sentences=1)
        self.assertEqual(answer["sections"][0]["content"], "A model simplifies reality.")
        self.assertNotIn("essential bullet points", adaptive_prompt(result))

    def test_conceptual_steps_and_bound_markers(self):
        source = {"document_id": str(UUID(int=1)), "filename": "Cours.pdf",
                  "page_number": 12, "content": "Mesurer le F1 sur le jeu de test."}
        raw = {"citations": [1], "sections": [{
            "heading": "Permutation", "content": "Mesure initiale [1]. Tableau `[1]`. Référence [99].",
            "code": "1. Mesurer le F1\n2. Mélanger la colonne",
            "code_language": "text", "walkthrough": [{"code": "F1 = 0.867", "explanation": "Valeur initiale."}],
        }]}
        result = _bind_sources(_normalize_explanation_payload(raw, "standard"), [source])
        section = result["sections"][0]
        self.assertEqual(section["code"], "")
        self.assertEqual(section["walkthrough"], [])
        self.assertIn("Mesure initiale.", section["content"])
        self.assertIn("[99]", section["content"])
        self.assertIn("[1]", section["content"])
        self.assertIn("1. Mesurer le F1\n2. Mélanger la colonne", section["content"])
        self.assertEqual(result["citations"][0]["page_number"], 12)


class CourseIntentTests(unittest.IsolatedAsyncioTestCase):
    async def test_scoped_chapter_uses_only_verified_owned_source_and_current_map(self):
        document = {"id": str(UUID(int=1)), "filename": "Chapitre6.pdf", "course_id": "course",
                    "content_hash": "current", "index_config": "config", "page_count": 6}
        other = {**document, "id": str(UUID(int=2)), "filename": "Other.pdf"}
        pages = ["Chap.6 – Source", "Chap.6 – Source\nPartie I", "I.1 Section\nPartie III\nPartie IV",
                 "Chap.6 – Source\nPartie II", "Chap.6 – Source\nPartie III", "Chap.6 – Source\nPartie IV"]
        current = {"document_id": document["id"], "document_version": "current",
                   "title": "Spanning summary", "page_start": 3, "page_end": 4}
        maps = [{**current, "document_version": "stale"}, {**current, "document_id": other["id"]}, current]
        base_state = {"course_id": "course", "user_id": "owner", "student_message": "Explique le chapitre 6 en détail"}
        with (
            patch.dict(explicateur.os.environ, {"EXPLAIN_SCOPED_SOURCES": "1", "SOCRA_CHAPTER_MODEL": "chapter-model"}),
            patch.object(explicateur, "course_documents", AsyncMock(return_value=[document, other])),
            patch.object(explicateur, "load_owned_explain_pages", AsyncMock(return_value=pages)) as read,
            patch.object(explicateur, "load_explain_course_map", AsyncMock(return_value=maps)) as get_map,
            patch.object(explicateur, "get_chat_llm", side_effect=AssertionError("Slice A must not generate")),
            patch.object(explicateur, "retrieve_summary_guided_chunks", side_effect=AssertionError("Slice A must not retrieve")),
        ):
            foreign = await explicateur.run_explicateur({**base_state, "explain_document_id": str(UUID(int=3))})
            self.assertNotIn("explain_source_manifest", foreign)
            read.assert_not_called()
            result = await explicateur.run_explicateur({**base_state, "explain_document_id": document["id"], "model": "chat-model"})
        read.assert_awaited_once_with(document, "owner")
        get_map.assert_awaited_once_with(document)
        manifest = result["explain_source_manifest"]
        self.assertEqual(manifest["model"], "chapter-model")
        self.assertEqual([(item["page_start"], item["page_end"]) for item in manifest["parts"]],
                         [(1, 1), (2, 3), (4, 4), (5, 5), (6, 6)])
        mapped = [section for item in manifest["parts"] for section in item["course_map"]]
        self.assertEqual([(row["page_start"], row["page_end"]) for row in mapped], [(3, 3), (4, 4)])
        self.assertIn(f"/api/documents/view/{document['id']}?page=6#page=6", result["explain_manifest_text"])

    async def test_course_uses_one_scoped_generation_per_explicit_part(self):
        document = {"id": str(UUID(int=1)), "filename": "Cours.pdf", "page_count": 7}
        chunks = [{"id": str(page), "document_id": document["id"], "filename": document["filename"],
                   "chunk_index": page - 1, "page_number": page, "content": f"Indexed passage about concept {page}."}
                  for page in range(1, 8)]
        maps = [{"document_id": document["id"], "page_start": page, "page_end": page,
                 "title": f"Concept {page}", "summary": "prediction probability audit evidence example"}
                for page in range(1, 8)]
        model = AsyncMock(return_value=SimpleNamespace(content=json.dumps({
            "definition": "", "intuition": "", "citations": [1],
            "sections": [{"heading": "Concept 1", "content": "", "source_indexes": [1]}],
        }), response_metadata={}))
        retrieval = AsyncMock(return_value=[chunks[0]])
        with patch.dict(explicateur.os.environ, {"EXPLAIN_INTENT_PLANS": "1"}), \
                patch.object(explicateur, "course_documents", AsyncMock(return_value=[document])), \
                patch.object(explicateur, "document_inventory_chunks", AsyncMock(return_value=(chunks, "full_document"))), \
                patch.object(explicateur, "get_current_course_sections", AsyncMock(return_value=maps)), \
                patch.object(explicateur, "retrieve_summary_guided_chunks", retrieval), \
                patch.object(explicateur, "get_chat_llm", return_value=SimpleNamespace(ainvoke=model)):
            state = {"course_id": "fixture", "user_id": "fixture", "student_message": "Explain the whole course",
                     "request_id": str(UUID(int=2))}
            first = (await explicateur.run_explicateur(state))["explanation"]["course_progress"]
            model.assert_awaited_once()
            self.assertNotIn("Indexed passage about concept 7.", model.call_args.args[0][-1].content)
            self.assertEqual(first["sections"][0]["status"], "missing")
            self.assertEqual(first["sections"][-1]["status"], "not_yet_generated")
            self.assertEqual(sum(first["counts"].values()), 7)
            second = (await explicateur.run_explicateur({
                **state, "request_id": first["next_request_id"], "explain_course_prior": first,
            }))["explanation"]["course_progress"]
            self.assertEqual(model.await_count, 2)
            retrieval.assert_awaited_once()
            self.assertIn("Indexed passage about concept 7.", model.call_args.args[0][-1].content)
            self.assertEqual(second["part"], 2)
            self.assertEqual(second["sections"][0]["status"], "missing")
