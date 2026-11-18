import json
import os
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from agents import explicateur
from agents.explain_budget import ExplainCallBudget, explain_budget
from agents.explain_planner import build_learning_plan
from agents.explain_lifecycle import UnitOutput
from agents.explain_tagged_output import MAX_TAGGED_BLOCKS, generation_format
from agents.explain_unit_generation import (
    _parse, generate_unit, generation_packet, linked_evidence,
    plan_generation_batch, teaching_findings, unpack_generation_batch,
)
from agents.explain_unit_review import review_units
from agents.explain_verifier import Anchor, Block, Claim, verify_unit
from agents.structured_output import CONTROL
from tests.test_explain_unit_generation import excerpt_rows, records_for
from rag.explain_preparation import prepare_units
from rag.unit_map import bind_chunks, build_unit_map
from worker import chunk_pages


ANSWER = "7c8d7c9c6d747737a13d2d67"
FIXTURES = Path(__file__).parent / "fixtures/explicateur_depth"
LIVE_DIGEST = "883e9dcb7614ca49c21511a3a9ac809946e78bfe89ed574f2d8de253dd16a61d"

# Exact excerpts from the live explanation blocks, reviewed for the four teaching criteria.
LIVE_TEACHING_EVIDENCE = (
    ("un modèle graphique avec plusieurs couleurs", "perturbe la lecture humaine",
     "en éliminant les éléments graphiques superflus", "le contenu textuel sera extrait"),
    ("ces qualificatifs génériques", "n'attire pas l'attention du recruteur",
     "mettant en avant des qualifications clés", "comprendre instantanément le positionnement"),
    ("une simple énumération", "ne peut pas mesurer le niveau réel de maîtrise",
     "illustrer les compétences techniques par des réalisations concrètes et mesurables",
     "mobiliser ses savoir-faire pour résoudre des problématiques"),
    ("les noms d'entreprises, les dates et les intitulés", "ne sait pas quelles responsabilités",
     "les missions réalisées, les outils mobilisés et les résultats obtenus", "apporter des preuves tangibles"),
    ("elle utilise une adresse électronique informelle", "prive le recruteur de canaux de vérification directe",
     "d'adopter une adresse e-mail strictement professionnelle et d'ajouter des liens pertinents",
     "facilite l'accès immédiat à des preuves concrètes"),
    ("exactement le même document", "ne répond pas aux spécificités ni aux attentes particulières",
     "adapter le contenu du CV aux compétences et exigences propres de chaque offre",
     "mettre en avant les aspects du parcours qui font écho aux besoins précis"),
)

# Positive control for the format and review fixtures. Each tuple supplies a problem,
# consequence, fix and rationale in that order, based on the original indexed case.
CORRECTIONS = (
    ("Le modèle graphique multiplie les éléments décoratifs.",
     "Le regard doit se déplacer entre des pictogrammes et des barres au lieu de trouver rapidement l’information utile.",
     "Yassmina devrait adopter des rubriques simples et remplacer les barres par du texte.",
     "Des intitulés explicites aident un recruteur à repérer les compétences et un logiciel ATS à lire leur nom."),
    ("L’accroche décrit surtout des qualités générales.",
     "Ces adjectifs ne renseignent guère sur le type de poste auquel le profil correspond.",
     "Elle devrait rédiger une phrase qui indique la fonction visée et le domaine dans lequel elle sait intervenir.",
     "Le lecteur pourrait ainsi situer la candidature dès les premières lignes et chercher les preuves utiles ensuite."),
    ("Les logiciels apparaissent comme une liste sans indication de leur usage.",
     "Le recruteur ne peut pas distinguer un outil déjà employé dans un projet d’un outil simplement découvert.",
     "Yassmina peut rattacher chaque compétence pertinente à une tâche qu’elle a effectivement réalisée.",
     "La tâche donne une preuve observable du niveau de pratique annoncé."),
    ("Le stage et le projet sont décrits essentiellement par leur nom et leur date.",
     "Le lecteur ne sait donc pas ce que Yassmina a fait personnellement ni ce que son travail a permis d’obtenir.",
     "Elle devrait décrire une mission réelle, l’outil employé, et le résultat qu’elle peut justifier.",
     "Ces éléments permettent d’évaluer sa contribution et de lui poser des questions précises en entretien."),
    ("Des données personnelles occupent de la place et le contact paraît informel.",
     "Les informations utiles à la prise de contact et à la vérification des réalisations deviennent moins visibles.",
     "Yassmina devrait retirer les détails superflus, utiliser une adresse professionnelle et ajouter des liens pertinents.",
     "Le recruteur trouve ainsi un canal de contact clair et peut consulter des preuves de son travail."),
    ("Yassmina adresse le même document à des employeurs qui cherchent des profils différents.",
     "Une expérience pertinente peut alors être noyée parmi des éléments secondaires pour l’offre.",
     "Elle devrait relever les exigences de chaque annonce et réordonner ses réalisations vérifiables en conséquence.",
     "Cette adaptation rend les correspondances entre son expérience et les besoins du poste plus faciles à repérer."),
)


def cv_source(pages):
    units = build_unit_map("cv", pages)["units"]
    rows = chunk_pages([page["text"] for page in pages], positions=True)
    bind_chunks(units, rows)
    records = prepare_units(units, pages, rows, rows, source_hash="fixture")
    plan = build_learning_plan(units, "map", "Explique en détail sans rien omettre", records)
    excerpts = {u["logical_id"]: excerpt_rows(u, rows) for u in units}
    return units, records, plan, excerpts


def tagged_block(kind, text, *, sources="1", items="-", provenance="derived"):
    return f"@@BLOCK kind={kind} provenance={provenance} sources={sources} items={items}\n{text}"


def cv_control(payload, *, copy=False):
    case_terms = ("modèle graphique", "rubrique « Profil »", "SQL et Power BI", "stage dans une entreprise",
                  "adresse électronique informelle", "le même CV")
    blocks = []
    for item, parts, term in zip(payload["checklist"], CORRECTIONS, case_terms, strict=True):
        context = next(source["index"] for source in payload["sources"] if term in source["quote"])
        index = item["sources"][0]
        text = payload["sources"][index - 1]["quote"] if copy else " ".join(parts)
        blocks.append(tagged_block("explanation", text, sources=f"{index},{context}", items=item["id"]))
        blocks.extend(tagged_block(kind, text, sources="-", provenance="supplementary", items=item["id"])
                      for kind, text in zip(("intuition", "source_example", "takeaway"), parts[1:]))
    return "\n".join([f"@@UNIT {payload['unit_id']}", *blocks])


def packet_shape(uid, kinds, *, items=0, sources=1):
    return {"unit_id": uid, "required_blocks": kinds, "checklist": [None] * items, "sources": [None] * sources}


class TaggedOutputTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"EXPLAIN_GENERATION_FORMAT": "tagged"}))

    def test_default_json_and_invalid_flag(self):
        with patch.dict(os.environ):
            os.environ.pop("EXPLAIN_GENERATION_FORMAT")
            self.assertEqual(generation_format(), "json")
            os.environ["EXPLAIN_GENERATION_FORMAT"] = "xml"
            with self.assertRaisesRegex(ValueError, "must be json or tagged"):
                generation_format()

    def test_multi_unit_normalization_repeated_kinds_and_calculation(self):
        text = "Le texte cite @@BLOCK au milieu de la ligne.\nPuis il continue."
        raw = "\n".join(["@@UNIT u1", tagged_block("explanation", text, sources="1,2", items="1"),
                         tagged_block("explanation", "Cadre général.", sources="-", items="2", provenance="supplementary"),
                         "@@UNIT u2", tagged_block("result", "Le résultat est 0,89."),
                         "@@CALC expression=0.43 + 0.46 expected=0.89"])
        packets = [packet_shape("u1", ["explanation"], items=2, sources=2), packet_shape("u2", ["result"])]
        batch = unpack_generation_batch(raw, ["u1", "u2"], packets=packets)
        self.assertTrue(all(not reason for _, reason in batch.values()))
        one, two = (json.loads(batch[uid][0])["blocks"] for uid in ("u1", "u2"))
        self.assertEqual([b["kind"] for b in one], ["explanation", "explanation"])
        self.assertEqual(one[0]["text"], text)
        self.assertEqual(one[0]["claims"], [{"start": 0, "end": len(text), "source_indexes": [1, 2]}])
        self.assertEqual(one[0]["candidate_items"], [1])
        self.assertEqual(one[1]["candidate_items"], [2])
        self.assertEqual(one[1]["claims"], [])
        self.assertEqual(two[0]["calculation"], {"expression": "0.43 + 0.46", "expected": "0.89"})

    def test_truncation_retains_closed_blocks_and_units(self):
        raw = "\n".join(["@@UNIT one", tagged_block("explanation", "Unit one complete."),
                         "@@UNIT two", tagged_block("explanation", "First block complete."),
                         tagged_block("intuition", "Trail")])
        packets = [packet_shape("one", ["explanation"]), packet_shape("two", ["explanation", "intuition"]),
                   packet_shape("three", ["explanation"])]
        batch = unpack_generation_batch(raw, ["one", "two", "three"], "truncated", packets=packets)
        self.assertEqual(batch["one"][1], "")
        self.assertEqual(batch["two"][1], "truncated")
        self.assertEqual(batch["three"], ("", "truncated"))
        self.assertEqual([b["text"] for b in json.loads(batch["two"][0])["blocks"]], ["First block complete."])
        blocks, reason = _parse(raw[raw.index("@@UNIT two"):], packet=packets[1], reason="truncated")
        self.assertEqual((len(blocks), reason), (1, "truncated"))

    def test_malformed_duplicate_missing_and_unknown_units(self):
        block = tagged_block("explanation", "An explanation.")
        one, two = (packet_shape(uid, ["explanation"]) for uid in ("one", "two"))
        self.assertEqual(unpack_generation_batch(f"@@UNIT one\n{block}", ["one", "two"], packets=[one, two])["two"],
                         ("", "missing_batch_unit"))
        self.assertEqual(unpack_generation_batch(f"@@UNIT one\n{block}\n@@UNIT one\n{block}", ["one"], packets=[one])["one"],
                         ("", "duplicate_batch_unit"))
        for raw in (f"@@UNIT unknown\n{block}", f"@@UNITS one\n{block}",
                    "@@UNIT one\n@@BLOCK no\ntext",
                    "@@UNIT one\n" + tagged_block("explanation", "Copied.", provenance="course")):
            with self.subTest(raw=raw):
                normalized, reason = unpack_generation_batch(raw, ["one"], packets=[one])["one"]
                self.assertEqual(reason, "malformed_tagged_output")
                self.assertFalse(normalized and json.loads(normalized)["blocks"])

    def test_rejects_invalid_group_layout_or_packet_indexes(self):
        packet = packet_shape("one", ["explanation", "intuition"], items=2, sources=2)
        first = [tagged_block(kind, "Premier contenu.", items=1) for kind in packet["required_blocks"]]
        second = [tagged_block(kind, "Deuxième contenu.", sources="2", items=2) for kind in packet["required_blocks"]]
        cases = (
            ("missing group", first, "incomplete_tagged_skeleton"),
            ("duplicate group", first * 2, "invalid_tagged_skeleton"),
            ("interleaved groups", [*second, *first], "invalid_tagged_skeleton"),
            ("incorrect kind order", [*reversed(first), *second], "invalid_tagged_skeleton"),
            ("missing kind", [*first, second[0]], "incomplete_tagged_skeleton"),
            ("unsupported kind", [tagged_block("question", "Wrong kind.", items=1), *first[1:], *second],
             "invalid_tagged_skeleton"),
            ("invalid item", [tagged_block("explanation", "Wrong item.", items=3), *first[1:], *second],
             "invalid_checklist_reference"),
            ("multiple item numbers", [tagged_block("explanation", "Wrong item list.", items="1,2"), *first[1:], *second],
             "invalid_tagged_skeleton"),
            ("invalid source", [tagged_block("explanation", "Wrong source.", sources="3", items=1), *first[1:], *second],
             "invalid_claim_index"),
            ("too many blocks", [*first, *second, first[0]], "tagged_block_limit_exceeded"),
        )
        for label, rows, expected in cases:
            with self.subTest(label=label):
                blocks, reason = _parse("\n".join(["@@UNIT one", *rows]), packet=packet)
                self.assertEqual(reason, expected)
                self.assertLessEqual(len(blocks), 4)

    def test_truncated_final_group_keeps_completed_blocks_and_fails_coverage(self):
        packet = packet_shape("one", ["explanation", "intuition"], items=2)
        raw = "\n".join(["@@UNIT one", tagged_block("explanation", "First explanation.", items=1),
                         tagged_block("intuition", "First intuition.", items=1),
                         tagged_block("explanation", "Second explanation.", items=2),
                         tagged_block("intuition", "Unfinished intui", items=2)])
        blocks, reason = _parse(raw, packet=packet, reason="truncated")
        self.assertEqual(reason, "truncated")
        self.assertEqual([b["text"] for b in blocks], ["First explanation.", "First intuition.", "Second explanation."])
        self.assertEqual([b["candidate_items"] for b in blocks], [[1], [1], [2]])

    def test_tagged_safety_ceiling_is_independent_of_packet_size(self):
        packet = packet_shape("one", ["explanation"], items=MAX_TAGGED_BLOCKS + 1)
        raw = "\n".join(["@@UNIT one", *(tagged_block("explanation", "Complete.", items=i)
                                       for i in range(1, MAX_TAGGED_BLOCKS + 2))])
        blocks, reason = _parse(raw, packet=packet)
        self.assertEqual(len(blocks), MAX_TAGGED_BLOCKS)
        self.assertEqual(reason, "tagged_block_limit_exceeded")

    async def test_saved_live_cv_answer_keeps_all_24_blocks_through_production_verification(self):
        path = FIXTURES / "cv-answer-1-live-tagged-response.json"
        envelope = path.read_bytes()
        self.assertEqual(sha256(envelope).hexdigest(), LIVE_DIGEST)
        self.assertIsNone(CONTROL.search(envelope.decode("utf-8")))
        candidate, = json.loads(envelope)["candidates"]
        self.assertEqual(candidate["finishReason"], "STOP")
        raw = candidate["content"]["parts"][0]["text"]
        self.assertIsNone(CONTROL.search(raw))
        pages = json.loads((FIXTURES / "cv-indexed-pages.json").read_bytes())
        units, records, plan, excerpts = cv_source(pages)
        unit = next(u for u in units if u["logical_id"] == ANSWER)
        context = linked_evidence(unit, units, records, excerpts)
        _, packet, _ = generation_packet(unit, records[ANSWER], excerpts[ANSWER], plan, {}, "French", context)
        normalized, error = unpack_generation_batch(raw, [ANSWER], packets=[packet])[ANSWER]
        self.assertEqual(error, "")
        blocks = json.loads(normalized)["blocks"]
        self.assertEqual(len(blocks), 24)
        required = plan["required_items"][ANSWER]
        self.assertEqual(len(required), 6)
        for index, parts in enumerate(LIVE_TEACHING_EVIDENCE, 1):
            group = blocks[(index - 1) * 4:index * 4]
            self.assertEqual([block["kind"] for block in group], packet["required_blocks"])
            self.assertEqual([block["candidate_items"] for block in group], [[index]] * 4)
            self.assertTrue(all(part in group[0]["text"] for part in parts))
        for batch_response in (None, (normalized, "")):
            with self.subTest(batched=batch_response is not None):
                mock = AsyncMock(return_value=(raw, ""))
                draft = await generate_unit(
                    unit, records[ANSWER], excerpts[ANSWER], plan, mock, fits=lambda _: True,
                    continuity={}, language="French", unit_map=units, related=context, batch_response=batch_response,
                )
                self.assertEqual(mock.await_count, int(batch_response is None))
                self.assertEqual([block["text"] for block in draft["blocks"]], [block["text"] for block in blocks])
                self.assertEqual(len(UnitOutput.model_validate(draft).blocks), 24)
                self.assertFalse(draft["interruptions"])
                self.assertFalse(draft["dropped_block_counts"])
                self.assertEqual(set(draft["reviewable_items"]), set(required))
                self.assertEqual(set(draft["missing_item_ids"]), set(required))
                self.assertFalse(any(f["severity"] == "authoritative" for f in draft["findings"]))
                for item_id, offset in zip(required, range(0, 24, 4), strict=True):
                    group = draft["blocks"][offset:offset + 4]
                    self.assertEqual(draft["reviewable_items"][item_id], [block["block_id"] for block in group])
                for parsed, block in zip(blocks, draft["blocks"], strict=True):
                    self.assertEqual(block["provenance"], "derived")
                    source_indexes = parsed["claims"][0]["source_indexes"]
                    self.assertEqual(block["source_indexes"], source_indexes)
                    for index in source_indexes:
                        anchor = draft["sources"][index - 1]
                        self.assertEqual(pages[anchor["page"] - 1]["text"][anchor["start"]:anchor["end"]], anchor["quote"])
        self.assertEqual(path.read_bytes(), envelope)

    async def test_tagged_dispatch_uses_no_schema_and_checks_packet_references(self):
        units, rows, records = records_for([{"text": "II.1 Source methods\nA concrete source statement needs explanation."}])
        unit = units[0]
        uid = unit["logical_id"]
        plan = build_learning_plan(units, "map", "Teach the course", records)
        replies = []

        async def mock(messages):
            p = json.loads(messages[-1].content)
            self.assertIn(f"{uid}: explanation, intuition, source_example, takeaway", messages[0].content)
            self.assertNotIn("Return one JSON object", messages[0].content)
            source = p["sources"][0]["quote"]
            raw = "\n".join([f"@@UNIT {uid}", tagged_block("explanation", source, items="1"),
                             tagged_block("intuition", "Invalid source.", sources="999", items="1")])
            replies.append(raw)
            return SimpleNamespace(content=raw, response_metadata={})

        with patch.object(explicateur, "get_chat_llm", return_value=SimpleNamespace(ainvoke=mock)) as model:
            result, = await explicateur._generate_course_units(
                {"model": "gemini-3.5-flash-lite", "provider": "google"},
                explicateur._ExplainMetrics("test", call_budget=ExplainCallBudget(learning_limit=1)),
                explain_budget("google", "gemini-3.5-flash-lite"), units, records, excerpt_rows(unit, rows),
                plan, units, "English", overview=True, continuity=[], prior_facts=[],
            )
        self.assertEqual(len(replies), 1)
        self.assertIsNone(model.call_args.kwargs["response_schema"])
        self.assertEqual(result["blocks"][0]["source_indexes"], [1])
        self.assertEqual(result["blocks"][0]["claims"][0]["end"], len(result["blocks"][0]["text"]))
        self.assertIn("invalid_claim_index", result["interruptions"])
        self.assertEqual({f["detail"] for f in result["findings"] if f["code"] == "missing_block"},
                         {"intuition", "source_example", "takeaway"})

    def test_supplementary_numbers_are_allowed_only_if_small_or_source_supported(self):
        text = "La portée maximale est de 32,5 mètres."
        unit = {"logical_id": "test", "start": [1, 0], "end": [1, len(text)], "kind": "concept"}
        for sample, flagged in (("Points : " + "; ".join(map(str, range(11))) + " et 32,5 mètres.", False),
                                ("La portée serait de 31,5 mètres.", True),
                                ("La portée est de 99 mètres.", True)):
            with self.subTest(sample=sample):
                findings = verify_unit(unit, [Block("b", "intuition", sample, "supplementary")],
                                       pages={1: text, 2: "99 ailleurs"}, sources=[])
                self.assertEqual("unmarked_hypothetical" in {f.code for f in findings}, flagged)
        finding = verify_unit(unit, [Block("b", "explanation", "7 mètres.", "derived", (Claim(0, 9, (1,)),))],
                              pages={1: text}, sources=[Anchor(1, 0, len(text), text)])
        self.assertIn("unsupported_claim_number", {f.code for f in finding})

    async def test_actual_cv_rejects_six_exact_source_copies_and_reviews_six_substantive_corrections(self):
        units, records, plan, excerpts = cv_source(json.loads((FIXTURES / "cv-indexed-pages.json").read_bytes()))
        unit = next(u for u in units if u["logical_id"] == ANSWER)
        uid = unit["logical_id"]
        context = linked_evidence(unit, units, records, excerpts)
        system, payload, _ = generation_packet(unit, records[uid], excerpts[uid], plan, {}, "French", context)
        self.assertEqual(payload["kind"], "concept")
        self.assertEqual(len(payload["checklist"]), 6)
        self.assertIn("a concrete fix", " ".join(payload["teaching_rules"]))
        self.assertNotIn("networking", " ".join(payload["teaching_rules"]))
        self.assertNotIn("ordering", " ".join(payload["teaching_rules"]))
        self.assertNotIn("correct options", system)
        async def generate(raw):
            return await generate_unit(
                unit, records[uid], excerpts[uid], plan, AsyncMock(return_value=(raw, "")), fits=lambda _: True,
                continuity={}, language="French", unit_map=units, related=context,
            )

        copied = await generate(cv_control(payload, copy=True))
        flags = [f for f in copied["findings"] if f["code"] == "copy_without_explanation"]
        self.assertEqual(len(flags), 6)
        self.assertTrue(all(f["severity"] == "missing" for f in flags))
        draft = await generate(cv_control(payload))
        self.assertFalse(any(f["code"] == "copy_without_explanation" or f["severity"] == "authoritative"
                             for f in draft["findings"]))
        self.assertEqual(draft["verified_facts"], [])
        self.assertEqual(set(draft["reviewable_items"]), set(plan["required_items"][uid]))
        self.assertEqual(len(draft["blocks"]), 24)
        self.assertTrue(all(not b["claims"] and not b["source_indexes"] for b in draft["blocks"]
                            if b["provenance"] == "supplementary"))
        for parts, block in zip(CORRECTIONS, draft["blocks"][::4], strict=True):
            self.assertEqual(len(parts), 4)
            self.assertTrue(all(part in block["text"] for part in parts))

        async def review(purpose, messages, schema):
            self.assertEqual(purpose, "review")
            packet, = json.loads(messages[-1].content)
            self.assertNotIn("networking", " ".join(packet["teaching_rules"]))
            evidence = [{"item_id": item["item_id"], "block_id": item["block_ids"][0],
                         "quote": draft["blocks"][(item["item_id"] - 1) * 4]["text"]}
                        for item in packet["reviewable_items"]]
            return json.dumps({"reviews": [{"unit_id": uid, "pedagogy_score": 3, "findings": [],
                                            "checklist_evidence": evidence}]})

        approved, = await review_units([draft], [unit], records, excerpts[uid], plan, [], review, allow_repair=set())
        self.assertEqual((approved["coverage"], approved["verification"]), ("explained", "reviewed"))
        self.assertEqual(set(approved["semantic_coverage_item_ids"]), set(plan["required_items"][uid]))

    def test_copy_check_compares_one_source_at_a_time_and_skips_problems(self):
        a = Anchor(1, 0, 60, "The input layer receives all attributes from the dataset.")
        b = Anchor(2, 0, 60, "A different phase collects metrics from the final run.")
        text = f"{a.quote} This sentence supplies a link. {b.quote}"
        unit = {"logical_id": "exercise", "kind": "exercise"}
        blocks = [Block("one", "working", text, "derived", (Claim(0, len(text), (1, 2)),)),
                  Block("two", "problem", a.quote, "derived", (Claim(0, len(a.quote), (1,)),))]
        self.assertFalse(teaching_findings(unit, blocks, [a, b], "English"))
        copied_question = Block("three", "working", a.quote, "supplementary")
        self.assertEqual([f.code for f in teaching_findings(
            unit, [copied_question], [a, b], "English", related={a: {"label": "Question 1"}},
        )], ["copy_without_explanation"])

    def test_batch_prompt_includes_each_ordered_skeleton_without_json_response_instructions(self):
        budget = explain_budget("google", "gemini-3.5-flash-lite")
        packets = [("", {"unit_id": uid, "required_blocks": kinds, "checklist": [1], "sources": []}, 100)
                   for uid, kinds in (("one", ["problem", "method"]), ("two", ["criteria", "table"]))]
        size, messages, *_ = plan_generation_batch(packets, budget)
        self.assertEqual(size, 2)
        self.assertIn("one: problem, method\ntwo: criteria, table", messages[0].content)
        self.assertIn("once per item, in ascending item order", messages[0].content)
        self.assertNotIn("Return one JSON object", messages[0].content)
