import asyncio
import json
import os
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from google.genai.errors import ServerError

from agents import explicateur
from agents.course_lesson import (
    Topic, _body_issue, _equations, _journal_code, _math_complete, _normalize_solution_body, _validate, _worked_math,
    fence_python_code, generate_course_lesson, lesson_mode, lesson_outline,
)
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

    def test_citation_diagnostics_identify_the_failed_check(self):
        target = [Topic("p3", "Contribution", (3,), 1)]
        indexed = {3: SOURCE}
        cases = (
            ([], "missing"),
            ([{"page": 4, "quote": SOURCE}], "page_outside_topic"),
            ([{"page": 3, "quote": "short"}], "quote_too_short"),
            ([{"page": 3, "quote": "Cette longue citation est absente de la source."}], "quote_not_found"),
        )
        for citations, reason in cases:
            with self.subTest(reason=reason):
                record = {"id": "p3", "body": BODY, "citations": citations}
                with self.assertLogs("agents.course_lesson", level="INFO") as captured:
                    accepted, issues = _validate(
                        response([record]), target, indexed, "detailed", "French", set(), request_id="test-request",
                    )
                self.assertEqual((accepted, issues), ({}, ["p3:citation"]))
                self.assertIn("request_id=test-request", captured.output[0])
                diagnostic = "reason=missing" if reason == "missing" else reason
                self.assertIn(diagnostic, "\n".join(captured.output))

    def test_partial_citations_keep_a_topic_with_valid_sources(self):
        target = [Topic("p3", "Contribution", (3, 7), 1)]
        second_source = "Un second extrait décrit la même contribution dans un contexte distinct."
        indexed = {3: SOURCE, 7: second_source}
        record = {
            "id": "p3", "body": BODY,
            "citations": [
                {"page": 3, "quote": SOURCE},
                {"page": 7, "quote": second_source},
                {"page": 9, "quote": SOURCE},
                {"page": 3, "quote": "citation courte"},
            ],
        }
        with self.assertLogs("agents.course_lesson", level="DEBUG") as captured:
            accepted, issues = _validate(response([record]), target, indexed, "standard", "French", set())
        self.assertEqual(issues, [])
        self.assertEqual(accepted["p3"][1], [3, 7])
        self.assertIn("accepted=2", captured.output[0])
        self.assertIn("'page_outside_topic': 1", captured.output[0])
        self.assertIn("'quote_too_short': 1", captured.output[0])

    def test_topic_headings_are_normalized_and_source_urls_are_allowed(self):
        target = [Topic("p3", "Contribution", (3,), 1)]
        url = "http://127.0.0.1:5000"
        indexed = {3: SOURCE + "\nServeur local : " + url}
        record = {
            "id": "p3",
            "body": f"# Contribution\n\n### Méthode ###\n\n{BODY}\n\nAdresse : {url}",
            "citations": [{"page": 3, "quote": SOURCE}],
        }
        accepted, issues = _validate(response([record]), target, indexed, "standard", "French", set())
        self.assertEqual(issues, [])
        self.assertIn("**Méthode**", accepted["p3"][0])
        self.assertNotIn("# Contribution", accepted["p3"][0])
        self.assertIn(url, accepted["p3"][0])

        record["body"] = f"{BODY}\n\nAdresse : https://example.invalid"
        accepted, issues = _validate(response([record]), target, indexed, "standard", "French", set())
        self.assertEqual(accepted, {})
        self.assertEqual(issues, ["p3:unexpected_link"])

        record["body"] = f"{BODY}\n\n[Serveur]({url})"
        accepted, issues = _validate(response([record]), target, indexed, "standard", "French", set())
        self.assertEqual(accepted, {})
        self.assertEqual(issues, ["p3:unexpected_link"])

    def test_equation_inventory_excludes_scalar_metrics_and_parameters(self):
        topic = Topic("p3", "Tracking", (3,), 1)
        indexed = {3: (
            "f1 = 0.8636\n"
            "n_estimators = 300\n"
            "max_depth = 12\n"
            "score = 2.7 * freq - 2.6 * anciennete"
        )}
        self.assertEqual(
            _equations(topic, indexed),
            ("score = 2.7 * freq - 2.6 * anciennete",),
        )

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
            response([
                row("p6", 6, "Cette autre analyse examine le même mécanisme. " + BODY),
                row("p7", 7, "Pour ce second point, voici une explication complète. " + BODY),
            ]),
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

    async def test_exhaustive_repair_targets_only_rejected_topics(self):
        request = resolve_explain_request("Explique le chapitre 6 de façon exhaustive")
        targets = [
            Topic("p3", "Contribution", (3,), 1),
            Topic("p4", "Mécanisme", (4,), 1),
        ]
        initial = response([
            row("p3", 3, "Pour le sujet p3, voici une explication détaillée. " + BODY),
            row("p4", 4, "Pour le sujet p4, voici une explication détaillée. " + BODY,
                "Citation absente de la source"),
        ])
        repaired = response([
            row("p4", 4, "Pour le sujet p4, voici une explication corrigée et détaillée. " + BODY),
        ])
        llm = Mock()
        llm.bind.return_value.ainvoke = AsyncMock(side_effect=[initial, repaired])
        with (
            patch("agents.course_lesson.get_chat_llm", return_value=llm),
            patch("agents.course_lesson.lesson_outline", return_value=targets),
        ):
            result = await generate_course_lesson(
                DOC, PAGES, INDEXED, MAP, request, model=None, provider="google", api_key=None,
                request_id="offline", deadline=asyncio.get_running_loop().time() + 10,
            )
        self.assertEqual(result.status, "unreviewed")
        self.assertEqual(result.missing, ())
        self.assertIn("Contribution", result.markdown)
        self.assertIn("Mécanisme", result.markdown)
        self.assertEqual(llm.bind.return_value.ainvoke.await_count, 2)

        repair_messages = llm.bind.return_value.ainvoke.await_args_list[1].args[0]
        repair_packet = json.loads(repair_messages[1].content)
        self.assertEqual([target["id"] for target in repair_packet["targets"]], ["p4"])
        self.assertEqual(repair_packet["completed_topics"], ["p3"])
        self.assertEqual([source["page"] for source in repair_packet["indexed_source"]], [4])
        repair_details = json.loads(repair_messages[2].content)
        self.assertEqual([draft["id"] for draft in repair_details["failed_topic_drafts"]], ["p4"])

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

    def test_full_report_solve_is_solutions_mode_without_changing_plain_tp_prompt(self):
        plain = resolve_explain_request("Résous ce TP")
        self.assertNotEqual(lesson_mode(plain), "solutions")
        request = resolve_explain_request("Résous ce TP", format_override="full_document")
        self.assertEqual((request.action, request.scope, lesson_mode(request)),
                         ("solve", "whole_document", "solutions"))
        exercises = resolve_explain_request("Solve all the exercises", format_override="full_document")
        self.assertEqual((exercises.action, exercises.scope, lesson_mode(exercises)),
                         ("solve", "exercises", "solutions"))

    def test_solutions_outline_uses_exercise_inventory(self):
        pages = [f"Exercice {index} : Tâche {index}\n{SOURCE}" for index in range(1, 7)]
        request = resolve_explain_request("Résous ce TP", format_override="full_document")
        topics = lesson_outline(DOC, pages, MAP, request)
        self.assertEqual([topic.title for topic in topics], [f"Exercice {index}" for index in range(1, 7)])
        self.assertEqual([topic.group for topic in topics], [1, 1, 2, 2, 3, 3])
        self.assertNotEqual([topic.id for topic in topics], [item.id for item in lesson_outline(
            DOC, pages, MAP, resolve_explain_request("Explique ce PDF"))])

    def test_fence_python_code_recovers_scripts_shell_and_invalid_blocks(self):
        spark = fence_python_code('Intro\nsc = SparkContext("local")\nprint(sc)\nsc.stop()\nFin')
        self.assertIn("```python", spark)
        self.assertIn('sc = SparkContext("local")', spark)
        shell = fence_python_code("Lancez :\npython ex2_top_mots.py data/test.txt 3\nensuite")
        self.assertIn("```bash", shell)
        self.assertIn("python ex2_top_mots.py data/test.txt 3", shell)
        broken = 'print("hello"\nvalue = 1\nprint(value)'
        flagged = fence_python_code("Exercice 6\n" + broken)
        self.assertIn("python unverified", flagged)
        self.assertIn('print("hello"', flagged)
        self.assertNotIn("```python\nprint", flagged)
        comment = "# comment\nvalue = 1\nprint(value)"
        self.assertEqual(_body_issue(BODY + "\n" + comment, "standard", "French", set()), "unfenced_code")
        repaired = fence_python_code(BODY + "\n" + comment)
        self.assertIsNone(_body_issue(repaired, "standard", "French", set()))
        self.assertIn("```python", repaired)

    def test_unfenced_comment_code_is_repaired_not_dropped(self):
        target = [Topic("ex6", "Exercice 6", (1,), 1)]
        indexed = {1: "Exercice 6 : Affichage\n" + SOURCE}
        body = BODY + "\nnon couvert par le cours\n# comment\nvalue = 1\nprint(value)"
        accepted, issues = _validate(
            response([{"id": "ex6", "body": body, "citations": [{"page": 1, "quote": SOURCE}]}]),
            target, indexed, "solutions", "French", set(),
        )
        self.assertEqual(issues, [])
        self.assertIn("ex6", accepted)
        self.assertIn("```python", accepted["ex6"][0])
        self.assertNotIn("unexpected_link_or_heading", "".join(issues))

    def test_solution_normalization_preserves_code_and_rejects_external_links(self):
        body = (
            "### Méthode\n\n" + BODY + "\n\nNon couvert par le cours. "
            "[PDF](/api/documents/view/lesson-pdf?page=1)\n\n```python\n# ## code heading\nprint(1)\n```"
        )
        normalized = _normalize_solution_body(body)
        self.assertIn("**Méthode**", normalized)
        self.assertNotIn("](/api/documents/view/", normalized)
        self.assertIn("```python\n# ## code heading\nprint(1)\n```", normalized)
        target = [Topic("ex1", "Exercice 1", (1,), 1)]
        indexed = {1: SOURCE}
        record = {
            "id": "ex1", "body": body,
            "citations": [{"page": 1, "quote": SOURCE}],
            "code_blocks": [{"label": "script", "language": "python", "code": "print(1)"}],
        }
        accepted, issues = _validate(response([record]), target, indexed, "solutions", "French", set())
        self.assertEqual(issues, [])
        self.assertIn("**Méthode**", accepted["ex1"][0])
        record["citations"] = []
        accepted, issues = _validate(response([record]), target, indexed, "solutions", "French", set())
        self.assertEqual(issues, [])
        self.assertEqual(accepted["ex1"][1], [1])
        record["body"] = BODY + "\n\nNon couvert par le cours. [PDF](https://example.com/file.pdf)"
        accepted, issues = _validate(response([record]), target, indexed, "solutions", "French", set())
        self.assertEqual(accepted, {})
        self.assertEqual(issues, ["ex1:unexpected_link"])

    async def test_six_exercise_tp_offline_solutions(self):
        pages = [f"Exercice {index} : Tâche {index}\n{SOURCE}" for index in range(1, 7)]
        indexed = dict(enumerate(pages, 1))
        request = resolve_explain_request("Résous ce TP", format_override="full_document")
        topics = lesson_outline(DOC, pages, [], request)
        self.assertEqual(len(topics), 6)

        def solution(topic, *, code=True, broken=False):
            extra = '\nprint("hello"\nvalue = 1\nprint(value)' if broken else ""
            record = {
                "id": topic.id, "body": BODY + " Solution non couvert par le cours." + extra,
                "citations": [{"page": topic.pages[0], "quote": SOURCE}],
            }
            if code:
                record["code_blocks"] = [{"label": "script", "language": "python", "code": "print(1)\nprint(2)"}]
            return record

        llm = Mock()
        groups = [topics[index:index + 2] for index in range(0, 6, 2)]
        llm.bind.return_value.ainvoke = AsyncMock(side_effect=[
            response([solution(topic, broken=topic.title == "Exercice 6") for topic in group])
            for group in groups
        ])
        with patch("agents.course_lesson.get_chat_llm", return_value=llm):
            result = await generate_course_lesson(
                DOC, pages, indexed, [], request, model=None, provider="google", api_key=None,
                request_id="offline", deadline=asyncio.get_running_loop().time() + 20,
            )
        self.assertEqual(result.missing, ())
        for title in (topic.title for topic in topics):
            self.assertIn(title, result.markdown)
        self.assertGreaterEqual(result.markdown.count("```"), 12)
        self.assertIn("python unverified", result.markdown)
        self.assertIn('print("hello"', result.markdown)
        packets = [json.loads(call.args[0][1].content) for call in llm.bind.return_value.ainvoke.await_args_list]
        self.assertEqual([len(packet["targets"]) for packet in packets], [2, 2, 2])
        self.assertIn("Implementation is requested", llm.bind.return_value.ainvoke.await_args_list[0].args[0][0].content)

    async def test_single_exercise_generation_filters_the_inventory(self):
        pages = [f"Exercice {index} : Tâche {index}\n{SOURCE}" for index in range(1, 7)]
        indexed = dict(enumerate(pages, 1))
        prompt = "Résous l'exercice 1"
        exercise_numbers = explicateur._requested_exercise_numbers(prompt, multilingual=True)
        request = resolve_explain_request(prompt, exercise_numbers=exercise_numbers, explicit_exercise=True)
        self.assertEqual(request.task.intent, "solve_single_exercise")
        target = lesson_outline(DOC, pages, [], request)[0]
        llm = Mock()
        llm.bind.return_value.ainvoke = AsyncMock(return_value=response([{
            "id": target.id, "body": BODY + " Solution non couvert par le cours.",
            "citations": [{"page": target.pages[0], "quote": SOURCE}],
            "code_blocks": [{"label": "script", "language": "python", "code": "print(1)"}],
        }]))
        with patch("agents.course_lesson.get_chat_llm", return_value=llm):
            result = await generate_course_lesson(
                DOC, pages, indexed, [], request, model=None, provider="google", api_key=None,
                request_id="offline", deadline=asyncio.get_running_loop().time() + 5,
                exercise_numbers=exercise_numbers,
            )
        self.assertEqual(result.missing, ())
        self.assertEqual(llm.bind.return_value.ainvoke.await_count, 1)
        packet = json.loads(llm.bind.return_value.ainvoke.await_args.args[0][1].content)
        self.assertEqual([item["id"] for item in packet["targets"]], ["ex1"])

    async def test_repair_server_error_retains_initial_valid_sections(self):
        pages = [f"Exercice {index} : Tâche {index}\n{SOURCE}" for index in range(1, 3)]
        indexed = dict(enumerate(pages, 1))
        request = resolve_explain_request(
            "Résous les exercices 1 et 2", exercise_numbers=["1", "2"], explicit_exercise=True,
        )
        topics = lesson_outline(DOC, pages, [], request)
        initial = []
        for topic in topics:
            row_data = {
                "id": topic.id, "body": BODY + f" Solution de l'exercice {topic.id[2:]} non couvert par le cours.",
                "citations": [{"page": topic.pages[0], "quote": SOURCE}],
            }
            if topic.id == "ex1":
                row_data["code_blocks"] = [{"label": "script", "language": "python", "code": "print(1)"}]
            initial.append(row_data)
        llm = Mock()
        llm.bind.return_value.ainvoke = AsyncMock(side_effect=[
            response(initial), ServerError(503, {"error": {"message": "Unavailable"}}),
        ])
        with patch("agents.course_lesson.get_chat_llm", return_value=llm):
            result = await generate_course_lesson(
                DOC, pages, indexed, [], request, model=None, provider="google", api_key=None,
                request_id="offline", deadline=asyncio.get_running_loop().time() + 5,
                exercise_numbers=["1", "2"],
            )
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.missing, ("Exercice 2",))
        self.assertIn("Exercice 1", result.markdown)
        self.assertIn("Sections incomplètes", result.markdown)
        self.assertEqual(llm.bind.return_value.ainvoke.await_count, 2)

        responses = []
        for group in groups:
            payload = response([solution(topic, code=topic.title != "Exercice 4") for topic in group])
            responses.extend((payload, payload))
        llm.bind.return_value.ainvoke = AsyncMock(side_effect=responses)
        with patch("agents.course_lesson.get_chat_llm", return_value=llm):
            incomplete = await generate_course_lesson(
                DOC, pages, indexed, [], request, model=None, provider="google", api_key=None,
                request_id="offline", deadline=asyncio.get_running_loop().time() + 20,
            )
        self.assertEqual(incomplete.missing, ("Exercice 4",))

    async def test_full_document_solve_reaches_lesson_generator(self):
        pages = [f"Exercice {index} : Tâche {index}\n{SOURCE}" for index in range(1, 7)]
        chunks = [{"id": f"c{index}", "page_number": index, "content": page} for index, page in enumerate(pages, 1)]
        lesson = SimpleNamespace(markdown="# Corrigé", status="unreviewed", attempts=1, missing=())
        with (
            patch.object(explicateur, "course_documents", AsyncMock(return_value=[DOC])),
            patch.object(explicateur, "load_owned_explain_pages", AsyncMock(return_value=pages)),
            patch.object(explicateur, "load_explain_course_map", AsyncMock(return_value=[])),
            patch.object(explicateur, "document_inventory_chunks", AsyncMock(return_value=(chunks, "full_document"))),
            patch.object(explicateur, "generate_course_lesson", AsyncMock(return_value=lesson)) as generate,
            patch.object(explicateur, "get_chat_llm", side_effect=AssertionError("normal explainer")),
        ):
            result = await explicateur.run_explicateur({
                "mode": "explain", "student_message": "Résous l'exercice 1",
                "course_id": "course", "user_id": "owner", "explain_document_id": DOC["id"],
                "explain_format": "full_document",
            })
        generate.assert_awaited_once()
        self.assertEqual(generate.await_args.args[4].action, "solve")
        self.assertEqual(lesson_mode(generate.await_args.args[4]), "solutions")
        self.assertEqual(generate.await_args.args[4].task.intent, "solve_single_exercise")
        self.assertEqual(generate.await_args.kwargs["exercise_numbers"], ["1"])
        self.assertEqual(result["course_lesson_status"], "unreviewed")
