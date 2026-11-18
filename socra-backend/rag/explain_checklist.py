"""Conservative exclusions for checklist candidates, using canonical source spans."""

from collections import defaultdict
import re

from rag.unit_map import CHOICE, NUMBERED, QUESTION, TASK_LIST, _page_rows


_PAGE_NUMBER = re.compile(r"(?:page\s+)?(\d{1,4})(?:\s*(?:/|sur|of)\s*(\d{1,4}))?", re.I)
_NUMBERED_LABEL = re.compile(r"(.+\S)\s+(\d{1,4})")
_ATTRIBUTION = re.compile(r"\b(?:par|by)\s+(?:pr|prof|pt|dr)\b", re.I)
_TASK_CUE = re.compile(
    r"^(?:objectif|objective|livrable|deliverable|attention|consigne|à analyser|à rendre|"
    r"rendre|soumettre|exécuter|calculer|afficher|vérifier|conserver|enregistrer|"
    r"submit|run|calculate|check|save|print|show|ensure|complete|must)\b",
    re.I,
)
_OBLIGATION = re.compile(r"\b(?:must|required|doit|doivent|obligatoire|il faut)\b", re.I)
_PART_TOPIC = re.compile(
    r"partie\s+(?:\d+|[IVXLCDM]+)\s*[–—-]\s*"
    r"(?:classification\s+(?:de|des)\s+|régression\s+sur\s+)(?P<topic>[\w’' -]+)",
    re.I,
)


def page_furniture(pages, unit_starts):
    """Find recurring margin labels and sequential page counters with layout evidence."""
    groups = defaultdict(list)
    for number, page in enumerate(pages, 1):
        height = page.get("height")
        if not height:
            continue
        positioned = [(offset, text, layout) for offset, text, layout in _page_rows(page) if layout]
        baselines = [layout[0] / height for _, _, layout in positioned]
        if not any(.1 < y < .9 for y in baselines):
            continue
        for (offset, text, (_, size, _)), y in zip(positioned, baselines):
            side = "header" if y >= .935 else "footer" if y <= .065 else None
            if not side or (number, offset) in unit_starts:
                continue
            direction = 1 if side == "header" else -1
            distances = [(direction * (y - other), row[2][1]) for row, other in zip(positioned, baselines)]
            if any(gap < -.001 for gap, _ in distances):
                continue
            neighbour = min((pair for pair in distances if pair[0] > .001), default=None)
            if not neighbour or neighbour[0] < .012:
                continue
            signature = " ".join(text.casefold().split())
            counter = _PAGE_NUMBER.fullmatch(signature)
            if counter:
                if int(counter[1]) != number or (counter[2] and int(counter[2]) != len(pages)):
                    continue
                reason = "page_number"
                signature = "sequential"
            elif (len(text) > 160 or re.search(r"[.!?:;=]$", text) or _OBLIGATION.search(text)
                  or _TASK_CUE.match(text) or NUMBERED.fullmatch(text) or TASK_LIST.fullmatch(text)
                  or QUESTION.fullmatch(text) or CHOICE.match(text)):
                continue
            else:
                reason = f"running_{side}"
                numbered = _NUMBERED_LABEL.fullmatch(signature)
                if numbered and int(numbered[2]) == number:
                    signature = numbered[1] + " {page}"
                elif size >= neighbour[1] and not _ATTRIBUTION.search(text):
                    continue  # Body-sized prose with no distinct margin label stays a candidate.
            key = (reason, side, signature)
            groups[key].append((number, offset, text, y, size, neighbour[0], neighbour[1]))

    matches = defaultdict(dict)
    for (reason, side, signature), rows in groups.items():
        if len(rows) < 2:
            continue
        for page, offset, text, y, size, gap, adjacent_size in rows:
            peers = {n for n, _, _, position, font_size, _, _ in rows
                     if abs(position - y) <= .012 and abs(font_size - size) <= 1}
            if len(peers) >= 2:
                matches[page][offset] = (text, reason, {
                    "rule": "recurring_isolated_margin", "side": side, "signature": signature,
                    "relative_baseline": round(y, 5), "font_size": size, "matching_pages": sorted(peers),
                    "relative_gap": round(gap, 5), "adjacent_font_size": adjacent_size,
                })
    return matches


def lab_transition(unit, next_unit, pages):
    """Recognize a descriptive part heading immediately before a new lab step."""
    page, end = unit["end"]
    if (unit["kind"] != "lab_step" or page <= unit["start"][0] or not next_unit
            or next_unit["kind"] != "lab_step" or next_unit["start"] != unit["end"]):
        return None
    source = pages[page - 1]
    rows = _page_rows(source)
    before = [(offset, text, layout) for offset, text, layout in rows if offset < end]
    if not before:
        return None
    offset, text, layout = before[-1]
    following = next((row[2] for row in rows if row[0] == end), None)
    title = _PART_TOPIC.fullmatch(text)
    if (not title or re.search(r"\b(?:et|puis|pour|avec|sans|avant|après|en)\b", title["topic"], re.I)
            or not layout or not following or not source.get("height")
            or layout[0] < source["height"] * .85 or layout[1] < following[1] * 1.2
            or source["text"][offset + len(text):end].strip()):
        return None
    return page, offset, text, {"rule": "descriptive_part_before_next_lab_step",
                               "next_unit_id": next_unit["logical_id"], "next_step_offset": end}


# Recognize only goals whose entire meaning is proved by these specific source operations.
_START_LOCAL = re.compile(
    r"Objectif\s*:\s*démarrer une session Spark locale et vérifier la version utilisée\.", re.I,
)
_READ_WITH_TYPES = re.compile(
    r"Objectif\s*:\s*charger les transactions dans un DataFrame Spark en contrôlant les types des colonnes\.", re.I,
)
_STARTUP_CODE = re.compile(
    r"(?m)^[ \t]*(?P<session>\w+)\s*=\s*\(SparkSession\.builder\s*"
    r"\.master\([\"']local(?:\[(?:\d+|\*)\])?[\"']\)"
    r"(?:\s*\.appName\([\"'][^\"'\n]+[\"']\))?\s*\.getOrCreate\(\)\)",
)
_TYPED_READ_CODE = re.compile(
    r"(?m)^[ \t]*(?P<schema>\w+)\s*=\s*StructType\(\[\s*"
    r"(?:StructField\([\"'][^\"'\n]+[\"']\s*,\s*\w+Type\(\)\s*,\s*(?:True|False)\)\s*,?\s*)+"
    r"\]\)\s*transactions_brutes\s*=\s*\(\s*spark\.read\.schema\((?P=schema)\)\s*"
    r"\.json\(str\(chemin_json\.resolve\(\)\)\)\s*\)",
)


def redundant_lab_objective(candidate, following):
    """Return the indexed operations that demonstrate a recognized goal is redundant."""
    objective = candidate["text"]
    if not (_START_LOCAL.fullmatch(objective) or _READ_WITH_TYPES.fullmatch(objective)):
        return None
    page = candidate["anchors"][0]["page"]
    spans = []
    position = 0
    for item in following:
        for source in item["anchors"]:
            if source["page"] == page:
                spans.append((position, source))
                position += len(source["quote"]) + 1
    operations = "\n".join(source["quote"] for _, source in spans)
    if _START_LOCAL.fullmatch(objective):
        startup = _STARTUP_CODE.search(operations)
        version = (re.search(r"(?m)^[ \t]*print\([^\n]*,\s*" + re.escape(startup["session"]) + r"\.version\s*\)",
                             operations[startup.end():]) if startup else None)
        if not version:
            return None
        proof = [(startup.start(), startup.end()),
                 (startup.end() + version.start(), startup.end() + version.end())]
        rule = "spark_session_and_version_operations"
    else:
        typed_read = _TYPED_READ_CODE.search(operations)
        if not typed_read:
            return None
        proof = [typed_read.span()]
        rule = "spark_typed_transaction_reader"
    evidence = [source for start, source in spans
                if any(start < right and left < start + len(source["quote"]) for left, right in proof)]
    return {"rule": rule, "supporting_anchors": evidence}
