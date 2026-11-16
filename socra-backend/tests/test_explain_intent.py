import unittest
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

from agents import explicateur
from agents.explicateur import _bind_sources, _normalize_explanation_payload
from agents.explain_intent import adaptive_prompt, classify_intent


FRENCH_CASES = [
    ("Donne-moi un résumé court de ce cours en français. Présente uniquement les idées essentielles en quelques phrases et au maximum quatre points clés. Ne développe pas chaque chapitre.", "summary"),
    ("Explique-moi les notions principales de ce cours en français, comme si j'étais un étudiant qui découvre le sujet. Pour chaque notion importante, donne une définition claire, une explication intuitive et un exemple tiré du document lorsque c'est possible. Organise la réponse de manière progressive, sans entrer dans tous les détails secondaires.", "standard"),
    ("Je veux apprendre et maîtriser l'intégralité de ce cours. Explique-moi tous les chapitres et toutes les sections dans l'ordre du document, sans omettre les notions importantes. Détaille les définitions, les mécanismes, les formules, les démonstrations, les tableaux et les exemples présents dans le PDF. Pour chaque concept, explique pourquoi il est important, comment il fonctionne et comment l'utiliser. Respecte fidèlement le contenu du cours, cite les pages correspondantes et distingue les informations du document de tes explications complémentaires. Si tu ne peux pas tout couvrir dans une seule réponse, indique précisément ce qu'il reste à expliquer au lieu de prétendre que le cours est terminé.", "full_course"),
    ("Je n'ai aucune connaissance préalable de ce domaine. Explique-moi les bases indispensables de ce cours avec des mots très simples, des analogies et des exemples concrets. Introduis les termes techniques progressivement et vérifie que les notions fondamentales sont comprises avant de passer aux notions avancées.", "beginner"),
    ("Prépare-moi une fiche de révision de ce cours pour un examen. Identifie les définitions, concepts, formules, distinctions et mécanismes essentiels présents dans le document. Organise-les par thème et ajoute des questions de révision sans inventer le contenu de l'examen.", "revision_sheet"),
]


class ExplainIntentTests(unittest.TestCase):
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
