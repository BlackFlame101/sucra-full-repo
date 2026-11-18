"""Phase 5 structured drafting and deterministic verification for one Unit Map unit."""
from collections import Counter
from dataclasses import asdict
import json
import re
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_core import PydanticCustomError

from agents.explain_budget import ExplainCallLimit
from agents.explain_tagged_output import MAX_TAGGED_BLOCKS, TaggedLayout, generation_format, parse_tagged_units
from agents.explain_lab_verification import KINDS as LAB_KINDS, deterministic_passed, lab_generation_rules, requires_lab_check, verify_spark_setup
from agents.explain_unit_prompts import generation_system, teaching_rules
from agents.explain_verifier import Anchor, Block, Calculation, Claim, CONTRACTS, Finding, evidence_lookup, verify_unit
from agents.structured_output import has_control_characters, message_text, recover_json_prefix
from rag.explain_preparation import verifier_checklist

PROVIDER_TEXT_CORRUPTION = "provider_text_corruption"
JSON_BLOCK_LIMIT = 16


class DraftClaim(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    start: int | None = None
    end: int | None = None
    quote: str | None = Field(default=None, min_length=1, max_length=3000,
                              validation_alias=AliasChoices("output_quote", "quote"))
    source_indexes: list[int] = Field(max_length=12)

    @model_validator(mode="after")
    def validate_selector(self):
        if self.quote is not None and (self.start is not None or self.end is not None):
            raise PydanticCustomError("mixed_claim_marker", "Claim mixes a quote with legacy offsets")
        if self.quote is None and (self.start is None or self.end is None):
            raise PydanticCustomError("missing_claim_selector", "Claim requires a quote or both legacy offsets")
        return self

    def resolve(self, text: str, indexes: tuple[int, ...]) -> Claim:
        if self.quote is None:
            return Claim(self.start, self.end, indexes)
        needle = evidence_lookup(self.quote)[0].strip()
        normalized, spans = evidence_lookup(text)
        start = normalized.find(needle) if needle else -1
        if start < 0:
            raise PydanticCustomError("claim_quote_not_found", "Claim quote was not found in the block")
        if normalized.find(needle, start + 1) >= 0:
            raise PydanticCustomError("ambiguous_claim_quote", "Claim quote occurs more than once in the block")
        return Claim(spans[start][0], spans[start + len(needle) - 1][1], indexes)


class DraftCalculation(BaseModel):
    expression: str = Field(max_length=256)
    expected: str = Field(max_length=64)


class DraftBlock(BaseModel):
    model_config = ConfigDict(strict=True)
    kind: str = Field(max_length=40)
    text: str = Field(min_length=1, max_length=3000)
    provenance: Literal["course", "derived", "supplementary", "unverified"]
    claims: list[DraftClaim] = Field(default_factory=list, max_length=80)
    hypothetical: bool = False
    calculation: DraftCalculation | None = None
    candidate_items: list[int] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_quote_spans(self):
        for claim in self.claims:
            if claim.quote is not None:
                claim.resolve(self.text, ())
        return self

class DraftUnit(BaseModel):
    blocks: list[DraftBlock] = Field(max_length=JSON_BLOCK_LIMIT)


SCHEMA = DraftUnit.model_json_schema()
BATCH_SCHEMA = {
    "$defs": SCHEMA["$defs"],
    "type": "object", "required": ["units"],
    "properties": {"units": {"type": "array", "items": {
        "type": "object", "required": ["unit_id", "blocks"],
        "properties": {"unit_id": {"type": "string"}, "blocks": SCHEMA["properties"]["blocks"]},
    }}},
}


def _source_material(unit, record, excerpts, required, related=None):
    """Revalidate persisted PDF offsets/quotes against the current unit's indexed excerpts."""
    page_segments = {}
    citations = {}
    complete, missing = [], []
    by_page = {}
    for row in excerpts:
        by_page.setdefault(row["page_number"], []).append(row)
    for item in record.get("checklist", ()):
        if item["item_id"] not in required:
            continue
        bindings = []
        for raw in item["anchors"]:
            source = Anchor(**raw)
            start, end = (source.page, source.start), (source.page, source.end)
            quote = " ".join(source.quote.split())
            chunk = next((row for row in by_page.get(source.page, ())
                          if quote and quote in " ".join(row["content"].split())), None)
            if (not chunk or not 0 <= source.start < source.end <= 1_000_000
                    or len(source.quote) != source.end - source.start
                    or start < tuple(unit["start"]) or end > tuple(unit["end"])):
                break
            bindings.append((source, chunk))
        if not bindings or len(bindings) != len(item["anchors"]):
            missing.append(item["item_id"])
            continue
        complete.append(item)
        for source, chunk in bindings:
            citations[source] = chunk
            page_segments.setdefault(source.page, []).append(source)
    for anchor, entry in (related or {}).items():
        if anchor not in citations:
            citations[anchor] = entry["chunk"]
            page_segments.setdefault(anchor.page, []).append(anchor)
    pages = {}
    for page, anchors in page_segments.items():
        text = [" "] * max(anchor.end for anchor in anchors)
        for anchor in anchors:
            text[anchor.start:anchor.end] = list(anchor.quote)
        pages[page] = "".join(text)
    return complete, missing, citations, pages


def related_unit_ids(unit, units, records):
    by_id = {candidate["logical_id"]: candidate for candidate in units}
    uid = unit["logical_id"]
    dependencies = list(records.get(uid, {}).get("depends_on", ()))
    if _instructional_context(unit) == "case_study" and unit.get("label", "").casefold().startswith("question "):
        dependencies.extend(candidate["logical_id"] for candidate in units
                            if candidate.get("label", "").casefold().startswith("réponse ")
                            and uid in records.get(candidate["logical_id"], {}).get("depends_on", ()))
    linked = dict.fromkeys([*dependencies, *(parent for dep in dependencies
                                           for parent in records.get(dep, {}).get("depends_on", ()))])
    return [dep for dep in linked if dep != uid and dep in by_id
            and by_id[dep].get("document_id") == unit.get("document_id")]


def linked_evidence(unit, units, records, excerpts_by_unit):
    linked, size = {}, 0
    by_id = {candidate["logical_id"]: candidate for candidate in units}
    for uid in related_unit_ids(unit, units, records):
        peer, record = by_id[uid], records.get(uid, {})
        if record.get("content_version") != peer["content_version"]:
            continue
        required = {item["item_id"] for item in record.get("checklist", ()) if item["importance"] != "optional"}
        _, _, anchors, _ = _source_material(peer, record, excerpts_by_unit.get(uid, ()), required)
        for anchor, chunk in anchors.items():
            if anchor in linked or size + len(anchor.quote) > 4500:
                continue
            linked[anchor] = {"unit_id": uid, "label": peer["label"], "chunk": chunk}
            size += len(anchor.quote)
            if len(linked) == 24:
                return linked
    return linked


def _packet_sources(items, related):
    return list(dict.fromkeys([*(Anchor(**a) for item in items for a in item["anchors"]), *(related or {})]))


def _prompt(unit, plan, items, sources, record, continuity, language, related=None):
    indexes = {source: index for index, source in enumerate(sources, 1)}
    pages = {source.page for source in sources}
    figure_captions = [figure["caption"] for figure in record.get("figures", ())
                       if figure.get("caption") and Anchor(**figure["caption"]) in indexes]
    context = _instructional_context(unit)
    ordered, rules = teaching_rules(unit["kind"], context, items, qcm_without_key=_qcm_without_key(sources))
    checklist_kinds = (kind for item in verifier_checklist({"checklist": items}) for kind in item.block_kinds)
    payload = {
        "unit": unit["title"], "unit_id": unit["logical_id"], "kind": unit["kind"],
        "level": plan["level"], "depth": plan["depth"],
        "omit_proofs": plan.get("omit_proofs", False), "language": language,
        "required_blocks": list(dict.fromkeys((*CONTRACTS.get(unit["kind"], ()), *checklist_kinds))),
        "checklist": [{"id": number, "type": item["type"], "text": item["text"],
                       "importance": item["importance"], "facts": item["facts"],
                       "sources": [indexes[Anchor(**anchor)] for anchor in item["anchors"]]}
                      for number, item in enumerate(items, 1)],
        "sources": [asdict(source) | {"index": index} | (
            {"relationship": "context", "unit_id": related[source]["unit_id"], "label": related[source]["label"]}
            if related and source in related else {}) for source, index in indexes.items()],
        "figure_captions": figure_captions,
        "table_columns": [table["columns"] for table in record.get("tables", ()) if table["page"] in pages],
        "source_gaps": [{key: gap[key] for key in ("page", "kind", "reason", "status") if key in gap}
                        for gap in plan.get("unverifiable_source", {}).get(unit["logical_id"], ())],
        "prior_learning": continuity,
        "instructional_context": context, "ordered_calculation": ordered, "teaching_rules": rules,
    }
    if requires_lab_check(unit):
        payload["lab_command_contract"] = lab_generation_rules(items, language, payload["checklist"])
    return [SystemMessage(content=generation_system([payload], generation_format())),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False))]



def _parse(raw, *, packet=None, reason=""):
    text = raw if isinstance(raw, str) else message_text(raw)
    if packet is not None:
        unit_id = packet["unit_id"]
        normalized, error = parse_tagged_units(text, {unit_id: TaggedLayout.from_packet(packet)}, reason)[unit_id]
        return json.loads(normalized)["blocks"] if normalized else [], error
    try:
        # Keep literal controls inside JSON strings so the affected block can be rejected.
        root = json.loads(text, strict=False)
        return root["blocks"], ""
    except (ValueError, KeyError, TypeError):
        return recover_json_prefix(text, frozenset({"blocks"})).get("blocks", []), "truncated"


def claim_validation_reason(error, fallback):
    reasons = {issue["type"] for issue in error.errors()}
    return next((reason for reason in ("mixed_claim_marker", "missing_claim_selector", "claim_quote_not_found",
                                      "ambiguous_claim_quote") if reason in reasons), fallback)


def resolve_claims(block, local, index_map, *, allowed_indexes=None):
    claims = []
    allowed = range(1, len(local) + 1) if allowed_indexes is None else allowed_indexes
    for claim in block.claims:
        if any(index not in allowed for index in claim.source_indexes):
            raise PydanticCustomError("invalid_claim_index", "Claim cites a source outside its authorized evidence")
        resolved = claim.resolve(block.text, tuple(index_map[index] for index in claim.source_indexes))
        if claim.quote is not None and block.provenance == "course":
            needle = evidence_lookup(block.text[resolved.start:resolved.end])[0].strip()
            if not needle or not any(needle in evidence_lookup(local[index - 1].quote)[0]
                                     for index in claim.source_indexes):
                raise PydanticCustomError("claim_quote_not_in_source", "Course quotation differs from the cited source")
        claims.append(resolved)
    return tuple(claims)


def _instructional_context(unit):
    if re.fullmatch(r"Q\s*\d+", unit.get("label", ""), re.I):
        return "qcm"
    if any(part[0] == "étude de cas" for part in unit.get("heading_path", ())):
        return "case_study"
    return ""


_EXPLANATION_KINDS = frozenset({
    "explanation", "intuition", "source_example", "takeaway", "method", "working", "final_answer",
    "interpretation", "trade_off", "specific_reading", "limitations",
})


def _word_grams(text):
    words = re.findall(r"\b[^\W_]+\b", evidence_lookup(text)[0].casefold())
    return set(zip(words, words[1:], words[2:], words[3:]))


def teaching_findings(unit, blocks, sources, language, *, related=None):
    context = _instructional_context(unit)
    checks = []
    uid = unit["logical_id"]
    questions = [_word_grams(anchor.quote) for anchor, link in (related or {}).items()
                 if re.match(r"(?i)^Q(?:uestion)?\s*\d", link.get("label", ""))]
    if unit.get("kind") == "exercise":
        questions.append(_word_grams(unit.get("title", "")))
    source_grams = [_word_grams(anchor.quote) for anchor in sources]
    for block in blocks:
        if block.kind in _EXPLANATION_KINDS:
            grams = _word_grams(block.text)
            cited = {i for claim in block.claims for i in claim.source_indexes if 1 <= i <= len(sources)}
            comparisons = [*questions, *(source_grams[i - 1] for i in cited)]
            if len(grams) >= 3 and any(len(grams & other) * 10 >= len(grams) * 7 for other in comparisons):
                checks.append(Finding("copy_without_explanation", "missing", uid,
                                      "The block repeats source material without explaining it", block_id=block.block_id))
        if language != "French" or block.kind in {"command_or_ui", "given_values", "problem"}:
            continue
        prose = re.sub(r"`{3}.*?`{3}|`[^`]*`", "", block.text, flags=re.S).casefold()
        words = re.findall(r"\b[^\W\d_]+\b", prose)
        english = sum(word in {"the", "and", "because", "which", "this", "that", "with", "is", "are", "should", "why"}
                      for word in words)
        french = sum(word in {"le", "la", "les", "de", "des", "du", "et", "est", "sont", "pour", "dans", "que", "avec"}
                     for word in words)
        if english >= 4 and english > 2 * french:
            checks.append(Finding("language_mismatch", "missing", uid, "Instructional prose should be in French",
                                  block_id=block.block_id))
    if context == "qcm" and _qcm_without_key(sources):
        for block in blocks:
            if block.kind == "final_answer" and not re.search(r"réponse[s]? raisonnée[s]?|reasoned answer", block.text, re.I):
                checks.append(Finding("qcm_answer_uncertainty_missing", "missing", uid,
                                      "Label the answer as reasoned when the unit has no source answer key",
                                      block_id=block.block_id))
            if re.search(r"selon (?:le corrigé|la correction)|confirmé[e]?[s]? par le (?:PDF|corrigé)|"
                         r"according to the answer key|confirmed by the (?:PDF|answer key)", block.text, re.I):
                checks.append(Finding("unsupported_answer_key_attribution", "missing", uid,
                                      "No answer key is present in this question's evidence",
                                      block_id=block.block_id))
    if context == "case_study" and blocks:
        cited = " ".join(evidence_lookup(source.quote)[0].casefold() for source in sources)
        reasoning = [block for block in blocks if block.kind in
                     {"method", "working", "intuition", "explanation", "takeaway"}
                     and block.provenance == "derived"
                     and evidence_lookup(block.text)[0].casefold() not in cited
                     and re.search(r"\b(?:parce que|car|donc|afin de|ce qui|permet de|risque de|because|therefore|so that)\b",
                                   block.text, re.I)]
        if not reasoning:
            checks.append(Finding("case_reasoning_missing", "missing", uid,
                                  "Explain how the case evidence leads to the recommendation"))
        if re.match(r"^(?:question|réponse)\s+\d+", unit.get("label", ""), re.I) and not any(
            block.provenance == "derived" and block.kind in {"method", "working", "explanation", "final_answer", "takeaway"}
            and re.search(r"\b(?:doit|devrait|peut|il faut|en (?:ajoutant|précisant|contactant)|"
                          r"ajouter|préciser|adapter|reformuler|corriger|contacter|solliciter|"
                          r"should|could|can|recommend)\b", block.text, re.I)
            for block in blocks
        ):
            checks.append(Finding("case_action_missing", "missing", uid,
                                  "Give a concrete action that addresses this question"))
        for block in blocks:
            if re.search(r"\b(?:module conceptuel associé|voir (?:le|la) (?:module|corrigé)|explained in another (?:unit|module))\b",
                         block.text, re.I):
                checks.append(Finding("deferred_required_answer", "missing", uid, "Answer the task in this unit",
                                      block_id=block.block_id))
    return checks


def _qcm_without_key(sources):
    labels = {match[1] for source in sources for match in
              re.finditer(r"(?im)^\s*([A-D])[.)]\s", source.quote)}
    return labels == {"A", "B", "C", "D"} and not any(
        re.search(r"\bcorrigé\b|\banswer key\b|\bbonnes? réponses?\s*[:=]", source.quote, re.I)
        for source in sources
    )


def systemic_generation_failure(drafts, required_items):
    """Find systemic failures without discarding a valid sibling for a local error."""
    if not drafts:
        return None
    drops = Counter()
    for draft in drafts:
        drops.update(draft.get("dropped_block_counts", {}))
    if drops[PROVIDER_TEXT_CORRUPTION] * 2 > sum(drops.values()):
        return PROVIDER_TEXT_CORRUPTION
    if not any(draft["blocks"] for draft in drafts):
        return "zero_retained_blocks"
    usable = [draft for draft in drafts if any(
        block["provenance"] in {"course", "derived"} and block["source_indexes"] for block in draft["blocks"]
    )]
    if not usable:
        return "no_usable_provenance"
    if len(drafts) >= 3 and (len(drafts) - len(usable)) * 2 > len(drafts):
        return "systemic_provenance_failure"
    bad_blocks = sum(len({f["block_id"] for f in draft["findings"]
                          if f["severity"] == "authoritative" and f.get("block_id")
                          and ("claim" in f["code"] or "anchor" in f["code"])}) for draft in drafts)
    if len(drafts) > 1 and bad_blocks * 2 > sum(len(draft["blocks"]) for draft in drafts):
        return "systemic_provenance_failure"
    if len(drafts) > 1 and all(
        (required := set(required_items.get(draft["logical_id"], ())))
        and required <= set(draft["missing_item_ids"]) for draft in drafts
    ):
        return "zero_required_coverage"
    return None
def generation_packet(unit, record, excerpts, plan, continuity, language, related=None):
    required = set(plan["required_items"].get(unit["logical_id"], ()))
    items, _, _, _ = _source_material(unit, record, excerpts, required)
    sources = _packet_sources(items, related)
    messages = _prompt(unit, plan, items, sources, record, continuity, language, related)
    payload = json.loads(messages[-1].content)
    payload.update(unit_id=unit["logical_id"], depends_on=record.get("depends_on", []))
    return messages[0].content, payload, _estimated_output(unit, items, sources)


def _estimated_output(unit, items, sources):
    # Output includes full teaching text, claim JSON and, in a lab, literal code.
    source_bytes = sum(len(source.quote.encode("utf-8")) for source in sources)
    # Exercises need room for reasoning about alternatives as well as solutions.
    base, per_item = (680, 150) if unit["kind"] == "exercise" else (480, 105)
    return base + per_item * len(items) + (source_bytes // (5 if unit["kind"] == "lab_step" else 12))


def plan_generation_batch(packets, budget, *, output_scale=1.0):
    """Take the longest consecutive prefix that fits both provider limits."""
    payloads = []
    selected = None
    estimated = 0
    wire_format = generation_format()
    schema = BATCH_SCHEMA if wire_format == "json" else None
    for _, payload, cost in packets:
        if not payload["checklist"]:
            break
        if wire_format == "tagged" and not 0 < TaggedLayout.from_packet(payload).block_count <= MAX_TAGGED_BLOCKS:
            break
        payloads.append(payload)
        estimated += cost
        output = max(budget.policy.min_output_tokens, int(estimated * output_scale))
        messages = [
            SystemMessage(content=generation_system(payloads, wire_format, batch=True)),
            HumanMessage(content=json.dumps({"units": payloads}, ensure_ascii=False)),
        ]
        if output > budget.max_output_tokens or budget.prompt_tokens(messages, schema) + output > budget.capacity:
            break
        selected = (len(payloads), messages, output, sum(len(row["sources"]) for row in payloads))
    return selected if selected and selected[0] > 1 else None


def unpack_generation_batch(raw, unit_ids, reason="", *, packets=None):
    """Isolate unique unit envelopes and leave block validation to generation."""
    if generation_format() == "tagged":
        layouts = {packet["unit_id"]: TaggedLayout.from_packet(packet) for packet in (packets or ())}
        if list(layouts) != list(unit_ids):
            raise ValueError("Tagged responses must be parsed against their original packets")
        return parse_tagged_units(raw, layouts, reason)
    try:
        root = json.loads(raw if isinstance(raw, str) else message_text(raw), strict=False)
    except ValueError:
        root = recover_json_prefix(raw, frozenset({"units"}))
        reason = reason or "truncated"
    rows = root.get("units", []) if isinstance(root, dict) else []
    found = {}
    duplicates = set()
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict) or not isinstance(row.get("unit_id"), str) or row["unit_id"] not in unit_ids:
            continue
        uid = row["unit_id"]
        if uid in found:
            duplicates.add(uid)
        blocks = row.get("blocks")
        found[uid] = ((json.dumps({"blocks": blocks}, ensure_ascii=False), "") if isinstance(blocks, list)
                      else ("", "invalid_batch_unit"))
    return {uid: (("", "duplicate_batch_unit") if uid in duplicates else
                  found.get(uid, ("", reason or "missing_batch_unit"))) for uid in unit_ids}


async def generate_unit(unit, record, excerpts, plan, dispatch, *, fits, continuity, language, unit_map, prior=None,
                        batch_response=None, max_output=None, stop_on_invalid_packet=False, related=None):
    identifier = unit["logical_id"]
    tagged = generation_format() == "tagged"
    strict_lab = requires_lab_check(unit)
    if strict_lab:
        prior = None  # Revalidate a complete standalone cell on every generation.
    required = set(plan["required_items"].get(identifier, ()))
    items, missing_anchors, bindings, pages = _source_material(unit, record, excerpts, required, related)

    def packet(selected):
        sources = _packet_sources(selected, related)
        return sources, _prompt(unit, plan, selected, sources, record, continuity, language, related)

    def packet_fits(selected, sources, messages):
        layout_fits = (0 < TaggedLayout.from_packet(json.loads(messages[-1].content)).block_count <= MAX_TAGGED_BLOCKS
                       if tagged else not strict_lab or len(selected) * len(LAB_KINDS) <= JSON_BLOCK_LIMIT)
        return layout_fits and fits(messages) and (
            max_output is None or _estimated_output(unit, selected, sources) <= max_output)

    def split_to_fit(selected):
        sources, messages = packet(selected)
        if len(selected) == 1 or packet_fits(selected, sources, messages):
            yield selected
        else:
            midpoint = len(selected) // 2
            yield from split_to_fit(selected[:midpoint])
            yield from split_to_fit(selected[midpoint:])

    _, messages = packet(items)
    batches = [items] if items or (tagged and not required and bool(related)) else []
    if batch_response is None and items and (tagged or strict_lab or max_output is not None):
        batches = list(split_to_fit(items))
    elif batch_response is None and items and (not fits(messages) or (plan["depth"] == "exhaustive" and len(items) >= 14)):
        split = len(items) // 2
        if split:
            batches = [items[:split], items[split:]]
    blocks, candidates, citations, interruptions = [], set(), {}, []
    dropped_blocks = Counter()
    candidates_by_block = {}
    sources = list(bindings)
    by_anchor = {source: index for index, source in enumerate(sources, 1)}
    if prior:
        old_sources = {index: by_anchor.get(Anchor(**source))
                       for index, source in enumerate(prior["sources"], 1)}
        disputed = {finding["block_id"] for finding in prior.get("findings", ())
                    if finding["severity"] in {"authoritative", "source"}}
        for old in prior["blocks"]:
            if old["provenance"] == "unverified" or old["block_id"] in disputed:
                continue
            if any(not old_sources.get(i) for claim in old["claims"] for i in claim["source_indexes"]):
                continue
            claims = tuple(Claim(claim["start"], claim["end"], tuple(old_sources[i] for i in claim["source_indexes"]))
                           for claim in old["claims"])
            blocks.append(Block(old["block_id"], old["kind"], old["text"], old["provenance"], claims,
                                old["hypothetical"], Calculation(**old["calculation"]) if old.get("calculation") else None))
            citations[old["block_id"]] = [old_sources[i] for i in old["source_indexes"]]
        continuity = continuity | {"deepen": True, "existing_blocks": [
            {"kind": block.kind, "text": block.text[:360]} for block in blocks
        ]}
    for batch in batches:
        item_ids = {number: item["item_id"] for number, item in enumerate(batch, 1)}
        local, messages = packet(batch)
        if prior:
            payload = json.loads(messages[-1].content)
            payload["prior_missing_items"] = [number for number, item_id in item_ids.items()
                                              if item_id in prior["missing_item_ids"]]
            messages[-1] = HumanMessage(content=json.dumps(payload, ensure_ascii=False))
        if batch_response is None and not packet_fits(batch, local, messages):
            interruptions.append("context_limit")
            continue
        try:
            raw, reason = batch_response if batch_response is not None else await dispatch(messages, len(local))
        except ExplainCallLimit:
            interruptions.append("call_budget")
            break
        if reason:
            interruptions.append(reason)
        if strict_lab and has_control_characters(raw):
            interruptions.append(PROVIDER_TEXT_CORRUPTION)
            continue
        if batch_response is not None and not raw:
            break
        tagged_packet = json.loads(messages[-1].content) if tagged and batch_response is None else None
        drafts, parse_reason = _parse(raw, packet=tagged_packet, reason=reason)
        if parse_reason:
            interruptions.append(parse_reason)
        if not isinstance(drafts, list):
            if stop_on_invalid_packet and not reason:
                interruptions.append("zero_retained_blocks")
                break
            continue
        first_new_block = len(blocks)
        for candidate in drafts if tagged else drafts[:JSON_BLOCK_LIMIT]:
            if has_control_characters(candidate):
                dropped_blocks[PROVIDER_TEXT_CORRUPTION] += 1
                interruptions.append(PROVIDER_TEXT_CORRUPTION)
                continue
            try:
                draft = DraftBlock.model_validate(candidate)
            except ValidationError as error:
                drop = claim_validation_reason(error, "invalid_draft_block")
                dropped_blocks[drop] += 1
                interruptions.append(drop)
                continue
            if not tagged and not strict_lab and any(draft.text == block.text for block in blocks):
                dropped_blocks["duplicate_text"] += 1
                continue
            try:
                claims = resolve_claims(draft, local, {i: by_anchor[anchor] for i, anchor in enumerate(local, 1)})
            except PydanticCustomError as error:
                dropped_blocks[error.type] += 1
                interruptions.extend(("invalid_marker", error.type))
                continue
            block_id = f"{identifier}:{'deepen-' if prior else ''}{len(blocks) + 1}"
            while block_id in citations:
                block_id += "-new"
            blocks.append(Block(block_id, draft.kind, draft.text, draft.provenance, claims, draft.hypothetical,
                                Calculation(**draft.calculation.model_dump()) if draft.calculation else None))
            mapped_items = [item_ids[number] for number in draft.candidate_items if number in item_ids]
            if len(mapped_items) != len(draft.candidate_items):
                interruptions.append("invalid_checklist_reference")
            candidates.update(mapped_items)
            candidates_by_block[block_id] = mapped_items
            citations[block_id] = list(dict.fromkeys(index for claim in claims for index in claim.source_indexes))
        if reason in {"provider_failure", "deadline"}:
            break
        if stop_on_invalid_packet and batch_response is None and not prior and not reason and len(blocks) == first_new_block:
            interruptions.append("zero_retained_blocks")
            break
        if blocks:
            continuity = continuity | {"previous_packet": [block.kind for block in blocks][-12:]}
    # Spark uses the exact scoped checklist contract below. Keep the general block,
    # provenance, citation, and arithmetic checks without requiring copied prose.
    checklist = () if strict_lab else verifier_checklist({"checklist": items})
    findings = verify_unit(unit, blocks, pages=pages, sources=sources, checklist=checklist,
                           unit_map=unit_map, depth=plan["depth"], require_all=True, related_anchors=frozenset(related or ()))
    findings.extend(teaching_findings(unit, blocks, sources, language, related=related))
    rejected = {f.block_id for f in findings if f.severity == "authoritative"
                and f.code != "displayed_equation_mismatch"}
    disputed_equations = {}
    for finding in findings:
        if finding.code in {"displayed_equation_mismatch", "unverifiable_equation"}:
            indexes = disputed_equations.setdefault(finding.block_id, [])
            if finding.source in by_anchor and by_anchor[finding.source] not in indexes:
                indexes.append(by_anchor[finding.source])
    displayed = [asdict(block) | {
        "provenance": "unverified" if block.block_id in rejected or block.block_id in disputed_equations else block.provenance,
        "source_indexes": disputed_equations.get(block.block_id, [] if block.block_id in rejected else citations[block.block_id]),
    } for block in blocks]
    missing = sorted(required - {item["item_id"] for item in items}
                     | {f.item_id for f in findings if f.item_id and f.severity != "heuristic"})
    reviewable = {}
    textual_items = {item["item_id"]: {by_anchor[Anchor(**anchor)] for anchor in item["anchors"]}
                     for item in items if item["item_id"] in missing and not item["facts"]
                     and item["type"] in {"definition", "question", "numeric_result"}
                     and not re.search(r"[=<>\d]", re.sub(r"^\d+[.)-]\s*", "", item["text"]))}
    for block in blocks:
        if block.provenance != "derived" or block.block_id in rejected or block.block_id in disputed_equations:
            continue
        for item_id in candidates_by_block.get(block.block_id, ()):
            if item_id in textual_items and textual_items[item_id] <= set(citations[block.block_id]):
                reviewable.setdefault(item_id, []).append(block.block_id)
    gaps = plan.get("unverifiable_source", {}).get(identifier, [])
    verified = []
    if not any(f.severity in {"source", "authoritative"} for f in findings):
        verified = [fact | {"unit_id": identifier, "content_version": unit["content_version"],
                            "verification": "deterministic_only"} for item in items
                    if item["item_id"] in candidates and item["item_id"] not in missing for fact in item["facts"]]
        for block in blocks:
            if (block.kind in {"result", "final_answer"} and block.provenance == "derived" and block.calculation
                    and not any(f.block_id == block.block_id for f in findings) and citations[block.block_id]):
                verified.append({"unit_id": identifier, "content_version": unit["content_version"],
                                 "label_path": [unit["label"], unit["title"], block.kind],
                                 "value": block.calculation.expected,
                                 "anchor": asdict(sources[citations[block.block_id][0] - 1]),
                                 "verification": "deterministic_only"})
    complete = bool(blocks and required and not (missing or gaps or interruptions)
                    and not any(f.severity != "heuristic" for f in findings))
    output = {"logical_id": identifier, "title": unit["title"], "language": language,
            "related_source_units": {str(by_anchor[anchor]): entry["unit_id"] for anchor, entry in (related or {}).items()
                                     if anchor in by_anchor},
            "blocks": displayed, "sources": [asdict(a) for a in sources],
            "content_version": unit["content_version"], "missing_item_ids": missing,
            "source_checklist_missing_item_ids": missing, "reviewable_items": reviewable,
            "unverifiable_source": gaps, "unverifiable_item_ids": missing_anchors,
            "interruptions": list(dict.fromkeys(interruptions)), "findings": [asdict(f) for f in findings],
            "dropped_block_counts": dict(dropped_blocks),
            "coverage": "explained" if complete else "partial" if blocks else "not_generated",
            "verification": "deterministic_only", "verified_facts": verified}
    if strict_lab:
        output["lab_verification"] = verify_spark_setup(
            output, items, required, candidates_by_block, raw_control=PROVIDER_TEXT_CORRUPTION in interruptions)
        if not deterministic_passed(output):
            output["coverage"] = "partial" if blocks else "not_generated"
            output["verified_facts"] = []
    return output


def legacy_projection(drafts, excerpts, document_id, language):
    """Keep existing cards and saved notes readable while exposing v2 blocks separately."""
    sections, citations = [], {}
    labels = ({"supplementary": "Complément", "unverified": "Non vérifié"} if language == "French"
              else {"supplementary": "Supplementary", "unverified": "Unverified"})
    for draft in drafts:
        for block in draft["blocks"]:
            local = {}
            for index in block["source_indexes"]:
                source = draft["sources"][index - 1]
                for row in excerpts:
                    source_unit = draft.get("related_source_units", {}).get(str(index), draft["logical_id"])
                    if row["unit_id"] != source_unit or row["page_number"] != source["page"]:
                        continue
                    quote = " ".join(row["content"].split())
                    if len(quote) >= 20 and " ".join(source["quote"].split()) in quote:
                        citation = {"document_id": document_id, "page_number": source["page"],
                                    "filename": row.get("filename") or "PDF", "excerpt": quote[:650]}
                        local[source["page"]] = citation
                        citations.setdefault(source["page"], citation)
                        break
            label = labels.get(block["provenance"])
            text = (f"**{label}**\n\n" if label else "") + block["text"]
            sections.append({"heading": draft["title"], "content": text[:3000], "covers": [draft["logical_id"]],
                             "title": draft["title"], "markdown": text[:3000], "pages": sorted(local),
                             "citations": list(local.values())})
    return {"schema_version": 2, "units": drafts, "definition": "", "intuition": "", "sections": sections[:30],
            "citations": list(citations.values())[:8], "course_example": "", "common_pitfalls": [],
            "check_question": "", "language": language, "presentation": "full_course"}
