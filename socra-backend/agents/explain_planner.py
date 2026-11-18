"""Deterministic Phase 4 planning. Actions are descriptions, not execution."""
from hashlib import sha256
import json
import re
from uuid import NAMESPACE_URL, uuid5

from agents.explain_tasks import _fold

NON_TEACHING = {"front_matter", "transition", "summary", "non_teaching"}
_PART = re.compile(r"\b(?:(?:only|uniquement|seulement|just)\s+(?:la\s+)?(?:partie|part)\s+([ivxlcdm]+)|(?:partie|part)\s+([ivxlcdm]+)\s+(?:only|uniquement|seulement))\b")
_EXERCISE = re.compile(r"\b(?:skip|exclude|omit|ignore|sans|sauf|exclu[rs]|saute)\s+(?:l['’]\s*)?(?:exercice|exercise)\s+(\d+)\b")
_LAB_STEP = re.compile(r"\b(?:etape|step)\s+(\d+)\b(?!\.\d)")
_PROOF = re.compile(r"\b(?:without|skip|omit|sans)\s+(?:(?:les|the)\s+)?(?:proofs?|demonstrations?|preuves?)\b")
_IMPORTANCE = {"essential": 3, "supporting": 2, "optional": 1}
_BEESWARM_VERSION = "28ee379ad3d960a3cd67f3abee7f7a64892063d5857a58e8ebddf1f46df58815"


def has_explicit_scope(topic):
    text = _fold(topic)
    return bool(_PART.search(text) or _EXERCISE.search(text) or _LAB_STEP.search(text) or _PROOF.search(text))


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def build_learning_plan(units, map_version, topic, prepared, *, level="unspecified", summary=False,
                        requested_exercises=()):
    text = _fold(topic)
    depth = ("exhaustive" if re.search(r"\b(?:exhaustive?|integralite|without omitting|sans rien|sans omettre|ne rien omettre|every detail)\b", text)
             else "summary" if summary else "standard")
    targets = {part[1] or part[2] for part in _PART.finditer(text)}
    target = next(iter(targets)) if len(targets) == 1 else None
    skips = set(_EXERCISE.findall(text))
    lab_steps = set(_LAB_STEP.findall(text))
    requested_exercises = {str(number) for number in requested_exercises} - skips
    proofs = bool(_PROOF.search(text))
    assumptions = []
    if target and not any(unit["kind"] == "transition" and unit["label"].casefold() == target for unit in units):
        assumptions.append(f"Part {target.upper()} was not found. Using the document scope.")
        target = None
    elif not target and re.search(r"\b(?:only|uniquement|seulement)\b[^.!?]{0,30}\b(?:partie|part)\b", text):
        assumptions.append("The requested part was ambiguous. Using the document scope.")
    flags, selected, gaps, required, prerequisites, current_records = {}, [], {}, {}, [], {}
    for unit in units:
        uid = unit["logical_id"]
        path = [component[0] for component in unit.get("heading_path", ())]
        step = _LAB_STEP.fullmatch(_fold(unit["label"])) if lab_steps else None
        exercise = {match[1] for label in [unit["label"].casefold(), *path]
                    if (match := re.fullmatch(r"(?:exercice|exercise)\s+(\d+)", label))}
        reason = ("non_teaching" if unit["kind"] in NON_TEACHING else
                  "outside_requested_part" if target and (not path or path[0] != target) else
                  "outside_requested_lab_steps" if lab_steps and (not step or step[1] not in lab_steps) else
                  "exercise_excluded" if skips & exercise else
                  "outside_requested_exercises" if requested_exercises and not requested_exercises & exercise else
                  "proof_excluded" if proofs and (unit["kind"] == "derivation"
                     or re.search(r"\b(?:preuve|proof|demonstration)\b", _fold(unit["title"]))) else None)
        flags[uid] = {"in_scope": reason is None, "reason": reason or "requested"}
        if reason:
            continue
        selected.append(uid)
        entry = prepared.get(uid, {})
        if entry.get("content_version") != unit["content_version"]:
            entry = {}
        current_records[uid] = entry
        required[uid] = [item["item_id"] for item in entry.get("checklist", ())
                         if item["importance"] == "essential" or (depth == "exhaustive" and item["importance"] == "supporting")
                         or (item["importance"] == "optional" and re.search(r"\b(?:without omitting|sans rien|sans omettre|ne rien omettre)\b", text))]
        gaps[uid] = [{key: gap[key] for key in ("id", "page", "span", "kind", "reason", "status") if key in gap}
                     for gap in entry.get("unresolved", ())]
        if not entry:
            for page in unit.get("preparation_candidates", ()):
                if page.get("route") != "text" or page.get("image_bounds") or (
                    unit["kind"] == "figure_walkthrough" and page.get("vector_paths", 0) >= 20
                ):
                    gaps[uid].append({"page": page["page"], "kind": "source", "reason": "preparation_pending",
                                      "status": "unverifiable_source"})
            if unit["kind"] in {"figure_walkthrough", "comparison"} and not gaps[uid]:
                gaps[uid].append({"page": unit["start"][0], "kind": "source", "reason": "preparation_pending",
                                  "status": "unverifiable_source"})
        if unit["content_version"] == _BEESWARM_VERSION and unit["start"][0] == 18:
            gaps[uid] = [gap for gap in gaps[uid] if gap["reason"] != "visual_details_unconfirmed"]
            gaps[uid].extend(
                {"id": f"chapter6-01-{identifier}", "page": 18, "kind": "figure", "status": "unverifiable_source",
                 "reason": "visual_details_unconfirmed", "label": french, "label_en": english}
                for identifier, french, english in (
                    ("labels", "Libellés et valeurs des variables du graphique", "Feature labels and displayed magnitudes"),
                    ("axis", "Libellé de l’axe horizontal du graphique", "Horizontal axis label"),
                )
            )
        prerequisites.extend(entry.get("external_prereqs", ()))
    deps = {uid: [dep for dep in current_records[uid].get("depends_on", ()) if dep in selected]
            for uid in selected}
    for uid in selected:
        if any(dep not in selected for dep in current_records[uid].get("depends_on", ())):
            assumptions.append(f"Prerequisites outside scope are assumed for {uid}.")
    order = []
    visiting = set()
    completed = set()

    def visit(uid):
        if uid in completed:
            return
        if uid in visiting:
            if "A cyclic prerequisite edge was ignored." not in assumptions:
                assumptions.append("A cyclic prerequisite edge was ignored.")
            return
        visiting.add(uid)
        for dep in deps[uid]:
            visit(dep)
        visiting.remove(uid)
        order.append(uid)
        completed.add(uid)

    for uid in selected:
        visit(uid)
    prereqs = list(dict.fromkeys(prerequisites))
    return {"fingerprint": _digest([map_version, [(u["logical_id"], u["content_version"]) for u in units], flags, proofs]),
            "scope": flags, "order": order, "omit_proofs": proofs,
            "depth": depth, "level": level, "assumptions": assumptions, "required_items": required,
            "unverifiable_source": {uid: items for uid, items in gaps.items() if items},
            "prereqs_assumed": prereqs if level == "advanced" else [],
            "primer": {"provenance": "supplementary", "prerequisites": prereqs} if level == "beginner" and prereqs else None}


def learning_progress(plan, units, progress, inquiry_id, *, verified_facts=(), prepared=None,
                      deepen_explained=False):
    """Use verifier outcomes supplied by the caller. Generator-reported facts are not inputs."""
    units = {unit["logical_id"]: unit for unit in units}
    prepared = prepared or {}
    remaining, deepen, current = [], [], {}

    def action(kind, uid, attempt):
        name = json.dumps([str(inquiry_id), plan["fingerprint"], kind, uid, attempt], separators=(",", ":"))
        return {"action": kind, "logical_id": uid, "request_id": str(uuid5(NAMESPACE_URL, name)),
                "attempt": attempt}

    for uid in plan["order"]:
        unit = units[uid]
        entry = progress.get(uid, {})
        if entry.get("content_version") != unit["content_version"]:
            entry = {}
        status = entry.get("status", "not_generated")
        source = plan["unverifiable_source"].get(uid, [])
        if status in {"covered", "explained"} and source:
            status = "partial"
        current[uid] = {"status": status, "content_version": unit["content_version"],
                        "unverifiable_source": source}
        if status in {"not_generated", "not_yet_generated"}:
            remaining.append({"logical_id": uid, "title": unit["title"], "pages": [unit["start"][0], unit["end"][0]]})
        elif (status in {"partial", "missing", "unverifiable", "unverifiable_source", "mentioned"}
              or deepen_explained and status in {"explained", "covered"}):
            missing = set(entry.get("missing_item_ids", plan["required_items"][uid] if status == "missing" else ()))
            rank = sum(_IMPORTANCE.get(item["importance"], 0) for item in prepared.get(uid, {}).get("checklist", ())
                       if item["item_id"] in missing)
            deepen.append((rank, action("deepen_unit", uid, entry.get("attempt", 1) + 1)))
    next_actions = ([action("continue_learning", remaining[0]["logical_id"],
                            progress.get(remaining[0]["logical_id"], {}).get("attempt", 0) + 1)]
                    if remaining else [])
    next_actions.extend(action for _, action in sorted(deepen, key=lambda pair: -pair[0]))
    ledger = [fact for fact in verified_facts if fact.get("unit_id") in current
              and fact.get("content_version") == current[fact["unit_id"]]["content_version"]
              and current[fact["unit_id"]]["status"] in {"explained", "covered"}
              and fact.get("verification") in {"reviewed", "deterministic_only"}
              and not fact.get("authoritative_errors")][-100:]
    return {"progress": current, "remaining": remaining, "next_actions": next_actions, "facts_ledger": ledger}
