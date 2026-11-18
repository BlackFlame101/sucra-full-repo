"""Build a scoped, indexed evidence packet and recover source notebook cells."""
from __future__ import annotations

import ast
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
import re

from agents.explain_document_scope import DocumentIntent, Section, SourceSpan, resolve_document_scope, stable_id
from models.educational_document import Citation, CodeCell
from rag.explain_checklist import page_furniture
from rag.explain_preparation import indexed_anchors
from rag.unit_map import _page_rows

_PY_START = re.compile(r"^(?:from [\w.]+ import\b|import [\w.]+|[a-z_]\w*(?:,\s*[a-z_]\w*)*\s*=\s*[^=]"
                       r"|[a-z_]\w*(?:\.[a-z_]\w*)+\(|(?:print|display)\()", re.I)
_SHELL_START = re.compile(r"^(?:cd |mkdir |new-item |copy-item |get-content |pip install |python (?:-m |[\w.-]+\.py)"
                          r"|&\s+\$|\.venv\\|\\?\.\\)", re.I)
_CODE_PATH = re.compile(r"^\S+\.py$")
_PROGRAMMING_TASK = re.compile(
    r"\b(?:tester|test|impl[eé]menter|implement|entra[iî]ner|train|ajuster|fit)\b",
    re.I,
)
_CODE_IDENTIFIER = re.compile(r"\b(?:[a-z][a-z0-9]+[A-Z]\w*|[a-z]\w*_\w+)\b")


def checksum(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LayoutLine:
    page: int
    start: int
    text: str
    x: float
    y: float
    pitch: float
    size: float


@dataclass(frozen=True)
class PlannedSection:
    section: Section
    citations: tuple[Citation, ...]
    cells: tuple[CodeCell, ...]
    requirement_id: str | None
    source_issues: tuple[str, ...]
    requires_solution_cell: bool


def _line_geometry(page, number):
    text = page["text"]
    astral = [i for i, char in enumerate(text) if ord(char) > 0xffff]
    astral_offsets = [i + extra for extra, i in enumerate(astral)]
    items = defaultdict(list)
    for offset, count, x, y, width, size in page.get("evidence", {}).get("items", ()):
        start = offset - bisect_left(astral_offsets, offset)
        end = offset + count - bisect_left(astral_offsets, offset + count)
        if end > start and size > 0:
            items[start].append((x, y, width / count, size))
    for start, value, _ in _page_rows(page):
        if items[start]:
            x, y, pitch, size = items[start][0]
            yield LayoutLine(number, start, value, x, y, pitch, size)
        else:
            yield LayoutLine(number, start, value, 0, 0, 0, 0)


def _fits_code_font(line, start):
    # Courier-family PDF code has a repeated character advance. Body text and
    # proportional snippets should not be guessed into a runnable cell.
    return (line.pitch > 0 and abs(line.pitch - start.pitch) / start.pitch < .045
            and abs(line.size - start.size) < .35)


def _cell_text(lines):
    origin = min(line.x for line in lines)
    result = []
    for index, line in enumerate(lines):
        aligned = (line.x - origin) / line.pitch
        width = round(aligned)
        if abs(aligned - width) > .2 or not 0 <= width <= 80:
            raise ValueError("Source code indentation cannot be verified.")
        if index and line.page == lines[index - 1].page and lines[index - 1].y - line.y > 1.6 * line.size:
            result.append("")
        result.append(" " * width + line.text)
    return "\n".join(result)


def _is_python(code):
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return False
    return bool(tree.body) and all(not isinstance(node, ast.Expr)
                                   or isinstance(node.value, (ast.Call, ast.Constant)) for node in tree.body)


def python_compile_issue(code):
    """Check compilation without executing the source or importing its dependencies."""
    try:
        compile(code, "<notebook cell>", "exec", dont_inherit=True)
    except (SyntaxError, ValueError) as error:
        return str(error)
    return None


def _source_cells(section, rows, covered, previous_cells):
    cells, issues = [], []
    group = []
    language = None

    def finish():
        if not group:
            return
        spans = [SourceSpan(line.page, line.start, line.start + len(line.text)) for line in group]
        try:
            if any(line.start + index not in covered[line.page] for line in group
                   for index, char in enumerate(line.text) if not char.isspace()):
                raise ValueError("Source code is absent from the verified index.")
            code = _cell_text(group)
            if language == "python" and not _is_python(code):
                raise ValueError("Source code does not form a complete Python cell.")
        except ValueError as error:
            issues.append(str(error))
            return
        cell_id = stable_id(section.section_id, "source", spans[0].page, spans[0].start)
        prior = cells[-1].cell_id if cells else previous_cells[-1].cell_id if previous_cells else None
        cells.append(CodeCell(cell_id=cell_id, section_id=section.section_id, origin="source", language=language,
                              code=code, checksum=checksum(code), source_spans=spans,
                              depends_on=[prior] if prior else [], verification="source_exact"))

    for line in rows:
        if group and _fits_code_font(line, group[0]) and (
            line.page == group[-1].page + 1 or (
                line.page == group[-1].page and 0 < group[-1].y - line.y <= line.size * 3
            )
        ) and not _CODE_PATH.fullmatch(line.text) and not re.match(r"^(?:RÉSULTAT ATTENDU|EXPECTED OUTPUT)\b", line.text):
            group.append(line)
            continue
        if group:
            finish()
            group = []
        if not line.pitch or not .48 <= line.pitch / line.size <= .65:
            continue
        if _SHELL_START.match(line.text):
            language = "powershell"
        elif _PY_START.match(line.text):
            language = "python"
        else:
            continue
        group = [line]
    finish()
    return tuple(cells), tuple(dict.fromkeys(issues))


def prepare_document_scope(document_id, pages, positioned, indexed, intent: DocumentIntent):
    if not pages or any(not isinstance(page.get("text"), str) for page in pages):
        raise ValueError("The PDF text could not be verified.")
    sections, prerequisites = resolve_document_scope(document_id, pages, intent)
    covered = indexed_anchors(positioned, indexed)
    furniture = page_furniture(pages, set())
    rows = {i: [row for row in _line_geometry(page, i) if row.start not in furniture.get(i, {})]
            for i, page in enumerate(pages, 1)}
    result = []
    previous_cells = []
    retain_cells = intent.action in {"solve", "guide"} or intent.document_type == "practical_lab"
    required = intent.action == "solve" or intent.depth == "exhaustive"
    for section in sections:
        clips = []
        issues = []
        for span in section.spans:
            page_text = pages[span.page - 1]["text"]
            quote = page_text[span.start:span.end]
            if not quote.strip():
                continue
            if any(i not in covered[span.page] and not page_text[i].isspace() for i in range(span.start, span.end)):
                issues.append(f"PDF page {span.page} does not match the indexed source.")
                continue
            clips.append(Citation(citation_id=stable_id(document_id, span.page, span.start, span.end, checksum(quote)),
                                  span=span, quote=quote, checksum=checksum(quote)))
        scoped_rows = [line for span in section.spans for line in rows[span.page] if span.start <= line.start < span.end]
        executable = (section.target and section.target.kind in {"step", "exercise"}) or bool(re.match(
            r"^(?:annex|annexe|appendix) a\b", section.title, re.I
        ))
        cells, code_issues = (_source_cells(section, scoped_rows, covered, previous_cells)
                              if retain_cells and executable else ((), ()))
        issues.extend(code_issues)
        previous_cells.extend(cells)
        if not clips:
            issues.append("No matching source excerpt for this section.")
        # Section-level IDs track learning obligations independently of the
        # number of generated headings and of the number of provider calls.
        item = stable_id(section.section_id, "requirement") if required else None
        source_text = "\n".join(line.text for line in scoped_rows)
        # An explicit programming task with source identifiers needs a
        # solution cell in addition to the original course cells.
        requires_solution = bool(
            intent.action == "solve" and section.target and section.target.kind == "exercise"
            and _PROGRAMMING_TASK.search(source_text) and _CODE_IDENTIFIER.search(source_text)
        )
        result.append(PlannedSection(section, tuple(clips), cells, item, tuple(dict.fromkeys(issues)), requires_solution))
    return result, prerequisites
