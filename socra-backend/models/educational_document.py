"""Versioned, canonical document stored in Explain assistant message metadata."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agents.explain_document_scope import DocumentIntent, Prerequisite, SourceSpan


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SourceIdentity(Contract):
    document_id: str
    filename: str
    source_hash: str
    index_generation: int


class Citation(Contract):
    citation_id: str
    span: SourceSpan
    quote: str = Field(min_length=1)
    checksum: str


class CodeCell(Contract):
    cell_id: str
    section_id: str
    origin: Literal["source", "generated"]
    language: str
    code: str
    checksum: str
    source_spans: list[SourceSpan]
    depends_on: list[str]
    verification: Literal["syntax_valid", "source_exact", "unverified"]
    corrects_cell_id: str | None = None


class DocumentSection(Contract):
    section_id: str
    title: str
    parent_id: str | None
    markdown_start: int
    markdown_end: int


class Coverage(Contract):
    requirement_id: str
    section_id: str
    state: Literal["missing", "candidate", "reviewed"]
    citation_ids: list[str] = Field(default_factory=list)
    evidence: str | None = None


class QualifiedOutput(Contract):
    section_id: str
    text: str
    status: Literal["expected", "illustrative", "environment_dependent", "verified"]
    receipt: str | None = None


ReviewCriterion = Literal["scope_completeness", "technical_correctness", "pedagogical_depth", "reasoning",
                          "solution_completeness", "code_quality", "revision_usefulness", "source_grounding"]


class CriterionScore(Contract):
    criterion: ReviewCriterion
    score: int = Field(ge=0, le=3)
    section_id: str
    evidence: str = Field(max_length=450)
    reason: str = Field(min_length=12, max_length=320)


class ReviewReceipt(Contract):
    model: str
    draft_hash: str
    score: int = Field(ge=0, le=3)
    good: bool
    findings: list[str]
    rubric: list[CriterionScore] = Field(default_factory=list)


class Verification(Contract):
    draft_hash: str
    passed: bool
    findings: list[str]
    reviewer: ReviewReceipt | None = None


class EducationalDocument(Contract):
    schema_version: Literal[3] = 3
    format: Literal["educational_document"] = "educational_document"
    document_id: str
    revision_id: str
    parent_revision_id: str | None = None
    state: Literal["draft", "partial", "review_pending", "approved", "superseded"]
    title: str
    summary: str
    document_markdown: str
    intent: DocumentIntent
    source: SourceIdentity
    ordered_targets: list[str]
    prerequisites: list[Prerequisite]
    remaining: list[str]
    sections: list[DocumentSection]
    citations: list[Citation]
    code_cells: list[CodeCell]
    outputs: list[QualifiedOutput]
    coverage: list[Coverage]
    verification: Verification
