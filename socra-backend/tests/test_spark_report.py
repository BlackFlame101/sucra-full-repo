import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from agents import explicateur
from agents.explain_course import scoped_source_manifest
from agents.explain_tasks import resolve_explain_request
from agents.spark_report import EXERCISE_CODE, Unit, correct_step_five, generate_spark_report, spark_part_one
from rag.explain_documents import rank_reference_chunks


class SparkReportTests(unittest.IsolatedAsyncioTestCase):
    def test_natural_solve_phrasings_share_the_same_scope(self):
        for prompt in (
            "Résous la Partie 1 du TD Spark en détail en utilisant Spark_MLlib_Cours_Sbihi.pdf.",
            "Peux-tu corriger la partie 1 avec le cours ?",
            "Can you work through part 1 in English?",
            "Complete Part 1 and explain the answers.",
        ):
            with self.subTest(prompt=prompt):
                request = resolve_explain_request(prompt)
                self.assertEqual((request.action, request.scope, request.target), ("solve", "part", 1))

    @unittest.skipUnless(os.getenv("SOCRA_SPARK_FIXTURE"), "Provide the local Spark TD")
    async def test_actual_pdf_layout_and_corrected_code(self):
        from worker import chunk_pages, extract_code_layout, extract_pages

        data = Path(os.environ["SOCRA_SPARK_FIXTURE"]).read_bytes()
        layout = await extract_code_layout(data)
        document = {"id": "td", "content_hash": "fixture", "index_config": "current"}
        manifest = scoped_source_manifest(document, [p["text"] for p in layout], "part", 1, [])
        self.assertEqual(manifest["prerequisite_pages"], [1])
        part, = manifest["parts"]
        self.assertEqual((part["page_start"], part["page_end"]), (2, 5))
        units = spark_part_one(layout, part)
        self.assertEqual([u.code_pages for u in units if u.code], [(2,), (2,), (3,), (3, 4), (4, 5), (5,)])
        self.assertEqual(sum(u.key.startswith("a") for u in units), 5)
        self.assertEqual(units[-1].key, "exercise")
        original = next(u.code for u in units if u.key == "s5")
        with self.assertRaisesRegex(SyntaxError, "keyword argument repeated"):
            compile(original, "<original>", "exec")
        corrected = correct_step_five(original)
        self.assertEqual(len(original) - len(corrected), len('labelCol="fraude", '))
        compile(corrected, "<corrected>", "exec")
        compile(EXERCISE_CODE, "<exercise>", "exec")
        if course_path := os.getenv("SOCRA_SPARK_COURSE_FIXTURE"):
            course = await extract_pages(Path(course_path).read_bytes())
            refs = [{**chunk, "document_id": "course"} for chunk in chunk_pages(course)]
            ranked = rank_reference_chunks(units[-1].text, refs, limit=2, prefer_content=True)
            self.assertTrue(ranked)
            self.assertTrue(all(ref["page_number"] > 3 for ref in ranked))
        else:
            refs = []

        td = {**document, "filename": "TP4_Spark_MLlib.pdf", "content_hash": sha256(data).hexdigest(), "page_count": len(layout)}
        course_document = {**document, "id": "course", "filename": "Spark_MLlib_Cours_Sbihi.pdf"}
        with (
            patch.dict("os.environ", {"EXPLAIN_SPARK_REPORT": "1", "EXPLAIN_SCOPED_SOURCES": "1",
                                     "SOCRA_SPARK_MODEL": "gemini-3.5-flash-lite"}),
            patch.object(explicateur, "course_documents", AsyncMock(return_value=[course_document, td])),
            patch("worker.download_document", AsyncMock(return_value=data)) as download,
            patch("worker.extract_code_layout", AsyncMock(return_value=layout)),
            patch.object(explicateur, "load_explain_course_map", AsyncMock(return_value=[])),
            patch.object(explicateur, "load_reference_chunks", AsyncMock(return_value=refs)) as reference,
            patch.object(explicateur, "generate_spark_report", AsyncMock(return_value=("# Rapport", "unreviewed", 3))) as generate,
        ):
            result = await explicateur.run_explicateur({
                "mode": "explain", "student_message": "Résous la Partie 1 en utilisant Spark_MLlib_Cours_Sbihi.pdf.",
                "course_id": "course-id", "user_id": "owner", "explain_document_id": "td",
            })
        download.assert_awaited_once_with(td, "owner")
        reference.assert_awaited_once_with("course-id", "owner", (course_document,))
        self.assertEqual(generate.await_args.args[0], units)
        self.assertEqual(generate.await_args.kwargs["model"], "gemini-3.5-flash-lite")
        self.assertEqual(result["course_lesson_text"], "# Rapport")

    async def test_batch_order_references_dedup_and_streaming(self):
        refs = [{"id": "course-chunk", "document_id": "course", "page_number": 42,
                 "content": "Validation et classification sur une partition distincte des données de test."}]
        task = "Validation et classification sur une partition indépendante."
        units = [Unit("s1", "Étape 1", (2,), task, "print(1)", (2,)),
                 Unit("a1", "Analyse 1", (3,), task),
                 Unit("exercise", "Exercice A", (5,), task)]
        llm = Mock()
        preview = AsyncMock()
        progress = AsyncMock()

        async def reply(messages):
            packet = json.loads(messages[1].content)
            key = packet[0]["id"]
            evidence = [{"id": 1, "quote": refs[0]["content"]}] if key == "a1" else [{"id": 1, "quote": "unsupported quote here"}]
            return SimpleNamespace(content=json.dumps({"answers": [{
                "id": key, "explanation": "On entraîne le modèle sur un jeu puis on vérifie ses prédictions sur "
                "la partition de validation. La sélection utilise ce jeu et le score final est calculé sur le test.",
                "evidence": evidence,
            }]}))

        llm.bind.return_value.ainvoke = AsyncMock(side_effect=reply)
        with patch("agents.spark_report.get_chat_llm", return_value=llm):
            markdown, status, attempts = await generate_spark_report(
                units, refs, "td", [1], language="French", model=None, provider="google", api_key=None,
                request_id="offline", deadline=asyncio.get_running_loop().time() + 10, preview=preview, progress=progress,
            )
        self.assertEqual((status, attempts, preview.await_count, progress.await_count), ("unreviewed", 3, 3, 3))
        self.assertEqual(markdown, "".join(call.args[0] for call in preview.await_args_list))
        self.assertEqual(markdown.count("course?page=42"), 1)
        self.assertEqual(markdown.count("Proposition du modèle"), 2)
        self.assertIn("td?page=1", markdown)
        self.assertIn("métriques sont à mesurer", markdown)
        self.assertFalse(llm.bind.call_args.kwargs.get("tools"))
        self.assertTrue(llm.bind.call_args.kwargs["automatic_function_calling"]["disable"])
