import asyncio
import hashlib
import json
import unittest
from types import SimpleNamespace
from unicodedata import normalize
from unittest.mock import AsyncMock, patch

import httpx
from google.genai import _extra_utils

from agents import explicateur
from agents.explain_tasks import is_qcm_solve_request, requested_qcm_ordinals
from agents.qcm_generation import QcmResult, generate_qcm
from graph.orchestrator import get_compiled_graph
from rag.qcm_inventory import ALL_QUESTIONS, FIRST_FIVE, QcmSourceError, build_qcm_inventory


REQUEST = "Résous les cinq premières questions du QCM, avec une justification pour chaque option."
FIRST_PAGE = "En-tête\n\n1\n\n" + "\n\n".join(
    f"Q{number}. Question {number}\nsur deux lignes ?\n\n"
    "A. Première option\nB. Une option\nsur deux lignes\n\nC. Autre choix\nD. Dernier choix"
    for number in range(1, 6)
)
NEXT_PAGE = "En-tête\n\n2\n\nQ6. Hors périmètre"
PDF = b"%PDF- benchmark substitute"
SOURCE_HASH = hashlib.sha256(PDF).hexdigest()
DOCUMENT = {
    "id": "owned-pdf", "filename": "TD.pdf", "course_id": "course",
    "page_count": 2, "content_hash": SOURCE_HASH, "index_config": "test-index",
}
STATE = {"mode": "explain", "student_message": REQUEST, "course_id": "course", "user_id": "owner"}


class InventoryTests(unittest.TestCase):
    def test_first_five_preserve_exact_text_and_page_offsets(self):
        inventory = build_qcm_inventory([FIRST_PAGE, NEXT_PAGE], "owned-pdf", SOURCE_HASH, "test-index")
        self.assertEqual(tuple(item.ordinal for item in inventory.items), (1, 2, 3, 4, 5))
        self.assertEqual(inventory.source_hash, SOURCE_HASH)
        self.assertEqual(inventory.index_version, "test-index")
        for item in inventory.items:
            self.assertEqual(item.exact_question_text, f"Question {item.ordinal}\nsur deux lignes ?")
            self.assertEqual(tuple(option.key for option in item.options), ("A", "B", "C", "D"))
            self.assertEqual(item.options[1].exact_text, "Une option\nsur deux lignes")
            for value, span in [(item.exact_question_text, item.question_span),
                                *((option.exact_text, option.span) for option in item.options)]:
                self.assertEqual(span.page, 1)
                self.assertEqual(FIRST_PAGE[span.start:span.end], value)

    def test_rejects_incomplete_or_ambiguous_sources(self):
        for page in (
            FIRST_PAGE.replace("D. Dernier choix", "", 1),
            FIRST_PAGE.replace("D. Dernier choix", "D. ", 1),
            FIRST_PAGE.replace("D. Dernier choix", "A. Dernier choix", 1),
            FIRST_PAGE.replace("C. Autre choix\nD. Dernier choix", "D. Dernier choix\nC. Autre choix", 1),
            FIRST_PAGE.replace("Q2.", "Q1.", 1),
            FIRST_PAGE.replace("Q3.", "Q9.", 1),
        ):
            with self.subTest(page=page), self.assertRaises(QcmSourceError):
                build_qcm_inventory([page, NEXT_PAGE], "owned-pdf", SOURCE_HASH, "test-index")
        continuation = NEXT_PAGE.replace("Q6.", "Continuation de la dernière option.\n\nQ6.")
        with self.assertRaises(QcmSourceError):
            build_qcm_inventory([FIRST_PAGE, continuation], "owned-pdf", SOURCE_HASH, "test-index")

    def test_explicit_solve_and_exact_scope(self):
        self.assertTrue(is_qcm_solve_request(REQUEST))
        self.assertEqual(requested_qcm_ordinals(REQUEST), FIRST_FIVE)
        self.assertEqual(requested_qcm_ordinals("Answer Q1–Q5 of the QCM."), FIRST_FIVE)
        self.assertFalse(is_qcm_solve_request("How to answer the first five questions of the QCM?"))
        self.assertFalse(is_qcm_solve_request("Do not solve Q1–Q5 of the QCM."))
        self.assertFalse(requested_qcm_ordinals("Résous Q1 à Q5 du QCM, sauf la deuxième question."))
        self.assertFalse(requested_qcm_ordinals("Résous Q1 à Q5 et Q6 du QCM."))
        self.assertEqual(requested_qcm_ordinals("Answer all 20 QCM questions."), ALL_QUESTIONS)
        self.assertEqual(requested_qcm_ordinals("Réponds à toutes les questions du QCM."), ALL_QUESTIONS)
        self.assertEqual(requested_qcm_ordinals("Résous Q11 à Q17 du QCM."), tuple(range(11, 18)))
        self.assertFalse(requested_qcm_ordinals("Résous Q1 à Q21 du QCM."))


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_pdf_routes_natural_french_and_english_requests(self):
        cases = [
            ("réponds à toutes les questions", "fr", "French"),
            ("corrige le QCM", "fr", "French"),
            ("answer all the questions with justification", "en", "English"),
            ("give me the answers and why", "en", "English"),
            ("I want every single questions answered with justification in english", "fr", "English"),
            ("Answer all the questions in French.", "en", "French"),
        ]
        for prompt, dropdown, expected in cases:
            with (
                self.subTest(prompt=prompt),
                patch.dict("os.environ", {"EXPLAIN_FIRST_FIVE_QCM": "1"}),
                patch.object(explicateur, "course_documents", AsyncMock(return_value=[DOCUMENT])),
                patch.object(explicateur, "load_qcm_inventory", AsyncMock(return_value=full_inventory())) as load,
                patch.object(explicateur, "generate_qcm", AsyncMock(return_value=QcmResult("unreviewed", "## Q1"))) as generate,
                patch.object(explicateur, "retrieve_summary_guided_chunks", side_effect=AssertionError("legacy path used")),
            ):
                result = await explicateur.run_explicateur({
                    **STATE, "student_message": prompt, "explain_document_id": DOCUMENT["id"],
                    "language": dropdown, "explain_language_explicit": True,
                })
                self.assertEqual(result["qcm_status"], "unreviewed")
                load.assert_awaited_once_with(DOCUMENT, "owner", ALL_QUESTIONS)
                self.assertEqual(generate.await_args.kwargs["language"], expected)

    async def test_explain_graph_passes_owned_source_to_generation(self):
        with (
            patch.dict("os.environ", {"EXPLAIN_FIRST_FIVE_QCM": "1"}),
            patch.object(explicateur, "course_documents", AsyncMock(return_value=[DOCUMENT])) as documents,
            patch("worker.download_document", AsyncMock(return_value=PDF)) as download,
            patch("worker.extract_pages", AsyncMock(return_value=[FIRST_PAGE, NEXT_PAGE])),
            patch.object(explicateur, "generate_qcm", AsyncMock(
                return_value=QcmResult("unreviewed", "## Q1"),
            )) as generate,
            patch.object(explicateur, "retrieve_summary_guided_chunks", side_effect=AssertionError("retrieval must not run")),
        ):
            result = await get_compiled_graph().ainvoke(STATE)
        documents.assert_awaited_once_with("course", "owner")
        download.assert_awaited_once_with(DOCUMENT, "owner")
        self.assertEqual(len(result["qcm_inventory"].items), 5)
        self.assertEqual(generate.await_args.args[0], result["qcm_inventory"])
        self.assertEqual(result["qcm_status"], "unreviewed")
        self.assertEqual(result["qcm_result"], "## Q1")

    async def test_rejects_foreign_source_and_changed_pdf(self):
        with (
            patch.dict("os.environ", {"EXPLAIN_FIRST_FIVE_QCM": "1"}),
            patch.object(explicateur, "course_documents", AsyncMock(return_value=[DOCUMENT])),
            patch("worker.download_document", AsyncMock(return_value=b"changed")) as download,
            patch("worker.extract_pages", side_effect=AssertionError("source hash must be checked first")),
        ):
            foreign = await explicateur.run_explicateur({**STATE, "explain_document_id": "foreign"})
            download.assert_not_awaited()
            changed = await explicateur.run_explicateur(STATE)
        self.assertNotIn("qcm_inventory", foreign)
        self.assertNotIn("qcm_inventory", changed)
        self.assertIn("changé", changed["qcm_result"])


def answer_payload(ordinals=FIRST_FIVE):
    reasons = (
        "Ce choix permet de développer des compétences adaptées à la situation.",
        "Cette action laisse de côté les besoins de formation du candidat.",
        "Cette démarche renforce la pratique et la capacité du candidat à évoluer.",
        "Le choix ne tient pas compte des facteurs présentés dans la question.",
    )
    return {"answers": [
        {"question_id": f"q{number}", "selected_keys": ["C", "A"], "answer_basis": "model_proposed",
         "option_reasons": {
             key: {"principe": "La formation continue aide à suivre les évolutions du métier.", "application": reason}
             for key, reason in zip("ABCD", reasons, strict=True)
         }}
        for number in ordinals
    ]}


def batch_payload(request):
    body = json.loads(request.content)
    packet = json.loads(body["contents"][0]["parts"][0]["text"])
    return answer_payload(int(item["question_id"][1:]) for item in packet)


def full_inventory():
    pages = [
        f"En-tête\n\n{page}\n\n" + "\n\n".join(
            f"Q{number}. Question {number} ?\n\nA. Première option\nB. Deuxième option\nC. Autre choix\nD. Dernier choix"
            for number in range(first, last + 1)
        )
        for page, (first, last) in enumerate(((1, 5), (6, 11), (12, 17), (18, 20)), 1)
    ]
    return build_qcm_inventory(pages, "owned-pdf", SOURCE_HASH, "test-index", ALL_QUESTIONS)


class GenerationTests(unittest.IsolatedAsyncioTestCase):
    async def generate(
        self, payload, *, finish="STOP", http_status=200, model="gemini-3.5-flash-lite",
        inventory=None, fail_dispatches=None, deadline=None, preview=None, progress=None, reference_chunks=None,
        language="French",
    ):
        inventory = inventory or build_qcm_inventory([FIRST_PAGE, NEXT_PAGE], "owned-pdf", SOURCE_HASH, "test-index")
        self.requests = []

        async def send(_client, request, **_kwargs):
            self.requests.append(request)
            if http_status != 200 and (fail_dispatches is None or len(self.requests) in fail_dispatches):
                return httpx.Response(
                    http_status, json={"error": {"code": http_status, "message": "Fixture error",
                                                "status": "UNAVAILABLE" if http_status == 503 else "RESOURCE_EXHAUSTED"}},
                    request=request,
                )
            batch_payload = payload(request) if callable(payload) else payload
            text = batch_payload if isinstance(batch_payload, str) else json.dumps(batch_payload)
            return httpx.Response(200, json={"candidates": [{
                "content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish,
            }]}, request=request)

        with (
            patch.dict("os.environ", {"GOOGLE_GENAI_USE_VERTEXAI": "false"}),
            patch("agents.llm.get_settings", return_value=SimpleNamespace(chat_model="never-use-default")),
            patch.object(httpx.AsyncClient, "send", autospec=True, side_effect=send),
            patch.object(_extra_utils, "should_disable_afc", wraps=_extra_utils.should_disable_afc) as afc,
            patch("agents.qcm_generation._RETRY_PAUSE_SECONDS", 0),
            patch("agents.qcm_generation._RETRY_JITTER_SECONDS", 0),
        ):
            result = await generate_qcm(
                inventory, provider="google", model=model, api_key="offline-key", request_id="offline", deadline=deadline,
                preview=preview, progress=progress, reference_chunks=reference_chunks, language=language,
            )
        self.assertEqual(afc.call_count, len(self.requests))
        for call in afc.call_args_list:
            self.assertIs(call.args[0].automatic_function_calling.disable, True)
        return result

    async def test_serialized_request_and_source_join(self):
        payload = answer_payload()
        payload["answers"].reverse()
        result = await self.generate(payload)
        self.assertEqual(result.status, "unreviewed")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertTrue(request.url.path.endswith("gemini-3.5-flash-lite:generateContent"))
        body = json.loads(request.content)
        self.assertNotIn("tools", body)
        self.assertNotIn("toolConfig", body)
        packet = json.loads(body["contents"][0]["parts"][0]["text"])
        self.assertEqual([item["question_id"] for item in packet], [f"q{i}" for i in range(1, 6)])
        self.assertEqual(packet[0]["question"], "Question 1\nsur deux lignes ?")
        self.assertEqual(packet[4]["options"]["B"], "Une option\nsur deux lignes")
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 6144)
        self.assertIn("answers", body["generationConfig"]["responseJsonSchema"]["properties"])
        self.assertEqual(result.markdown.count("?page=1#page=1"), 5)
        self.assertEqual(result.markdown.count("**Choix proposés** · A, C"), 5)
        self.assertIn("✗ **B. Une option sur deux lignes**", result.markdown)
        self.assertLess(result.markdown.index("## Q1"), result.markdown.index("## Q5"))

    async def test_reference_evidence_is_separate_and_requires_an_exact_quote(self):
        quote = "La première option dépend d’un critère qui figure dans le cours."
        reference = {"id": "ref", "document_id": "course-pdf", "page_number": 3, "content": quote}
        payload = answer_payload()
        payload["answers"][0]["evidence"] = [{"reference_index": 1, "quote": quote}]
        payload["answers"][1]["evidence"] = [{"reference_index": 1, "quote": "Ce passage ne figure pas dans le cours."}]
        result = await self.generate(payload, reference_chunks=[reference])
        self.assertEqual((result.status, result.attempts), ("unreviewed", 1))
        body = json.loads(self.requests[0].content)
        packet = json.loads(body["contents"][0]["parts"][0]["text"])
        self.assertEqual(packet["course_reference_excerpts"], [{"reference_index": 1, "content": quote}])
        self.assertEqual(packet["questions"][0]["options"]["A"], "Première option")
        self.assertIn("[Cours, p. 3](/api/documents/view/course-pdf?page=3#page=3)", result.markdown)
        self.assertEqual(result.markdown.count("Appuyé par le cours"), 1)
        self.assertEqual(result.markdown.count("Proposition du modèle"), 4)

    async def test_twenty_questions_dispatch_in_four_source_ordered_batches(self):
        previews = []
        events = []

        async def preview(text):
            previews.append(text)
            events.append(("preview", len(self.requests)))

        async def progress(text):
            events.append((text, len(self.requests)))

        result = await self.generate(batch_payload, inventory=full_inventory(), preview=preview, progress=progress)
        self.assertEqual(result.status, "unreviewed")
        self.assertEqual(result.attempts, 4)
        self.assertEqual(len(self.requests), 4)
        for offset, request in enumerate(self.requests):
            body = json.loads(request.content)
            self.assertNotIn("tools", body)
            self.assertNotIn("toolConfig", body)
            ids = [item["question_id"] for item in json.loads(body["contents"][0]["parts"][0]["text"])]
            self.assertEqual(ids, [f"q{number}" for number in range(offset * 5 + 1, offset * 5 + 6)])
        for number, page in ((5, 1), (6, 2), (11, 2), (12, 3), (17, 3), (18, 4), (20, 4)):
            self.assertIn(f"## Q{number} · [Énoncé, p. {page}](/api/documents/view/owned-pdf?page={page}#page={page})", result.markdown)
        self.assertEqual(result.markdown.count("**Choix proposés**"), 20)
        self.assertEqual(result.markdown.count("**Principe**"), 80)
        self.assertEqual(result.markdown.count("**Application**"), 80)
        self.assertEqual("".join(previews).rstrip(), result.markdown)
        self.assertEqual([text.count("## Q") for text in previews], [5, 5, 5, 5])
        self.assertEqual(events, [
            event
            for i in range(1, 5)
            for event in ((f"Préparation du lot {i}/4.", i - 1), ("preview", i))
        ])

    async def test_first_5xx_retries_same_request_then_finishes_in_five_dispatches(self):
        result = await self.generate(batch_payload, inventory=full_inventory(), http_status=503, fail_dispatches={1})
        self.assertEqual((result.status, result.attempts), ("unreviewed", 5))
        self.assertEqual(len(self.requests), 5)
        self.assertEqual(self.requests[0].content, self.requests[1].content)
        self.assertEqual(result.markdown.count("**Choix proposés**"), 20)

    async def test_last_batch_retry_accepts_a_complete_response(self):
        with self.assertLogs("agents.qcm_generation", level="INFO") as logs:
            result = await self.generate(
                batch_payload, inventory=full_inventory(), http_status=503, fail_dispatches={4}, finish="MAX_TOKENS",
            )
        self.assertEqual((result.status, result.attempts), ("unreviewed", 5))
        self.assertIn("qcm_batch_validated request_id=offline batch=4 attempted_dispatches=5", "\n".join(logs.output))
        self.assertIn("## Q20", result.markdown)

    async def test_last_batch_retry_logs_the_rejected_question_and_rule(self):
        def payload(request):
            result = batch_payload(request)
            for row in result["answers"]:
                if row["question_id"] == "q18":
                    row["option_reasons"]["A"]["application"] = "Sans raison."
            return result

        with self.assertLogs("agents.qcm_generation", level="INFO") as logs:
            result = await self.generate(payload, inventory=full_inventory(), http_status=503, fail_dispatches={4})
        self.assertEqual((result.status, result.attempts), ("partial", 5))
        self.assertIn("missing_questions=[18] rejected=[(18, 'reason_too_short')]", "\n".join(logs.output))
        self.assertIn("Questions sans réponse exploitable** · Q18", result.markdown)
        self.assertIn("## Q20", result.markdown)

    async def test_english_reasons_and_labels_keep_french_source_text(self):
        payload = answer_payload()
        applications = (
            "This option supports the intended outcome by building the relevant skill.",
            "This response overlooks the requirements of the stated situation.",
            "The proposed action addresses the practical constraint in the question.",
            "This option does not connect the action to the expected result.",
        )
        for answer in payload["answers"]:
            for reason, application in zip(answer["option_reasons"].values(), applications, strict=True):
                reason["principe"] = "The criterion is whether the action can address the stated need."
                reason["application"] = application
        payload["answers"][0]["option_reasons"]["A"]["application"] = (
            "Continuing education builds adaptable skills, improving long-term employability."
        )
        result = await self.generate(payload, language="English")
        self.assertEqual(result.status, "unreviewed")
        self.assertIn("**Principle**", result.markdown)
        self.assertIn("**Proposed choices**", result.markdown)
        self.assertIn("**A. Première option**", result.markdown)
        self.assertNotIn("Choix proposés", result.markdown)
        with self.assertLogs("agents.qcm_generation", level="WARNING") as logs:
            del payload["answers"][1]["option_reasons"]["D"]
            payload["answers"][2]["option_reasons"]["A"]["application"] = (
                "La pratique régulière permet de renforcer les compétences dans cette situation."
            )
            partial = await self.generate(payload, language="English")
        self.assertIn("Questions without a usable answer** · Q2, Q3", partial.markdown)
        self.assertIn("(2, 'answer_schema:option_reasons')", "\n".join(logs.output))
        self.assertIn("(3, 'reason_language')", "\n".join(logs.output))

    async def test_later_provider_failure_preserves_finished_batches(self):
        result = await self.generate(batch_payload, inventory=full_inventory(), http_status=503, fail_dispatches={3, 4})
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.attempts, 4)
        self.assertEqual(len(self.requests), 4)
        self.assertEqual(result.markdown.count("**Choix proposés**"), 10)
        self.assertIn(", ".join(f"Q{i}" for i in range(11, 21)), result.markdown)

    async def test_elapsed_deadline_stops_before_dispatch(self):
        result = await self.generate(batch_payload, inventory=full_inventory(), deadline=asyncio.get_running_loop().time() - 1)
        self.assertEqual((result.status, result.attempts), ("failed", 0))
        self.assertEqual(self.requests, [])

    async def test_preserves_french_accents_from_provider_to_markdown(self):
        reason = "Cette démarche favorise l’accès à l’emploi et le développement des compétences."
        payload = answer_payload()
        payload["answers"][0]["option_reasons"]["A"]["application"] = normalize("NFD", reason)
        result = await self.generate(payload)
        self.assertEqual(result.status, "unreviewed")
        self.assertIn(reason, result.markdown)
        self.assertIn("**A. Première option**", result.markdown)
        body = json.loads(self.requests[0].content)
        self.assertIn("face à l’évolution", body["systemInstruction"]["parts"][0]["text"])

    async def test_flags_known_accent_loss_without_another_call(self):
        payload = answer_payload()
        payload["answers"][0]["option_reasons"]["A"]["application"] = (
            "Cette demarche favorise l'acces a l'emploi et le developpement des competences."
        )
        result = await self.generate(payload)
        self.assertEqual(result.status, "partial")
        self.assertIn("**Questions sans réponse exploitable** · Q1", result.markdown)
        self.assertEqual(len(self.requests), 1)

    async def test_invalid_rows_become_partial_without_a_repair_call(self):
        for change in (
            {"option_reasons": []},
            {"selected_keys": ["E"]},
            {"answer_basis": "official_key"},
            {"option_reasons": [{"key": key, "reason": "This is the wrong answer for the student."} for key in "ABCD"]},
            {"option_reasons": [{"key": key, "reason": "Ce choix est correct car c’est la bonne réponse."} for key in "ABCD"]},
        ):
            with self.subTest(change=change):
                payload = answer_payload()
                payload["answers"][4].update(change)
                result = await self.generate(payload)
                self.assertEqual(result.status, "partial")
                self.assertIn("**Questions sans réponse exploitable** · Q5", result.markdown)
                self.assertNotIn("## Q5", result.markdown)
                self.assertEqual(len(self.requests), 1)

    async def test_truncation_and_uncertainty_are_visible(self):
        payload = answer_payload()
        payload["answers"][0].update(answer_basis="unresolved", selected_keys=[])
        truncated = '{"answers":[' + json.dumps(payload["answers"][0]) + ', {"question_id":'
        result = await self.generate(truncated, finish="MAX_TOKENS")
        self.assertEqual(result.status, "partial")
        self.assertIn("**Réponse non tranchée.**", result.markdown)
        self.assertIn("Q2, Q3, Q4, Q5", result.markdown)
        self.assertEqual(len(self.requests), 1)

    async def test_quota_has_no_retry_and_persistent_5xx_has_only_one(self):
        quota = await self.generate({}, http_status=429)
        self.assertEqual((quota.status, quota.attempts), ("failed", 1))
        self.assertIn("usage limit", quota.markdown)
        self.assertEqual(len(self.requests), 1)
        unavailable = await self.generate({}, http_status=503)
        self.assertEqual((unavailable.status, unavailable.attempts), ("failed", 2))
        self.assertIn("indisponible", unavailable.markdown)
        self.assertEqual(len(self.requests), 2)

    async def test_copied_markdown_preserves_ordinary_french_punctuation(self):
        payload = answer_payload()
        payload["answers"][0]["option_reasons"]["A"]["application"] = (
            "Ce choix permet aux non-techniciens de suivre les nouvelles technologies."
        )
        result = await self.generate(payload)
        self.assertEqual(result.status, "unreviewed")
        self.assertIn("non-techniciens de suivre les nouvelles technologies.", result.markdown)
        self.assertNotIn("non\\-techniciens", result.markdown)
        self.assertNotIn("technologies\\.", result.markdown)

    async def test_rejects_blocked_or_unconfigured_models_before_dispatch(self):
        for model in ("gemini-2.5-flash", "gemini-flash-latest", "gemini-not-in-budget"):
            with self.subTest(model=model):
                result = await self.generate({}, model=model)
                self.assertEqual(result.status, "failed")
                self.assertEqual(self.requests, [])
