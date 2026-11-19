"""Build and evaluate one part of a course using indexed evidence."""
from collections import Counter
from hashlib import sha256
import json
import re
from uuid import UUID, uuid5

from agents.explain_tasks import _fold
from rag.explain_documents import ExplainSourceError, rank_reference_chunks

CHAPTER_HEADING = re.compile(r"^(?:chap\.|chapitre|chapter)\s*(\d+)(?:\.\d+)*\b", re.I)


def scoped_source_manifest(document, pages, scope, target, maps):
    """Use exact PDF boundaries and attach the current Course Map inside them."""
    if scope == "chapter":
        headings = {page: match for page, text in enumerate(pages, 1)
                    if (match := CHAPTER_HEADING.match(_fold(text.lstrip())))}
        if not headings or {int(match[1]) for match in headings.values()} != {target}:
            raise ExplainSourceError("Le chapitre demandé n’est pas identifié dans ce PDF.")
        dividers = [
            (page, label.upper())
            for page, text in enumerate(pages, 1)
            if page in headings
            for label in re.findall(r"(?m)^[ \t]*partie[ \t]+(iv|iii|ii|i)[ \t]*$", _fold(text))
        ]
        if [number for _, number in dividers] != ["I", "II", "III", "IV"]:
            raise ExplainSourceError("Les quatre parties du chapitre ne peuvent pas être délimitées.")
        bounds = [(1, dividers[0][0] - 1, "Introduction")] if dividers[0][0] > 1 else []
        bounds.extend((start, dividers[index + 1][0] - 1 if index + 1 < len(dividers) else len(pages), f"Partie {number}")
                      for index, (start, number) in enumerate(dividers))
        prerequisites = []
    elif scope == "part":
        dividers = [(page, int(match[1])) for page, text in enumerate(pages, 1)
                    if (match := re.search(r"(?m)^\s*partie[ \t]+(\d+)[ \t]*[–—:-]", _fold(text)))]
        candidates = [index for index, (_, number) in enumerate(dividers) if number == target]
        if len(candidates) != 1:
            raise ExplainSourceError("La partie demandée ne peut pas être délimitée dans ce PDF.")
        index = candidates[0]
        start = dividers[index][0]
        end = dividers[index + 1][0] - 1 if index + 1 < len(dividers) else len(pages)
        bounds = [(start, end, f"Partie {target}")]
        prerequisites = [page for page, text in enumerate(pages[:start - 1], 1)
                         if re.search(r"(?m)^\s*(?:etape|step)[ \t]+0\b", _fold(text))]
    else:
        bounds = [(1, len(pages), "TD")]
        prerequisites = []

    document_id = str(document["id"])
    source_hash = document["content_hash"]
    sections = [
        row for row in maps
        if str(row.get("document_id")) == document_id
        and row.get("document_version", source_hash) == source_hash
        and type(row.get("page_start")) is int and type(row.get("page_end")) is int
        and 1 <= row["page_start"] <= row["page_end"] <= len(pages)
        and isinstance(row.get("title"), str) and row["title"].strip()
    ]
    sections.sort(key=lambda row: (row["page_start"], row["page_end"], row["title"]))
    return {
        "document_id": document_id,
        "source_hash": source_hash,
        "index_version": document["index_config"],
        "parts": [
            {"label": label, "page_start": start, "page_end": end, "course_map": [
                {"title": row["title"], "page_start": max(start, row["page_start"]), "page_end": min(end, row["page_end"])}
                for row in sections if row["page_start"] <= end and start <= row["page_end"]
            ]}
            for start, end, label in bounds
        ],
        "prerequisite_pages": prerequisites,
    }


def exercise_reference_batches(pages, manifest, scope, references):
    """Prepare the reference evidence without generating a Spark or TD solution."""
    task_pages = pages[manifest["parts"][0]["page_start"] - 1:manifest["parts"][-1]["page_end"]]
    occurrences = Counter(line for page in task_pages for line in set(page.splitlines()) if line.strip())
    selected = "\n".join(line for page in task_pages for line in page.splitlines() if occurrences[line] < 2)
    if scope == "part":
        pattern = r"(?im)(?=^[ \t]*(?:étape\s+\d+|à analyser\b|exercice\s+[a-z0-9]+\b))"
        batches = []
        analyses = 0
        for block in re.split(pattern, selected):
            head = _fold(block.lstrip())
            if step := re.match(r"etape\s+(\d+)", head):
                batches.append((f"Étape {step[1]}", block))
            elif head.startswith("a analyser"):
                analyses += 1
                batches.append((f"Analyse {analyses}", block))
            elif exercise := re.match(r"exercice\s+([a-z0-9]+)", head):
                batches.append((f"Exercice {exercise[1].upper()}", block))
        if not batches:
            batches = [("Partie", selected)]
    else:
        exercises = re.split(r"(?im)(?=^[ \t]*exercice\s+[a-z0-9]+\b)", selected)[1:]
        batches = [(f"Exercice {index}", block) for index, block in enumerate(exercises, 1)] or [("TD", selected)]
    return [{"label": label, "excerpts": [
        {"document_id": row["document_id"], "page_number": row["page_number"], "filename": row["filename"],
         "chunk_id": row["id"], "content": row["content"],
         "snippet": row["content"].lstrip().split("\n", 1)[0][:110].strip()}
        for row in sorted(rank_reference_chunks(text, references, limit=2, prefer_content=True),
                          key=lambda row: (row["page_number"], row["document_id"]))
    ]} for label, text in batches]


def plan_course(document, maps, chunks, verified_index, context_tokens):
    document_id = str(document["id"])
    per_page = Counter()
    for row in chunks:
        page = row.get("page_number")
        if type(page) is int and page > 0 and isinstance(row.get("content"), str) and row["content"].strip():
            per_page[page] += (len(row["content"].encode("utf-8")) + 2) // 3
    page_count = document.get("page_count") or max(per_page, default=0)
    sections = []
    for row in maps:
        start, end = row.get("page_start"), row.get("page_end")
        title = row.get("title")
        if (str(row.get("document_id")) != document_id or type(start) is not int
                or type(end) is not int or not 1 <= start <= end <= page_count
                or not isinstance(title, str) or not title.strip()):
            continue
        label = title.strip()
        identity = sha256(f"{document_id}:{start}:{end}:{label}".encode()).hexdigest()[:20]
        if any(section["id"] == identity for section in sections):
            continue
        sections.append({"id": identity, "title": label, "start": start, "end": end,
                         "outline": str(row.get("summary") or "")[:800]})
    sections.sort(key=lambda section: (section["start"], section["end"]))
    mapped = {page for section in sections for page in range(section["start"], section["end"] + 1)}
    # Course Map summaries can omit subheadings even when their ranges cover the PDF.
    # Page gaps get explicit placeholders and can never establish course completion.
    for page in sorted(set(range(1, page_count + 1)) - mapped):
        sections.append({"id": f"page-{page}", "title": "", "start": page, "end": page, "outline": ""})
    sections.sort(key=lambda section: (section["start"], section["end"]))
    cap = max(1, min(context_tokens // 2, 12_000))
    parts = []
    current = []
    for section in sections:
        expected = set(range(section["start"], section["end"] + 1))
        section["available"] = bool(verified_index and expected <= per_page.keys())
        candidate = current + [section]
        page_set = {page for item in candidate for page in range(item["start"], item["end"] + 1)}
        evidence_size = sum(per_page[page] for page in page_set)
        output_size = sum(450 + len(item["outline"]) // 2 for item in candidate)
        if current and (evidence_size > cap or output_size > 2600):
            parts.append(current)
            current = []
        current.append(section)
    if current:
        parts.append(current)
    fingerprint = sha256(json.dumps([document_id, document.get("content_hash"), parts],
                                    ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return parts, fingerprint


def _terms(text):
    return set(re.findall(r"[^\W_]{4,}", _fold(text))) - {
        "dans", "avec", "pour", "sont", "cette", "comme", "that", "with", "from", "this", "section",
    }


_FACETS = (
    (r"\b(?:formules?|formulas?|equations?)\b", r"\$|\\\[|\b(?:formules?|formulas?|equations?)\b[^.!?\n]{0,80}="),
    (r"\b(?:exemples?|examples?)\b", r"\b(?:exemples?|examples?|supposons|suppose|imaginons|imagine|prenons)\b"),
    (r"\b(?:tableaux|tables?)\b", r"(?m)^\s*\|[^\n|]+\|"),
)


def assess_part(part, explanation, excerpts, document_id, complete_index):
    pages = {row["page_number"] for row in excerpts}
    results = {}
    for requirement in part:
        key = requirement["id"]
        expected = set(range(requirement["start"], requirement["end"] + 1))
        if not complete_index or not requirement["title"] or not expected <= pages:
            results[key] = "unverifiable"
            continue
        title = _terms(requirement["title"])
        outline = _terms(requirement["outline"]) - title
        required_facets = [pattern for signal, pattern in _FACETS if re.search(signal, _fold(requirement["outline"]))]
        source_terms = _terms(" ".join(row["content"] for row in excerpts if row["page_number"] in expected))
        best = "missing"
        for answer in explanation.sections:
            body = _terms(answer.content)
            cited = {cite.page_number for cite in (answer.citations or [])
                     if str(cite.document_id) == document_id}
            matches = key in (answer.covers or []) or bool(title and title <= (_terms(answer.heading) | body))
            if not matches or len(body) < 10 or not (body & (title | outline)):
                continue
            best = "partial"
            if (cited & expected and len(body) >= 25 and len(body & outline) >= min(5, len(outline))
                    and len(outline) >= 3 and len(body & source_terms) >= 5
                    and all(re.search(pattern, _fold(answer.content)) for pattern in required_facets)):
                best = "covered"
                break
        results[key] = best
    return results


def part_progress(parts, version, document_id, part_index, results, prior, request_id, language):
    statuses = {item["id"]: "not_yet_generated" for group in parts for item in group}
    if prior:
        statuses.update({item["id"]: item["status"] for item in prior["sections"]})
    statuses.update(results)
    rows = [{key: value for key, value in item.items() if key != "outline"} |
            {"status": statuses[item["id"]], "part": index + 1}
            for index, group in enumerate(parts) for item in group]
    counts = Counter(statuses.values())
    next_id = str(uuid5(UUID(request_id), "explain-course-next")) if request_id and part_index + 1 < len(parts) else None
    generated = [*(prior.get("generated_parts", []) if prior else []),
                 {"part": part_index + 1, "request_id": request_id}]
    return {"document_id": document_id, "version": version, "part": part_index + 1,
            "total_parts": len(parts), "sections": rows, "counts": dict(counts),
            "request_id": request_id, "next_request_id": next_id, "language": language,
            "inventory_uncertain": True, "generated_parts": generated}
