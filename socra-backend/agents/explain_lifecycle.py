"""Versioned explanation contract and recovery from inquiry checkpoints."""
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

from agents.explain_lab_verification import lab_approval_passed, requires_lab_check

PROMPT_VERSION = "unit-v2-linked-evidence"


class Contract(BaseModel):
    model_config = ConfigDict(extra="allow")


class UnitVerdict(Contract):
    coverage: Literal["explained", "partial", "mentioned", "not_generated", "missing"]
    verification: Literal["unreviewed", "deterministic_only", "reviewed", "review_failed"]
    confidence: Literal["low", "medium", "high"] = "low"
    missing_item_ids: list[str]
    unverifiable_source: list[dict]


class SourceAnchor(Contract):
    page: PositiveInt
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str


class UnitBlock(Contract):
    block_id: str
    kind: str
    text: str
    provenance: Literal["course", "derived", "supplementary", "unverified"]
    source_indexes: list[PositiveInt]


class UnitOutput(UnitVerdict):
    logical_id: str
    title: str
    content_version: str
    blocks: list[UnitBlock]
    sources: list[SourceAnchor]
    verified_facts: list[dict]

    @model_validator(mode="after")
    def valid_binding(self):
        if any(index > len(self.sources) for block in self.blocks for index in block.source_indexes):
            raise ValueError("Block sources must refer to this unit's anchors.")
        if self.coverage == "explained" and (self.unverifiable_source or self.missing_item_ids):
            raise ValueError("Explained units cannot carry unresolved requirements.")
        return self


class UnitVersion(Contract):
    request_id: str
    stage: Literal["draft", "repaired", "ready"]
    output: UnitOutput
    change_log: list[dict] = Field(default_factory=list)


class UnitProgress(Contract):
    logical_id: str
    content_version: str
    title: str
    pages: tuple[int, int]
    status: Literal["explained", "partial", "mentioned", "missing", "not_generated", "skipped"]
    verification: str
    missing_item_ids: list[str]
    unverifiable_source: list[dict]
    kind: str | None = None
    label: str | None = None
    fallback: bool | None = None


class FactsLedger(Contract):
    verified_facts: list[dict]


class LearningState(Contract):
    progress: list[UnitProgress]
    facts: FactsLedger
    next_actions: list[dict]


class ExplanationV2(Contract):
    schema_version: Literal[2]
    units: list[UnitOutput]
    versions: list[UnitVersion]
    learning_state: LearningState
    coverage_ledger: dict
    sections: list[dict]


def review_safe_output(output):
    if requires_lab_check(output) and not lab_approval_passed(output):
        return output | {"coverage": "partial" if output["blocks"] else "not_generated",
                         "review_state": "incomplete" if output["blocks"] else "unreviewed",
                         "confidence": "low", "verified_facts": []}
    if output["coverage"] == "explained" and output["verification"] != "reviewed":
        return output | {"coverage": "partial", "review_state": "unreviewed",
                         "confidence": "low", "verified_facts": []}
    return output


def version_for(request_id, stage, output):
    if stage == "ready" and requires_lab_check(output) and not lab_approval_passed(output):
        stage = "draft"
        output = review_safe_output(output)
    changes = [change | {"reason": change.get("reason", "review_repair"),
                         "severity": change.get("severity", "medium")}
               for change in output.get("repair_changes", ())] if stage != "draft" else []
    provisional = output | {"verification": "unreviewed", "confidence": "low", "verified_facts": [],
                            "coverage": "partial" if output["coverage"] == "explained" else output["coverage"]}
    return UnitVersion(request_id=request_id or "", stage=stage,
                       output=review_safe_output(output) if stage == "ready" else provisional | {
                           "review_state": output.get("review_state", "unreviewed") if requires_lab_check(output)
                           and output.get("review_state") != "approved" else "unreviewed"},
                       change_log=changes).model_dump(mode="json")


def correction_event(row, change):
    output = row["output"]
    return {"logical_id": output["logical_id"], "content_version": output.get("content_version"),
            "version_request_id": row.get("request_id"), "generation": row.get("generation"), **change}


def same_source(checkpoint, document):
    return (checkpoint.get("document_id") == str(document["id"])
            and checkpoint.get("source_hash") == document.get("content_hash")
            and checkpoint.get("generation") == document.get("index_generation"))


def saved_versions(checkpoints, document, units, rebind=None):
    current = {unit["logical_id"]: unit["content_version"] for unit in units}
    result = []
    for checkpoint in checkpoints:
        if checkpoint["document_id"] != str(document["id"]):
            continue
        for raw in checkpoint["versions"]:
            row = UnitVersion.model_validate(raw).model_dump(mode="json")
            output = row["output"]
            if row["stage"] == "ready" and requires_lab_check(output) and not lab_approval_passed(output):
                row = row | version_for(row["request_id"], "draft", review_safe_output(output))
                output = row["output"]
            if current.get(output["logical_id"]) == output["content_version"]:
                if same_source(checkpoint, document):
                    result.append(row)
                elif rebind and row["stage"] == "ready" and (rebased := rebind(row)):
                    result.append(rebased | {"generation": document["index_generation"],
                                             "source_hash": document["content_hash"]})
    return result


def latest_outputs(versions):
    return {row["output"]["logical_id"]: row["output"] for row in versions
            if row["stage"] == "ready" and row["output"]["blocks"]
            and (not requires_lab_check(row["output"]) or lab_approval_passed(row["output"]))}


def rebind_version(row, anchors, required, gaps):
    """Reuse only outputs whose complete evidence can be rebound to the current index."""
    old = row["output"]
    if (not old["blocks"] or not old["sources"] or old["unverifiable_source"] or gaps
            or old.get("findings") or old.get("independent_review", {}).get("findings")
            or row.get("required_item_ids") != sorted(required)):
        return None
    replacements = {}
    for source in old["sources"]:
        matches = [anchor for anchor in anchors if anchor["quote"] == source["quote"]]
        if len(matches) != 1:
            return None
        replacements[(source["page"], source["start"], source["end"], source["quote"])] = matches[0]
    facts = []
    for fact in old["verified_facts"]:
        anchor = fact.get("anchor") or {}
        valid = replacements.get(tuple(anchor.get(key) for key in ("page", "start", "end", "quote")))
        if valid:
            facts.append(fact | {"anchor": valid})
    return row | {"reconciled": True, "output": old | {"sources": list(replacements.values()), "verified_facts": facts}}


def next_unit(plan, known, operation, target=None):
    order = plan["order"]
    if operation == "deepen_unit":
        if target not in order or target not in known:
            raise ValueError("Choose an existing unit from the current document to deepen.")
        return target
    return next((uid for uid in order if uid not in known), None)


def attach_contract(card, plan, units, versions, shown, learning, prepared):
    latest = latest_outputs(versions)
    provisional = {row["output"]["logical_id"]: row["output"] for row in versions if row["stage"] != "ready"}
    rows = []
    review_counts = dict.fromkeys(("generated", "reviewed", "approved", "rejected",
                                   "incomplete", "unreviewed", "not_generated"), 0)
    for unit in units:
        uid = unit["logical_id"]
        output = latest.get(uid) or provisional.get(uid) or {}
        in_scope = plan["scope"][uid]["in_scope"]
        gaps = list(output.get("unverifiable_source", ()))
        gaps.extend(gap for gap in plan["unverifiable_source"].get(uid, ()) if gap not in gaps)
        status = output.get("coverage", "not_generated") if in_scope else "skipped"
        reviewed = uid in latest and output.get("verification") == "reviewed"
        if status == "explained" and (gaps or not reviewed):
            status = "partial"
        review_state = "not_applicable"
        if in_scope:
            generated = bool(output.get("blocks"))
            review_state = ("not_generated" if not generated else "unreviewed" if not reviewed
                            else "approved" if status == "explained"
                            else output.get("review_state") if output.get("review_state") in {"rejected", "incomplete"}
                            else "incomplete")
            review_counts["generated"] += generated
            review_counts["reviewed"] += generated and reviewed
            review_counts["incomplete"] += review_state != "approved"
            if review_state != "incomplete":
                review_counts[review_state] += 1
        rows.append(UnitProgress(logical_id=uid, title=unit["title"], content_version=unit["content_version"],
                                 pages=(unit["start"][0], unit["end"][0]), status=status,
                                 kind=unit.get("kind"), label=unit.get("label"), fallback=unit.get("fallback"),
                                 verification=output.get("verification", "unreviewed") if in_scope else "not_applicable",
                                 missing_item_ids=output.get("missing_item_ids", plan["required_items"].get(uid, [])),
                                 unverifiable_source=gaps, scope_reason=plan["scope"][uid]["reason"],
                                 review_state=review_state,
                                 review_reason=output.get("review_reason") if in_scope else None).model_dump(mode="json"))
    corrections = [{"logical_id": row["output"]["logical_id"], **change}
                   for index, row in enumerate(versions) if row["stage"] == "ready" and row not in versions[:index]
                   for change in row["change_log"]]
    displayed_ids = {output["logical_id"] for output in card["units"]}
    if any(change["logical_id"] in displayed_ids for change in corrections):
        message = "Une correction a été apportée à cette explication." if card["language"] == "French" else (
            "A correction was made to this explanation.")
        card["sections"].append({"heading": "Correction", "content": message,
                                 "title": "Correction", "markdown": message, "pages": [], "citations": []})
    gap_pages = sorted({gap["page"] for row in rows for gap in row["unverifiable_source"]
                        if row["logical_id"] in displayed_ids and isinstance(gap.get("page"), int)})
    if gap_pages:
        pages = ", ".join(map(str, gap_pages))
        french = card["language"] == "French"
        card["coverage_notices"] = [{
            "heading": "Sources à vérifier" if french else "Unverified source material",
            "content": f"Des éléments restent non vérifiables aux pages {pages}." if french
                       else f"Some source material remains unverified on pages {pages}.",
        }]
    learning_state = LearningState(progress=rows, facts={"verified_facts": learning["facts_ledger"]},
                                   next_actions=learning["next_actions"])
    coverage_order = ("not_generated", "missing", "mentioned", "partial", "explained")
    document_status = min((row["status"] for row in rows if row["status"] != "skipped"),
                          key=coverage_order.index, default="not_applicable")
    ledger = {"coverage_counts": dict(Counter(row["status"] for row in rows)),
              "verification_counts": dict(Counter(row["verification"] for row in rows)),
              "review_counts": review_counts, "document_status": document_status,
              "document_complete": document_status == "explained",
              "remaining": [row for row in rows if row["status"] in {"missing", "not_generated"}],
              "partial": [row for row in rows if row["status"] in {"partial", "mentioned"}],
              "skipped_optional_items": {uid: [item["item_id"] for item in record.get("checklist", ())
                                              if item["importance"] == "optional"
                                              and item["item_id"] not in plan["required_items"].get(uid, ())]
                                         for uid, record in prepared.items() if uid in plan["order"]},
              "low_fidelity_pages": sorted({gap["page"] for row in rows for gap in row["unverifiable_source"]
                                            if isinstance(gap.get("page"), int)}),
              "corrections": corrections, "next_actions": learning["next_actions"]}
    outputs = [review_safe_output(output) for output in card["units"]]
    shown = [row | {"output": review_safe_output(row["output"])} for row in shown]
    return ExplanationV2.model_validate(card | {"units": outputs, "versions": shown, "learning_state": learning_state,
                                                "coverage_ledger": ledger}).model_dump(mode="json")
