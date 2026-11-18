"""Run the CV and Spark tagged scorecards with local response dispatches only.

From socra-backend: python -m tests.run_explain_scorecard --output-dir <folder>
Use --spark-pdf to verify and re-extract the original PDF instead of the portable index.
"""

import argparse
import asyncio
from hashlib import sha256
import ipaddress
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from agents.explain_budget import explain_budget
from agents.explain_lifecycle import ExplanationV2, attach_contract, version_for
from agents.explain_planner import build_learning_plan, learning_progress
from agents.explain_unit_generation import generate_unit, legacy_projection, linked_evidence
from agents.explain_unit_review import review_units
from rag.explain_preparation import prepare_units
from rag.unit_map import bind_chunks, build_unit_map
from tests.explain_scorecard import PacketReplay, aggregate, original_ids, score_unit
from tests.test_explain_cv_acceptance_golden import ITEM_IDS, PAGES_DIGEST, REVIEW_DIGEST
from tests.test_explain_review_contract import saved_text
from tests.test_explain_tagged_generation import ANSWER, FIXTURES, LIVE_DIGEST, cv_source, tagged_block
from tests.test_explain_unit_generation import excerpt_rows
from worker import chunk_pages, extract_pages


SCOPE = "Explique en détail sans rien omettre"
HISTORICAL = "historical_live_replay"
MOCKED = "mocked_structural"
TWO_PACKET_OUTPUT_LIMIT = 1900  # Between the measured full-unit and two half-unit output estimates.

SPARK_SETUP_PROSE = (
    ("Les deux réglages donnent aux processus PySpark le même interpréteur que le notebook.",
     "Les imports donnent accès à la session SQL ainsi qu’aux briques nécessaires aux pipelines et à la mise à l’échelle.",
     "Le constructeur sert à réunir les options avant l’ouverture effective de la session."),
    ("Le mode local suffit pour pratiquer avec les ressources disponibles sur cette machine.",
     "Le notebook demande à Spark de fonctionner dans son environnement local.",
     "Vérifiez le mode choisi avant de poursuivre avec les données du laboratoire."),
    ("Le nom permet de repérer cette application Spark parmi les autres travaux.",
     "Les outils Spark identifient cette session avec le nom de l’application donné au constructeur.",
     "Comparez le nom de l’application à celui demandé dans le notebook."),
    ("La création ou la récupération de la session rend disponibles les fonctions Spark au notebook.",
     "La version affichée par spark.version est relevée à l’exécution. Le numéro dépend du moteur installé dans le notebook courant.",
     "Le niveau WARN réduit le bruit des journaux pour faire ressortir les avertissements."),
    ("Dans ce mode le traitement utilise deux fils d’exécution sur la même machine.",
     "Une session locale rend possible un essai reproductible sur le poste de travail.",
     "Un essai sur un seul poste ne mesure ni la répartition du travail ni les performances d’un cluster."),
)


def guard_network(event, args):
    if event == "socket.getaddrinfo" and args[0] not in (None, "localhost", "127.0.0.1", "::1"):
        raise RuntimeError("External DNS disabled for the offline scorecard.")
    if event == "socket.connect" and isinstance(args[1], tuple):
        if not ipaddress.ip_address(args[1][0]).is_loopback:
            raise RuntimeError("External connections disabled for the offline scorecard.")


def load_spark_fixture():
    annotation = json.loads((FIXTURES / "spark-lab-annotation.json").read_text(encoding="utf-8"))
    fixture = json.loads((FIXTURES / "spark-lab-indexed-pages.json").read_text(encoding="utf-8"))
    if fixture["source_sha256"] != annotation["sha256"]:
        raise ValueError("Spark annotation and portable index refer to different PDF versions.")
    return annotation, fixture["pages"], fixture["indexed"]


def prepare_spark(annotation, pages, indexed):
    unit_map = build_unit_map(annotation["document_id"], pages)
    units = unit_map["units"]
    rows = chunk_pages([page["text"] for page in pages], positions=True)
    bind_chunks(units, rows)
    selected = {row["unit_id"] for row in annotation["units"]}
    records = prepare_units(units, pages, rows, chunk_pages(indexed), source_hash=annotation["sha256"], requested=selected)
    plan = build_learning_plan(units, "spark-scorecard", SCOPE, records)
    by_id = {u["logical_id"]: u for u in units}
    excerpts = {uid: excerpt_rows(by_id[uid], rows) for uid in selected}
    return units, by_id, records, plan, excerpts


def structural_tagged(payload):
    """Return source-quote derived markers and explicitly synthetic supplementary slots."""
    blocks = []
    for item in payload["checklist"]:
        source = payload["sources"][item["sources"][0] - 1]
        if lab := payload.get("lab_command_contract"):
            group = next(group for group in lab["groups"] if group["item_id"] == item["id"])
            from agents.explain_lab_verification import COMMANDS

            commands = tuple(group["command_lines"])
            action, result, checkpoint = SPARK_SETUP_PROSE[COMMANDS.index(commands)]
            code = "\n".join(["```python", *commands, "```"]) if commands else lab["no_command_marker"]
            for kind, value in zip(payload["required_blocks"], (action, code, result, checkpoint), strict=True):
                derived = kind != "command_or_ui" or bool(commands)
                blocks.append(tagged_block(kind, value, items=item["id"],
                                           sources=str(source["index"]) if derived else "-",
                                           provenance="derived" if derived else "supplementary"))
            continue
        for kind in payload["required_blocks"]:
            derived = kind in {"action", "command_or_ui"}
            blocks.append(tagged_block(
                kind, source["quote"] if derived else "Contrôle structurel hors ligne.",
                items=item["id"], sources=str(source["index"]) if derived else "-",
                provenance="derived" if derived else "supplementary",
            ))
    return "\n".join([f"@@UNIT {payload['unit_id']}", *blocks])


async def generate_replay(unit, units, records, plan, excerpts, response, *, related=None,
                          policy_fit=True, output_limit=None):
    # Budget metadata is local configuration. This never initializes a provider.
    budget = explain_budget("google", "gemini-3.5-flash-lite") if policy_fit else None
    if policy_fit and budget is None:
        raise ValueError("The previously used Spark planning budget is unavailable.")
    packets = []

    async def dispatch(messages, _source_count):
        payload = json.loads(messages[-1].content)
        raw, reason = response(payload, len(packets) + 1)
        packets.append(PacketReplay(payload, raw, reason))
        return raw, reason

    with patch.dict(os.environ, {"EXPLAIN_GENERATION_FORMAT": "tagged"}):
        draft = await generate_unit(
            unit, records[unit["logical_id"]], excerpts, plan, dispatch, language="French",
            fits=(lambda messages: budget.fits(messages, None)) if budget else (lambda _: True),
            max_output=output_limit if output_limit is not None else budget.max_output_tokens if budget else None,
            continuity={}, unit_map=units, related=related,
        )
    return packets, draft


async def replay_cv():
    indexed = (FIXTURES / "cv-indexed-pages.json").read_bytes()
    if sha256(indexed).hexdigest() != PAGES_DIGEST:
        raise ValueError("The portable CV index differs from the golden baseline.")
    pages = json.loads(indexed)
    units, records, plan, excerpts = cv_source(pages)
    unit = next(unit for unit in units if unit["logical_id"] == ANSWER)
    related = linked_evidence(unit, units, records, excerpts)
    raw_generation = saved_text("cv-answer-1-live-tagged-response.json", LIVE_DIGEST)
    raw_review = saved_text("cv-answer-1-positive-live-review.json", REVIEW_DIGEST)
    packets, draft = await generate_replay(unit, units, records, plan, excerpts[ANSWER],
                                           lambda _payload, _: (raw_generation, ""), related=related, policy_fit=False)
    candidates = records[ANSWER]["checklist"]
    names = ("Simplify the graphical layout for ATS compatibility.", "Use a role-specific profile.",
             "Support technical skills with concrete examples.", "Describe missions, tools and results.",
             "Remove irrelevant personal details and improve professional contact and links.",
             "Tailor the CV to each job posting.")
    by_id = {row["item_id"]: row for row in candidates}
    annotation = {"unit_id": ANSWER, "label": "Réponse 1", "expected_packet_count": 1, "actual_source_pages": [2],
                  "requirements": [{"id": cid, "requirement": name, "category": "concept", "mandatory": True,
                                    "block_kinds": ["explanation", "intuition", "source_example", "takeaway"],
                                    "evidence": by_id[cid]["anchors"], "candidate_ids": [cid]}
                                   for cid, name in zip(ITEM_IDS, names, strict=True)]}
    review_packet = None

    async def dispatch(purpose, messages, _schema):
        nonlocal review_packet
        if purpose != "review" or review_packet is not None:
            raise ValueError("Unexpected second review or repair in the CV replay.")
        review_packet, = json.loads(messages[-1].content)
        return raw_review

    verdict, = await review_units([draft], units, records, excerpts[ANSWER], plan, [], dispatch,
                                  allow_repair=set(), related={ANSWER: related})
    stage = "ready" if verdict["review_state"] == "approved" else "draft"
    version = version_for("cv-scorecard", stage, verdict)
    saved_plan = build_learning_plan([unit], "cv-golden", SCOPE, records)
    learning = learning_progress(saved_plan, [unit], {ANSWER: {"content_version": verdict["content_version"],
                                 "status": verdict["coverage"]}}, "cv-scorecard",
                                 verified_facts=verdict["verified_facts"], prepared=records)
    card = attach_contract(legacy_projection([verdict], excerpts[ANSWER], "cv", "French"), saved_plan,
                           [unit], [version], [version], learning, records)
    ready = ExplanationV2.model_validate_json(json.dumps(card, ensure_ascii=False)).versions[0]
    if ready.output.model_dump(mode="json") != version["output"]:
        raise AssertionError("The CV version changed after local JSON reload.")
    raw_rows = json.loads(raw_review)["reviews"][0]["checklist_evidence"]
    reference_rows = [r | {"expected_original_id": ITEM_IDS[r["item_id"] - 1]} for r in raw_rows]
    return score_unit(annotation, pages, candidates, plan["required_items"][ANSWER], packets, draft,
                      evidence_kind=HISTORICAL, review_packet=review_packet, reference_rows=reference_rows,
                      verdict=verdict, ready=ready.stage)


async def review_reference_probe(draft, packets, candidates, units, records, excerpts, plan):
    """Probe the production review ID join, without contributing a review score or verdict."""
    uid = draft["logical_id"]
    block_starts = []
    block_index = 0
    for packet in packets:
        for number, cid in original_ids(packet.payload, candidates).items():
            block_starts.append((number, cid, draft["blocks"][block_index]))
            block_index += len(packet.payload["required_blocks"])
    reference_rows = []
    review_packet = None

    async def dispatch(purpose, messages, _schema):
        nonlocal review_packet
        if purpose != "review" or review_packet is not None:
            raise ValueError("Unexpected second review or repair in the Spark mapping probe.")
        review_packet, = json.loads(messages[-1].content)
        findings = []
        for review_number, (generation_number, cid, block) in enumerate(block_starts, 1):
            reference_rows.append({"item_id": review_number, "generation_local_id": generation_number,
                                   "block_id": block["block_id"], "expected_original_id": cid})
            findings.append({"kind": "missing", "item_id": review_number, "block_id": block["block_id"],
                             "quote": block["text"],
                             "detail": "Sonde de correspondance des identifiants, sans évaluation pédagogique."})
        return json.dumps({"reviews": [{"unit_id": uid, "pedagogy_score": 2, "findings": findings}]}, ensure_ascii=False)

    probed, = await review_units([draft], units, records, excerpts, plan, [], dispatch, allow_repair=set())
    remapped = {row["block_id"]: row["item_id"]
                for row in probed.get("independent_review", {}).get("findings", ())}
    for row in reference_rows:
        row["production_remapped_original_id"] = remapped.get(row["block_id"])
    return review_packet, reference_rows


async def _spark_scope(scope, pages, units, by_id, records, plan, excerpts, *, output_limit=None):
    uid = scope["unit_id"]
    record = records[uid]
    candidates = record["checklist"]
    packets, draft = await generate_replay(by_id[uid], units, records, plan, excerpts[uid],
                                           lambda payload, _: (structural_tagged(payload), ""),
                                           output_limit=output_limit)
    review_packet, probe = await review_reference_probe(draft, packets, candidates, units, records, excerpts[uid], plan)
    return score_unit(scope, pages, candidates, plan["required_items"][uid], packets, draft, evidence_kind=MOCKED,
                      review_packet=review_packet, reference_rows=probe, exclusions=record["checklist_exclusions"])


async def spark_replay(annotation, pages, indexed):
    scope_inputs = prepare_spark(annotation, pages, indexed)
    units = scope_inputs[0]
    results = [await _spark_scope(scope | {"expected_packet_count": 1}, pages, *scope_inputs)
               for scope in annotation["units"]]
    control = await _spark_scope(annotation["units"][1], pages, *scope_inputs, output_limit=TWO_PACKET_OUTPUT_LIMIT)
    return {"document_id": annotation["document_id"], "filename": annotation["filename"], "sha256": annotation["sha256"],
            "page_count": len(pages), "lab_units": [{"label": u["label"], "id": u["logical_id"],
                "start": u["start"], "end": u["end"]} for u in units if u["kind"] == "lab_step"],
            "aggregate": aggregate(results), "units": results,
            "two_packet_control": control | {"test_output_limit": TWO_PACKET_OUTPUT_LIMIT}}


def markdown_report(report):
    def fraction(value):
        return f"{value['count']}/{value['total']}" if value else "not evaluated"

    def rate(value, spec):
        return format(value, spec) if value is not None else "not applicable"

    lines = ["# Socra Explicateur offline scorecard", "",
             "The CV row replays historical live output. Spark rows use deterministic structural mock output. "
             "The Spark review probe checks ID wiring only. Provider and database calls in this run were zero.", ""]
    for doc in report["documents"]:
        lines.extend([f"## {doc['filename']}", ""])
        for unit in doc["units"]:
            s, a, m, c, r = (unit[k] for k in ("source", "assignment", "merged", "citations", "review"))
            quality = s["extraction_quality"]
            lines.extend([f"### {unit['label']} · {unit['evidence_kind']}", "",
                f"- Source scope: {s['correct_requirements']}/{s['ground_truth_requirements']} genuine requirements "
                f"represented. {s['pre_filter_candidates']} candidates before filtering, "
                f"{s['extracted_candidates']} retained for planning, {s['accepted_candidates']} planned, "
                f"{s['correct_candidates']} in scope. Precision {rate(quality['precision']['rate'], '.1%')}, "
                f"recall {rate(quality['recall']['rate'], '.1%')}, F1 {rate(quality['f1'], '.3f')}.",
                f"- Source traceability: {fraction(s['source_traceability'])} annotated excerpts matched. "
                f"{fraction(s['page_attribution'])} attributed to the verified page.",
                f"- Packets: {a['actual_packets']}/{a['expected_packets']}. "
                f"Original IDs retained {fraction(a['original_id_preservation'])}.",
                f"- Merged: {m['actual_blocks']}/{m['planned_blocks']} planned slots. "
                f"Retention {fraction(m['parsed_to_merged_retention'])}. "
                f"Order preserved: {m['ordered_blocks_match']}. Ground-truth requirements with linked groups retained "
                f"{fraction(m['source_requirements_with_all_linked_groups_retained'])}. "
                f"Production coverage {m['production_coverage']} before review and {m['final_coverage']} in the final scored artifact.",
                f"- Citations: {fraction(c['resolved_anchors'])} anchors and "
                f"{fraction(c['resolved_claim_anchor_references'])} claim references resolved.",
                f"- Verification: {len(unit['verification']['verified_facts'])} verified facts, "
                f"{len(unit['verification']['reviewable_items'])} reviewable items, "
                f"{len(unit['verification']['missing_checklist_item_ids'])} missing checklist items before review, "
                f"{len(unit['verification']['final_missing_checklist_item_ids'])} in the final scored artifact.",
                f"- Review: {r['status']}. Mapping {fraction(r['mapping_probe'])}. "
                f"Evidence {fraction(r['evidence_completeness'])}. "
                f"Pedagogy {r['pedagogy_score']}, verdict {r['verdict']}, version {r['ready_stage']}.", ""])
            for entry in s["exclusion_ledger"]:
                source = entry["anchors"][0]
                lines.append(f"- Excluded `{entry['reason']}`, page {source['page']}, "
                             f"`{source['start']}–{source['end']}`. {entry['text']}")
            if s["exclusion_ledger"]:
                lines.append("")
            for packet in unit["packets"]:
                lines.extend([f"#### Packet {packet['number']}", "",
                              f"- Blocks {packet['parsed_blocks']}/{packet['expected_blocks']}, "
                              f"ordered groups {fraction(packet['groups_complete'])}, "
                              f"retention {fraction(packet['parsed_to_merged_retention'])}, "
                              f"resolved anchors {fraction(packet['resolved_packet_anchors'])}.",
                              "- Local → original: " + ", ".join(
                                  f"`{number}` → `{cid}`" for number, cid in packet["numeric_to_original_id"].items()),
                              ""])
            lines.extend(["#### Findings", ""])
            for issue in unit["failures"]:
                lines.append(f"- `{issue['code']}` " + json.dumps(
                    {k: v for k, v in issue.items() if k != "code"}, ensure_ascii=False))
            if not unit["failures"]:
                lines.append("- No structural scorecard failures.")
            lines.extend(["", "#### Source traceability", ""])
            for row in s["trace"]:
                excerpts = " · ".join(f'p. {a["page"]} `{a["start"]}–{a["end"]}`' for a in row["evidence"])
                lines.append(f"- `{row['id']}`. {row['requirement']} {excerpts}")
            lines.append("")
    lines.extend(["## Aggregate by evidence type", ""])
    for mode, counts in report["aggregate"].items():
        lines.extend([f"- **{mode}** · {counts['units']} units. "
                      f"Source requirements {fraction(counts['source_requirements'])}. "
                      f"Packet retention {fraction(counts['block_retention'])}.", ""])
    control = report["documents"][1]["two_packet_control"]
    lines.extend(["## Dedicated two-packet Spark control", "",
                   f"The test-only output limit is {control['test_output_limit']} tokens. "
                   f"Production planning is reported in the Step 2 section. Control retention was "
                   f"{fraction(control['merged']['parsed_to_merged_retention'])} blocks, "
                   f"{fraction(control['citations']['resolved_anchors'])} anchors and "
                   f"{fraction(control['review']['mapping_probe'])} review ID references.", ""])
    return "\n".join(lines)


async def run(spark_pdf=None):
    annotation, pages, indexed = load_spark_fixture()
    if spark_pdf is not None:
        pdf = spark_pdf.read_bytes()
        if sha256(pdf).hexdigest() != annotation["sha256"]:
            raise ValueError("Spark PDF hash does not match the manual annotation.")
        pages = await extract_pages(pdf, layout=True, evidence=True)
        indexed = await extract_pages(pdf)
    cv = await replay_cv()
    spark = await spark_replay(annotation, pages, indexed)
    return {"schema_version": 1, "generation_format": "tagged", "provider_calls": 0, "database_calls": 0,
            "documents": [{"document_id": "cv", "filename": "TD N° 3 ANALYSE CV.pdf",
                           "aggregate": aggregate([cv]), "units": [cv]}, spark],
            "aggregate": aggregate([cv, *spark["units"]])}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output-dir", required=True, type=Path)
    cli.add_argument("--spark-pdf", type=Path)
    args = cli.parse_args()
    sys.addaudithook(guard_network)
    result = asyncio.run(run(args.spark_pdf))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cv, spark = result["documents"]
    step_zero, step_two = spark["units"]
    artifacts = {"scorecard": result, "cv-answer-1": cv["units"][0], "spark-step-0": step_zero,
                 "spark-step-2-merged": step_two, "spark-step-2-two-packet-control": spark["two_packet_control"]}
    for packet in spark["two_packet_control"]["packets"]:
        n = packet["number"]
        artifacts[f"spark-step-2-control-packet-{n}"] = {
            "evidence_kind": MOCKED, "packet": packet,
            "failures": [row for row in spark["two_packet_control"]["failures"] if row.get("packet") == n],
        }
    for name, value in artifacts.items():
        (args.output_dir / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                                                     encoding="utf-8")
    (args.output_dir / "scorecard.md").write_text(markdown_report(result) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
