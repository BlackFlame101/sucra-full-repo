"""Validate complete Markdown sections against their source and review evidence."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, get_args

from pydantic import Field

from agents.explain_document_scope import stable_id
from agents.explain_verifier import Anchor, Block, Claim, verify_unit
from agents.structured_output import has_control_characters
from models.educational_document import CodeCell, Contract, Coverage, CriterionScore, QualifiedOutput, ReviewCriterion
from rag.explain_document_source import PlannedSection, _is_python, checksum, python_compile_issue

_CITATION = re.compile(r"\[\[([^\]\n]+)\]\]")
_CELL = re.compile(r"(?m)^ *\{\{cell:([^\}\n]+)\}\} *$")
_FENCE = re.compile(r"^\s{0,3}(\x60{3,}|~{3,})([^\n]*)$")
_BLOCK_HEADING = re.compile(r"(?m)^ {0,3}#{1,2}(?:\s|$)")
_CORRECTION = re.compile(r"(?:python|py) corrects:([a-f0-9]{24})")
_EXECUTION_ASSERTION = re.compile(r"\b(?:we ran|I ran|I executed|we executed|j'ai exécuté|"
                                  r"nous avons exécuté)\b", re.I)
_UNFINISHED = re.compile(r"\b(?:TODO|FIXME|your code here|votre code ici|à compléter)\b", re.I)
_QUALIFIERS = {
    "expected": re.compile(r"attendu|expected", re.I),
    "illustrative": re.compile(r"illustrat|exemple|example|hypoth", re.I),
    "environment_dependent": re.compile(r"environnement|environment|locally|dépend|depends", re.I),
}


class ClaimDraft(Contract):
    quote: str = Field(min_length=12, max_length=1600)
    citations: list[str] = Field(min_length=1, max_length=12)


class OutputDraft(Contract):
    text: str = Field(min_length=12, max_length=1600)
    status: Literal["expected", "illustrative", "environment_dependent", "verified"]


class DraftSection(Contract):
    section_id: str
    title: str = Field(min_length=1, max_length=180)
    markdown: str = Field(min_length=1, max_length=40000)
    claims: list[ClaimDraft] = Field(min_length=1, max_length=64)
    outputs: list[OutputDraft] = Field(default_factory=list, max_length=16)


class DraftBatch(Contract):
    sections: list[DraftSection] = Field(min_length=1, max_length=100)


class ReviewEvidence(Contract):
    requirement_id: str
    quote: str = Field(min_length=30, max_length=2000)


class DocumentReview(Contract):
    draft_hash: str
    rubric: list[CriterionScore] = Field(min_length=8, max_length=8)
    findings: list[str] = Field(max_length=30)
    evidence: list[ReviewEvidence] = Field(max_length=120)


@dataclass(frozen=True)
class CheckedSection:
    draft: DraftSection
    markdown: str
    cells: tuple[CodeCell, ...]
    coverage: Coverage | None
    outputs: tuple[QualifiedOutput, ...]
    problems: tuple[str, ...]


def _markdown_parts(markdown):
    """Yield exact top-level fenced cells and prose without parsing fence contents."""
    segment = []
    opening = None
    for line in markdown.splitlines(keepends=True):
        value = line.rstrip("\n")
        match = _FENCE.match(value)
        if opening:
            if match and match[1][0] == opening[0][0] and len(match[1]) >= len(opening[0]) and not match[2].strip():
                yield opening[1], "".join(segment).removesuffix("\n")
                segment = []
                opening = None
            else:
                segment.append(line)
        elif match:
            if segment:
                yield None, "".join(segment)
            segment = []
            opening = match[1], match[2].strip() or "text"
        else:
            segment.append(line)
    if opening:
        raise ValueError("Unclosed code fence.")
    if segment:
        yield None, "".join(segment)


def _fenced(cell):
    longest = max((len(run) for run in re.findall(r"~+", cell.code)), default=0)
    fence = "~" * max(3, longest + 1)
    return f"{fence}{cell.language} cell:{cell.cell_id}\n{cell.code}\n{fence}\n"


def _unique_quote(text, quote):
    return bool(quote.strip()) and text.count(quote) == 1


def check_section(draft: DraftSection, planned: PlannedSection, pages: dict[int, str], prior_cells=()):
    """Keep verifiable text and cells from a complete provider section."""
    if draft.section_id != planned.section.section_id or has_control_characters(draft.model_dump()):
        raise ValueError("Invalid document section identity or text.")
    if "\n" in draft.title or "\r" in draft.title or _CITATION.search(draft.title):
        raise ValueError("Invalid section title.")
    markdown = draft.markdown.replace("\r\n", "\n")
    parts = list(_markdown_parts(markdown))
    prose = "\n".join(text for language, text in parts if language is None)
    if _BLOCK_HEADING.search(prose) or _EXECUTION_ASSERTION.search(prose):
        raise ValueError("Duplicate document headings or an unverified execution claim.")
    if any(line.lstrip().startswith(("<script", "<iframe", "<img", "<object")) for line in prose.splitlines()):
        raise ValueError("Unexpected raw document HTML.")

    valid = {ref.citation_id: ref for ref in planned.citations}
    markers = set(_CITATION.findall(prose))
    if not markers or not markers <= valid.keys():
        raise ValueError("Missing or unknown scoped citation.")
    for ref in valid.values():
        span = ref.span
        if (pages.get(span.page, "")[span.start:span.end] != ref.quote
                or checksum(ref.quote) != ref.checksum):
            raise ValueError("The cited source no longer matches the indexed evidence.")

    source_by_id = {cell.cell_id: cell for cell in planned.cells}
    defective = {cell.cell_id for cell in planned.cells if cell.language == "python" and python_compile_issue(cell.code)}
    corrected = set()
    code_order, parts_out, cells = [], [], []
    prior = list(prior_cells)
    for language, text in parts:
        if language is None:
            def insert(match):
                cid = match[1]
                if cid not in source_by_id or cid in code_order:
                    raise ValueError("Unknown or duplicate original code-cell marker.")
                cell = source_by_id[cid]
                code_order.append(cid)
                cells.append(cell)
                prior.append(cell)
                return _fenced(cell).rstrip("\n")
            parts_out.append(_CELL.sub(insert, text))
            continue
        correction = _CORRECTION.fullmatch(language)
        correction_id = correction[1] if correction else None
        if correction:
            if correction_id not in code_order or correction_id in corrected:
                raise ValueError("A correction needs an earlier original cell in the same section.")
            corrected.add(correction_id)
            language = "python"
        language = {"py": "python", "plain": "text", "plaintext": "text"}.get(language, language)
        if language == "text":
            if not any(item.text in text and item.status != "verified" for item in draft.outputs):
                raise ValueError("Plain-text output must be qualified.")
            parts_out.append(f"~~~text\n{text}\n~~~\n")
            continue
        if language != "python":
            raise ValueError("Generated code requires a supported syntax verifier.")
        if (not _is_python(text) or python_compile_issue(text) or _UNFINISHED.search(text)
                or re.search(r"(?m)^\s*(?:\.\.\.|pass)\s*$", text)):
            raise ValueError("Generated Python cell is incomplete or invalid.")
        if any(checksum(text) == cell.checksum for cell in (*prior, *planned.cells)):
            raise ValueError("Duplicate code cell.")
        cell = CodeCell(cell_id=stable_id(draft.section_id, "solution", len(cells)), section_id=draft.section_id,
                        origin="generated", language="python", code=text, checksum=checksum(text), source_spans=[],
                        depends_on=[prior[-1].cell_id] if prior else [], verification="syntax_valid",
                        corrects_cell_id=correction_id)
        cells.append(cell)
        prior.append(cell)
        parts_out.append(_fenced(cell))
    if code_order != list(source_by_id):
        raise ValueError("Original source cells are missing or out of order.")
    if defective - corrected:
        raise ValueError("A detected Python source error requires a separate corrected cell.")
    if planned.requires_solution_cell and not any(cell.origin == "generated" and not cell.corrects_cell_id for cell in cells):
        raise ValueError("This programming exercise requires a complete solution cell.")

    problems = list(planned.source_issues)
    stripped = _CITATION.sub("", _CELL.sub("", prose))
    # Each claim must name exact visible wording and link it to an adjacent
    # trusted marker. Numeric support and arithmetic use the existing verifier.
    bound = set()
    anchors = tuple(Anchor(r.span.page, r.span.start, r.span.end, r.quote) for r in valid.values())
    anchor_ids = {cid: i for i, cid in enumerate(valid, 1)}
    span_start = planned.section.spans[0]
    span_end = planned.section.spans[-1]
    unit = {"logical_id": draft.section_id, "kind": "concept",
            "start": (span_start.page, span_start.start), "end": (span_end.page, span_end.end)}
    for item in draft.claims:
        ids = set(item.citations)
        if len(ids) != len(item.citations) or not ids <= markers or not _unique_quote(prose, item.quote):
            raise ValueError("A claim requires one exact quote and in-scope sources.")
        offset = prose.index(item.quote) + len(item.quote)
        trailing = re.match(r"(?:[ \t]*\[\[[^\]\n]+\]\])+", prose[offset:])
        attached = _CITATION.findall(trailing[0]) if trailing else []
        if len(attached) != len(ids) or ids != set(attached):
            raise ValueError("Claim markers must appear next to their exact text.")
        bound.update(ids)
        checks = verify_unit(unit, [Block("claim", "explanation", item.quote, "derived", (
            Claim(0, len(item.quote), tuple(anchor_ids[cid] for cid in item.citations)),
        ))], pages=pages, sources=anchors, legacy=False)
        problems.extend(f"{finding.code}: {finding.detail}" for finding in checks
                        if finding.code not in {"missing_block", "claim_support_unchecked"})
    if markers != bound:
        raise ValueError("Every citation marker must belong to a checked claim.")

    checked = verify_unit(unit, [Block("section", "explanation", stripped, "derived")],
                          pages=pages, sources=anchors, legacy=True)
    problems.extend(f"{finding.code}: {finding.detail}" for finding in checked)

    outputs = []
    for item in draft.outputs:
        if (item.status == "verified" or not _unique_quote(markdown, item.text)
                or not _QUALIFIERS[item.status].search(item.text)):
            raise ValueError("Output must be visibly qualified and cannot claim execution.")
        outputs.append(QualifiedOutput(section_id=draft.section_id, text=item.text, status=item.status))
    coverage = None
    if planned.requirement_id:
        coverage = Coverage(requirement_id=planned.requirement_id, section_id=draft.section_id,
                            state="candidate", citation_ids=sorted(markers))
    return CheckedSection(draft, "".join(parts_out).strip(), tuple(cells), coverage,
                          tuple(outputs), tuple(dict.fromkeys(problems)))


def apply_independent_review(review: DocumentReview, draft_hash: str, checked: dict[str, CheckedSection]):
    """Confirm exact, substantive reviewer evidence against the same immutable draft."""
    if review.draft_hash != draft_hash:
        raise ValueError("Independent review was bound to a different revision.")
    if {item.criterion for item in review.rubric} != set(get_args(ReviewCriterion)):
        raise ValueError("Independent review must rate each educational criterion once.")
    findings = list(review.findings)
    for item in review.rubric:
        row = checked.get(item.section_id)
        if row is None or (item.evidence and not _unique_quote(row.markdown, item.evidence)):
            raise ValueError("Rubric evidence must identify one exact passage in the reviewed section.")
        if item.score >= 2 and len(re.findall(r"\b\w+\b", item.evidence)) < 4:
            raise ValueError("A passing score requires concrete evidence from the section.")
        if item.score < 2:
            findings.append(f"{item.section_id}: {item.criterion} — {item.reason}")
    by_requirement = {row.coverage.requirement_id: row for row in checked.values() if row.coverage}
    evidence = {}
    for item in review.evidence:
        row = by_requirement.get(item.requirement_id)
        if (not row or item.requirement_id in evidence or not _unique_quote(row.draft.markdown, item.quote)
                or not re.search(r"[.!?](?:\s|$)", item.quote)
                or len(re.findall(r"\b\w+\b", item.quote)) < 8):
            raise ValueError("Independent review did not quote substantive, unique solution evidence.")
        evidence[item.requirement_id] = item.quote
    missing = by_requirement.keys() - evidence.keys()
    findings.extend(f"{row.draft.section_id}: No substantive review evidence for the requested task."
                    for rid, row in by_requirement.items() if rid in missing)
    return evidence, list(dict.fromkeys(findings))
