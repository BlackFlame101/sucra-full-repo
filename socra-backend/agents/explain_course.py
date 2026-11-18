"""Build and evaluate one part of a course using indexed evidence."""
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from hashlib import sha256
import json
import re
from uuid import UUID, uuid5

from agents.explain_tasks import _fold
from rag.unit_map import chunk_text_hash


def plan_course(document, maps, chunks, verified_index, context_tokens, *, units=None, batch_units=False):
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
    if units is not None:
        sections = [{
            "id": unit["logical_id"], "title": unit["title"], "start": unit["start"][0], "end": unit["end"][0],
            "start_position": unit["start"], "end_position": unit["end"], "outline": unit["title"],
            "kind": unit["kind"], "label": unit["label"], "fallback": unit["fallback"],
            "content_version": unit["content_version"],
            "evidence_spans": unit["evidence_spans"], "weight": unit["weight"],
        } for unit in units if unit["kind"] not in {"transition", "front_matter", "summary"}]
    else:
        mapped = {page for section in sections for page in range(section["start"], section["end"] + 1)}
        # Missing Course Map pages must never establish course completion.
        for page in sorted(set(range(1, page_count + 1)) - mapped):
            sections.append({"id": f"page-{page}", "title": "", "start": page, "end": page, "outline": ""})
        sections.sort(key=lambda section: (section["start"], section["end"]))
    chunk_hashes = {row["chunk_index"]: chunk_text_hash(row["content"]) for row in chunks
                    if type(row.get("chunk_index")) is int and isinstance(row.get("content"), str)} if units is not None else {}
    cap = max(1, min(context_tokens // 2, 12_000))
    parts = []
    current = []
    for section in sections:
        expected = set(range(section["start"], section["end"] + 1))
        if units is None:
            section["available"] = bool(verified_index and expected <= per_page.keys())
        else:
            spans = section["evidence_spans"]
            section["available"] = bool(verified_index and spans and all(
                chunk_hashes.get(chunk) == digest for chunk, _, _, digest in spans
            ))
        candidate = current + [section]
        page_set = {page for item in candidate for page in range(item["start"], item["end"] + 1)}
        evidence_size = (sum(per_page[page] for page in page_set) if units is None
                         else sum(item["weight"] for item in candidate))
        output_size = sum(450 + len(item["outline"]) // 2 for item in candidate)
        if current and not batch_units and (evidence_size > cap or output_size > 2600):
            parts.append(current)
            current = []
        current.append(section)
    if current:
        parts.append(current)
    fingerprint = sha256(json.dumps([document_id, document.get("content_hash"), parts],
                                    ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return parts, fingerprint


def unit_excerpts(part, chunks):
    indexed = {row.get("chunk_index"): row for row in chunks}
    hashes = {index: chunk_text_hash(row["content"]) for index, row in indexed.items()
              if isinstance(row.get("content"), str)}
    for unit in part:
        for index, start, end, digest in unit["evidence_spans"]:
            if hashes.get(index) == digest:
                row = indexed[index]
                yield row | {"content": row["content"][start:end], "unit_id": unit["id"]}


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
        unit = "content_version" in requirement
        if unit:
            owned = [row for row in excerpts if row.get("unit_id") == key]
            expected = {row["page_number"] for row in owned}
            owned_citations = {(row["page_number"], " ".join(row["content"].split())[:650]) for row in owned}
        else:
            owned = [row for row in excerpts if row["page_number"] in expected]
        if (not complete_index or not requirement["title"] or not expected or not expected <= pages
                or (unit and (requirement["fallback"] or not requirement["available"]
                              or len(owned) != len(requirement["evidence_spans"])))):
            results[key] = "unverifiable"
            continue
        title = _terms(requirement["title"])
        outline = _terms(requirement["outline"]) - title
        required_facets = [pattern for signal, pattern in _FACETS if re.search(signal, _fold(requirement["outline"]))]
        source_terms = _terms(" ".join(row["content"] for row in owned))
        best = "missing"
        for answer in explanation.sections:
            body = _terms(answer.content)
            cited = {cite.page_number for cite in (answer.citations or [])
                     if str(cite.document_id) == document_id
                     and (not unit or (cite.page_number, cite.excerpt) in owned_citations)}
            matches = key in (answer.covers or []) or bool(title and title <= (_terms(answer.heading) | body))
            if not matches or len(body) < 10 or not (body & (title | outline)):
                continue
            best = "partial"
            if (cited & expected and len(body) >= 25 and len(body & outline) >= min(5, len(outline))
                    and (unit or len(outline) >= 3) and len(body & source_terms) >= 5
                    and all(re.search(pattern, _fold(answer.content)) for pattern in required_facets)):
                best = "covered"
                break
        results[key] = best
    return results


def _reconcile_units(items, previous):
    matched = {item["id"]: item for item in previous if item["id"] in items}
    unmatched = {key: item for key, item in items.items() if key not in matched}
    by_content = defaultdict(list)
    by_heading = defaultdict(list)
    for key, item in unmatched.items():
        by_content[item["content_version"]].append(key)
        by_heading[item["label"], item["kind"]].append((key, item))
    old = [item for item in previous if item["id"] not in matched and item["status"] != "not_yet_generated"]
    candidates = {}
    exact_content = {}
    for item in old:
        same_text = by_content[item.get("content_version")]
        exact_content[item["id"]] = same_text
        candidates[item["id"]] = same_text or [
            key for key, new in by_heading[item.get("label"), item.get("kind")]
            if min(new["end"], item["end"]) >= max(new["start"], item["start"])
            and SequenceMatcher(None, new["title"].casefold(), item["title"].casefold()).ratio() >= .72
        ]
    reverse = Counter(key for keys in candidates.values() for key in keys)
    ledger = []
    for item in old:
        keys = candidates[item["id"]]
        if len(keys) == 1 and reverse[keys[0]] == 1:
            matched[keys[0]] = item
            reason = "rename"
        elif len(keys) > 1:
            reason = "possible_split"
        elif keys:
            reason = "possible_merge"
        else:
            reason = "removed"
        ledger.append({
            "prior_id": item["id"], "current_ids": keys, "reason": reason,
            "stale": reason != "rename" or keys != exact_content[item["id"]] or bool(item.get("stale")),
        })
    return matched, ledger


def part_progress(parts, version, document_id, part_index, results, prior, request_id, language):
    items = {item["id"]: item for group in parts for item in group}
    statuses = dict.fromkeys(items, "not_yet_generated")
    stale = set()
    ledger = []
    if prior:
        if prior.get("unit_map_version"):
            matches, ledger = _reconcile_units(items, prior["sections"])
            stale.update(key for entry in ledger if entry["stale"] for key in entry["current_ids"])
        else:
            matches = {item["id"]: item for item in prior["sections"] if item["id"] in items}
        for key, item in matches.items():
            if items[key].get("content_version") == item.get("content_version") and not item.get("stale"):
                statuses[key] = item["status"]
            elif item["status"] != "not_yet_generated" or item.get("stale"):
                stale.add(key)
    statuses.update(results)
    rows = [{key: value for key, value in item.items() if key not in {"outline", "weight", "evidence_spans"}} |
            {"status": statuses[item["id"]], "part": index + 1} |
            ({"stale": True} if item["id"] in stale and item["id"] not in results else {})
            for index, group in enumerate(parts) for item in group]
    counts = Counter(statuses.values())
    next_id = str(uuid5(UUID(request_id), "explain-course-next")) if request_id and part_index + 1 < len(parts) else None
    generated = [*(prior.get("generated_parts", []) if prior else []),
                 {"part": part_index + 1, "request_id": request_id}]
    return {"document_id": document_id, "version": version, "part": part_index + 1,
            "total_parts": len(parts), "sections": rows, "counts": dict(counts),
            "request_id": request_id, "next_request_id": next_id, "language": language,
            "inventory_uncertain": True, "generated_parts": generated,
            **({"unit_reconciliation": ledger} if ledger else {})}


def reconcile_saved_units(units, previous, rebound):
    """Describe stale, removed and split/merged archived outputs without transferring their statuses."""
    items = {unit["logical_id"]: unit | {"start": unit["start"][0], "end": unit["end"][0]} for unit in units}
    matches, ledger = _reconcile_units(items, previous)
    recorded = {entry["prior_id"] for entry in ledger}
    for uid, old in matches.items():
        if old["id"] in recorded:
            continue
        stale = uid not in rebound or old["content_version"] != items[uid]["content_version"]
        ledger.append({"prior_id": old["id"], "current_ids": [uid],
                       "reason": "content_changed" if old["content_version"] != items[uid]["content_version"]
                       else "source_unconfirmed" if stale else "source_rebound", "stale": stale})
    for entry in ledger:
        if entry["reason"] == "rename":
            entry["stale"] |= not any(uid in rebound for uid in entry["current_ids"])
    return ledger


def resume_unit_part(parts, prior):
    """Resume at the first part whose units need generation against this map."""
    items = {item["id"]: item for part in parts for item in part}
    old, _ = _reconcile_units(items, prior["sections"])
    for index, part in enumerate(parts):
        for item in part:
            previous = old.get(item["id"], {})
            if (previous.get("content_version") != item["content_version"]
                    or previous.get("stale")
                    or previous.get("status") not in {"covered", "partial", "missing", "unverifiable"}):
                return index
    return len(parts)
