"""Deterministic evidence checks. Coverage is not correctness."""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from rag.document_inventory import DocumentInventory, Requirement, _ARABIC_HEADING_ORDINAL, _ARABIC_ORDINALS, _LABELS

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_STOP = set("avec dans pour apres avant cette votre notre leurs selon resultat result voir voici explique question exercise exercice screenshot capture ensuite document required montre shown يظهر باستخدام المطلوب".split())
_FLOORS = {"screenshot": 10, "step": 7, "formula": 3, "question": 7, "exercise": 7,
           "subquestion": 5, "deliverable": 4, "file": 4, "appendix": 6, "installation": 6,
           "table": 5, "expected_result": 4}


def normalized(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(c)).translate(_DIGITS)


def _floor(kind: str) -> int:
    default = _FLOORS.get(kind, 6)
    try:
        return max(1, min(100, int(os.getenv(f"SOCRA_EXPLAIN_COVERAGE_MIN_{kind.upper()}_WORDS", str(default)))))
    except ValueError:
        return default


def _heading_ordinals(text: str) -> str:
    return _ARABIC_HEADING_ORDINAL.sub(lambda match: match[1] + _ARABIC_ORDINALS[match[2]], text)


def _mention(item: Requirement, text: str) -> bool:
    label = normalized(item.id)
    kind, identifier = label.split(":", 1)
    if re.search(r"(?<![\w.])" + re.escape(label) + r"(?![\w.]|\d)", text):
        return True
    if kind in {"file", "deliverable"}:
        return "." in identifier and bool(re.search(r"(?<![\w.-])" + re.escape(identifier) + r"(?![\w-])", text))
    if kind in _LABELS and len(identifier) <= 12:
        text = "\n".join(_heading_ordinals(line) for line in text.split("\n"))
        qualifier = r"(?:[ \t]+checkpoint)?(?:[ \t]*[:–—-][ \t]*(?:captures?|screenshots?))?" if kind == "screenshot" else ""
        return bool(re.search(r"(?<!\w)(?:" + _LABELS[kind] + r")" + qualifier + r"[ \t:–—-]*(?:(?:n[°ºo]|no\.)[ \t]*|#[ \t]*)?"
                              + re.escape(identifier) + r"(?![\w]|\.\d)", text))
    return normalized(item.original_heading) in text


def requirement_label(item: Requirement) -> str:
    heading = re.sub(r"(?<![\w/])(?:[\w-]+:)?[a-f0-9]{16,}(?![\w/])", "", " ".join(item.original_heading.split()), flags=re.I).strip()
    _, identifier = item.id.split(":", 1)
    if heading:
        return heading[:160]
    if re.fullmatch(r"[a-f0-9]{16}", identifier, re.I):
        return item.kind.replace("_", " ").capitalize()
    return f"{item.kind.replace('_', ' ').capitalize()} {identifier}"[:160]


def relevant_requirements(
    inventory: DocumentInventory, topic: str, *, broad: bool, omitted_labels=(), source_chunks=(),
) -> list[Requirement]:
    text = normalized(topic)
    items = inventory.requirements
    named = {item.key for item in items if _mention(item, text)}
    excluded = set()
    exclusion = re.search(r"\b(?:except|excluding|skip|sauf|باستثناء|إلا|الا)\b(.*)", text)
    if exclusion:
        excluded = {item.key for item in items if _mention(item, exclusion[1])}
    # A numbered request restricts scope unless the request explicitly asks for all.
    all_items = bool(re.search(r"\b(?:all|every|tous|toutes|chaque|كل|جميع)\b", text))
    chosen = set(named - excluded)
    if broad and (not named or all_items):
        chosen.update(item.key for item in items if item.status == "required")
        fallback_sentences = [
            normalized(line) for row in source_chunks for line in row["content"].splitlines()
            if re.search(r"\b(?:otherwise|fallback|sinon|reg[eé]n[eé]r|بديل)\w*", line, re.I)
        ]
        chosen.update(item.key for item in items if item.kind == "appendix" and item.status != "optional"
                      and any(_mention(item, line) for line in fallback_sentences))
    chosen.update(item.key for item in items
                  if (item.status == "required" or item.kind == "subquestion" and item.status != "optional")
                  and item.parent_key in chosen)
    chosen.difference_update(excluded)
    excluded.update(item.key for item in items if item.parent_key in excluded)
    # A deliberate Phase 1 cap is presented by its own persistent notice.
    omitted = {item.key for item in items if item.kind == "exercise" and any(
        _mention(item, normalized(label)) for label in omitted_labels)}
    omitted.update(item.key for item in items if item.parent_key in omitted)
    return [item for item in items if item.status != "structural" and item.key in chosen and item.key not in excluded | omitted]


_SIGNALS = {
    "when": r"\b(?:after|before|once|when|then|apres|avant|lorsque|puis|بعد|قبل|عند|ثم)\b",
    "view": r"\b(?:visible|show|display|include|showing|affiche|afficher|visible|montre|apparaitre|اظهر|تظهر|مرئي)\b",
    "save": r"\b(?:save|export|attach|report|insert|enregistre\w*|rapport|joindre|حفظ|احفظ|ارفق|التقرير)\b",
    "method": r"\b(?:compare|calculate|inspect|explain|derive|because|using|check|measure|run|calcul\w*|compar\w*|expliqu\w*|car|verifi\w*|mesur\w*|احسب|قارن|تحقق|اشرح|لان)\b",
    "action": r"\b(?:open|click|select|run|install|enter|create|ouvre\w*|cliqu\w*|selection\w*|installe\w*|افتح|اختر|ثبت|شغل)\b",
    "outcome": r"\b(?:shows?|results?|expect\w*|displays?|verify|output|resultat|affich\w*|obten\w*|يظهر|النتيجة|تحقق)\b",
    "verify": r"\b(?:check|verify|substitut\w*|verifi\w*|تحقق|عوض)\b",
    "derive": r"\b(?:derive|therefore|from|using|donc|dedui\w*|a partir|اذن|من)\b",
    "example": r"\b(?:example|for instance|exemple|مثال)\b",
    "practice": r"\b(?:practice|try|use|usage|utilise\w*|essay\w*|تدرب|استخدم)\b",
    "limits": r"\b(?:limit\w*|uncertain\w*|bias|limite\w*|incertitude|قيود|حدود)\b",
    "unit": r"\b(?:units?|unites?|percent|pour cent|kg|ms|seconds?|secondes?|وحدة|نسبة)\b|%",
    "test": r"\b(?:test\w*|pytest|assert|verifi\w*|اختبار|تحقق)\b",
}


def _signals(text: str, *names: str) -> bool:
    return all(re.search(_SIGNALS[name], text) for name in names)


def _anchored(item: Requirement, text: str) -> bool:
    anchor = normalized(item.evidence_anchor)
    prefix = _LABELS.get(item.kind)
    if prefix:
        anchor = re.sub(r"^(?:" + prefix + r")\s*#?\s*[\w.]+\s*[:.)–—-]?\s*", "", anchor, count=1)
    filename_or_formula = re.findall(r"[\w-]+\.[a-z0-9]{1,8}\b|[\w]+\s*=\s*[\w+*/^.-]+", anchor)
    if any(re.sub(r"\s+", "", value) in re.sub(r"\s+", "", text) for value in filename_or_formula):
        return True
    aliases = (
        (r"matrice de confusion|confusion matrix", "confusion matrix"),
        (r"feux au vert|all[- ]green|all nodes (?:are )?green|green status", "green nodes"),
        (r"exactitude|accuracy", "accuracy"),
        (r"reproductibilite|reproducibility", "reproducibility"),
        (r"cout des erreurs|cost of errors|error costs?", "error cost"),
        (r"cible|target column", "target column"),
        (r"jeu de donnees|dataset", "dataset"),
        (r"entrainement|training", "training"),
    )
    for pattern, canonical in aliases:
        anchor = re.sub(r"\b(?:" + pattern + r")\b", canonical, anchor)
        text = re.sub(r"\b(?:" + pattern + r")\b", canonical, text)
    words = {w for w in re.findall(r"\b(?:[^\W\d_]{4,}|f1)\b", anchor) if w not in _STOP}
    hits = words & set(re.findall(r"\b(?:[^\W\d_]{4,}|f1)\b", text))
    return len(hits) >= min(2, len(words)) and bool(hits)


# Compare only explicit nested paths with the same root and basename.
# Alternate roots, bare filenames and inferred working directories are ambiguous.
_RELATIVE_FILE = re.compile(r"(?<![\w./:-])(?:[\w.-]+/)+[\w.-]+\.[a-z0-9]{1,8}(?![\w/-]|\.[\w.])")
_INSTALL_ACTION = r"\b(?:install(?:er|ation)?|set[ -]?up|download|telecharg\w*)\b"


def _conflicting_file_path(anchor: str, text: str) -> bool:
    sources = {}
    for path in _RELATIVE_FILE.findall(anchor.replace("\\", "/")):
        parts = path.split("/")
        sources.setdefault((parts[0], parts[-1]), set()).add(path)
    for path in _RELATIVE_FILE.findall(text.replace("\\", "/")):
        parts = path.split("/")
        expected = sources.get((parts[0], parts[-1]), set())
        if len(expected) == 1 and path not in expected:
            return True
    return False


def _installation_heading_matches(item: Requirement, heading: str) -> bool:
    if item.kind != "installation" or not re.search(_INSTALL_ACTION, heading):
        return False
    # Match the product name even when a translated heading drops the source verb or step number.
    name = re.search(r"\b(?:install|installer) ([a-z][\w-]*(?: [a-z][\w-]*)*)\s*$",
                     normalized(item.original_heading))
    return bool(name and re.search(r"(?<!\w)" + re.escape(name[1]) + r"(?!\w)", heading))


def _substantive(item: Requirement, text: str, *, lab_question: bool = False) -> bool:
    if len(re.findall(r"\b\w+\b", text)) < _floor(item.kind):
        return False
    if item.kind == "screenshot":
        return _signals(text, "when", "save") and (
            _signals(text, "view") or bool(re.search(r"\b(?:capture|screenshot|photograph|captur\w*)\b", text))
        )
    if item.kind == "step":
        return _signals(text, "when", "action", "outcome")
    if item.kind == "formula":
        return _signals(text, "derive", "verify") and "=" in text
    anchor = normalized(item.evidence_anchor)
    if lab_question:
        # Read/record are valid investigative actions even without a second generic
        # method verb. Require detail beyond repeating the assignment's wording.
        text = _QUESTION_GUIDANCE_LABEL.sub("", text)
        if not re.search(_LAB_GUIDANCE["question"], text):
            return False
        subjects = r"\b[^\W\d_]{4,}\b"
        source_words = set(re.findall(subjects, anchor))
        detail = re.sub(_LAB_GUIDANCE["question"], " ", text)
        detail = re.sub(_SIGNALS["method"], " ", detail)
        added = set(re.findall(subjects, detail)) - source_words - _STOP
        return bool(added - {"reported", "relevant", "your", "these", "those", "with", "from", "that", "which"})
    if item.kind in {"file", "installation", "deliverable"}:
        if not (_signals(text, "action") or _signals(text, "save")
                or item.kind == "installation" and re.search(_INSTALL_ACTION, text)):
            return False
        if item.kind in {"file", "deliverable"} and _conflicting_file_path(anchor, text):
            return False
        if re.search(r"\b(?:test|pytest|tests|اختبار)\b", anchor) and not _signals(text, "test"):
            return False
    if item.kind == "table":
        return (_signals(text, "method") and
                (not _signals(anchor, "unit") or _signals(text, "unit")) and
                (not _signals(anchor, "limits") or _signals(text, "limits")))
    if re.search(r"\b(?:vocabulary|grammar|vocabulaire|grammaire|مفردات|قواعد)\b", anchor):
        return _signals(text, "example", "practice")
    if re.search(r"\b(?:methodology|methodologie|منهجية)\b", anchor):
        return _signals(text, "method") and (not _signals(anchor, "limits") or _signals(text, "limits"))
    if item.kind in {"question", "exercise", "subquestion", "table"}:
        return _signals(text, "method")
    return True


_LAB_GUIDANCE = {
    "screenshot": (
        r"\b(?:open|click|select|navigate|switch|ouvre\w*|cliqu\w*|selection\w*|\u0627\u0641\u062A\u062D|\u0627\u0646\u0642\u0631)\b"
    ),
    "question": (
        r"\b(?:inspect|record|measure|calculate|compute|read|verify|check|collect|trace|identify|"
        r"relev\w*|calcul\w*|observ\w*|verifi\w*|mesur\w*|\u0627\u062D\u0633\u0628|\u0633\u062C\u0644|\u062A\u062D\u0642\u0642)\b"
    ),
}

_QUESTION_GUIDANCE_LABEL = re.compile(
    r"(?m)^[ \t#*_]*(?:where to look|how to reason|what to write|watch out|"
    r"ou chercher|comment raisonner|quoi ecrire|a surveiller|"
    r"اين تبحث|كيف تستدل|ماذا تكتب|انتبه)"
    r"[*_ \t]*(?::[*_ \t]*|$)"
)

_LAB_TARGET_HEADING = re.compile(
    r"^(?:" + "|".join(_LABELS[kind] for kind in ("screenshot", "question", "appendix"))
    + r")\s*[:#]?\s*(?:\d|[a-z]\b|checkpoint\b)"
)
_LAB_BOLD_HEADING = re.compile(r"^ {0,3}(?:\d+[.)]\s+|[-*]\s+)?\*\*([^*]+)\*\*[ \t]*[:–—-]?[ \t]*(.*)$")

def _lab_blocks(section):
    # Markdown subheadings support grouping when the card has more targets than sections.
    heading = section.heading
    body = []
    fence = ""
    depth = int(bool(_LAB_TARGET_HEADING.match(_heading_ordinals(normalized(heading)))))
    for line in section.content.splitlines():
        boundary = re.match(r"^\s*(`{3,}|~{3,})", line)
        if boundary:
            if not fence:
                fence = boundary[1]
            elif boundary[1][0] == fence[0] and len(boundary[1]) >= len(fence):
                fence = ""
        subheading = re.match(r"^ {0,3}#{1,6}[ \t]+(.+)$", line) if not fence else None
        bold = _LAB_BOLD_HEADING.match(line) if not fence and not subheading else None
        if bold and _LAB_TARGET_HEADING.match(_heading_ordinals(normalized(bold[1]))):
            yield normalized(heading), normalized("\n".join(body))
            heading, body = bold[1], [bold[2]]
            continue
        label = normalized(subheading[1]) if subheading else ""
        heading_depth = len(line.lstrip().split(maxsplit=1)[0]) if subheading else 0
        target = bool(subheading and _LAB_TARGET_HEADING.match(_heading_ordinals(label)))
        if subheading and not _QUESTION_GUIDANCE_LABEL.fullmatch(label) and (target or not depth or heading_depth <= depth):
            yield normalized(heading), normalized("\n".join(body))
            heading, body = subheading[1], []
            depth = heading_depth
        else:
            body.append(line)
    if section.code:
        body.extend(["~~~", section.code, "~~~"])
    body.extend(entry.get("explanation", "") for entry in section.walkthrough)
    yield normalized(heading), normalized("\n".join(body))



@dataclass(frozen=True)
class CoverageResult:
    requirement: Requirement
    status: Literal["covered", "partial", "missing"]
    reason: str | None = None
    section_heading: str | None = None

    @property
    def diagnostic(self) -> str | None:
        return COVERAGE_REASONS.get(self.reason) if self.reason else None


COVERAGE_REASONS = {
    "NOT_MENTIONED": "No matching heading or explicit reference was found.",
    "SOURCE_UNAVAILABLE": "The indexed source chunk was outside the supplied evidence.",
    "SOURCE_ANCHOR_MISSING": "The checker could not match enough source terms.",
    "INSUFFICIENT_DETAIL": "The matching passage lacks procedural or explanatory signals.",
    "ARTIFACT_MISSING": "The matching appendix lacks a fenced block with recognized script statements.",
    "UNRECOGNIZED_STRUCTURE": "The requirement appears without its own recognizable block.",
}


def evaluate_coverage(items: list[Requirement], sections, evidence_ids: set[str], *, lab=False) -> list[CoverageResult]:
    texts = [(normalized(section.heading), normalized("\n".join((
        section.content, section.code, *(entry.get("explanation", "") for entry in section.walkthrough),
    )))) for section in sections]
    blocks = [block for section in sections for block in _lab_blocks(section)] if lab else []

    def evaluate(item):
        dedicated = lab and item.kind in {"screenshot", "question", "appendix"}
        candidates = [
            (heading, body) for heading, body in (blocks if dedicated else texts)
            if _mention(item, heading if dedicated else f"{heading}\n{body}")
            or _installation_heading_matches(item, heading)
        ]
        mentioned = bool(candidates) or any(_mention(item, f"{heading}\n{body}") for heading, body in texts)
        if item.chunk_id not in evidence_ids:
            return CoverageResult(item, "partial" if mentioned else "missing", "SOURCE_UNAVAILABLE")
        if not candidates:
            return CoverageResult(item, "partial" if mentioned else "missing",
                                  "UNRECOGNIZED_STRUCTURE" if mentioned else "NOT_MENTIONED")
        reason = "INSUFFICIENT_DETAIL"
        for _, body in candidates:
            if not _substantive(item, body, lab_question=dedicated and item.kind == "question"):
                continue
            if dedicated and item.kind == "screenshot" and not re.search(_LAB_GUIDANCE["screenshot"], body):
                continue
            if not _anchored(item, body):
                reason = "SOURCE_ANCHOR_MISSING"
                continue
            needs_script = re.search(r"\bscript\b|\.(?:py|ps1|sh)\b", normalized(item.evidence_anchor))
            if dedicated and item.kind == "appendix" and needs_script:
                fenced = re.findall(r"(?ms)^[ \t]*(\x60{3,}|~{3,})[^\n]*\n(.*?)^[ \t]*\1[ \t]*$", body)
                if not any(re.search(r"(?m)^[ \t]*(?:(?:def|class|with|for|while)\s+\S+"
                                     r"|\$?\w+\s*=|\w+(?:\.\w+)*\s*\()", code)
                           for _, code in fenced):
                    reason = "ARTIFACT_MISSING"
                    continue
            return CoverageResult(item, "covered")
        matching_heading = next((section.heading for section in sections
                                 if normalized(section.heading) == candidates[0][0]), None)
        return CoverageResult(item, "partial", reason, matching_heading)

    return [evaluate(item) for item in items]


def missing_requirements(items: list[Requirement], sections, evidence_ids: set[str], *, lab=False) -> list[Requirement]:
    return [result.requirement for result in evaluate_coverage(items, sections, evidence_ids, lab=lab)
            if result.status != "covered"]
