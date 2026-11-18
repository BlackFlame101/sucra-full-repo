import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from time import monotonic
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from agents import explicateur
from agents.explain_arithmetic import arithmetic, displayed_equations
from agents.explain_course import part_progress, plan_course, resume_unit_part, unit_excerpts
from rag import explain_documents
from rag.explain_preparation import prepare_units
from rag.unit_map import bind_chunks, build_unit_map
from tests.test_pdf_worker import WorkerFixture, fixture_pdf
import worker


def map_text(*pages):
    return build_unit_map("doc", [{"text": page} for page in pages])


class UnitMapTests(unittest.TestCase):
    def test_repeated_choices_and_genuine_roman_sections(self):
        units = map_text(
            "I. First topic\nQ1. Pick one\nA. Alpha\nB. Beta\nC. Gamma",
            "D. Delta\nQ2. Pick again\nA. Alpha\nB. Beta\nC. Gamma\nD. Delta\nC. Genuine section\nSection body",
        )["units"]
        self.assertEqual([(u["label"], u["kind"]) for u in units],
                         [("I", "transition"), ("Q1", "exercise"), ("Q2", "exercise"), ("C", "transition")])
        self.assertEqual(units[1]["end"], units[2]["start"])

    def test_recaps_are_non_teaching(self):
        for title in ("À retenir et prochaine étape", "Résumé du chapitre", "Key takeaways"):
            with self.subTest(title=title):
                units = map_text(f"II.1 Explanation\nBody text\nII.2 {title}\nReview text")["units"]
                self.assertEqual(units[-1]["kind"], "summary")
                for unit in units:
                    unit["evidence_spans"] = []
                parts, _ = plan_course({"id": "doc"}, [], [], False, 16_000, units=units)
                self.assertEqual([unit["title"] for part in parts for unit in part], ["Explanation"])

    @patch("rag.unit_map.MAX_UNIT_CHARS", 100)
    def test_oversized_unit_prefers_subsection_then_source_marker_then_page_boundary(self):
        before = "II.1 Main topic\n" + "a" * 25 + "\n"
        with self.subTest(boundary="subsection before optional split"):
            prefix = before + "Figure 1\n" + "b" * 30 + "\n"
            units = map_text(prefix + "II.1.1 Details\n" + "c" * 75)["units"]
            self.assertEqual(len(units), 2)
            self.assertEqual(units[0]["end"], [1, len(prefix)])
            self.assertEqual(units[1]["heading_path"][:-1], units[0]["heading_path"])
        for label in ("Figure 1", "Tableau 1", "Exemple 1"):
            with self.subTest(boundary=label):
                first_page = before + label + "\n" + "b" * 25
                units = map_text(first_page, "c" * 60)["units"]
                self.assertEqual(units[0]["end"], [1, len(before)])
                self.assertEqual(units[1]["start"], units[0]["end"])
                self.assertEqual(units[1]["heading_path"][:-1], units[0]["heading_path"][:-1])
        with self.subTest(boundary="page window without source markers"):
            first_page = before + "b" * 32
            units = map_text(first_page, "c" * 60)["units"]
            self.assertEqual([unit["end"] for unit in units], [[1, len(first_page)], [2, 60]])
            self.assertEqual(units[1]["start"], [2, 0])

    def test_tree_trace_and_performance_tradeoff_have_distinct_kinds(self):
        units = map_text("III.2 Arbre peu profond : le chemin d'une décision",
                         "III.3 Performance ou interprétabilité ?")["units"]
        self.assertEqual([unit["kind"] for unit in units], ["figure_walkthrough", "comparison"])

    def test_exercise_questions_and_subquestions(self):
        fixture = Path(__file__).parent / "fixtures/explicateur_depth/dependent_exercise_sheet.txt"
        units = map_text(fixture.read_text(encoding="utf-8"))["units"]
        exercises = [unit for unit in units if unit["kind"] == "exercise"]
        self.assertEqual([unit["label"] for unit in exercises],
                         ["Exercice 1", "(a)", "(b)", "(c)", "Exercice 2", "(a)", "(b)", "Exercice 3"])
        self.assertEqual(len({unit["logical_id"] for unit in exercises}), 8)
        self.assertTrue(all(left["end"] == right["start"] for left, right in zip(units, units[1:])))

    def test_adjacent_repeats_continue_and_separated_repeats_are_siblings(self):
        units = map_text("Exemple\nFirst", "Exemple\nContinued", "II.2 Different heading",
                         "Exemple\nSecond")["units"]
        self.assertEqual([unit["title"] for unit in units], ["Exemple", "Different heading", "Exemple"])
        self.assertEqual(units[0]["continuations"], [[2, 0]])
        self.assertEqual([units[0]["sibling_ordinal"], units[2]["sibling_ordinal"]], [1, 2])
        self.assertNotEqual(units[0]["logical_id"], units[2]["logical_id"])
        self.assertEqual(map_text("front matter", "Exemple\nFirst", "Exemple\nContinued",
                                  "II.2 Different heading", "Exemple\nSecond")["units"][1]["logical_id"],
                         units[0]["logical_id"])

    def test_agenda_uses_prominent_active_part_and_ignores_other_markers(self):
        for numeral, heading in [("II", "Post hoc explanations"), ("III", "Interpretable models")]:
            with self.subTest(part=numeral):
                lines = ["Chapter overview", "II", "Post hoc explanations", "III", "Interpretable models",
                         f"Partie {numeral}", "II.1 Appears in the agenda only"]
                positions = [(470, 36), (302, 24), (303, 24), (225, 24), (227, 24), (400, 32), (210, 20)]
                offset = 0
                runs = []
                for line, (y, size) in zip(lines, positions, strict=True):
                    runs.append((offset, y, size, "test-font"))
                    offset += len(line) + 1
                pages = [{"text": "\n".join(lines), "runs": runs, "height": 540}]
                units = build_unit_map("agenda", pages)["units"]
                self.assertEqual([(unit["label"], unit["title"], unit["kind"]) for unit in units],
                                 [(numeral, heading, "transition")])

    def test_overlap_assigns_each_chunk_once_with_earliest_tie_break(self):
        units = map_text("Question 1: A\nQuestion 2: B")["units"]
        boundary = units[1]["start"][1]
        chunks = [
            {"chunk_index": 0, "page_number": 1, "start_offset": boundary - 4, "end_offset": boundary + 4,
             "source_offsets": list(range(boundary - 4, boundary + 4)), "content": "12345678"},
            {"chunk_index": 1, "page_number": 1, "start_offset": boundary - 1, "end_offset": boundary + 4,
             "source_offsets": list(range(boundary - 1, boundary + 4)), "content": "12345"},
        ]
        bind_chunks(units, chunks)
        self.assertEqual([unit["chunk_indexes"] for unit in units], [[0], [1]])
        part, _ = plan_course({"id": "doc"}, [], chunks, True, 16_000, units=units)
        self.assertEqual([excerpt["content"] for excerpt in unit_excerpts(part[0], chunks)],
                         ["1234", "1", "5678", "2345"])
        positioned = worker.chunk_pages(["   First\n\n\nSecond  "], positions=True)
        self.assertEqual(positioned[0]["content"], "First\n\nSecond")
        self.assertEqual((positioned[0]["start_offset"], positioned[0]["end_offset"]), (3, 17))

    def test_same_identity_changed_content_becomes_stale(self):
        doc = {"id": "doc", "page_count": 2}
        old_map = map_text("II.1 First\nSome text", "II.2 Second\nOther text")
        new_map = map_text("II.1 First\nChanged text", "II.2 Second\nOther text")
        for skeleton in (old_map, new_map):
            for unit in skeleton["units"]:
                unit["evidence_spans"] = []
        old_parts, old_version = plan_course(doc, [], [], False, 16_000, units=old_map["units"])
        new_parts, new_version = plan_course(doc, [], [], False, 16_000, units=new_map["units"])
        previous = part_progress(old_parts, old_version, "doc", 0,
                                 {item["id"]: "covered" for item in old_parts[0]}, None, None, "English")
        previous["unit_map_version"] = old_map["text_hash"]
        self.assertEqual(resume_unit_part(new_parts, previous), 0)
        updated = part_progress(new_parts, new_version, "doc", 0, {}, previous, None, "English")
        changed, stable = updated["sections"]
        self.assertEqual(changed["id"], previous["sections"][0]["id"])
        self.assertTrue(changed["stale"])
        self.assertEqual(changed["status"], "not_yet_generated")
        self.assertEqual(stable["status"], "covered")


class RealDocumentUnitMapTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_pdf_boundary_and_evidence_regression(self):
        directory = os.getenv("SOCRA_FOUR_PDF_DIR")
        if not directory:
            self.skipTest("SOCRA_FOUR_PDF_DIR was not supplied")
        names = {
            "course": "Cours_Chapitre6_Explicabilite_Auditabilite.pdf",
            "cv": "TD N° 3 ANALYSE CV.pdf",
            "revision": "TD de révision.pdf",
            "spark": "TP4_Spark_MLlib.pdf",
        }
        for document, filename in names.items():
            with self.subTest(document=document):
                raw = (Path(directory) / filename).read_bytes()
                pages = await worker.extract_pages(raw, layout=True, evidence=True)
                texts = [page["text"] for page in pages]
                skeleton = build_unit_map(document, pages)
                self.assertEqual(skeleton, build_unit_map(document, await worker.extract_pages(raw, layout=True)))
                units = skeleton["units"]
                positioned = worker.chunk_pages(texts, positions=True)
                bind_chunks(units, positioned)
                records = prepare_units(units, pages, positioned, worker.chunk_pages(await worker.extract_pages(raw)),
                                        source_hash=hashlib.sha256(raw).hexdigest())
                by_label = {unit["label"]: unit for unit in units}
                for unit in units:
                    for item in records[unit["logical_id"]]["checklist"]:
                        for anchor in item["anchors"]:
                            page, start, end = (anchor[k] for k in ("page", "start", "end"))
                            self.assertEqual(anchor["quote"], texts[page - 1][start:end])
                            self.assertLessEqual(tuple(unit["start"]), (page, start))
                            self.assertLessEqual((page, end), tuple(unit["end"]))

                def record(label):
                    return records[by_label[label]["logical_id"]]

                def checklist(label):
                    return [item["text"] for item in record(label)["checklist"]]

                if document == "cv":
                    self.assertIn("Yassmina est", " ".join(checklist("Étude de cas")))
                    for number in (1, 2):
                        question, answer = f"Question {number}", f"Réponse {number}"
                        self.assertEqual(by_label[question]["start"][0], 1)
                        self.assertEqual(by_label[answer]["start"][0], 2)
                        self.assertEqual(record(question)["depends_on"], [by_label["Étude de cas"]["logical_id"]])
                        self.assertEqual(record(answer)["depends_on"], [by_label[question]["logical_id"]])
                        self.assertTrue(checklist(question)[0].endswith("."))
                elif document == "revision":
                    questions = [u["label"] for u in units if re.fullmatch(r"Q\d+", u["label"])]
                    self.assertEqual(questions, [f"Q{i}" for i in range(1, 21)])
                    self.assertFalse(any(u["kind"] == "transition" for u in units))
                    for label in questions:
                        stem, *choices = checklist(label)
                        self.assertTrue(stem.endswith("?"), stem)
                        self.assertEqual([choice[:2] for choice in choices], ["A.", "B.", "C.", "D."])
                        self.assertEqual(by_label[label]["start"][0], by_label[label]["end"][0])
                elif document == "spark":
                    self.assertEqual([u["label"] for u in units if u["kind"] == "lab_step"],
                                     [f"Étape {i}" for i in range(11)])
                    self.assertNotIn("12.0", by_label)
                    step_two = " ".join(checklist("Étape 2"))
                    for literal in ("StructType", ".schema(schema_tx)", "printSchema", "multiLine=True"):
                        self.assertIn(literal, step_two)
                    step_seven = " ".join(checklist("Étape 7"))
                    for literal in ("12.0", "1.25", "6.0", "35.0", "F.randn(34)", "duree_min"):
                        self.assertIn(literal, step_seven)
                    self.assertFalse(any(gap["kind"] == "figure" and gap["page"] in {2, 3}
                                         for entry in records.values() for gap in entry["unresolved"]))
                else:
                    self.assertEqual(len(units), 33)
                    self.assertEqual([u["label"] for u in units if u["kind"] == "transition"], ["I", "II", "III", "IV"])
                    self.assertEqual(by_label["II.3"]["kind"], "worked_calculation")
                    self.assertEqual(sum(len(r["checklist"]) for r in records.values()), 288)
                    checks = [(number, sides) for number, text in enumerate(texts, 1)
                              for _, sides in displayed_equations(text)]
                    self.assertEqual(len(checks), 8)
                    self.assertEqual(sum(number == 16 for number, _ in checks), 7)
                    for _, sides in checks:
                        for side in sides[1:]:
                            self.assertAlmostEqual(arithmetic(sides[0]), arithmetic(side))


class PagedIndexTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_index_and_missing_or_superseded_second_page(self):
        document = {"id": "doc", "page_count": 1, "index_chunk_count": 502, "index_generation": 4}
        rows = [{"id": str(index), "document_id": "doc", "page_number": 1,
                 "chunk_index": index, "content": "Indexed source."} for index in range(502)]
        for tail, expected_scope in [(rows[500:], "full_document"), (rows[501:], "retrieved_only"),
                                     ([], "retrieved_only")]:
            with self.subTest(scope=expected_scope), patch.dict(worker.os.environ, {"EXPLAIN_UNIT_PIPELINE": "1"}):
                client, query = MagicMock(), MagicMock()
                client.table.return_value = query
                for name in ("select", "eq", "is_", "limit", "order", "gt"):
                    getattr(query, name).return_value = query
                query.execute.side_effect = [SimpleNamespace(data=rows[:500], count=502),
                                             SimpleNamespace(data=tail, count=None)]
                with patch.object(explain_documents, "get_supabase", return_value=client):
                    result, scope = await explain_documents.document_inventory_chunks("course", "owner", document, [])
                self.assertEqual(scope, expected_scope)
                self.assertEqual(len(result), 502 if scope == "full_document" else 0)
                self.assertEqual(query.eq.call_args_list.count(unittest.mock.call("documents.index_generation", 4)), 2)


class UnitMapWorkerTests(WorkerFixture, unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(shutil.which("node") and (worker.PDF_EXTRACTOR.parents[1] / "node_modules/unpdf").is_dir(),
                         "requires the worker PDF extractor and its pinned Node dependencies")
    async def test_pdf_headings_with_only_size_or_weight_signal(self):
        body = "BT /F1 12 Tf 40 550 Td (An ordinary line of supporting body text.) Tj ET"
        pdf = fixture_pdf([
            "BT /F1 24 Tf 40 730 Td (A larger heading) Tj ET\n" + body,
            "BT /F2 12 Tf 40 730 Td (A bolder heading) Tj ET\n" + body,
        ], raw_streams=True)
        pages = await worker.extract_pages(pdf, layout=True)
        headings = build_unit_map("typography", pages)["units"]
        self.assertEqual([(unit["label"], unit["title"]) for unit in headings],
                         [("", "A larger heading"), ("", "A bolder heading")])
        self.assertEqual(pages[1]["runs"][0][2], pages[1]["runs"][1][2])

    async def test_index_queues_on_both_new_and_reused_paths_only_with_flag(self):
        for reused, enabled in [(False, True), (True, True), (False, False), (True, False)]:
            with self.subTest(reused=reused, enabled=enabled):
                job = self.job | {"pages": ["Some extracted course text."], "content_hash": "digest"}

                async def rpc_call(_job, name, **_fields):
                    return reused if name.startswith("reuse_pdf_index") else True

                with patch.dict(worker.os.environ, {"EXPLAIN_UNIT_PIPELINE": str(int(enabled))}), \
                     patch.object(worker, "job_rpc", AsyncMock(side_effect=rpc_call)) as rpc, \
                     patch.object(worker, "embed_documents", AsyncMock(return_value=[[0.1]])):
                    await worker.process_job(job)
                names = [call.args[1] for call in rpc.await_args_list]
                suffix = "_with_unit_map" if enabled else ""
                self.assertIn("reuse_pdf_index" + suffix, names)
                self.assertEqual("activate_versioned_pdf_index" in names, not reused and not enabled)
                self.assertEqual("activate_pdf_index_with_unit_map" in names, not reused and enabled)
                for call in rpc.await_args_list:
                    if call.args[1].startswith(("reuse_pdf_index", "activate_")):
                        if enabled:
                            self.assertEqual(call.kwargs["extractor_version"], worker.EXTRACTOR_VERSION)
                        else:
                            self.assertNotIn("extractor_version", call.kwargs)

    @unittest.skipUnless(shutil.which("node") and (worker.PDF_EXTRACTOR.parents[1] / "node_modules/unpdf").is_dir(),
                         "requires the worker PDF extractor and its pinned Node dependencies")
    async def test_large_headingless_pdf_publishes_flagged_windows_within_job_limit(self):
        text = "body evidence " * 227
        pdf = fixture_pdf([text] * 300)
        job = self.job | {"kind": "unit_map", "content_hash": hashlib.sha256(pdf).hexdigest()}
        started = monotonic()
        with patch.object(worker, "download_document", AsyncMock(return_value=pdf)), \
             patch.object(worker, "job_rpc", AsyncMock(return_value=True)) as rpc:
            await worker.process_job(job)
        self.assertLess(monotonic() - started, worker.PDF_JOB_TIMEOUT)
        rpc.assert_awaited_once()
        self.assertEqual(rpc.await_args.args[1], "publish_explain_unit_map")
        self.assertEqual(rpc.await_args.kwargs["extractor_version"], worker.EXTRACTOR_VERSION)
        units = rpc.await_args.kwargs["skeleton"]["units"]
        self.assertTrue(all(unit["fallback"] for unit in units))
        self.assertEqual(units[0]["start"], [1, 0])
        self.assertEqual(units[-1]["end"][0], 300)


class UnitMapRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_final_card_reports_contradicted_part_without_repair_calls(self):
        document_id = str(uuid4())
        source = ["I. Source methods\nIntroducing the first part.",
                  "II. Independent review\nIntroducing the second part.",
                  "II.1 Audit trail\nA real audit trail uses recorded evidence and a timestamp."]
        skeleton = build_unit_map(document_id, [{"text": page} for page in source])
        rows = [row | {"id": str(uuid4()), "document_id": document_id, "filename": "Course.pdf", "similarity": 0.0}
                for row in worker.chunk_pages(source, positions=True)]
        bind_chunks(skeleton["units"], rows)
        response = SimpleNamespace(content=json.dumps({
            "definition": "A source-based explanation.",
            "intuition": "Evidence supports an audit.",
            "sections": [{"heading": "Audit trail", "content": "Part I: Independent review.", "source_indexes": [1]}],
            "citations": [1],
        }), response_metadata={})
        invoke = AsyncMock(return_value=response)
        document = {"id": document_id, "filename": "Course.pdf", "page_count": 3, "index_generation": 1}
        with patch.dict(worker.os.environ, {"EXPLAIN_UNIT_PIPELINE": "1", "EXPLAIN_INTENT_PLANS": "1"}), \
             patch.object(explicateur, "retrieve_summary_guided_chunks", AsyncMock(return_value=rows[2:])), \
             patch.object(explicateur, "course_documents", AsyncMock(return_value=[document])), \
             patch.object(explicateur, "document_inventory_chunks", AsyncMock(return_value=(rows, "full_document"))), \
             patch.object(explicateur, "load_or_queue_unit_map", AsyncMock(return_value=skeleton)), \
             patch.object(explicateur, "queue_unit_evidence", AsyncMock()) as preparation, \
             patch.object(explicateur, "get_chat_llm", return_value=SimpleNamespace(ainvoke=invoke)):
            state = await explicateur.run_explicateur({
                "course_id": "course", "user_id": "owner", "explain_document_id": document_id,
                "student_message": "Teach me the entire course in order, all chapters and sections.",
                "provider": "google", "model": "gemini-3.5-flash-lite", "request_id": str(uuid4()),
            })
        card = state["explanation"]
        self.assertEqual(card["sections"][0]["content"], "Part I: Independent review.")
        finding, = card["deterministic_findings"]
        self.assertEqual((finding["code"], finding["unit_id"], finding["source"]["page"]),
                         ("incorrect_part", skeleton["units"][-1]["logical_id"], 2))
        invoke.assert_awaited_once()
        preparation.assert_awaited_once_with("owner", document, [skeleton["units"][-1]["logical_id"]])

    async def test_flagged_course_continues_with_unit_spans_and_unassessed_coverage(self):
        prompt = "Teach me the entire course in order, all chapters and sections, without omitting anything."
        document_id = str(uuid4())
        source = ["Unstructured source evidence. " * 20] * 18
        skeleton = build_unit_map(document_id, [{"text": page} for page in source])
        rows = [row | {"id": str(uuid4()), "document_id": document_id, "filename": "Course.pdf", "similarity": 0.0}
                for row in worker.chunk_pages(source, positions=True)]
        bind_chunks(skeleton["units"], rows)
        response = SimpleNamespace(content=json.dumps({
            "definition": "Course content from the supplied source.",
            "intuition": "The source connects the concepts.",
            "sections": [{"heading": "Page window", "content": "A short explanation from the source."}],
            "citations": [1],
        }), response_metadata={})
        doc = {"id": document_id, "filename": "Course.pdf", "page_count": len(source), "index_generation": 1}
        state = {"course_id": "course", "user_id": "owner", "student_message": prompt,
                 "provider": "google", "model": "gemini-3.5-flash-lite", "request_id": str(uuid4()),
                 "explain_document_id": document_id}
        with patch.dict(worker.os.environ, {"EXPLAIN_UNIT_PIPELINE": "1", "EXPLAIN_INTENT_PLANS": "1"}), \
             patch.object(explicateur, "retrieve_summary_guided_chunks", AsyncMock(return_value=rows[:1])), \
             patch.object(explicateur, "course_documents", AsyncMock(return_value=[doc])), \
             patch.object(explicateur, "document_inventory_chunks", AsyncMock(return_value=(rows, "full_document"))), \
             patch.object(explicateur, "load_or_queue_unit_map", AsyncMock(return_value=skeleton)), \
             patch.object(explicateur, "queue_unit_evidence", AsyncMock()) as preparation, \
             patch.object(explicateur, "get_current_course_sections", AsyncMock()) as legacy, \
             patch.object(explicateur, "get_chat_llm", return_value=SimpleNamespace(ainvoke=AsyncMock(return_value=response))), \
             patch.object(explicateur._ExplainMetrics, "log", autospec=True) as log:
            first = await explicateur.run_explicateur(state)
            progress = first["explanation"]["course_progress"]
            self.assertEqual(progress["part"], 1)
            self.assertEqual(progress["sections"][0]["start_position"], [1, 0])
            self.assertEqual(progress["sections"][0]["status"], "unverifiable")
            self.assertEqual(log.call_args.args[0].retrieval["unit_assessed_count"], 0)
            self.assertIsNone(log.call_args.args[0].retrieval["unit_coverage_missing"])
            after = await explicateur.run_explicateur(state | {
                "explain_course_prior": progress, "request_id": progress["next_request_id"],
            })
            self.assertEqual(after["explanation"]["course_progress"]["part"], 2)
            legacy.assert_not_awaited()
            preparation.assert_not_awaited()
