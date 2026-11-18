"""Measure offline Explicateur replays against independently annotated source scopes."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
import re

from agents.explain_tagged_output import TaggedLayout, parse_tagged_units


@dataclass(frozen=True)
class PacketReplay:
    payload: dict
    raw: str
    finish_reason: str = ""


def _anchor(source):
    return source["page"], source["start"], source["end"], source["quote"]


def _exact(source, pages):
    page, start, end, quote = _anchor(source)
    return (1 <= page <= len(pages) and 0 <= start < end <= len(pages[page - 1]["text"])
            and pages[page - 1]["text"][start:end] == quote)


def _contains(anchor, evidence):
    page, start, end, quote = _anchor(anchor)
    target_page, left, right, text = _anchor(evidence)
    return page == target_page and start <= left < right <= end and quote[left-start:right-start] == text


def _item_key(item, anchors):
    return item["type"], item["text"], tuple(_anchor(source) for source in anchors)


def original_ids(payload, candidates, *, review=False):
    """Join by exact candidate text, classification and ordered source anchors."""
    by_key = defaultdict(list)
    for item in candidates:
        by_key[_item_key(item, item["anchors"])].append(item["item_id"])
    anchors = {row.get("index", i): row for i, row in enumerate(payload["sources"], 1)}
    index_key, id_key = ("source_indexes", "item_id") if review else ("sources", "id")
    result = {}
    for row in payload["checklist"]:
        indexes = row[index_key]
        matches = by_key[_item_key(row, [anchors[i] for i in indexes])] if all(i in anchors for i in indexes) else []
        result[row[id_key]] = matches[0] if len(matches) == 1 else None
    return result


def _ratio(numerator, denominator):
    return {"count": numerator, "total": denominator, "rate": numerator / denominator if denominator else None}


def _prf(correct_candidates, candidates, covered, requirements):
    precision, recall = _ratio(correct_candidates, candidates), _ratio(covered, requirements)
    p, r = precision["rate"], recall["rate"]
    f1 = None if p is None or r is None else 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def _signature(block, anchors):
    claims = tuple((c["start"], c["end"], tuple(anchors.get(i) for i in c["source_indexes"]))
                   for c in block["claims"])
    return (block["kind"], block["text"], block["provenance"], claims, block.get("hypothetical", False),
            json.dumps(block.get("calculation"), sort_keys=True))


def _scoped_requirements(requirements, available, anchors):
    return {row["id"] for row in requirements if all(
        any(_contains(anchor, excerpt) for item in row["candidate_ids"] if item in available
            for anchor in anchors.get(item, ()))
        for excerpt in row["evidence"]
    )}


def _duplicates(values):
    return {value: n for value, n in Counter(values).items() if n > 1}


def _packet_score(packet, ordinal, uid, candidates, excluded, permitted_related, issues):
    def flag(code, **details):
        issues.append({"code": code, "packet": ordinal} | details)

    payload = packet.payload
    layout = TaggedLayout.from_packet(payload)
    normalized, error = parse_tagged_units(packet.raw, {uid: layout}, packet.finish_reason)[uid]
    blocks = json.loads(normalized)["blocks"] if normalized else []
    mapped = original_ids(payload, candidates)
    numbers = [item["id"] for item in payload["checklist"]]
    if payload["unit_id"] != uid or numbers != list(range(1, len(numbers) + 1)) or None in mapped.values():
        flag("incorrect_packet_local_mapping", numeric_ids=numbers)
    if error:
        flag(error)
        if error in {"invalid_checklist_reference", "invalid_tagged_skeleton"}:
            flag("inspect_packet_item_sequence")
    assigned = [mapped[number] for number in numbers if mapped[number] is not None]
    invalid = [item for item in assigned if item in excluded]
    for item in invalid:
        flag("non_requirement_packet_assignment", original_id=item, classification=excluded[item])
    anchors = {source["index"]: _anchor(source) for source in payload["sources"]}
    if len(anchors) != len(payload["sources"]) or sorted(anchors) != list(range(1, len(anchors) + 1)):
        flag("invalid_packet_source_index_table")
    item_sources = {item["id"]: set(item["sources"]) for item in payload["checklist"]}
    signature_rows = []
    locality_failures = []
    seen_ids = set()
    for index, block in enumerate(blocks, 1):
        local_items = block["candidate_items"]
        block_items = [mapped.get(number) for number in local_items]
        if None in block_items:
            flag("incorrect_packet_local_mapping", block=index, numeric_ids=local_items)
        seen_ids.update(item for item in block_items if item)
        allowed = permitted_related | {anchors[i] for number in local_items for i in item_sources.get(number, ()) if i in anchors}
        refs = [i for claim in block["claims"] for i in claim["source_indexes"]]
        if any(anchors.get(i) not in allowed for i in refs):
            locality_failures.append(index)
        if (block["provenance"] == "derived") != bool(refs):
            flag("unsupported_provenance", block=index)
        signature_rows.append((_signature(block, anchors), block_items))
    if locality_failures:
        flag("citation_outside_item_source", blocks=locality_failures)
    if parsed_missing := sorted(set(assigned) - seen_ids):
        flag("missing_generated_group", original_ids=parsed_missing)

    headers = Counter(re.findall(r"(?m)^@@BLOCK kind=(\w+) provenance=\w+ sources=[\d,-]+ items=(\d+)\r?$", packet.raw))
    duplicate_slots = [{"kind": kind, "number": number, "occurrences": n}
                       for (kind, number), n in headers.items() if n > 1]
    if duplicate_slots:
        flag("duplicate_block_group", slots=duplicate_slots)
    complete_groups = sum(
        [b["kind"] for b in blocks if b["candidate_items"] == [number]] == list(layout.kinds)
        for number in numbers)
    expected_slots = [(number, kind) for number in numbers for kind in layout.kinds]
    actual_slots = [(b["candidate_items"][0], b["kind"]) for b in blocks if len(b["candidate_items"]) == 1]
    valid_by_group = sum((Counter(actual_slots) & Counter(expected_slots)).values())
    if expected_slots != actual_slots:
        flag("required_kind_order_or_completeness", expected=len(expected_slots), actual=len(actual_slots))
    derived = sum(b["provenance"] == "derived" for b in blocks)
    claim_count = sum(len(b["claims"]) for b in blocks)
    return ({
        "number": ordinal, "unit_id": payload["unit_id"], "expected_blocks": layout.block_count,
        "raw_response_sha256": sha256(packet.raw.encode("utf-8")).hexdigest(),
        "parsed_blocks": len(blocks), "finish_reason": packet.finish_reason or None, "parse_reason": error or None,
        "invalid_source_references": int(error == "invalid_claim_index"),
        "invalid_item_references": int(error == "invalid_checklist_reference"),
        "truncated": packet.finish_reason.lower().rsplit(".", 1)[-1] in {"length", "max_tokens", "truncated"},
        "malformed": error in {"malformed_tagged_output", "missing_batch_unit", "duplicate_batch_unit"},
        "numeric_to_original_id": mapped, "assigned_original_ids": assigned, "invalid_assignments": invalid,
        "source_anchors": payload["sources"], "candidate_ids_recovered_from_blocks": sorted(seen_ids),
        "required_kind_coverage": _ratio(valid_by_group, len(expected_slots)),
        "groups_complete": _ratio(complete_groups, len(numbers)), "duplicate_group_slots": duplicate_slots,
        "ordered_slots_match": expected_slots == actual_slots,
        "derived_blocks": derived, "supplementary_blocks": len(blocks) - derived,
        "derived_claims": claim_count, "locality_failures": locality_failures,
        "complete_group_original_ids": [mapped[number] for number in numbers if mapped[number] and
            [b["kind"] for b in blocks if b["candidate_items"] == [number]] == list(layout.kinds)],
    }, signature_rows, set(anchors.values()))


def score_unit(annotation, pages, candidates, requested_ids, packets, draft, *,
               evidence_kind, review_packet=None, reference_rows=(), verdict=None, ready=None, exclusions=()):
    """Score the same production artifacts for every document. Mock evidence stays labelled."""
    uid = annotation["unit_id"]
    requirements = [row for row in annotation["requirements"] if row["mandatory"]]
    expected_ids = {item for row in requirements for item in row["candidate_ids"]}
    annotations_by_item = defaultdict(list)
    for row in requirements:
        for item in row["candidate_ids"]:
            annotations_by_item[item].append(row["id"])
    excluded = {row["candidate_id"]: row["classification"] for row in annotation.get("non_requirement_candidates", ())}
    true_false_positives = {row["candidate_id"] for row in annotation.get("non_requirement_candidates", ())
                            if row["is_false_positive"]}
    issues = []

    def flag(code, **details):
        issues.append({"code": code} | details)

    candidate_ids = [row["item_id"] for row in candidates]
    item_anchors = {row["item_id"]: [a for a in row["anchors"] if _exact(a, pages)] for row in candidates}
    excluded_anchors = [a for row in exclusions for a in row["anchors"]]
    exact_exclusions = sum(_exact(a, pages) for a in excluded_anchors)
    if exact_exclusions != len(excluded_anchors):
        flag("invalid_excluded_source_offsets", count=len(excluded_anchors) - exact_exclusions)
    expected_reasons = {"supporting_objective": "redundant_objective"}
    for row in exclusions:
        cid = row["item_id"]
        if cid in candidate_ids or row["reason"] != expected_reasons.get(excluded.get(cid), excluded.get(cid)):
            flag("unexpected_checklist_exclusion", original_id=cid, reason=row["reason"])
    covered = _scoped_requirements(requirements, set(candidate_ids), item_anchors)
    accepted = _scoped_requirements(requirements, set(requested_ids), item_anchors)
    missing_requirements = [row["id"] for row in requirements if row["id"] not in covered]
    if missing_requirements:
        flag("missing_genuine_source_requirement", annotation_ids=missing_requirements)
    if missing_accepted := sorted(covered - accepted):
        flag("missing_accepted_requirement", annotation_ids=missing_accepted)
    if repeated := _duplicates(candidate_ids):
        flag("duplicate_checklist_item", original_ids=repeated)
    false_positives = [item for item in candidate_ids if item in true_false_positives or item not in expected_ids | excluded.keys()]
    for cid in false_positives:
        flag("running_margin_false_positive" if excluded.get(cid, "").startswith("running_")
             else "checklist_false_positive", original_id=cid, classification=excluded.get(cid, "unmapped"))
    if unexpected_accepted := [cid for cid in requested_ids if cid not in expected_ids]:
        flag("accepted_non_requirement_candidates", original_ids=unexpected_accepted)
    candidate_anchors = [a for item in candidates for a in item["anchors"]]
    exact_candidate = sum(_exact(a, pages) for a in candidate_anchors)
    if exact_candidate != len(candidate_anchors):
        flag("invalid_checklist_source_offsets", count=len(candidate_anchors) - exact_candidate)
    source_trace = []
    for row in requirements:
        excerpts = []
        for evidence in row["evidence"]:
            matching_ids = [cid for cid in row["candidate_ids"]
                            if any(_contains(a, evidence) for a in item_anchors.get(cid, ()))]
            exact = _exact(evidence, pages)
            correct_page = evidence["page"] in annotation["actual_source_pages"]
            if not exact or not correct_page:
                flag("invalid_annotation_evidence", annotation_id=row["id"], page=evidence["page"])
            excerpts.append(evidence | {"exact_indexed_span": exact, "correct_page": correct_page,
                                        "matching_original_ids": matching_ids})
        source_trace.append(row | {"evidence": excerpts})

    allowed_context = {int(i) for i in draft.get("related_source_units", {})}
    merged_anchors = {i: _anchor(a) if _exact(a, pages) else None for i, a in enumerate(draft["sources"], 1)}
    permitted_related = {merged_anchors[i] for i in allowed_context if i in merged_anchors and merged_anchors[i]}
    observed_signatures = [_signature(b, merged_anchors) for b in draft["blocks"]]
    remaining = Counter(observed_signatures)
    packets_report, expected_signatures = [], []
    assignments = []
    mapped_blocks = defaultdict(list)
    fully_retained_groups = set()
    block_origins = defaultdict(dict)
    non_requirements = excluded | {cid: "unmapped" for cid in set(candidate_ids) - expected_ids - excluded.keys()}
    for ordinal, packet in enumerate(packets, 1):
        report, rows, local_anchors = _packet_score(
            packet, ordinal, uid, candidates, non_requirements, permitted_related, issues,
        )
        assigned = report["assigned_original_ids"]
        assignments.extend(assigned)
        report["assigned_annotation_ids"] = sorted(_scoped_requirements(
            requirements, set(assigned), item_anchors))
        retained = 0
        lost_groups = set()
        for signature, originals in rows:
            expected_signatures.append(signature)
            block_origins[signature[:2]][ordinal] = local_anchors
            retained += bool(remaining[signature])
            if remaining[signature]:
                remaining[signature] -= 1
            else:
                lost_groups.update(originals)
            for cid in originals:
                mapped_blocks[cid].append(signature)
        report["parsed_to_merged_retention"] = _ratio(retained, len(rows))
        report["resolved_packet_anchors"] = _ratio(sum(a in merged_anchors.values() for a in local_anchors), len(local_anchors))
        fully_retained_groups.update(set(report["complete_group_original_ids"]) - lost_groups)
        packets_report.append(report)
    if len(packets_report) < annotation["expected_packet_count"]:
        flag("missing_packet", expected=annotation["expected_packet_count"], actual=len(packets_report))
    if len(packets_report) > annotation["expected_packet_count"]:
        flag("extra_packet", expected=annotation["expected_packet_count"], actual=len(packets_report))
    packet_assignments = [tuple(r["assigned_original_ids"]) for r in packets_report]
    if _duplicates(packet_assignments):
        flag("duplicate_packet", packet_numbers=[p["number"] for p, signature in zip(packets_report, packet_assignments)
                                                  if packet_assignments.count(signature) > 1])
    if assignment_duplicates := _duplicates(assignments):
        flag("duplicate_packet_assignments", original_ids=assignment_duplicates)
    if assignment_missing := sorted(set(requested_ids) - set(assignments)):
        flag("missing_packet_assignments", original_ids=assignment_missing)
    if unexpected_assignments := sorted(set(assignments) - set(requested_ids)):
        flag("unexpected_packet_assignments", original_ids=unexpected_assignments)
    if Counter(assignments) == Counter(requested_ids) and assignments != list(requested_ids):
        flag("incorrect_packet_assignment_order")
    source_union = _scoped_requirements(requirements, set(assignments), item_anchors)
    missing_from_packets = sorted({row["id"] for row in requirements} - source_union)
    if missing_from_packets:
        flag("source_requirements_missing_from_packet_union", annotation_ids=missing_from_packets)

    expected_counts = Counter(expected_signatures)
    observed_counts = Counter(observed_signatures)
    dropped, added = sum((expected_counts - observed_counts).values()), sum((observed_counts - expected_counts).values())
    if dropped or added:
        flag("merged_block_or_evidence_mismatch", missing=dropped, unexpected=added)
    order_ok = observed_signatures == expected_signatures
    if not order_ok and not dropped and not added:
        flag("incorrect_merged_order")
    if _duplicates([block["block_id"] for block in draft["blocks"]]):
        flag("duplicate_merged_block_id")

    # Rows enter the review wire with one new unit-local enumeration, after generation merges.
    review_map = original_ids(review_packet, candidates, review=True) if review_packet else {}
    blocks_by_id = {block["block_id"]: observed_signatures[i] for i, block in enumerate(draft["blocks"])}
    expected_review_ids = [cid for cid in requested_ids if cid in set(assignments)]
    if review_packet and list(review_map.values()) != expected_review_ids:
        flag("incorrect_review_numeric_mapping", expected=expected_review_ids, actual=list(review_map.values()))
    confirmed = (verdict or {}).get("independent_review", {}).get("checklist_evidence", [])
    valid_reviews = 0
    valid_control_refs = 0
    raw_review_count = len(confirmed)
    for row in reference_rows:
        original = review_map.get(row["item_id"])
        block = blocks_by_id.get(row["block_id"])
        if (row["expected_original_id"] != original or block not in mapped_blocks[original]
                or row.get("production_remapped_original_id", original) != original):
            flag("incorrect_review_item_or_block_mapping", numeric_id=row["item_id"], original_id=original)
        else:
            valid_control_refs += 1
    if verdict is not None:
        raw_review_count = len(reference_rows)
        for row in confirmed:
            valid_reviews += bool(row["item_id"] in expected_ids
                                  and blocks_by_id.get(row["block_id"]) in mapped_blocks[row["item_id"]])
        if valid_reviews != len(requirements) or raw_review_count != valid_reviews:
            flag("incomplete_or_invalid_review_evidence", confirmed=valid_reviews, raw=raw_review_count)
    claim_refs = [i for block in draft["blocks"] for claim in block["claims"] for i in claim["source_indexes"]]
    display_refs = [i for block in draft["blocks"] for i in block["source_indexes"]]
    source_anchors = sum(a is not None for a in merged_anchors.values())
    resolved_refs = sum(merged_anchors.get(i) is not None for i in claim_refs)
    if resolved_refs != len(claim_refs) or any(not merged_anchors.get(i) for i in display_refs):
        flag("invalid_merged_source_reference")
    derived_losses = [b["block_id"] for b in draft["blocks"] if b["provenance"] == "derived" and not b["source_indexes"]]
    if derived_losses:
        flag("missing_derived_citation", block_ids=derived_losses)
    display_mismatches = [b["block_id"] for b in draft["blocks"] if b["provenance"] in {"course", "derived"}
                          and set(b["source_indexes"]) != {i for c in b["claims"] for i in c["source_indexes"]}]
    if display_mismatches:
        flag("displayed_claim_reference_mismatch", block_ids=display_mismatches)
    bounds = tuple(annotation.get("unit_map_start", ())), tuple(annotation.get("unit_map_end", ()))
    cross_unit = sorted({i for i in claim_refs if (anchor := merged_anchors.get(i)) and i not in allowed_context
                         and ((bounds[0] and (bounds[0] > anchor[:2] or (anchor[0], anchor[2]) > bounds[1]))
                              or (not bounds[0] and anchor[0] not in annotation["actual_source_pages"]))})
    if cross_unit:
        flag("unauthorized_cross_unit_evidence", source_indexes=cross_unit)
    cross_packet = []
    for block in draft["blocks"]:
        origins = block_origins[(block["kind"], block["text"])]
        if len(origins) == 1:
            origin, allowed = next(iter(origins.items()))
            foreign = [i for claim in block["claims"] for i in claim["source_indexes"]
                       if (source := merged_anchors.get(i)) is not None and source not in allowed]
            if foreign:
                cross_packet.append({"block_id": block["block_id"], "packet": origin, "source_indexes": foreign})
    if cross_packet:
        flag("cross_packet_evidence_leakage", blocks=cross_packet)
    fully_retained_requirements = _scoped_requirements(requirements, fully_retained_groups, item_anchors)
    exact_evidence = [a for row in source_trace for a in row["evidence"]]
    findings = draft["findings"]
    return {
        "unit_id": uid, "label": annotation["label"], "evidence_kind": evidence_kind,
        "source": {"ground_truth_requirements": len(requirements), "extracted_candidates": len(candidates),
                   "pre_filter_candidates": len(candidates) + len(exclusions),
                   "exclusion_ledger": list(exclusions),
                   "exclusion_counts": dict(Counter(row["reason"] for row in exclusions)),
                   "exact_exclusion_anchors": _ratio(exact_exclusions, len(excluded_anchors)),
                   "accepted_candidates": len(requested_ids), "correct_candidates": len(set(candidate_ids) & expected_ids),
                   "correct_requirements": len(covered), "accepted_requirements": len(accepted),
                   "missing_requirements": missing_requirements, "false_positive_candidates": false_positives,
                   "requirements_without_standalone_candidate": [r["id"] for r in requirements if
                       not any(annotations_by_item[i] == [r["id"]] and all(
                           any(_contains(a, evidence) for a in item_anchors.get(i, ())) for evidence in r["evidence"]
                       ) for i in r["candidate_ids"])],
                   "redundant_objectives": [c for c in candidate_ids if excluded.get(c) == "supporting_objective"],
                   "duplicate_candidates": repeated, "excluded_candidate_details": annotation.get("non_requirement_candidates", []),
                   "extraction_quality": _prf(sum(cid in expected_ids for cid in candidate_ids), len(candidates),
                                               len(covered), len(requirements)),
                   "accepted_quality": _prf(sum(cid in expected_ids for cid in requested_ids), len(requested_ids),
                                              len(accepted), len(requirements)),
                   "source_traceability": _ratio(sum(a["exact_indexed_span"] and bool(a["matching_original_ids"])
                                                     for a in exact_evidence), len(exact_evidence)),
                   "page_attribution": _ratio(sum(a["correct_page"] and bool(a["matching_original_ids"])
                                                  for a in exact_evidence), len(exact_evidence)),
                   "exact_candidate_anchors": _ratio(exact_candidate, len(candidate_anchors)),
                   "trace": source_trace, "candidates": candidates},
        "assignment": {"expected_packets": annotation["expected_packet_count"], "actual_packets": len(packets_report),
                       "original_ids": assignments, "genuine_source_union": sorted(source_union),
                       "genuine_source_missing": missing_from_packets, "duplicate_original_ids": assignment_duplicates,
                       "missing_accepted_original_ids": assignment_missing, "unexpected_original_ids": unexpected_assignments,
                       "invalid_assignments": [i for i in assignments if i not in expected_ids],
                       "cross_packet_duplicate_assignments": sorted(assignment_duplicates),
                       "original_id_preservation": _ratio(len(set(assignments) & set(requested_ids)), len(set(requested_ids)))},
        "packets": packets_report,
        "merged": {"planned_blocks": sum(p["expected_blocks"] for p in packets_report),
                   "ground_truth_skeleton_if_one_group_per_requirement": sum(len(r["block_kinds"]) for r in requirements),
                   "actual_blocks": len(observed_signatures),
                   "parsed_to_merged_retention": _ratio(len(expected_signatures) - dropped, len(expected_signatures)),
                   "missing_blocks": dropped, "unexpected_blocks": added, "ordered_blocks_match": order_ok,
                   "source_requirements_with_all_linked_groups_retained": _ratio(len(fully_retained_requirements),
                                                                               len(requirements)),
                   "final_coverage": (verdict or draft)["coverage"],
                   "linked_group_missing_source_requirements": sorted({r["id"] for r in requirements}
                                                                     - fully_retained_requirements),
                   "interruptions": draft["interruptions"], "dropped_block_counts": draft.get("dropped_block_counts", {}),
                   "production_coverage": draft["coverage"]},
        "citations": {"resolved_anchors": _ratio(source_anchors, len(merged_anchors)),
                      "derived_claims": sum(len(b["claims"]) for b in draft["blocks"] if b["provenance"] == "derived"),
                      "claims_retained_in_unverified_blocks": sum(len(b["claims"]) for b in draft["blocks"]
                                                                   if b["provenance"] == "unverified"),
                      "supplementary_blocks_without_claims": sum(b["provenance"] == "supplementary" and not b["claims"]
                                                                for b in draft["blocks"]),
                      "resolved_claim_anchor_references": _ratio(resolved_refs, len(claim_refs)),
                      "unresolved_source_references": len(claim_refs) - resolved_refs,
                      "authorized_cross_unit_anchors": draft.get("related_source_units", {}),
                      "unauthorized_cross_unit_references": cross_unit,
                      "cross_packet_evidence": [p["number"] for p in packets_report if p["invalid_source_references"]],
                      "merged_cross_packet_evidence": cross_packet,
                      "item_locality_failures": {p["number"]: p["locality_failures"] for p in packets_report
                                                 if p["locality_failures"]},
                      "derived_blocks_without_citations": derived_losses, "displayed_claim_mismatches": display_mismatches},
        "verification": {"verified_facts": draft["verified_facts"], "reviewable_items": draft["reviewable_items"],
                         "missing_checklist_item_ids": draft["missing_item_ids"],
                         "final_missing_checklist_item_ids": (verdict or draft)["missing_item_ids"],
                         "semantic_coverage_item_ids": (verdict or {}).get("semantic_coverage_item_ids", []),
                         "calculation_blocks": [b["block_id"] for b in draft["blocks"] if b.get("calculation")],
                         "hypothetical_blocks": [b["block_id"] for b in draft["blocks"] if b.get("hypothetical")],
                         "numeric_source_requirements": [row["id"] for row in requirements
                                                         if row["category"] in {"numeric_literal", "runtime_output"}],
                         "numeric_findings": [f for f in findings if any(term in f["code"] for term in ("numeric", "number", "fact", "value"))],
                         "calculation_findings": [f for f in findings if any(term in f["code"] for term in ("calc", "equation"))],
                         "hypothetical_findings": [f for f in findings if "hypothetical" in f["code"]],
                         "teaching_findings": [f for f in findings if any(term in f["code"] for term in ("teach", "reasoning", "copy", "action_missing"))],
                         "copy_without_explanation": [f for f in findings if f["code"] == "copy_without_explanation"],
                         "authoritative_findings": [f for f in findings if f["severity"] == "authoritative"],
                         "all_findings": findings},
        "review": {"status": "historical_live_replay" if verdict else "not_evaluated", "numeric_to_original_id": review_map,
                   "mapping_probe": _ratio(valid_control_refs, len(reference_rows)),
                   "mapping_references": reference_rows,
                   "evidence_completeness": _ratio(valid_reviews, len(requirements)) if verdict else None,
                   "invalid_evidence_references": raw_review_count - valid_reviews if verdict else None,
                   "pedagogy_score": (verdict or {}).get("independent_review", {}).get("pedagogy_score"),
                   "findings": (verdict or {}).get("independent_review", {}).get("findings"),
                   "verdict": (verdict or {}).get("review_state"), "ready_stage": ready},
        "failures": issues,
    }


def aggregate(units):
    """Micro-count independent denominators. Keep separate evidence populations visible."""
    totals = {}
    for kind in sorted({row["evidence_kind"] for row in units}):
        reports = [row for row in units if row["evidence_kind"] == kind]
        totals[kind] = {
            "units": len(reports),
            "source_requirements": _ratio(sum(u["source"]["correct_requirements"] for u in reports),
                                          sum(u["source"]["ground_truth_requirements"] for u in reports)),
            "candidate_precision": _ratio(sum(u["source"]["correct_candidates"] for u in reports),
                                          sum(u["source"]["extracted_candidates"] for u in reports)),
            "packet_count": {"actual": sum(u["assignment"]["actual_packets"] for u in reports),
                             "expected": sum(u["assignment"]["expected_packets"] for u in reports)},
            "block_retention": _ratio(sum(u["merged"]["parsed_to_merged_retention"]["count"] for u in reports),
                                       sum(u["merged"]["parsed_to_merged_retention"]["total"] for u in reports)),
            "failures_by_code": dict(Counter(f["code"] for u in reports for f in u["failures"])),
        }
    return totals
