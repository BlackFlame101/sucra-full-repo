"""Deterministic, source-ordered Unit Map skeletons."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter
from hashlib import sha256
import json
import os
import re
from unicodedata import normalize

EXTRACTOR_VERSION = "layout-v3"
MAX_UNIT_CHARS = 8_000
NUMBERED = re.compile(
    r"^(?P<label>(?:partie\s+[IVXLCDM]+|(?:exercice|question|étape|etape|tp)\s*\d+)(?:\.\d+)*"
    r"|[IVXLCDM]+\.\d+(?:\.\d+)*|[IVXLCDM]+\.(?=\s)|\d+\.[a-z\d]+(?:\.\d+)*"
    r"|\([a-z]\)|\d+[.)])(?:\s*[:.–—-]\s*|\s+|$)(?P<title>.*)$", re.I
)


QUESTION = re.compile(r"^(?P<label>Q\s*\d+)\s*[.):]\s*(?P<title>\S.*)$", re.I)
CHOICE = re.compile(r"^([A-D])[.)]\s+\S", re.I)
CASE = re.compile(r"^(?:(?:TD|TP)\s*(?:n[°ºo]\s*)?\d+\s*[:.–—-]\s*)?(?:étude de cas|case study)\b", re.I)
CORRECTION = re.compile(r"^(?:corrigé|correction|answer key)\b", re.I)
TASK_LIST = re.compile(r"^(?:TAF|travail à faire|questions|consignes)\s*:?$", re.I)
TASK_NUMBER = re.compile(r"^(\d+)[.)]\s+(\S.*)$")
ANSWER_NUMBER = re.compile(r"^(\d+)\s*[:–—-]\s*(\S.*)$")


def unit_pipeline_enabled() -> bool:
    return os.getenv("EXPLAIN_UNIT_PIPELINE", "").strip().casefold() in {"1", "true", "on", "yes"}


def _normalized(value: str) -> str:
    return " ".join(normalize("NFKC", value).casefold().split())


def _hash(value) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _kind(label: str, title: str, in_exercise: bool) -> str:
    if re.match(r"^(?:tp|étape|etape)\s*\d", label, re.I):
        return "lab_step"
    if in_exercise or re.match(r"exercice|question", label, re.I):
        return "exercise"
    if re.match(r"^(?:à retenir|récapitulatif|récap|résumé|synthèse|summary|recap|key takeaways)\b", title, re.I):
        return "summary"
    if re.search(r"calculer|calcul (?:de|à)|worked calculation", title, re.I):
        return "worked_calculation"
    if re.search(r"waterfall|beeswarm|graphique|schéma|^SHAP local|chemin d['’]une décision", title, re.I):
        return "figure_walkthrough"
    if re.search(r"comparaison|compromis|shap ou lime|performance ou interprétabilité", title, re.I):
        return "comparison"
    return "concept"


def _page_rows(page: dict):
    text = page["text"]
    # PDF.js offsets count UTF-16 code units. Convert to Python character offsets.
    astral = [index for index, character in enumerate(text) if ord(character) > 0xFFFF]
    runs = {}
    extra = 0
    for offset, y, size, _font, *properties in page.get("runs", []):
        while extra < len(astral) and astral[extra] + extra < offset:
            extra += 1
        runs[offset - extra] = (y, size, bool(properties and properties[0]))
    rows = []
    offset = 0
    for raw in text.splitlines(keepends=True):
        line = raw.strip()
        start = offset + len(raw) - len(raw.lstrip())
        if line:
            rows.append((start, line, runs.get(start)))
        offset += len(raw)
    return rows


def _choice_rows(page_rows):
    """Recognize complete choice sequences within explicitly introduced questions."""
    choices = set()
    pending = []
    in_question = False
    for page, rows in enumerate(page_rows, 1):
        for offset, line, _ in rows:
            if QUESTION.fullmatch(line) or re.match(r"^Question\s+\d+\b", line, re.I):
                in_question, pending = True, []
            elif in_question and (match := CHOICE.match(line)):
                if match[1].upper() != "ABCD"[len(pending)]:
                    in_question, pending = False, []
                    continue
                pending.append((page, offset))
                if len(pending) == 4:
                    choices.update(pending)
                    in_question, pending = False, []
            elif NUMBERED.fullmatch(line):
                in_question, pending = False, []
    return choices


def _page_headings(page: dict, rows: list, choices: set):
    for start, line, layout in rows:
        part = re.fullmatch(r"Partie\s+([IVXLCDM]+)", line, re.I)
        if part and layout and layout[1] >= 20:
            numeral = part[1].upper()
            markers = [candidate for _, value, candidate in rows if value == numeral and candidate]
            if len(markers) == 1:
                marker_y, marker_size, _ = markers[0]
                titles = [value for _, value, candidate in rows
                          if candidate and len(value.split()) >= 2
                          and abs(candidate[0] - marker_y) < 5 and abs(candidate[1] - marker_size) < 2]
                if len(titles) == 1:
                    return [(0, numeral, titles[0], "transition")]

    body_sizes = Counter(round(layout[1]) for _, line, layout in rows
                         if layout and len(line) >= 20)
    body_size = body_sizes.most_common(1)[0][0] if body_sizes else 0
    headings = []
    task_list = correction = False
    for start, line, layout in rows:
        if layout and layout[0] < page.get("height", 0) * .035:
            continue
        if start in choices or re.fullmatch(r"[+−-]?\d+(?:[.,]\d+)?", line):
            continue
        if CASE.match(line):
            headings.append((start, "Étude de cas", line, "exercise"))
            task_list = correction = False
            continue
        if CORRECTION.match(line) and (not layout or layout[2] or layout[1] > body_size):
            headings.append((start, "", line, "concept"))
            task_list, correction = False, True
            continue
        if TASK_LIST.fullmatch(line):
            task_list = True
            continue
        if task_list and (question := TASK_NUMBER.fullmatch(line)):
            headings.append((start, f"Question {question[1]}", question[2], "exercise"))
            continue
        if correction and (answer := ANSWER_NUMBER.fullmatch(line)):
            headings.append((start, f"Réponse {answer[1]}", answer[2], "concept"))
            continue
        if question := QUESTION.fullmatch(line):
            headings.append((start, question["label"], question["title"], "exercise"))
            continue
        match = NUMBERED.fullmatch(line)
        if match:
            label, title = match["label"], match["title"].strip()
            if (label[0].isdigit() and "." in label and not label.endswith(".")
                    and (not title or re.match(r"^[+−*/=)\]},-]", title))):
                continue
            if (re.fullmatch(r"partie\s+[IVXLCDM]+", label, re.I) and not title
                    or re.match(r"^à\s+tp\s*\d+", title, re.I)):
                continue
            if label[0].isdigit() and label.endswith((")", ".")) and layout:
                continue  # Numbered body lists are common in slide decks.
            if re.fullmatch(r"[IVXLCDM]+\.?", label, re.I):
                headings.append((start, label.rstrip(".").upper(), title, "transition"))
            else:
                headings.append((start, label, title, ""))
        elif (layout and body_size and (layout[1] >= max(19, body_size * 1.35) or layout[2])
              and layout[0] >= page.get("height", 0) * .82
              and not re.match(r"chap\.|partie\b", line, re.I)):
            headings.append((start, "", line, ""))
        elif re.fullmatch(r"(?:exemple|example)(?:\s*[:–—-]\s*.+)?", line, re.I):
            headings.append((start, "", line, ""))
    return headings


def build_unit_map(document_id: str, pages: list[dict]) -> dict:
    """Positions are one-based pages and zero-based, end-exclusive character offsets."""
    if not pages:
        raise ValueError("A Unit Map requires at least one page")
    source = [page["text"] for page in pages]
    clean = []
    headings = []
    page_rows = [_page_rows(page) for page in pages]
    choice_rows = _choice_rows(page_rows)
    for page_number, (page, rows) in enumerate(zip(pages, page_rows), 1):
        headings.extend(((page_number, offset), label, title, kind)
                        for offset, label, title, kind in _page_headings(
                            page, rows, {offset for number, offset in choice_rows if number == page_number}))
        characters = list(page["text"])
        for offset, line, layout in rows:
            if layout and layout[0] < page.get("height", 0) * .035:
                characters[offset:offset + len(line)] = " " * len(line)
        clean.append("".join(characters))
    fallback = not headings
    if fallback:
        headings = [((page, 0), "", "Page window", "concept")
                    for page in range(1, len(source) + 1, 3)]
    elif headings[0][0] != (1, 0):
        headings.insert(0, ((1, 0), "", "Front matter", "front_matter"))

    units = []
    ordinal = Counter()
    part = ()
    exercise = ()
    question = ()
    case = ()
    correction = ()
    numbered_paths = {}
    last_seen = None
    for position, label, title, kind in headings:
        key = (_normalized(label), _normalized(title))
        is_part = kind == "transition"
        is_case = label == "Étude de cas"
        is_correction = bool(CORRECTION.match(title))
        is_answer = bool(re.fullmatch(r"réponse \d+", label, re.I))
        is_exercise = is_case or bool(re.match(r"exercice\b", label, re.I))
        is_question = bool(re.match(r"question\b", label, re.I) or re.fullmatch(r"q\s*\d+", label, re.I))
        is_subquestion = label.startswith("(") or bool(re.fullmatch(r"\d+\.[a-z]", label, re.I))
        parent = () if is_part else part
        number = key[0] if re.fullmatch(r"[ivxlcdm]+\.\d+(?:\.\d+)*", key[0]) else ""
        if number.count(".") > 1:
            parent = numbered_paths.get(number.rsplit(".", 1)[0], parent)
        if not is_exercise and (is_question or is_subquestion):
            parent += exercise
        if is_subquestion:
            parent += question
        if is_correction:
            parent += case
        elif is_answer:
            parent = correction or parent
        signature = (parent, key)
        if (not fallback and last_seen and last_seen[0] == signature
                and last_seen[1] + 1 == position[0]):
            units[-1]["continuations"].append(list(position))
            last_seen = (signature, position[0])
            continue
        ordinal[signature] += 1
        path = (*parent, (*key, ordinal[signature]))
        if is_part:
            part, exercise, question = path, (), ()
            case = correction = ()
            numbered_paths.clear()
        elif is_exercise:
            exercise, question = (path[-1],), ()
            case = exercise if is_case else ()
            correction = ()
        elif is_question:
            question = (path[-1],)
        elif is_correction:
            correction = path
        if number:
            numbered_paths[number] = path
        units.append({
            "label": label, "title": title or label, "heading_path": path, "start": list(position),
            "kind": kind or _kind(label, title, bool(exercise and (is_subquestion or is_question))),
            "sibling_ordinal": ordinal[signature], "continuations": [], "fallback": fallback,
        })
        last_seen = (signature, position[0])

    result = []
    end_of_document = [len(source), len(source[-1])]
    for index, unit in enumerate(units):
        end = units[index + 1]["start"] if index + 1 < len(units) else end_of_document
        next_page = end[0] == unit["start"][0] + 1
        previous_header = {line for _, line, _ in page_rows[end[0] - 2][:3]} if next_page else set()
        header_only = next_page and unit["kind"] == "exercise" and all(
            line in previous_header or line == str(end[0])
            for offset, line, _ in page_rows[end[0] - 1] if offset < end[1]
        )
        if (end[1] == 0 or header_only) and end[0] > unit["start"][0]:
            end = [end[0] - 1, len(source[end[0] - 2])]
        fragments = list(_split_span(clean, unit["start"], end))
        for number, (start, stop, content) in enumerate(fragments, 1):
            path = unit["heading_path"]
            if len(fragments) > 1:
                path = (*path, ("", "split", number))
            normalized_content = " ".join(normalize("NFC", content).split())
            kind = unit["kind"]
            if kind == "concept" and not unit["label"] and index + 1 < len(units):
                if _normalized(normalized_content) == _normalized(unit["title"]):
                    kind = "non_teaching"
            result.append(unit | {
                "start": start, "end": stop, "heading_path": path, "kind": kind,
                "split": number if len(fragments) > 1 else None,
                "logical_id": _hash([document_id, path])[:24],
                "content_version": _hash([normalized_content, []]),
                "weight": (len(content.encode("utf-8")) + 2) // 3,
                "enrichment_state": "skeleton",
            })
    return {"extractor_version": EXTRACTOR_VERSION, "text_hash": _hash(source), "units": result}


def _split_span(pages: list[str], start: list[int], end: list[int]):
    segments = []
    offsets = [0]
    markers = []
    for page in range(start[0], end[0] + 1):
        left = start[1] if page == start[0] else 0
        stop = end[1] if page == end[0] else len(pages[page - 1])
        segment = pages[page - 1][left:stop]
        segments.append(segment)
        markers.extend(offsets[-1] + match.start() for match in re.finditer(
            r"(?im)^[ \t]*(?:figure|tableau|table|exemple|example)\b", segment
        ))
        offsets.append(offsets[-1] + len(segment))
    if offsets[-1] <= MAX_UNIT_CHARS:
        yield start, end, "\n".join(segments)
        return

    cursor = 0
    while cursor < offsets[-1]:
        boundary = min(cursor + MAX_UNIT_CHARS, offsets[-1])
        if boundary < offsets[-1]:
            marker = bisect_right(markers, boundary) - 1
            page_end = offsets[bisect_right(offsets, boundary) - 1]
            if marker >= 0 and markers[marker] > cursor:
                boundary = markers[marker]
            elif page_end > cursor:
                boundary = page_end
            else:
                page = bisect_right(offsets, cursor) - 1
                page_start = offsets[page]
                line_end = segments[page].rfind("\n", cursor - page_start + 1, boundary - page_start)
                if line_end >= 0:
                    boundary = page_start + line_end + 1
        first = bisect_right(offsets, cursor) - 1
        last = bisect_left(offsets, boundary) - 1
        left, right = cursor - offsets[first], boundary - offsets[last]
        content = segments[first:last + 1]
        content[-1] = content[-1][:right]
        content[0] = content[0][left:]
        begin = start if cursor == 0 else [start[0] + first, left + (start[1] if not first else 0)]
        stop = end if boundary == offsets[-1] else [start[0] + last, right + (start[1] if not last else 0)]
        yield begin, stop, "\n".join(content)
        cursor = boundary


def bind_chunks(units: list[dict], chunks: list[dict]) -> None:
    """Largest overlap owns the chunk. Each intersecting unit may cite its own slice."""
    by_page = {}
    for unit in units:
        unit["chunk_indexes"] = []
        unit["evidence_spans"] = []
        for page in range(unit["start"][0], unit["end"][0] + 1):
            start = unit["start"][1] if page == unit["start"][0] else 0
            end = unit["end"][1] if page == unit["end"][0] else None
            by_page.setdefault(page, []).append((unit, start, end))
    for chunk in chunks:
        start, end = chunk["start_offset"], chunk["end_offset"]
        offsets = chunk["source_offsets"]
        digest = chunk_text_hash(chunk["content"])
        best_overlap = 0
        owner = None
        for unit, left, right in by_page.get(chunk["page_number"], []):
            if left >= end:
                break
            if right is not None and right <= start:
                continue
            first = bisect_left(offsets, left)
            last = len(offsets) if right is None else bisect_left(offsets, right)
            if last > first:
                unit["evidence_spans"].append([chunk["chunk_index"], first, last, digest])
            if last - first > best_overlap:
                owner, best_overlap = unit, last - first
        if owner is not None:
            owner["chunk_indexes"].append(chunk["chunk_index"])


def chunk_text_hash(text: str) -> str:
    return sha256(text.encode()).hexdigest()
