"""Phase 2 deterministic checks over supplied evidence and structured answers."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from agents.explain_arithmetic import arithmetic, displayed_equations, numeric_array
from agents.explain_tasks import _fold

_NUMBER = re.compile(r"(?<![\w.,])[+−-]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d+)?(?!\w|[.,]\d)")
_PART = re.compile(r"(?:\b(?:partie|part)\s+([ivxlcdm]+)\s*(?:[=:–—-]|est\s+|is\s+)\s*|\b([ivxlcdm]+)\.\s+)([^,;.!?\n]+)", re.I)
_HYPOTHETICAL = re.compile(r"\b(?:imaginons|supposons|hypothétique|fictif|imagine|suppose|hypothetical)\b", re.I)
_DIRECTION = re.compile(r"\b(augmente|hausse|diminue|baisse|increase[sd]?|decrease[sd]?|rose|fell)\b")
_NUMERIC_DIRECTION = re.compile(rf"(?:\bde\s+|\bfrom\s+)({_NUMBER.pattern})\s+(?:à|to|vers)\s+({_NUMBER.pattern})", re.I)
_CLAUSE = re.compile(r"(?:\d[.,](?=\d)|[^;.!?\n])+")
_COMPARISON_SEPARATOR = re.compile(r"\b(?:contre|versus|vs\.?|tandis que)\s+|,(?=\s)", re.I)

CONTRACTS = {
    "concept": ("explanation", "intuition", "source_example", "takeaway"),
    "derivation": ("given", "ordered_steps", "result", "interpretation"),
    "worked_calculation": ("given_values", "formula", "substitution", "result", "interpretation"),
    "comparison": ("criteria", "table", "interpretation", "trade_off"),
    "rule_examples": ("rule", "sourced_examples", "common_error"),
    "figure_walkthrough": ("what_it_shows", "how_to_read", "specific_reading", "takeaway"),
    "exercise": ("problem", "method", "working", "final_answer", "verification"),
    "lab_step": ("action", "command_or_ui", "expected_result", "checkpoint"),
    "research_finding": ("evidence", "interpretation", "limitations"),
}
NON_TEACHING = {"non_teaching", "transition", "front_matter", "summary"}
_SPLIT_WORD = re.compile(r"\b(?:intellige\s+nce|ambitie\s+use|professionne\s+lles)\b", re.I)


def evidence_lookup(text):
    """Normalize layout whitespace and attested split words, retaining original offsets."""
    skipped = {i for match in _SPLIT_WORD.finditer(text) for i in range(*match.span()) if text[i].isspace()}
    chars, spans = [], []
    for i, char in enumerate(text):
        if i in skipped:
            continue
        if char.isspace() and chars and chars[-1] == " ":
            spans[-1] = (spans[-1][0], i + 1)
            continue
        chars.append(" " if char.isspace() else char)
        spans.append((i, i + 1))
    return "".join(chars), spans


def _wording(text):
    text = _SPLIT_WORD.sub(lambda match: "".join(match[0].split()), text)
    return " ".join(re.findall(r"[^\W_]+", _fold(text)))


def _includes(text, phrase):
    return bool(phrase and f" {phrase} " in f" {text} ")


def decimal_value(text):
    if not _NUMBER.fullmatch(text):
        raise ValueError("unsupported numeric notation")
    try:
        return Decimal(re.sub(r"\s", "", text).replace("−", "-").replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("invalid number") from exc


def _numbers(text):
    return {decimal_value(match[0]) for match in _NUMBER.finditer(text)}


@dataclass(frozen=True)
class Anchor:
    page: int
    start: int
    end: int
    quote: str = ""


@dataclass(frozen=True)
class Fact:
    label_path: tuple[str, ...]
    value: str
    anchor: Anchor


@dataclass(frozen=True)
class ChecklistItem:
    item_id: str
    anchors: tuple[Anchor, ...]
    phrases: tuple[str, ...] = ()
    facts: tuple[Fact, ...] = ()
    block_kinds: tuple[str, ...] = ()
    importance: str = "essential"


@dataclass(frozen=True)
class Claim:
    start: int
    end: int
    source_indexes: tuple[int, ...]


@dataclass(frozen=True)
class Calculation:
    expected: str | list
    expression: str = ""
    operation: str = ""
    arrays: tuple = ()


@dataclass(frozen=True)
class Block:
    block_id: str
    kind: str
    text: str
    provenance: str
    claims: tuple[Claim, ...] = ()
    hypothetical: bool = False
    calculation: Calculation | None = None
    entities: tuple[str, ...] = ()


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    unit_id: str
    detail: str
    item_id: str | None = None
    block_id: str | None = None
    output_span: tuple[int, int] | None = None
    source: Anchor | None = None


def _excerpt(anchor, pages, unit=None):
    text = pages.get(anchor.page)
    if text is None or not 0 <= anchor.start < anchor.end <= len(text):
        return None
    if unit and (tuple(unit["start"]) > (anchor.page, anchor.start)
                 or tuple(unit["end"]) < (anchor.page, anchor.end)):
        return None
    value = text[anchor.start:anchor.end]
    return value if not anchor.quote or value == anchor.quote else None


def _bindings(text, path):
    """Yield unambiguous value spans for a labeled row/cell or a local prose clause."""
    if len(path) == 1 and re.fullmatch(r"φ\([\w -]+\)", path[0], re.I):
        equation = re.compile(
            rf"{re.escape(path[0])}\s*=\s*(?:[\d.,()+−–*/÷× \t-]+?=\s*)?({_NUMBER.pattern})", re.I
        )
        for match in equation.finditer(text):
            yield decimal_value(match[1]), match.span()
        return
    labels = [_wording(label) for label in path]
    header = None
    offset = 0
    for line in text.splitlines(keepends=True):
        if "|" in line:
            cells = list(re.finditer(r"[^|]+", line.strip().strip("|")))
            data = [cell[0].strip() for cell in cells]
            if data and not all(re.fullmatch(r"[:\-\s]*", cell) for cell in data):
                columns = [i for i, cell in enumerate(data) if _wording(cell) == labels[-1]]
                if len(labels) >= 2 and columns and not all(
                    any(_includes(_wording(cell), label) for cell in data) for label in labels[:-1]
                ):
                    header = columns[0] if len(columns) == 1 else None
                elif header is not None and header < len(data) and all(
                    any(_includes(_wording(cell), label) for i, cell in enumerate(data) if i != header)
                    for label in labels[:-1]
                ):
                    values = _numbers(data[header])
                    if len(values) == 1:
                        yield next(iter(values)), (offset, offset + len(line.rstrip()))
        else:
            header = None
            for clause in _CLAUSE.finditer(line):
                # Prefer a full label path within one clause. For split comparisons, only
                # inherit a shared metric from the same clause, never a row or model label.
                start = 0
                separators = list(_COMPARISON_SEPARATOR.finditer(clause[0]))
                candidates = [(0, len(clause[0]), False)]
                for separator in separators:
                    candidates.append((start, separator.start(), True))
                    start = separator.end()
                if separators:
                    candidates.append((start, len(clause[0]), True))
                for left, right, inherit_metric in candidates:
                    fragment = clause[0][left:right]
                    words = _wording(fragment)
                    local = labels
                    if (inherit_metric and len(labels) > 1 and labels[-1] in {"f1", "auc", "accuracy", "precision", "recall"}
                            and _includes(_wording(clause[0]), labels[-1])):
                        local = labels[:-1]
                    if not all(_includes(words, label) for label in local):
                        continue
                    value_text = _fold(fragment)
                    for label in path:
                        value_text = re.sub(re.escape(_fold(label)), "", value_text)
                    values = _numbers(value_text)
                    if len(values) == 1:
                        yield next(iter(values)), (offset + clause.start() + left, offset + clause.start() + right)
                        if not inherit_metric:
                            break
        offset += len(line)


def structure_findings(text, unit_id, unit_map, *, block_id=None):
    """Only flag a recognized course title explicitly assigned to another known part."""
    titles = {_wording(unit["title"]): unit for unit in unit_map
              if unit.get("kind") == "transition" and unit.get("label")}
    labels = {unit["label"].casefold() for unit in titles.values()}
    findings = []
    for match in _PART.finditer(text):
        label = (match[1] or match[2]).casefold()
        wording = _wording(match[3])
        matches = [unit for title, unit in titles.items() if _includes(wording, title)]
        if label in labels and len(matches) == 1 and label != matches[0]["label"].casefold():
            correct = matches[0]
            start, end = correct["start"], correct["end"]
            anchor = Anchor(start[0], start[1], end[1]) if start[0] == end[0] else None
            findings.append(Finding("incorrect_part", "authoritative", unit_id,
                                    f"{correct['title']} belongs to Part {correct['label']}, not {label.upper()}",
                                    block_id=block_id, output_span=match.span(),
                                    source=anchor))
    return findings


def _close(actual, expected):
    if isinstance(actual, list):
        return isinstance(expected, list) and len(actual) == len(expected) and all(
            _close(left, right) for left, right in zip(actual, expected)
        )
    return abs(Decimal(str(actual)) - decimal_value(str(expected))) <= Decimal("0.000000001")


def _equation_key(sides):
    return tuple("".join(side.split()) for side in sides)


def _equation_anchor(block, span, pages, sources, unit, related):
    anchors = [sources[index - 1] for claim in block.claims
               if claim.start < span[1] and span[0] < claim.end
               for index in claim.source_indexes if type(index) is int and 1 <= index <= len(sources)]
    valid = [anchor for anchor in anchors if _excerpt(anchor, pages, None if anchor in related else unit) is not None]
    return next((anchor for anchor in valid if any(displayed_equations(_excerpt(anchor, pages)))),
                valid[0] if valid else None)


def verify_unit(unit, blocks, *, pages, sources, checklist=(), facts=(), unit_map=(),
                depth="standard", require_all=False, legacy=False, related_anchors=frozenset()):
    """Verify one unit using trusted page text, scoped markers and supplied source/ledger facts.

    Legacy replay verifies observable omissions and contradictions. It cannot establish coverage.
    """
    unit_id = unit["logical_id"]
    checklist = tuple(checklist)
    findings = []

    def report(code, detail, *, block=None, span=None, anchor=None, item=None, severity="authoritative"):
        findings.append(Finding(code, severity, unit_id, detail, item, block.block_id if block else None, span, anchor))

    item_facts = {fact: item.item_id for item in reversed(checklist) for fact in item.facts}
    facts = tuple(dict.fromkeys((*facts, *item_facts)))
    trusted = []
    for fact in facts:
        value = _excerpt(fact.anchor, pages)
        if value is not None and decimal_value(fact.value) in _numbers(value):
            trusted.append(fact)
        else:
            report("invalid_fact_anchor", "Source does not contain the expected value", anchor=fact.anchor,
                   item=item_facts.get(fact),
                   severity="source")
    if not legacy and unit["kind"] not in NON_TEACHING:
        required = CONTRACTS.get(unit["kind"])
        if required is None:
            report("unknown_unit_kind", unit["kind"], severity="source")
        else:
            supplied = {block.kind for block in blocks if block.text.strip() and block.provenance != "unverified"}
            for kind in required:
                if kind not in supplied:
                    report("missing_block", kind, severity="missing")
            allowed = set(required)
            if unit["kind"] == "concept":
                allowed.add("check_question")
            questions = 0
            for block in blocks:
                questions += block.kind == "check_question"
                if block.kind not in allowed or (block.kind == "check_question" and questions > 1):
                    report("unexpected_block", block.kind, block=block, severity="missing")
    coverage_text = []
    grounded_kinds = set()
    valid_calculations = set()
    unit_numbers = {value for page, text in pages.items() if unit["start"][0] <= page <= unit["end"][0]
                    for value in _numbers(text)}
    for block in blocks:
        findings.extend(structure_findings(block.text, unit_id, unit_map, block_id=block.block_id))
        bad_equations = []
        for span, sides in displayed_equations(block.text):
            original = block.text[slice(*span)]
            try:
                values = [Decimal(str(arithmetic(side))) for side in sides]
            except ValueError as error:
                report("unverifiable_equation", f"{original}: {error}", block=block, span=span,
                       anchor=_equation_anchor(block, span, pages, sources, unit, related_anchors), severity="source")
            else:
                if all(abs(value - values[0]) <= Decimal("0.000000001") for value in values[1:]):
                    continue
                evaluated = " ≠ ".join(format(value.quantize(Decimal("0.000000001")).normalize(), "f")
                                       for value in values)
                report("displayed_equation_mismatch", f"{original}; evaluated sides: {evaluated}",
                       block=block, span=span, anchor=_equation_anchor(block, span, pages, sources, unit, related_anchors))
            bad_equations.append(span)
        calculation_ok = False
        operands = set()
        if block.calculation:
            calculation = block.calculation
            try:
                actual = (arithmetic(calculation.expression, operands=operands) if calculation.expression
                          else numeric_array(calculation.operation, calculation.arrays))
                if not calculation.expression:
                    operands.update(_numeric_leaves(calculation.arrays))
                calculation_ok = _close(actual, calculation.expected)
                stated = str(calculation.expected)
                leaves = [stated] if not isinstance(calculation.expected, list) else list(_numeric_leaves(calculation.expected))
                calculation_ok &= all(decimal_value(leaf) in _numbers(block.text) for leaf in leaves)
                if not calculation_ok:
                    report("calculation_mismatch", f"Recomputed {actual}; claimed {stated}", block=block,
                           span=(0, len(block.text)))
            except (TypeError, ValueError) as exc:
                report("unsupported_calculation", str(exc), block=block, span=(0, len(block.text)), severity="missing")
        if not legacy and block.provenance not in {"course", "derived", "supplementary", "unverified"}:
            report("invalid_provenance", block.provenance, block=block)
            continue
        if not legacy and block.provenance == "unverified":
            continue
        for fact in trusted:
            for observed, span in _bindings(block.text, fact.label_path):
                if observed != decimal_value(fact.value):
                    report("label_value_mismatch", f"{' / '.join(fact.label_path)}: expected {fact.value}, got {observed}",
                           block=block, span=span, anchor=fact.anchor, item=item_facts.get(fact))
        if not legacy and block.provenance == "supplementary":
            unsupported = {value for value in _numbers(block.text) - unit_numbers
                           if not (0 <= value <= 10 and value == value.to_integral_value())}
            if unsupported and not (block.hypothetical and _HYPOTHETICAL.search(block.text)):
                report("unmarked_hypothetical", "Supplementary numbers require an explicit hypothetical label",
                       block=block, span=(0, len(block.text)))
            for entity in block.entities:
                if not any(_includes(_wording(text), _wording(entity)) for text in pages.values()):
                    report("unsupported_entity", entity, block=block, span=(0, len(block.text)))
        elif legacy:
            if not bad_equations:
                coverage_text.append(block.text)
        else:
            grounded = list(_grounded_claims(block, pages, sources, unit, trusted,
                                            operands if calculation_ok else None, report, bad_equations, related_anchors))
            if grounded:
                coverage_text.extend(grounded)
                grounded_kinds.add(block.kind)
                if calculation_ok:
                    valid_calculations.add(block.kind)
        for match in _NUMERIC_DIRECTION.finditer(block.text):
            cue = _DIRECTION.search(_fold(block.text[block.text.rfind(".", 0, match.start()) + 1:match.start()]))
            if cue:
                before, after = map(decimal_value, match.groups())
                increasing = cue[0] in {"augmente", "hausse", "increase", "increases", "increased", "rose"}
                if (increasing and after <= before) or (not increasing and after >= before):
                    report("direction_conflict", f"Direction disagrees with {before} → {after}", block=block,
                           span=match.span(), severity="heuristic")
    if not legacy and unit["kind"] in {"worked_calculation", "derivation"} and not valid_calculations:
        report("missing_calculation", "No source-anchored calculation could be recomputed", severity="missing")
    text = "\n".join(coverage_text)
    wording = _wording(text)
    grounded_equations = {_equation_key(sides) for _, sides in displayed_equations(text)}
    if legacy:
        grounded_kinds = {block.kind for block in blocks if block.text.strip()}
    for item in checklist:
        if not (require_all or item.importance == "essential"
                or (depth == "exhaustive" and item.importance == "supporting")):
            continue
        if not item.anchors or any(_excerpt(anchor, pages, unit) is None for anchor in item.anchors):
            report("unverifiable_item", "Checklist anchor is missing or outside the unit", item=item.item_id,
                   anchor=item.anchors[0] if item.anchors else None, severity="source")
            continue
        phrases_present = all(_includes(wording, _wording(phrase))
                              and all(_equation_key(sides) in grounded_equations
                                      for _, sides in displayed_equations(phrase))
                              for phrase in item.phrases)
        facts_present = all(any(value == decimal_value(fact.value) for value, _ in _bindings(text, fact.label_path))
                            for fact in item.facts)
        kinds_present = all(kind in grounded_kinds for kind in item.block_kinds)
        if not (phrases_present and facts_present and kinds_present
                and (item.phrases or item.facts or item.block_kinds)):
            report("missing_item", "Required wording, labeled value or instructional block absent", item=item.item_id,
                   anchor=item.anchors[0], severity="missing")
    return findings


def _numeric_leaves(values):
    for value in values:
        if isinstance(value, (tuple, list)):
            yield from _numeric_leaves(value)
        else:
            yield str(value)


def _grounded_claims(block, pages, sources, unit, facts, operands, report, bad_equations, related):
    cursor = 0
    numeric_spans = [match.span() for match in _NUMBER.finditer(block.text)]
    for claim in block.claims:
        span = (claim.start, claim.end)
        if not cursor <= claim.start < claim.end <= len(block.text):
            report("invalid_claim_span", "Claim offsets are invalid or overlap", block=block, span=span)
            continue
        if _wording(block.text[cursor:claim.start]):
            report("missing_claim_marker", "Text has no claim marker", block=block, span=(cursor, claim.start))
        cursor = claim.end
        if any(left < boundary < right for left, right in numeric_spans for boundary in span):
            report("split_claim_number", "Claim boundary cuts through a number", block=block, span=span)
            continue
        if not claim.source_indexes:
            report("missing_claim_marker", "Claim has no source marker", block=block, span=span)
            continue
        anchors = [sources[index - 1] if type(index) is int and 1 <= index <= len(sources) else None
                   for index in claim.source_indexes]
        excerpts = [_excerpt(anchor, pages, None if anchor in related else unit) if anchor else None for anchor in anchors]
        if any(excerpt is None for excerpt in excerpts):
            report("invalid_claim_anchor", "Marker is unknown or points outside the cited unit", block=block,
                   span=span, anchor=next(anchor for anchor, excerpt in zip(anchors, excerpts) if excerpt is None))
            continue
        text = block.text[claim.start:claim.end]
        unbound = next((fact for fact in facts if any(_bindings(text, fact.label_path)) and not any(
            anchor.page == fact.anchor.page and anchor.start <= fact.anchor.start
            and fact.anchor.end <= anchor.end for anchor in anchors
        ) and not any(value == decimal_value(fact.value) for excerpt in excerpts
                      for value, _ in _bindings(excerpt, fact.label_path))), None)
        if unbound is not None:
            report("unsupported_claim_label", "The cited passages do not contain the labeled source value",
                   block=block, span=span, anchor=unbound.anchor)
            continue
        source_values = _numbers("\n".join(excerpts))
        unsupported = _numbers(text) - source_values
        if block.provenance == "derived" and operands is not None:
            missing_operands = {abs(Decimal(str(value))) for value in operands} - {abs(value) for value in source_values}
            if missing_operands:
                report("unsupported_calculation_operand", f"Operands absent from the cited passages: {sorted(missing_operands)}",
                       block=block, span=span, anchor=anchors[0])
                continue
            expected = block.calculation.expected
            unsupported -= {decimal_value(value) for value in
                            (_numeric_leaves(expected) if isinstance(expected, list) else [str(expected)])}
        if unsupported:
            report("unsupported_claim_number", f"Numbers absent from cited passages: {sorted(unsupported)}",
                   block=block, span=span, anchor=anchors[0])
            continue
        if not (_numbers(text) or _includes(_wording("\n".join(excerpts)), _wording(text))):
            report("claim_support_unchecked", "Paraphrase requires semantic review", block=block, span=span,
                   anchor=anchors[0], severity="heuristic")
            continue
        if not any(left < claim.end and claim.start < right for left, right in bad_equations):
            yield text
    if _wording(block.text[cursor:]):
        report("missing_claim_marker", "Text has no claim marker", block=block, span=(cursor, len(block.text)))
