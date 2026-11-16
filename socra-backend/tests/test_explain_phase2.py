"""Offline coverage, source selection, and budget tests for Explain Phase 2."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import HumanMessage

from agents import explicateur
from agents.explain_budget import explain_budget
from rag import explain_documents
from rag.document_inventory import build_inventory

TP = "00000000-0000-0000-0000-000000000011"
OTHER = "00000000-0000-0000-0000-000000000012"
FOREIGN = "00000000-0000-0000-0000-000000000013"
REQUEST = "Walk me through every step of the complete lab, including all screenshots."


def chunk(page, text, document=TP, *, index=None, key=None):
    return {
        "id": key or f"{document}-{page}", "document_id": document, "filename": "Lab.pdf",
        "page_number": page, "chunk_index": page - 1 if index is None else index,
        "content": text, "similarity": 0.9,
    }


def document(document_id=TP, pages=2, filename="Lab.pdf"):
    return {"id": document_id, "filename": filename, "page_count": pages,
            "index_chunk_count": pages, "content_hash": "version", "index_config": "config"}


class DocumentInventoryTests(unittest.TestCase):
    def check_tp(self, index):
        by_id = {item.id: item for item in index.requirements}
        for item in [*(f"screenshot:{i}" for i in range(1, 6)), *(f"question:{i}" for i in range(1, 7))]:
            self.assertEqual(by_id[item].status, "required")
        self.assertIn("appendix:A", by_id)
        for filename in ("fraude-orange.ows", "tp-fraude.knwf", "comparatif.md",
                         "nom_prénom_filière_groupe_tp_lowcode.pdf"):
            self.assertEqual(by_id[f"deliverable:{filename}"].status, "required")
        for number in (1, 2, 3):
            self.assertEqual(by_id[f"bonus:B{number}"].status, "optional")
        self.assertTrue(any(item.kind == "installation" for item in index.requirements))
        self.assertFalse(any(item.kind == "exercise" for item in index.requirements))
        self.assertNotIn("deliverable:donnees.py", by_id)
        self.assertEqual(index.scope, "full_document")

    def test_tp_requirements_from_synthetic_transcribed_structure(self):
        index = build_inventory([
            chunk(1, "Partie 0 : Installation\nÉtape 0.1 : Installer Orange\n1. Créer le dossier."),
            chunk(2, "À FAIRE\nCapture 1 : Fenêtre principale\nCapture 2 : Matrice\nCapture 3 : Workflow"),
            chunk(3, "Capture 4 : KNIME\nCapture 5 : Statistiques\nBonus (facultatifs)\nB1 : Optimisation"),
            chunk(4, "B2 : Variante\nB3 : Comparaison\nPartie IV : Questions d'analyse (obligatoires)\n"
                     "Question 1 : Scores\nQuestion 2 : Contrôles\nQuestion 3 : Limites"),
            chunk(5, "Question 4 : Cible\nQuestion 5 : Comparaison\nQuestion 6 : Analyse\n"
                     "Partie V : Livrables\nRemettre fraude-orange.ows, tp-fraude.knwf et comparatif.md.\n"
                     "Nom du fichier à respecter : Nom_Prénom_Filière_Groupe_TP_lowcode.pdf\n"
                     "Annexe A : Générer les données\nExécutez donnees.py."),
        ], "full_document")
        self.check_tp(index)

    def test_local_tp_extracted_with_the_production_worker(self):
        fixture = Path(__file__).parent / "fixtures/local/phase2_orange_knime_chunks.json"
        if not fixture.is_file():
            self.skipTest("Private local PDF extraction is unavailable; portable TP fixture also runs.")
        rows = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 15)
        self.check_tp(build_inventory([
            {**row, "id": f"chunk-{row['chunk_index']}", "document_id": TP} for row in rows
        ], "full_document"))

    def test_multilingual_inventory_handles_mixed_educational_structures(self):
        rows = [chunk(1, "Chapter 1: Programming assignment\nRequired files: analysis.py\n"
                          "Exercise 1: Implement a parser\n(a) Explain your algorithm\n") ,
                chunk(2, "Chapitre II : Vocabulaire\nExercice 1 : Conjugaison\n"
                          "Figure 2 : Résultat\nTableau 1 : Mesures\nÉquation 3 : E=mc²\n"
                          "Résultats attendus : Valeurs positives\nDépannage : Vérifier le port\nAttention : Sauvegarder"),
                chunk(3, "الفصل ٣: تقرير\nالسؤال ٢: احسب النتيجة\n(أ) اشرح السبب\n"
                          "لقطة الشاشة ٤: النتائج\nالملحق A: المصادر\n"
                          "المخرجات المطلوبة: report.csv\nالمعادلة ٥: x=2\nالسؤال الأول: ماذا لاحظت؟")]
        inventory = build_inventory(rows)
        expected = {"section:1", "section:II", "section:3", "file:analysis.py", "exercise:1",
                    "subquestion:A", "figure:2", "table:1", "formula:3", "question:2",
                    "screenshot:4", "appendix:A", "deliverable:report.csv", "formula:5", "question:1"}
        self.assertTrue(expected <= {item.id for item in inventory.requirements})
        self.assertTrue({"warning", "troubleshooting", "expected_result"} <= {item.kind for item in inventory.requirements})
        self.assertEqual(inventory.scope, "retrieved_only")
        self.assertTrue(all(item.evidence_anchor and item.document_id == TP for item in inventory.requirements))

    def test_repeated_label_keeps_distinct_requirements_and_collapses_chunk_overlap(self):
        rows = [
            chunk(1, "Exercise 1: First task\nQuestion 1: Different subject\nQuestion 1: First measurement", index=0),
            chunk(1, "Question 1: First measurement\nQuestion 1: Second measurement", index=1, key="overlap"),
            chunk(2, "Question 1: First measurement"),
        ]
        questions = [item for item in build_inventory(rows).requirements if item.id == "question:1"]
        self.assertEqual(len(questions), 4)
        self.assertEqual(len({item.key for item in questions}), 4)
        self.assertEqual(build_inventory(rows).as_state(), build_inventory(list(reversed(rows))).as_state())

    def test_numbered_list_does_not_become_exercises(self):
        index = build_inventory([chunk(1, "Part 1: Procedure\n1. Open tools\n2. Select Run\n3. Screenshot the output")])
        self.assertFalse(any(item.kind == "exercise" for item in index.requirements))
        self.assertEqual({item.id for item in index.requirements if item.kind == "step"}, {"step:1", "step:2", "step:3"})


class SourceSelectionTests(unittest.IsolatedAsyncioTestCase):
    def test_named_dominant_and_multi_source_resolution(self):
        docs = [document(), document(OTHER, filename="Math.pdf")]
        rows = [chunk(1, "Evidence"), chunk(2, "Evidence"), chunk(3, "Evidence"), chunk(1, "Other", OTHER)]
        select = explain_documents.select_document
        self.assertEqual(select(docs, "Use Math.pdf.", rows, None, 0.7).reason, "filename")
        self.assertEqual(select(docs, "Explain the lab", rows, None, 0.7).reason, "dominant_retrieval")
        self.assertIsNone(select(docs, "Compare Lab.pdf with Math.pdf.", rows, None, 0.7).document)
        self.assertIsNone(select(docs, "Compare both PDFs.", rows, None, 0.7).document)
        with self.assertRaisesRegex(ValueError, "Which PDF"):
            select(docs, "Explain the lab", rows[2:], None, 0.7)
        with self.assertRaisesRegex(ValueError, "Several PDFs"):
            select([document(), document(OTHER)], "Use Lab.pdf", rows, None, 0.7)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            select(docs, "Explain this specific PDF", rows, FOREIGN, 0.7)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            select(docs[:1], "Explain Missing.pdf.", rows, None, 0.7)

    async def test_complete_ranked_retrieval_reuses_chunks_without_a_query(self):
        rows = [chunk(2, "Question 5: Explain the result."), chunk(1, "Required Questions")]
        with patch.object(explain_documents, "get_supabase") as db:
            actual, scope = await explain_documents.document_inventory_chunks("course", "owner", document(), rows)
        self.assertEqual(actual, rows)
        self.assertEqual(scope, "full_document")
        db.assert_not_called()

    async def test_catalog_read_filters_verified_course_and_owner(self):
        with patch.object(explain_documents, "get_supabase") as db:
            query = MagicMock()
            db.return_value.table.return_value = query
            for method in ("select", "eq", "order", "limit"):
                getattr(query, method).return_value = query
            query.execute.return_value = SimpleNamespace(count=0, data=[])
            self.assertEqual(await explain_documents.course_documents("verified-course", "verified-owner"), [])
            self.assertIn(unittest.mock.call("course_id", "verified-course"), query.eq.call_args_list)
            self.assertIn(unittest.mock.call("courses.user_id", "verified-owner"), query.eq.call_args_list)
            self.assertIn("courses!inner(user_id)", query.select.call_args.args[0])

    async def test_index_read_filters_course_owner_and_index_version(self):
        with patch.object(explain_documents, "get_supabase") as db:
            query = MagicMock()
            db.return_value.table.return_value = query
            for method in ("select", "eq", "is_", "order", "limit"):
                getattr(query, method).return_value = query
            query.execute.return_value = SimpleNamespace(count=0, data=[])
            retrieved = [chunk(1, "Existing source excerpt.")]
            result, scope = await explain_documents.document_inventory_chunks("verified-course", "verified-owner", document(), retrieved)
            self.assertEqual((result, scope), (retrieved, "retrieved_only"))
            for field, value in (("document_id", TP), ("documents.course_id", "verified-course"),
                                 ("documents.courses.user_id", "verified-owner"),
                                 ("documents.content_hash", "version")):
                self.assertIn(unittest.mock.call(field, value), query.eq.call_args_list)
            query.execute.return_value = SimpleNamespace(
                count=2, data=[chunk(1, "Only one returned chunk, even though the exact count was two.")],
            )
            self.assertEqual(
                await explain_documents.document_inventory_chunks("verified-course", "verified-owner", document(), retrieved),
                (retrieved, "retrieved_only"),
            )

    async def test_available_page_numbers_cannot_prove_complete_chunks(self):
        rows = [chunk(1, "Page 1"), chunk(2, "Page 2")]
        self.assertFalse(explain_documents.complete_index(rows, {**document(), "index_chunk_count": 3}))
        self.assertFalse(explain_documents.complete_index(rows, {**document(), "page_count": 3}))
        self.assertFalse(explain_documents.complete_index(rows, {**document(), "index_chunk_count": None}))


class ExplainBudgetTests(unittest.TestCase):
    def test_model_context_and_minute_budget_are_independent(self):
        gemini = explain_budget("google", "gemini-3.5-flash-lite")
        self.assertEqual((gemini.capacity, gemini.max_output_tokens), (200000, 16000))
        for model in ("openai/gpt-oss-120b", "openai/gpt-oss-20b"):
            groq = explain_budget("groq", model)
            self.assertEqual((groq.capacity, groq.max_output_tokens), (6400, 2133))
            messages = [HumanMessage(content="a" * 13000)]
            self.assertFalse(groq.fits(messages, {}))
            self.assertTrue(gemini.fits(messages, {}))
        self.assertIsNone(explain_budget("groq", "unlisted-model"))

    def test_limits_use_the_config_override(self):
        payload = json.loads((Path(__file__).resolve().parents[1] / "explain_model_limits.json").read_text())
        entry = payload["models"][0]
        self.assertIsNone(entry["tokens_per_day"])
        entry.update(context_tokens=5000, tokens_per_minute=20000, max_output_tokens=1000)
        with patch.dict(explicateur.os.environ, {"SOCRA_EXPLAIN_MODEL_LIMITS_JSON": json.dumps(payload)}):
            budget = explain_budget("google", entry["model_id"])
        self.assertEqual((budget.capacity, budget.max_output_tokens), (5000, 1000))


class Phase2ExplainTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch.dict(explicateur.os.environ, {
            "EXPLAIN_TASK_MODES": "1", "EXPLAIN_DOCUMENT_INVENTORY": "1",
            "EXPLAIN_FULL_DOCUMENT": "1", "EXPLAIN_COVERAGE_CHECK": "0",
        }))
        self.rows = [
            chunk(1, "Required Questions (obligatory)\nQuestion 1: Explain the setup and report your conclusions."),
            chunk(2, "Question 5: Explain the result.\nQuestion 6: Describe limitations."),
        ]
        self.retrieval = self.enterContext(patch.object(
            explicateur, "retrieve_summary_guided_chunks", AsyncMock(return_value=self.rows[:1]),
        ))
        self.catalog = self.enterContext(patch.object(
            explicateur, "course_documents", AsyncMock(return_value=[document()]),
        ))
        self.index = self.enterContext(patch.object(
            explicateur, "document_inventory_chunks", AsyncMock(return_value=(self.rows, "full_document")),
        ))
        response = SimpleNamespace(content=json.dumps({
            "definition": "A course-based test definition.",
            "intuition": "Course context is preserved.",
            "sections": [{"heading": "Fixture section", "content": "The fixture has enough content to be useful."}],
            "citations": [1],
        }), response_metadata={})
        self.invoke = AsyncMock(return_value=response)
        self.model = self.enterContext(patch.object(
            explicateur, "get_chat_llm", return_value=SimpleNamespace(ainvoke=self.invoke),
        ))

    async def run_explain(self, topic=REQUEST, **extra):
        return await explicateur.run_explicateur({
            "course_id": "verified-course", "user_id": "verified-owner", "student_message": topic,
            "provider": "google", "model": "gemini-3.5-flash-lite", **extra,
        })

    async def test_focus_does_not_read_catalog_or_change_retrieval_and_model_calls(self):
        await self.run_explain("What does cross-validation mean?")
        self.catalog.assert_not_awaited()
        self.index.assert_not_awaited()
        self.retrieval.assert_awaited_once_with("What does cross-validation mean?", "verified-course", k=20)
        self.invoke.assert_awaited_once()

    async def test_missing_required_evidence_gets_added_with_local_citation_indexes(self):
        result = await self.run_explain()
        self.assertEqual(result["explain_inventory"]["inventory_scope"], "full_document")
        self.assertTrue({"question:5", "question:6"} <= {row["id"] for row in result["explain_inventory"]["requirements"]})
        self.assertEqual(set(result["explain_evidence_chunk_ids"]), {row["id"] for row in self.rows})
        self.assertIn("Question 5", self.invoke.await_args.args[0][1].content)
        self.index.assert_awaited_once_with("verified-course", "verified-owner", document(), self.rows[:1])
        self.invoke.assert_awaited_once()

    async def test_nonprocedural_whole_document_request_also_builds_inventory(self):
        result = await self.run_explain("Teach me everything in the PDF.")
        self.catalog.assert_awaited_once()
        self.index.assert_awaited_once()
        self.assertEqual(result["explain_inventory"]["inventory_scope"], "full_document")

    async def test_unused_index_chunk_does_not_turn_into_full_document_answer_path(self):
        self.rows[1]["content"] = "Appendix A: Additional reference text."
        result = await self.run_explain()
        self.assertEqual(result["explain_inventory"]["inventory_scope"], "full_document")
        self.assertEqual(result["explain_evidence_chunk_ids"], [self.rows[0]["id"]])
        self.assertNotIn("Additional reference", self.invoke.await_args.args[0][1].content)

    async def test_cross_user_and_cross_course_explicit_scope_refuses_before_retrieval(self):
        for owner, course, identifier in (("other-user", "verified-course", TP),
                                          ("verified-owner", "other-course", TP),
                                          ("verified-owner", "verified-course", FOREIGN)):
            self.catalog.side_effect = lambda course_id, user: (
                [document()] if (course_id, user) == ("verified-course", "verified-owner") else []
            )
            with self.assertRaisesRegex(ValueError, "unavailable"):
                await self.run_explain(explain_document_id=identifier, user_id=owner, course_id=course)
        self.retrieval.assert_not_awaited()
        self.index.assert_not_awaited()
        self.model.assert_not_called()

    async def test_ambiguity_asks_for_a_pdf_and_multiple_named_sources_still_work(self):
        self.catalog.return_value = [document(), document(OTHER, filename="Notes.pdf")]
        self.retrieval.return_value = [self.rows[0], chunk(1, "A sufficiently long excerpt from Notes.pdf.", OTHER)]
        with self.assertRaisesRegex(ValueError, "Which PDF"):
            await self.run_explain()
        self.model.assert_not_called()
        result = await self.run_explain("Compare every step of the complete lab in Lab.pdf and Notes.pdf.")
        self.assertEqual(result["explain_inventory"]["inventory_scope"], "retrieved_only")
        self.assertEqual(len(result["explain_evidence_chunk_ids"]), 2)
        self.index.assert_not_awaited()
        self.invoke.assert_awaited_once()

    async def test_tpm_limits_large_excerpts_and_saves_an_explicit_notice(self):
        large = chunk(2, "Question 5: " + "Detailed evidence. " * 800)
        self.retrieval.return_value = [self.rows[0], large]
        self.index.return_value = ([self.rows[0], large], "full_document")
        result = await self.run_explain(provider="groq", model="openai/gpt-oss-20b")
        self.assertEqual(result["explain_evidence_chunk_ids"], [self.rows[0]["id"]])
        self.assertEqual(self.model.call_args.kwargs["max_completion_tokens"], 2133)
        self.assertEqual(self.model.call_args.kwargs["provider"], "groq")
        self.assertEqual(result["explanation"]["sections"][-1]["heading"], "Limited source coverage")
        self.assertIn("Question 5", result["explanation"]["sections"][-1]["content"])
        self.invoke.assert_awaited_once()

    async def test_unknown_limits_do_not_add_missing_chunks_or_switch_provider(self):
        result = await self.run_explain(provider="groq", model="unlisted-model")
        self.assertEqual(result["explain_evidence_chunk_ids"], [self.rows[0]["id"]])
        self.assertEqual(self.model.call_args.kwargs["model"], "unlisted-model")
        self.assertIn("Question 6", result["explanation"]["sections"][-1]["content"])
        self.invoke.assert_awaited_once()

    async def test_large_primary_attempt_leaves_no_second_minute_reservation(self):
        self.rows[0]["content"] += " Additional detail." * 150
        bad = json.loads(self.invoke.return_value.content)
        bad["citations"] = [900]
        self.invoke.return_value.content = json.dumps(bad)
        with self.assertRaisesRegex(ValueError, "token budget was exceeded"):
            await self.run_explain(provider="groq", model="openai/gpt-oss-20b")
        self.invoke.assert_awaited_once()
