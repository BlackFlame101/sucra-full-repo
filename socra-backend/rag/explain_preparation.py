"""Offline source preparation. Optional vision results are never indexed text."""
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from hashlib import sha256
import asyncio
import json
import logging
import re

from agents.explain_verifier import Anchor, ChecklistItem, Fact, Finding, decimal_value, verify_unit
from rag.explain_checklist import lab_transition, page_furniture, redundant_lab_objective
from rag.unit_map import CHOICE, QUESTION, TASK_NUMBER

PREPARATION_VERSION = "evidence-v5"
MAX_VISION_DOCUMENT = 12
MAX_VISION_UNIT = 3
logger = logging.getLogger(__name__)
NON_TEACHING = {"transition", "front_matter", "summary", "non_teaching"}
_NUMBER = r"[+−-]?\d+(?:[.,]\d+)?"
_CAPTION = re.compile(r"^(?:figure|graphique|schéma|diagramme|chart|diagram)\b", re.I)
_GARBLED = re.compile(r"[\ufffd\ue000-\uf8ff]|\(cid:\d+\)")
_UNIT_REFERENCE = re.compile(r"(?:\bvoir|\bcf\.|\bsee)\s+([IVXLCDM]+\.\d+(?:\.\d+)*|"
                             r"(?:étape|etape|step)\s+\d+(?:\.\d+)*)", re.I)
_EXERCISE_REFERENCE = re.compile(r"\b(exercice\s+\d+)\s*(\([a-z]\))", re.I)
_LOCAL_EXERCISE_REFERENCE = re.compile(r"\b(?:résultat|finale|valeur)\s+de\s+(\([a-z]\))", re.I)
_DISPLAY = re.compile(r"^(?:comment lire|ce qu.on y lit|ce que montrent les mesures|comment choisir|à la cliente|"
                      r"ordre \d+\s*:.*|vérification\s*\(efficacité\)\s*:|prérequis|note)\s*[:.]?$", re.I)


def _source_lines(text, left, right, excluded, table_spans, title, *, question_pattern=None):
    rows = []
    for match in re.finditer(r"[^\n]+", text[left:right]):
        raw = match[0]
        line = raw.strip()
        start = left + match.start() + len(raw) - len(raw.lstrip())
        if not line or (start, start + len(line)) in excluded or any(
            start == min(a["start"] for a in row) and start + len(line) == max(a["end"] for a in row)
            for row in table_spans
        ):
            continue
        question_continuation = question_pattern and rows and not (
            question_pattern.match(line) or CHOICE.match(line)
        )
        if question_continuation or (rows and line[0].islower() and line[:1] not in "φ"
                and title not in rows[-1][0] and not _DISPLAY.fullmatch(rows[-1][0])
                and _kind(line, "") not in {"formula", "worked_calc", "command", "question"}
                and not rows[-1][0].endswith((".", "!", "?", ":"))
                and _kind(rows[-1][0], "") not in {"formula", "worked_calc", "command"}
                and not rows[-1][0][-1:].isdigit()
                and not re.search(r"[^\s]", text[rows[-1][2]:start])):
            previous, begin, _ = rows[-1]
            rows[-1] = (previous + " " + line, begin, start + len(line))
        else:
            rows.append((line, start, start + len(line)))
    return rows


def _importance(line, kind, unit_kind):
    if re.match(r"^(?:dans le TP|coût\s*:|(?:LIME|SHAP) propose)", line, re.I):
        return "optional"
    if kind in {"worked_calc", "number_table", "command", "deliverable", "question", "figure"}:
        return "essential"
    if unit_kind == "figure_walkthrough" and re.search(r"0[,\.]\d+|point|couleur|contribution|fraude", line, re.I):
        return "essential"
    if kind == "numeric_result" or (unit_kind == "lab_step" and kind == "definition"):
        return "supporting"
    return "essential"


@dataclass
class VisionBudget:
    limit: int = MAX_VISION_DOCUMENT
    unit_calls: Counter = field(default_factory=Counter)
    attempted: set = field(default_factory=set)

    def available(self, unit_id):
        return (len(self.attempted) < min(MAX_VISION_DOCUMENT, self.limit)
                and self.unit_calls[unit_id] < MAX_VISION_UNIT)


def inspect_page(page_number, page):
    text = page["text"]
    layout = page.get("evidence", {})
    graphics = layout.get("graphics", {})
    area = max(1, layout.get("width", 1) * page.get("height", 1))
    bounds = []
    image_ratio = 0
    for image in graphics.get("images", []):
        ratio = max(0, (image[2] - image[0]) * (image[3] - image[1]) / area)
        if .015 <= ratio and (ratio < .97 or len(text.strip()) < 80):
            image_ratio += ratio
            bounds.append(image)
    text_ratio = min(1, sum(max(0, cell[4] * cell[5]) for cell in layout.get("items", [])) / area)
    garble = len(_GARBLED.findall(text)) / max(1, len(text))
    return {"page": page_number, "text_ratio": round(text_ratio, 4),
            "image_ratio": round(min(image_ratio, 1), 4), "garble_ratio": round(garble, 4),
            "ocr_confidence": page.get("ocr_confidence"),
            "route": "ocr_or_vision" if not text.strip() or garble > .025
            or (image_ratio > .50 and len(text.strip()) < 80) else "text",
            "image_bounds": bounds, "vector_paths": graphics.get("paths", 0)}


def _hash(*values):
    return sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def indexed_anchors(positioned, indexed):
    """Translate verified chunk characters back to PDF offsets without trusting page labels alone."""
    rows = {row["chunk_index"]: row for row in indexed}
    covered = defaultdict(set)
    for chunk in positioned:
        other = rows.get(chunk["chunk_index"])
        if other and (other["page_number"], other["content"]) == (chunk["page_number"], chunk["content"]):
            covered[chunk["page_number"]].update(chunk["source_offsets"])
    return covered


def _layout_tables(page_number, page, anchor, excluded=()):
    text = page["text"]
    items = page.get("evidence", {}).get("items", [])
    raw = text.encode("utf-16-le")
    groups = defaultdict(list)
    extra = 0
    astral = [i for i, character in enumerate(text) if ord(character) > 0xFFFF]
    for offset, length, x, y, _, _ in items:
        while extra < len(astral) and astral[extra] + extra < offset:
            extra += 1
        groups[round(y / 2)].append((x, offset, length, offset - extra))
    rows = []
    for group in sorted(groups, reverse=True):
        cells = []
        for x, offset, length, start in sorted(groups[group]):
            cell = raw[offset * 2:(offset + length) * 2].decode("utf-16-le", errors="replace")
            value = cell.strip()
            start += len(cell) - len(cell.lstrip())
            if value and not any(left <= start < start + len(value) <= right for left, right in excluded):
                cells.append((x, value, anchor(page_number, start, start + len(value))))
        rows.append(cells)
    tables = []
    unresolved = False
    for i, header in enumerate(rows):
        if not 2 <= len(header) <= 8 or any(not cell[2] or not re.search(r"[A-Za-zÀ-ÿ]", cell[1]) for cell in header):
            continue
        data = []
        for row in rows[i + 1:]:
            row = [cell for cell in row if header[0][0] - 12 <= cell[0] <= header[-1][0] + 12]
            if not row:
                continue  # A parallel column of prose may interleave in reading order.
            if not any(re.fullmatch(_NUMBER, cell[1]) for cell in row[1:]):
                break
            if len(row) != len(header) or any(abs(a[0] - b[0]) > 12 or not a[2] for a, b in zip(row, header)):
                unresolved = True
                break
            data.append(row)
        if len(data) < 2:
            continue
        columns = [cell[1] for cell in header]
        if len(set(columns)) != len(columns) or len({row[0][1] for row in data}) != len(data):
            unresolved = True
            continue
        tables.append({
            "table_id": _hash(page_number, columns, header[0][2]["start"]), "page": page_number,
            "columns": columns, "confidence": "high",
            "header_anchors": [cell[2] for cell in header],
            "rows": [[{"text": value, "anchor": source} for _, value, source in row] for row in data],
        })
    return tables, unresolved


def _kind(line, unit_kind):
    if re.search(r"(?:\d[.,]?\d*\s*[%+÷×−*/-]|[φ∑√]|\bF1\b).*=|[=≤≥<>].*" + _NUMBER, line):
        return "worked_calc" if unit_kind in {"derivation", "worked_calculation"} else "formula"
    if _CAPTION.match(line):
        return "figure"
    if re.match(r"^(?:\$\s|>>>\s|(?:pip|python|docker|git|npm|uv)\s)", line):
        return "command"
    if re.match(r"^(?:rendre|livrable|deliverable)\b", line, re.I):
        return "deliverable"
    if unit_kind == "exercise":
        return "question"
    if unit_kind == "lab_step" or re.match(r"^(?:perturber|prédire|pondérer|ajuster|lire ses coefficients)\b", line, re.I):
        return "command"
    if re.match(r"^(?:attention|limite|précaution)\b", line, re.I):
        return "caveat"
    return "numeric_result" if re.search(_NUMBER, line) else "definition"


def prepare_units(units, pages, positioned, indexed, *, source_hash, requested=None):
    """Generate checkpointable records from the exact indexed document version."""
    coverage = indexed_anchors(positioned, indexed)
    labels = defaultdict(list)
    order = {unit["logical_id"]: i for i, unit in enumerate(units)}
    furniture = page_furniture(pages, {tuple(unit["start"]) for unit in units if unit["kind"] not in NON_TEACHING})
    by_path = {tuple(tuple(part) for part in unit["heading_path"]): unit["logical_id"] for unit in units}
    case_questions = {}
    exercise_parent = {}
    for unit in units:
        identifier = unit["logical_id"]
        label = unit.get("label", "").casefold()
        if label:
            labels[label].append(identifier)
        path = tuple(tuple(part) for part in unit["heading_path"])
        if len(path) >= 2 and path[-2][0] == "étude de cas" and label.startswith("question "):
            case_questions[(path[:-1], label.split()[-1])] = identifier
        if label.startswith("("):
            parent = next((part[0] for part in reversed(unit["heading_path"][:-1])
                           if part[0].startswith("exercice ")), None)
            if parent:
                exercise_parent[identifier] = parent
                labels[parent + label].append(identifier)
    result = {}
    for unit_index, unit in enumerate(units):
        identifier = unit["logical_id"]
        if requested is not None and identifier not in requested:
            continue
        start, end = unit["start"], unit["end"]
        quality, unresolved, items, tables, figures, math = [], [], [], [], [], []
        exclusions = []
        dependencies = set()
        path = tuple(tuple(part) for part in unit["heading_path"])
        label = unit["label"].casefold()
        case_question = len(path) >= 2 and path[-2][0] == "étude de cas" and label.startswith("question ")
        answer = case_questions.get((path[:-2], label.split()[-1])) if label.startswith("réponse ") else None
        if case_question and (parent := by_path.get(path[:-1])):
            dependencies.add(parent)
        if answer:
            dependencies.add(answer)
        question_pattern = TASK_NUMBER if case_question else QUESTION if re.fullmatch(r"q\s*\d+", label) else None
        external_prereqs = []
        teaching = unit["kind"] not in NON_TEACHING

        def anchor(page_number, left, right):
            text = pages[page_number - 1]["text"]
            if (not 0 <= left < right <= len(text) or tuple(start) > (page_number, left)
                    or (page_number, right) > tuple(end)):
                return None
            if any(not text[i].isspace() and i not in coverage[page_number] for i in range(left, right)):
                return None
            return asdict(Anchor(page_number, left, right, text[left:right]))

        def candidate(kind, text, anchors, importance="essential", facts=()):
            return {"item_id": _hash(identifier, kind, [a["quote"] for a in anchors], text),
                    "type": kind, "text": text, "anchors": anchors, "importance": importance,
                    "facts": list(facts)}

        def item(kind, text, anchors, importance="essential", facts=()):
            items.append(candidate(kind, text, anchors, importance, facts))

        calculation = []
        next_unit = units[unit_index + 1] if unit_index + 1 < len(units) else None
        transition = lab_transition(unit, next_unit, pages)

        for number in range(start[0], end[0] + 1):
            page = pages[number - 1]
            text = page["text"]
            left = start[1] if number == start[0] else 0
            right = end[1] if number == end[0] else len(text)
            decisions = dict(furniture.get(number, {}))
            if transition and transition[0] == number:
                _, offset, title, detection = transition
                decisions[offset] = (title, "section_transition", detection)
            excluded = set()
            if teaching:
                for offset, (line, reason, detection) in sorted(decisions.items()):
                    line_end = offset + len(line)
                    if not left <= offset < line_end <= right or text[offset:line_end] != line:
                        continue
                    raw_start = max(left, text.rfind("\n", left, offset) + 1)
                    newline = text.find("\n", line_end, right)
                    raw_end = right if newline < 0 else newline
                    if text[raw_start:raw_end].strip() != line:
                        continue
                    excluded.add((offset, line_end))
                    kind = _kind(line, unit["kind"])
                    source = asdict(Anchor(number, offset, line_end, line))
                    exclusions.append(candidate(kind, line, [source], _importance(line, kind, unit["kind"]))
                                      | {"reason": reason, "detection": detection})
            layout = page.get("evidence", {})
            inspection = inspect_page(number, page)
            for bounds in inspection["image_bounds"]:
                figures.append({"figure_id": _hash(source_hash, number, bounds), "page": number,
                                "bbox": bounds, "type": "embedded_graphic", "confidence": "unresolved",
                                "asset": {"document_hash": source_hash, "page": number, "bbox": bounds}})
            low_text = inspection["route"] != "text"
            found, misaligned = _layout_tables(number, page, anchor, excluded) if teaching else ([], False)
            quality.append(inspection | {"table_confidence": "low" if misaligned else "high" if found else None,
                                         "route": "vision" if misaligned and not low_text else inspection["route"]})
            if (low_text or misaligned or layout.get("graphics_unavailable") or layout.get("geometry_truncated")
                    or layout.get("graphics", {}).get("truncated")):
                unresolved.append({"page": number, "kind": "table" if misaligned else "page",
                                   "reason": "low_source_quality", "status": "unverifiable_source"})
            tables.extend(found)
            table_spans = []
            for record in found:
                table_spans.append(record["header_anchors"])
                for row in record["rows"]:
                    table_spans.append([cell["anchor"] for cell in row])
                    for column, header_anchor, cell in zip(record["columns"][1:], record["header_anchors"][1:], row[1:]):
                        try:
                            decimal_value(cell["text"])
                        except ValueError:
                            continue
                        fact = {"label_path": [row[0]["text"], column], "value": cell["text"],
                                "anchor": cell["anchor"]}
                        item("number_table", f"{row[0]['text']} / {column}", [header_anchor, row[0]["anchor"], cell["anchor"]],
                             facts=[fact])
            page_figures = [figure for figure in figures if figure["page"] == number]
            captions = []
            prereq_list = False
            for line, offset, line_end in _source_lines(
                text, left, right, excluded, table_spans, unit["title"], question_pattern=question_pattern
            ):
                if not teaching:
                    continue
                if unit["kind"] != "exercise" and (
                    line == unit["title"] or (offset == left and unit["label"] and unit["title"] in line)
                ):
                    continue
                kind = _kind(line, unit["kind"])
                code_fragment = unit["kind"] == "lab_step" and re.fullmatch(
                    r"(?:[+−-]?\d+\.\d+[,)]?|[)\]}]+[,;]?)", line
                )
                if len(line) < 12 and kind not in {"formula", "worked_calc"} and not code_fragment:
                    continue
                source = anchor(number, offset, line_end)
                if not source or _GARBLED.search(line):
                    unresolved.append({"page": number, "kind": "math" if kind in {"formula", "worked_calc"} else kind,
                                       "span": [offset, line_end], "reason": "unreadable_or_unindexed",
                                       "status": "unverifiable_source"})
                    logger.info("explain_preparation_anchor_rejected unit_id=%s page=%d offset=%d", identifier, number, offset)
                    continue
                if kind == "figure":
                    captions.append(source)
                if kind in {"formula", "worked_calc"}:
                    math.append({"notation": "latex" if "$" in line or "\\frac" in line else "plain",
                                 "text": line, "anchor": source})
                prerequisite = re.match(r"^(?:prérequis|prerequisites?)\s*:?\s*(.*)$", line, re.I)
                if prerequisite:
                    prereq_list = not prerequisite[1]
                    if prerequisite[1]:
                        external_prereqs.append(prerequisite[1])
                elif prereq_list and line.startswith(("• ", "- ")):
                    external_prereqs.append(line[2:])
                else:
                    prereq_list = False
                references = _UNIT_REFERENCE.findall(line)
                references.extend(parent + subquestion for parent, subquestion in _EXERCISE_REFERENCE.findall(line))
                if identifier in exercise_parent:
                    references.extend(exercise_parent[identifier] + subquestion
                                      for subquestion in _LOCAL_EXERCISE_REFERENCE.findall(line))
                for label in references:
                    targets = labels[label.casefold()]
                    if len(targets) == 1 and order[targets[0]] < order[identifier]:
                        dependencies.add(targets[0])
                    elif targets != [identifier]:
                        unresolved.append({"page": number, "kind": "prerequisite", "reason": "unknown_reference",
                                           "label": label, "status": "unverifiable_source"})
                if unit["kind"] == "worked_calculation" and re.match(r"^(?:ordre|order)\s+\d+\s*:", line, re.I):
                    calculation.append((line, source))
                    continue
                if _DISPLAY.fullmatch(line):
                    continue
                repeated = re.fullmatch(r"(.+?)\s*[:=]\s*(" + _NUMBER + r")\s*\.?", line)
                if repeated:
                    label, value = repeated.groups()
                    folded = " ".join(label.casefold().split())
                    existing = next((entry for entry in items for fact in entry["facts"]
                                     if folded in {fact["label_path"][0].casefold(),
                                                   " / ".join(fact["label_path"]).casefold()}
                                     and decimal_value(value) == decimal_value(fact["value"])), None)
                    if existing:
                        existing["anchors"].append(source)
                        continue
                importance = _importance(line, kind, unit["kind"])
                if kind == "worked_calc" and unit["kind"] == "worked_calculation" and importance == "essential" \
                        and not re.match(r"^Mme\s", line):
                    calculation.append((line, source))
                else:
                    item(kind, line, [source], importance)
            if not page_figures and captions:
                page_figures = [{"figure_id": _hash(source_hash, number, c["start"]), "page": number,
                                 "type": "captioned_figure", "confidence": "unresolved",
                                 "asset": {"document_hash": source_hash, "page": number, "bbox": None}}
                                for c in captions]
                figures.extend(page_figures)
            elif not page_figures and teaching and unit["kind"] == "figure_walkthrough" and inspection["vector_paths"] >= 20:
                page_figures = [{"figure_id": _hash(source_hash, number, "vector"), "page": number,
                                 "type": "vector_candidate", "confidence": "unresolved",
                                 "asset": {"document_hash": source_hash, "page": number, "bbox": None}}]
                figures.extend(page_figures)
            if len(page_figures) == 1 and len(captions) == 1:
                page_figures[0]["caption"] = captions[0]
                caption = captions[0]["quote"].casefold()
                for name in ("waterfall", "beeswarm"):
                    if name in caption:
                        page_figures[0]["type"] = name
                        break
            if len(page_figures) == 1 and unit["kind"] == "figure_walkthrough" and "arbre" in unit["title"].casefold():
                page_figures[0]["type"] = "decision_tree"
            if page_figures and quality[-1]["route"] == "text":
                quality[-1]["route"] = "vision"
            for figure in page_figures:
                unresolved.append({"page": number, "kind": "table_or_figure" if unit["kind"] == "comparison" else "figure",
                                   "id": figure["figure_id"], "reason": "visual_details_unconfirmed",
                                   "status": "unverifiable_source"})
        if calculation:
            facts = []
            for line, source in calculation:
                attribution = re.fullmatch(r"(φ\([\w -]+\))\s*=.+?=\s*(" + _NUMBER + r")", line, re.I)
                if attribution:
                    facts.append({"label_path": [attribution[1]], "value": attribution[2], "anchor": source})
            item("worked_calc", "\n".join(dict.fromkeys(line for line, _ in calculation)),
                 [a for _, a in calculation], facts=facts)
        if unit["kind"] == "lab_step" and items:
            # Consider only the lead objective. The proof comes from surviving indexed items.
            if detection := redundant_lab_objective(items[0], items[1:]):
                exclusions.append(items.pop(0) | {"reason": "redundant_objective", "detection": detection})
        unique = {}
        for entry in items:
            previous = unique.setdefault(entry["item_id"], entry)
            if previous is not entry:
                previous["anchors"].extend(a for a in entry["anchors"] if a not in previous["anchors"])
        result[identifier] = {"unit_id": identifier, "content_version": unit["content_version"],
                              "checklist": list(unique.values()),
                              "checklist_exclusions": sorted(exclusions, key=lambda entry: (
                                  entry["anchors"][0]["page"], entry["anchors"][0]["start"])),
                              "page_quality": quality, "tables": tables, "figures": figures, "math": math,
                              "depends_on": sorted(dependencies), "external_prereqs": list(dict.fromkeys(external_prereqs)),
                              "unresolved": unresolved, "enrichment_state": "enriched"}
    validate_dependencies(result, {unit["logical_id"] for unit in units})
    return result


def validate_dependencies(records, valid_ids):
    accepted = defaultdict(set)

    def reaches(start, target):
        pending = [start]
        seen = set()
        while pending:
            node = pending.pop()
            if node == target:
                return True
            if node not in seen:
                seen.add(node)
                pending.extend(accepted[node])
        return False

    for identifier, record in records.items():
        for dependency in record["depends_on"]:
            if dependency not in valid_ids or reaches(dependency, identifier):
                record["unresolved"].append({"kind": "prerequisite", "reason": "cycle_or_invalid_reference",
                                             "target": dependency, "status": "unverifiable_source"})
            else:
                accepted[identifier].add(dependency)
        record["depends_on"] = sorted(accepted[identifier])


def verifier_checklist(record):
    """Pass only verified indexed text to the Phase 2 verifier."""
    return tuple(ChecklistItem(entry["item_id"], tuple(Anchor(**a) for a in entry["anchors"]),
                               phrases=() if entry["facts"] and entry["type"] != "worked_calc"
                               else tuple(entry["text"].splitlines()),
                               facts=tuple(Fact(tuple(f["label_path"]), f["value"], Anchor(**f["anchor"]))
                                           for f in entry["facts"]),
                               importance=entry["importance"]) for entry in record["checklist"])


def verify_prepared_unit(unit, blocks, record, *, pages, sources, **options):
    if (record["unit_id"], record["content_version"]) != (unit["logical_id"], unit["content_version"]):
        raise ValueError("Prepared evidence belongs to another unit version")
    findings = verify_unit(unit, blocks, pages=pages, sources=sources,
                           checklist=verifier_checklist(record), **options)
    for element in record["unresolved"]:
        anchor = Anchor(element["page"], *element["span"]) if "span" in element else None
        findings.append(Finding("unverifiable_source", "source", unit["logical_id"],
                                f"{element['kind']}: {element['reason']}", item_id=element.get("id"), source=anchor))
    return findings


async def resolve_visuals(records, render, vision, cache, *, budget):
    """Optional injected vision boundary. No provider is configured or called by default."""
    if vision is None:
        return 0
    calls = 0
    for record in records.values():
        unit_id = record["unit_id"]
        # Captioned instructional figures precede anonymous graphics.
        candidates = sorted(record["figures"], key=lambda f: ("caption" not in f, f["page"]))
        full_pages = {figure["page"] for figure in candidates if figure["asset"].get("bbox") is None}
        for element in record["unresolved"]:
            page = element.get("page")
            if page and page not in full_pages and element["kind"] in {"page", "math", "table"}:
                full_pages.add(page)
                candidates.append({"figure_id": _hash(record["unit_id"], page, element["kind"]),
                                   "page": page, "type": element["kind"], "confidence": "unresolved",
                                   "asset": {"page": page, "bbox": None}, "unresolved_element": element})
        for figure in candidates:
            if figure["confidence"] != "unresolved":
                continue
            if not budget.available(unit_id):
                continue
            try:
                image = await asyncio.wait_for(render(figure["asset"]), timeout=10)
                if not isinstance(image, bytes) or not 0 < len(image) <= 4_000_000:
                    continue
                image_hash = sha256(image).hexdigest()
                result = cache.get(image_hash)
                if result is None:
                    if image_hash in budget.attempted:
                        continue
                    calls += 1
                    budget.unit_calls[unit_id] += 1
                    budget.attempted.add(image_hash)
                    result = await asyncio.wait_for(vision(image), timeout=20)
                    if not isinstance(result, dict):
                        continue
                    table = result.get("table")
                    result = {key: str(result[key])[:1000] for key in
                              ("type", "title", "axes", "series", "takeaway", "plain", "latex") if key in result} | {
                        "key_values": [
                            {"label": str(value["label"])[:160], "value": str(value["value"])[:80],
                             "approximate": value.get("printed") is not True}
                            for value in (result["key_values"][:24] if isinstance(result.get("key_values"), list) else [])
                            if isinstance(value, dict) and "label" in value and "value" in value
                        ],
                    }
                    if isinstance(table, dict):
                        columns, rows = table.get("columns"), table.get("rows")
                        if (isinstance(columns, list) and 2 <= len(columns) <= 8
                                and all(isinstance(label, str) and 0 < len(label) <= 160 for label in columns)
                                and len(set(columns)) == len(columns)
                                and isinstance(rows, list) and 1 <= len(rows) <= 30
                                and all(isinstance(row, list) and len(row) == len(columns)
                                        and all(isinstance(cell, str) and len(cell) <= 160 for cell in row)
                                        for row in rows)):
                            result["table"] = {"columns": columns, "rows": rows}
                    if result["key_values"] or len(result) > 1:
                        cache[image_hash] = result
                    else:
                        continue
                if result:
                    figure.get("unresolved_element", figure).update(
                        vision_observation=result, image_hash=image_hash, confidence="vision_unconfirmed")
            except (OSError, TimeoutError, ValueError):
                logger.warning("explain_preparation_visual_unavailable figure_id=%s", figure["figure_id"])
    return calls
