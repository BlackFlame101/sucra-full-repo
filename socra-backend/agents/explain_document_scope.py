"""Intent and source boundaries for version-three educational documents."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re

from agents.explain_intent import classify_intent
from agents.explain_tasks import _fold
from rag.explain_checklist import page_furniture
from rag.unit_map import _page_headings, _page_rows

_NUMBER = r"(?:\d+(?:\.\d+)*|[ivxlcdm]+)"
_TARGET = re.compile(rf"\b(partie|part|chapitre|chapter|exercice|exercise|etape|step|question)\b"
                     rf"\s+(?:n[°ºo]\s*|#\s*)?({_NUMBER}|[a-z])\b", re.I)
_EXCLUSION = re.compile(r"\b(?:sans|sauf|exclure|exclus|ignore|skip|except|without|excluding)\b")
_LABELS = {"partie": "part", "part": "part", "chapitre": "chapter", "chapter": "chapter",
           "exercice": "exercise", "exercise": "exercise", "etape": "step", "step": "step",
           "question": "question"}
_ACTIONS = (
    ("correct", r"\b(?:corrige|corriger|debogue|debug|correct|fix)\b"),
    ("guide", r"\b(?:guide|guidance|aide|help|hints?|indices)\b"),
    ("solve", r"\b(?:resous|resoudre|solve|reponds|answer|termine|fais|realise|solution complete"
              r"|complete solution)\b|^(?:please )?complete\b"),
    ("revise", r"\b(?:fiche(?:s)? de revision|revision sheet|study sheet|study guide|prepare.*examen)\b"),
    ("summarize", r"\b(?:resume|summarize|summarise|summary)\b"),
)
_NUMBERED_LESSON = re.compile(r"^[IVXLCDM]+\.\d+(?:\.\d+)*\s+\S", re.I)
_ABBREVIATED_CHAPTER = re.compile(r"^chap\.\s*(\d+)\s*[-–—]", re.I)
_REQUIREMENT = re.compile(r"^(?:a analyser|analysis questions?|questions? \d+|q\s*\d+[.)]"
                          r"|capture \d+\s*:|annexe [a-z]\s*:|annex [a-z]\s*:|livrables?\b)")


class ScopeClarification(ValueError):
    """A request needs an explicit document or a unique source boundary."""


def _number(value: str, kind: str) -> str:
    value = value.casefold()
    if value.isdecimal():
        return str(int(value))
    if kind not in {"part", "chapter"} or not re.fullmatch(r"[ivxlcdm]+", value):
        return value
    values = dict(i=1, v=5, x=10, l=50, c=100, d=500, m=1000)
    return str(sum(-values[c] if i + 1 < len(value) and values[c] < values[value[i + 1]]
                   else values[c] for i, c in enumerate(value)))


@dataclass(frozen=True)
class Target:
    kind: str
    number: str


@dataclass(frozen=True)
class DocumentIntent:
    action: str
    document_type: str
    depth: str
    scope: str
    language: str
    audience: str
    targets: tuple[Target, ...]
    exclusions: tuple[Target, ...]
    max_points: int | None
    max_sentences: int | None


def classify_document_request(message: str, language=None, explicit_language=False, source_name="") -> DocumentIntent:
    text = _fold(message)
    adaptive = classify_intent(message, language, explicit_language, [source_name] if source_name else ())
    positive = _EXCLUSION.split(text, maxsplit=1)[0]
    if re.search(r"\b(?:sans (?:resoudre|donner (?:la solution|les reponses))"
                 r"|without (?:solving|giving (?:the solution|answers))|hints only|indices seulement)\b", text):
        action = "guide"
    else:
        action = next((action for action, pattern in _ACTIONS
                       if action != "guide" and re.search(pattern, positive)), None)
        action = action or ("guide" if re.search(dict(_ACTIONS)["guide"], positive) else "explain")

    def targets(value):
        return tuple(dict.fromkeys(Target(_LABELS[m[1]], _number(m[2], _LABELS[m[1]]))
                                   for m in _TARGET.finditer(value)))

    requested = targets(positive)
    excluded = targets(text[len(positive):])
    whole = adaptive.scope == "whole_document" or bool(re.search(
        r"\b(?:(?:ce|le) (?:tp|td)|this (?:lab|assignment)|(?:the|entire) (?:lab|assignment)"
        r"|complete tp|everything|tout le document)\b", positive))
    scope = requested[0].kind if requested else "whole_document" if whole else "concept"
    lab = adaptive.document_kind == "lab" or bool(re.search(
        r"\b(?:tp\d*|lab|travaux pratiques|knime|mllib|spark)\b", text + " " + _fold(source_name).replace("_", " ")))
    kind = ("revision_sheet" if action == "revise" else "practical_lab" if lab else
            "exercise_solution" if action == "solve" or scope in {"exercise", "question"} else "lesson")
    depth = ("brief" if action == "summarize" or adaptive.max_sentences is not None else
             "exhaustive" if (whole and not requested) or re.search(r"\b(?:everything|exhaustive|sans omettre|sans rien)\b", text) else
             "detailed" if action == "solve" or re.search(r"\b(?:detail\w*|approfondi\w*)\b", text) else "standard")
    return DocumentIntent(action, kind, depth, scope, adaptive.language, adaptive.level,
                          requested, excluded, adaptive.max_points, adaptive.max_sentences)


@dataclass(frozen=True)
class SourceSpan:
    page: int
    start: int
    end: int


@dataclass(frozen=True)
class Section:
    section_id: str
    title: str
    label: str
    target: Target | None
    parent_id: str | None
    spans: tuple[SourceSpan, ...]


@dataclass(frozen=True)
class Prerequisite:
    section_id: str
    title: str
    page: int


def stable_id(*fields):
    return sha256("\0".join(map(str, fields)).encode()).hexdigest()[:24]


def _headings(pages):
    matches = []
    furniture = page_furniture(pages, set())
    chapters = set()
    for page, data in enumerate(pages, 1):
        lines = [(start, value, layout) for start, value, layout in _page_rows(data)
                 if start not in furniture.get(page, {})]
        divider = next((row for row in _page_headings(data, lines, set()) if row[3] == "transition"), None)
        for i, (start, value, layout) in enumerate(lines):
            if not value:
                continue
            folded = _fold(value)
            label, target = value, None
            match = _TARGET.match(folded)
            if abbreviated_chapter := _ABBREVIATED_CHAPTER.match(value):
                target = Target("chapter", abbreviated_chapter[1])
                if target in chapters:
                    continue
                chapters.add(target)
            elif match:
                kind = _LABELS[match[1]]
                tail = value[match.end():].strip(" .:–—-")
                # Standalone part dividers appear in slide decks and in page
                # headings that wrap. Prefer the following title to a nav label.
                if kind == "part" and not tail:
                    if layout and layout[1] < 20:
                        continue
                    nearby = (divider[2] if divider and divider[1].casefold() == match[2] else
                              lines[i + 1][1] if i + 1 < len(lines) else "")
                    if not nearby and page < len(pages):
                        nearby = next((row for position, row, _ in _page_rows(pages[page])
                                       if position not in furniture.get(page + 1, {})), "")
                    if not nearby or _TARGET.match(_fold(nearby)) or len(nearby) > 140:
                        continue
                    label = f"{value} — {nearby}"
                target = Target(kind, _number(match[2], kind))
            elif question := re.match(r"^q\s*(\d+)[.)]", folded):
                target = Target("question", question[1])
            elif _NUMBERED_LESSON.match(value) or _REQUIREMENT.match(folded):
                pass
            else:
                continue
            matches.append((page, start, label, target, value))
    return matches


def _spans(pages, start, end):
    for page in range(start[0], end[0] + 1):
        data = pages[page - 1]
        text = data["text"]
        left = start[1] if page == start[0] else 0
        right = end[1] if page == end[0] else len(text)
        meaningful = [(offset, value) for offset, value, layout in _page_rows(data)
                      if left <= offset < right and (
                          not layout or not data.get("height") or .065 < layout[0] / data["height"] < .935
                          or offset == start[1] and page == start[0])]
        if meaningful:
            yield SourceSpan(page, meaningful[0][0], meaningful[-1][0] + len(meaningful[-1][1]))


def resolve_document_scope(document_id, pages, intent: DocumentIntent) -> tuple[list[Section], list[Prerequisite]]:
    headings = _headings(pages)
    last = len(pages), len(pages[-1]["text"])
    ranges = [(1, 0, "Introduction", None, "")]
    ranges.extend(headings)
    hierarchy = []
    sections = []
    # Roman outer parts can contain their own Arabic numbered practical parts.
    part_spellings = {_TARGET.match(_fold(value))[2] for _, _, _, target, value in headings
                      if target and target.kind == "part"}
    nested_arabic = any(s.isdecimal() for s in part_spellings) and any(not s.isdecimal() for s in part_spellings)
    for i, (page, start, title, target, value) in enumerate(ranges):
        kind = target.kind if target else ("analysis" if _REQUIREMENT.match(_fold(value)) else "topic")
        level = {"chapter": 0, "part": 1, "exercise": 3, "step": 3, "question": 4, "analysis": 4, "topic": 3}[kind]
        if nested_arabic and kind == "part" and _TARGET.match(_fold(value))[2].isdecimal():
            level = 2
        while hierarchy and hierarchy[-1][0] >= level:
            hierarchy.pop()
        parent = hierarchy[-1][1] if hierarchy else None
        end = ranges[i + 1][:2] if i + 1 < len(ranges) else last
        spans = tuple(_spans(pages, (page, start), end))
        if not spans:
            continue
        sid = stable_id(document_id, parent, kind, title, page, start)
        label = re.split(r"\s*[:–—]\s*", value, 1)[0] if value else title
        section = Section(sid, title, label, target, parent, spans)
        sections.append(section)
        if kind in {"chapter", "part", "exercise", "step"}:
            hierarchy.append((level, sid))

    def descendants(section):
        scope = {section.section_id}
        for child in sections:
            if child.parent_id in scope:
                scope.add(child.section_id)
        return scope

    def match(target, eligible):
        candidates = [section for section in eligible if section.target == target]
        if len(candidates) != 1:
            if intent.language == "French":
                raise ScopeClarification(f"Quel passage désigne « {target.kind} {target.number} » dans ce PDF ?")
            raise ScopeClarification(f"Which section does “{target.kind} {target.number}” refer to in this PDF?")
        return candidates[0]

    selected = {s.section_id for s in sections}
    for kind in ("chapter", "part", "step", "exercise", "question"):
        targets = [target for target in intent.targets if target.kind == kind]
        if targets:
            eligible = [s for s in sections if s.section_id in selected]
            selected &= set().union(*(descendants(match(target, eligible)) for target in targets))
    for target in intent.exclusions:
        selected -= descendants(match(target, sections))
    prerequisites = [
        Prerequisite(s.section_id, s.title, s.spans[0].page) for s in sections
        if s.section_id not in selected and s.target == Target("step", "0") and s.target not in intent.exclusions
    ] if intent.document_type == "practical_lab" and intent.action in {"solve", "guide"} else []
    scoped = [section for section in sections if section.section_id in selected]
    if not scoped:
        raise ScopeClarification("No source section matches the requested scope.")
    return scoped, prerequisites
