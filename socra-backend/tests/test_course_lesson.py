import asyncio
import json
import os
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from google.genai.errors import ServerError

from agents import explicateur
from agents.course_lesson import Topic, _journal_code, _math_complete, _validate, _worked_math, generate_course_lesson, lesson_mode, lesson_outline
from agents.explain_tasks import resolve_explain_request


DOC = {"id": "lesson-pdf", "filename": "Chapitre6.pdf", "content_hash": "a", "index_config": "current"}
SOURCE = "Une contribution est la différence entre deux prédictions."
BODY = (
    "Une contribution mesure la différence entre deux prédictions. Pour comprendre cette différence, "
    "on fixe d'abord un point de comparaison, puis on observe la réponse du modèle après l'ajout "
    "de la variable. La différence obtenue dépend du contexte, car les autres variables présentes "
    "peuvent déjà expliquer une partie du résultat."
)
PAGES = ["Chap.6\nPlan"] + [
    page for part in ("I", "II", "III", "IV")
    for page in (f"Chap.6\nPartie {part}", f"{part}.1 Contribution\n{SOURCE}", f"{part}.2 Mécanisme\n{SOURCE}")
]
INDEXED = dict(enumerate(PAGES, 1))
MAP = [{"document_id": DOC["id"], "document_version": "a", "title": "Contributions", "page_start": 3, "page_end": 5}]


def response(rows):
    return SimpleNamespace(content=json.dumps({"topics": rows}), response_metadata={"finish_reason": "STOP"})


def row(topic_id, page, body=BODY, quote=SOURCE):
    return {"id": topic_id, "body": body, "citations": [{"page": page, "quote": quote}]}


class LessonTests(unittest.IsolatedAsyncioTestCase):
    def test_requested_closing_summary_does_not_shorten_main_answer(self):
        for prompt in (
            "Fully explain this pdf and at the end at a summary or a tldr of everything that i need to know",
            "Explique intégralement ce PDF et à la fin donne-moi un résumé.",
        ):
            request = resolve_explain_request(prompt, short_style=True)
            self.assertEqual((request.action, request.scope, lesson_mode(request), request.closing_recap),
                             ("explain", "whole_document", "exhaustive", True))
        request = resolve_explain_request("Explain this", format_override="full_document")
        self.assertEqual((request.scope, lesson_mode(request)), ("whole_document", "exhaustive"))
        request = resolve_explain_request("Fully explain this PDF", format_override="focused")
        self.assertEqual((request.scope, lesson_mode(request)), ("focused", "standard"))

    async def test_single_batch_can_append_closing_recap_without_an_extra_call(self):
        llm = Mock()
        llm.bind.return_value.ainvoke = AsyncMock(return_value=SimpleNamespace(
            content=json.dumps({"topics": [row("source", 1)], "recap": ["Une contribution compare deux prédictions."]}),
            response_metadata={"finish_reason": "STOP"},
        ))
        request = resolve_explain_request("Explique intégralement ce PDF et termine par un résumé.", "fr", True)
        with patch("agents.course_lesson.get_chat_llm", return_value=llm):
            result = await generate_course_lesson(
                DOC, [SOURCE], {1: SOURCE}, [], request, model=None, provider="google", api_key=None,
                request_id="offline", deadline=asyncio.get_running_loop().time() + 5,
            )
        self.assertEqual((result.status, result.attempts), ("unreviewed", 1))
        self.assertTrue(result.markdown.endswith("## À retenir\n\n- Une contribution compare deux prédictions."))

    def test_natural_full_chapter_request_routes_to_exhaustive(self):
        for prompt, scope, target in (
            ("I want a full explanation of everything in course chapitre 5 everything included", "chapter", 5),
            ("Could you fully explain chapter 5?", "chapter", 5),
            ("Explique-moi le chapitre 5 en entier, sans rien oublier.", "chapter", 5),
            ("Je veux une explication complète du chapitre 5.", "chapter", 5),
            ("Fully explain this PDF.", "whole_document", None),
            ("Explain every page of this lecture.", "whole_document", None),
            ("Explain all of it.", "whole_document", None),
            ("Explique-moi intégralement ce document.", "whole_document", None),
            ("Explique tout le cours en français.", "whole_document", None),
        ):
            with self.subTest(prompt=prompt):
                request = resolve_explain_request(prompt, "fr", True)
                self.assertEqual((request.action, request.scope, request.target, lesson_mode(request)),
                                 ("explain", scope, target, "exhaustive"))
        for prompt in (
            "Explain what a Transformer does.", "Fully explain what a Transformer does.",
            "Explique simplement ce que fait un Transformer.",
            "Don't fully explain the whole PDF.", "Résumé court de tout le cours.",
            "Explain only section 2 of chapter 5.",
        ):
            with self.subTest(prompt=prompt):
                request = resolve_explain_request(prompt)
                self.assertFalse(request.action == "explain" and request.depth == "exhaustive"
                                 and request.scope in {"chapter", "whole_document"})

    def test_whole_document_without_map_keeps_all_pages_in_order(self):
        pages = [f"Topic {i}\n{SOURCE}" for i in range(1, 33)]
        request = resolve_explain_request("Fully explain this PDF.")
        outline = lesson_outline(DOC, pages, [], request)
        self.assertEqual([topic.group for topic in outline], [1, 2, 3, 4])
        self.assertEqual([page for topic in outline for page in topic.pages], list(range(1, 33)))

    @unittest.skipUnless(os.getenv("SOCRA_CHAPTER5_FIXTURE"), "Provide the local Chapter 5 PDF")
    async def test_chapter_five_with_preface_plans_four_ordered_batches(self):
        from worker import extract_pages

        path = Path(os.environ["SOCRA_CHAPTER5_FIXTURE"])
        pages = await extract_pages(path.read_bytes())
        request = resolve_explain_request("I want a full explanation of everything in course chapitre 5 everything included")
        topics = lesson_outline({**DOC, "filename": path.name}, pages, [], request)
        self.assertEqual(sorted({topic.group for topic in topics}), [1, 2, 3, 4])
        self.assertEqual([min(topic.pages[0] for topic in topics if topic.group == group) for group in range(1, 5)],
                         [2, 12, 19, 24])
        self.assertEqual(topics[-1].pages, (32,))

    @unittest.skipUnless(os.getenv("SOCRA_CHAPTER6_FIXTURE"), "Provide the local Chapter 6 PDF")
    async def test_actual_pdf_math_validates_meaningful_prose_without_repeating_latex(self):
        from worker import extract_pages

        pages = await extract_pages(Path(os.environ["SOCRA_CHAPTER6_FIXTURE"]).read_bytes())
        indexed = dict(enumerate(pages, 1))
        request = resolve_explain_request("Explique le chapitre 6 en détail")
        topics = {t.id: t for t in lesson_outline(DOC, pages, MAP, request)}
        cases = {
            "p9": ("Un modèle interprétable expose ses coefficients ou ses règles. On peut suivre directement la façon "
                   "dont les entrées influencent la décision. À l'inverse, pour une forêt composée de nombreux arbres, "
                   "une méthode post-hoc estime quelles variables ont le plus pesé et cette estimation doit être vérifiée.",
                   r"\cdots"),
            "p12": ("On mesure le F1 sur les données de test, puis on mélange les valeurs de la colonne du montant. "
                    "Cette permutation conserve la distribution du montant mais rompt son association avec chaque transaction. "
                    "La baisse mesure la dépendance du modèle à la variable. On répète le calcul pour réduire le bruit.",
                    "0.867-0.274=0.593"),
            "p16": ("#### Les deux ordres\n\nOn compare la prédiction de chaque coalition à celle qui précède l'ajout "
                    "de la variable. Le montant apporte une différence quand il arrive en premier et une autre quand il "
                    "arrive après la nuit. La moyenne des deux écarts donne sa contribution. La somme des contributions "
                    "ramène de la valeur de base à la prédiction finale.", "0.12+0.46+0.31&=0.89"),
            "p24": ("La régression relie les variables standardisées au logarithme de la cote de fraude. À variables "
                    "fixes, une hausse d'un écart-type de la fréquence augmente le logit du coefficient correspondant. "
                    "On exponentie cette variation pour obtenir le multiplicateur de cote. La variation de probabilité "
                    "dépend encore de la cote de départ.", "15.64"),
        }
        for topic_id, (body, equation) in cases.items():
            with self.subTest(topic=topic_id):
                topic = topics[topic_id]
                display = _worked_math(topic, indexed, True)
                self.assertIn(equation, display)
                self.assertTrue(_math_complete(f"$$\n{display}\n$$"))
                page = topic.pages[0]
                source = next(line for line in indexed[page].splitlines()[1:]
                              if len(line.strip()) >= 30 and not line.startswith("Prof."))
                records = [row(topic_id, page, body, source)]
                accepted, issues = _validate(response(records), [topic], indexed, "detailed", "French", set())
                self.assertEqual(issues, [])
                self.assertIn(topic_id, accepted)
                if topic_id == "p24":
                    records[0]["body"] += " Une transaction multiplie la cote par 15,64."
                    self.assertEqual(_validate(response(records), [topic], indexed, "detailed", "French", set())[1],
                                     ["p24:unsupported_numeric_claim"])
        code_topic = topics["p30"]
        code_source = next(line for line in indexed[30].splitlines() if line.startswith("mv ="))
        explanation = (
            "Le journal d'audit associe l'alias de production à une version précise. En reliant les métriques "
            "et les artefacts au même run, l'auditeur peut retrouver les éléments effectivement utilisés pour "
            "la décision. Les tags identifient la version et l'empreinte des données pour rendre la vérification reproductible."
        )
        llm = Mock()
        echo = "".join(_journal_code([code_topic], indexed).split())
        llm.bind.return_value.ainvoke = AsyncMock(return_value=response([
            row("p30", 30, "`src/journaliser.py`\n\n```python\n" + code_source + "\n```\n\n"
                + "`" + echo + "`\n\n" + explanation, code_source)
        ]))
        preview = AsyncMock()
        with (
            patch("agents.course_lesson.get_chat_llm", return_value=llm),
            patch("agents.course_lesson.lesson_outline", return_value=[code_topic]),
        ):
            result = await generate_course_lesson(
                DOC, pages, indexed, MAP, request, model=None, provider="google", api_key=None,
                request_id="offline", deadline=asyncio.get_running_loop().time() + 5, preview=preview,
            )
        self.assertEqual(result.status, "unreviewed")
        self.assertEqual(result.markdown.count("```python"), 1)
        self.assertEqual(result.markdown.count(code_source), 1)
        self.assertNotIn(echo, result.markdown)
        self.assertIn("`src/journaliser.py`\n\n```python", result.markdown)
        self.assertIn("```\n\n" + explanation, result.markdown)

    def test_modes_and_language(self):
        for prompt, expected in (
            ("Résume le chapitre 6 en 5 points", "summary"),
            ("Explique le chapitre 6", "standard"),
            ("Explique le chapitre 6 pour un débutant", "beginner"),
            ("Explique le chapitre 6 en détail", "detailed"),
            ("Explique le chapitre 6 de façon exhaustive, sans rien omettre", "exhaustive"),
            ("Fais une fiche de révision du chapitre 6", "revision_sheet"),
        ):
            with self.subTest(prompt=prompt):
                request = resolve_explain_request(prompt)
                self.assertEqual((request.scope, request.target, lesson_mode(request)), ("chapter", 6, expected))
        self.assertEqual(resolve_explain_request("Explain chapter 6 in English.", "fr", True).intent.language, "English")

    def test_ordered_scope_and_course_map(self):
        order = lesson_outline(DOC, PAGES, MAP, resolve_explain_request("Explique le chapitre 6 en détail"))
        self.assertEqual([topic.pages for topic in order], [(3,), (4,), (6,), (7,), (9,), (10,), (12,), (13,)])
        self.assertEqual(order[0].map_titles, ("Contributions",))
        self.assertFalse(order[2].map_titles)

    def test_validation_rejects_shallow_invalid_and_repeated_prose(self):
        target = [Topic("p3", "Contribution", (3,), 1)]
        indexed = {3: SOURCE + "\nP(fraude) = 0,924"}
        cases = [
            (row("p3", 3, "Une contribution."), "prose_length"),
            (row("p3", 4), "citation"),
            (row("p3", 3, BODY, "Cette citation est absente de la source"), "citation"),
            (row("p3", 3, BODY + " Le résultat est $x = 0,924."), "incomplete_equation"),
            (row("p3", 3, BODY), "equation_not_explained"),
            (row("p3", 3, BODY + "\n\n" + BODY), "repeated_prose"),
            (row("p3", 3, BODY + " La source commence par « un extrait."), "unclosed_quotation"),
            (row("p3", 3, BODY + " La suite du calcul est"), "incomplete_sentence"),
        ]
        for record, rule in cases:
            with self.subTest(rule=rule):
                self.assertEqual(_validate(response([record]), target, indexed, "detailed", "French", set()),
                                 ({}, [f"p3:{rule}"]))
        verified, issues = _validate(response([row("p3", 3, BODY + " On lit $P=0{,}924$.")]),
                                     target, indexed, "detailed", "French", set())
        self.assertFalse(issues)
        self.assertEqual(verified["p3"][1], [3])
        verified, issues = _validate(response([row("p3", 3, BODY + "\n\n- Calcul final $P=0{,}924$")]),
                                     target, indexed, "detailed", "French", set())
        self.assertFalse(issues)
        self.assertIn("p3", verified)

    async def test_summary_uses_one_dispatch_and_no_tools(self):
        short = "Les différences entre prédictions indiquent comment les variables contribuent au résultat du modèle."
        llm = Mock()
        llm.bind.return_value.ainvoke = AsyncMock(return_value=response([row("overview", 3, short)]))
        with patch("agents.course_lesson.get_chat_llm", return_value=llm) as factory:
            result = await generate_course_lesson(
                DOC, PAGES, INDEXED, MAP, resolve_explain_request("Résume le chapitre 6 en 5 points"),
                model=None, provider="google", api_key=None, request_id="offline",
                deadline=asyncio.get_running_loop().time() + 1,
            )
        self.assertEqual((result.status, result.attempts), ("unreviewed", 1))
        self.assertIn("page=3#page=3", result.markdown)
        factory.assert_called_once()
        self.assertTrue(factory.call_args.kwargs["single_attempt"])
        self.assertNotIn("tools", llm.bind.call_args.kwargs)
        self.assertEqual(llm.bind.call_args.kwargs["automatic_function_calling"], {"disable": True})
        self.assertIn("at most 5 bullet points", llm.bind.return_value.ainvoke.call_args.args[0][0].content)

    async def test_exhaustive_batches_stream_and_preserve_partial(self):
        preview, progress = AsyncMock(), AsyncMock()
        llm = Mock()
        llm.bind.return_value.ainvoke = AsyncMock(side_effect=[
            response([row("p3", 3), row("p4", 4, BODY + " Ce second exemple illustre le mécanisme.")]),
            response([row("p6", 6, "Cette autre analyse examine le même mécanisme. " + BODY)]),
            RuntimeError("offline failure"),
        ])
        with patch("agents.course_lesson.get_chat_llm", return_value=llm):
            result = await generate_course_lesson(
                DOC, PAGES, INDEXED, MAP,
                resolve_explain_request("Explique le chapitre 6 de façon exhaustive"),
                model=None, provider="google", api_key=None, request_id="offline",
                deadline=asyncio.get_running_loop().time() + 1, preview=preview, progress=progress,
            )
        self.assertEqual((result.status, result.attempts), ("partial", 3))
        self.assertEqual((preview.await_count, progress.await_count), (2, 3))
        self.assertTrue(result.markdown.startswith("".join(call.args[0].rstrip() for call in preview.await_args_list)))
        self.assertIn("IV.2 Mécanisme", result.missing)
        packets = [json.loads(call.args[0][1].content) for call in llm.bind.return_value.ainvoke.await_args_list]
        self.assertEqual(packets[1]["completed_topics"], ["p3", "p4"])
        self.assertEqual([row["page"] for row in packets[1]["indexed_source"]], [6, 7])

    async def test_chapter_route_uses_owned_selected_pdf(self):
        with (
            patch.dict("os.environ", {"EXPLAIN_COURSE_LESSONS": "1", "EXPLAIN_SCOPED_SOURCES": "1"}),
            patch.object(explicateur, "course_documents", AsyncMock(return_value=[DOC, {**DOC, "id": "other"}])),
            patch.object(explicateur, "load_owned_explain_pages", AsyncMock(return_value=PAGES)) as read,
            patch.object(explicateur, "load_explain_course_map", AsyncMock(return_value=MAP)),
            patch.object(explicateur, "document_inventory_chunks", AsyncMock(return_value=([], "retrieved_only"))),
            patch.object(explicateur, "get_chat_llm", side_effect=AssertionError("no model")),
        ):
            result = await explicateur.run_explicateur({
                "mode": "explain", "student_message": "Explique le chapitre 6 en détail",
                "course_id": "course", "user_id": "owner", "explain_document_id": DOC["id"],
            })
        read.assert_awaited_once_with(DOC, "owner")
        self.assertEqual(result["course_lesson_status"], "failed")

    async def test_one_server_retry_keeps_full_order_and_dispatch_cap(self):
        request = resolve_explain_request("Explique le chapitre 6 de façon exhaustive")
        preview = AsyncMock()
        llm = Mock()
        targets = lesson_outline(DOC, PAGES, MAP, request)
        llm.bind.return_value.ainvoke = AsyncMock(side_effect=[
            ServerError(503, {"error": {"message": "Unavailable"}}),
            *[response([row(t.id, t.pages[0], f"Pour le sujet {t.title}, voici le raisonnement. " + BODY)
                        for t in targets if t.group == group]) for group in range(1, 5)],
        ])
        with (
            patch("agents.course_lesson.get_chat_llm", return_value=llm),
            patch("agents.course_lesson.asyncio.sleep", new_callable=AsyncMock) as delay,
        ):
            result = await generate_course_lesson(
                DOC, PAGES, INDEXED, MAP, request, model=None, provider="google", api_key=None,
                request_id="offline", deadline=asyncio.get_running_loop().time() + 20, preview=preview,
            )
        delay.assert_awaited_once_with(2.5)
        self.assertEqual((result.status, result.attempts, result.missing), ("unreviewed", 5, ()))
        self.assertEqual(preview.await_count, 4)
        positions = [result.markdown.index(t.title) for t in targets]
        self.assertEqual(positions, sorted(positions))
