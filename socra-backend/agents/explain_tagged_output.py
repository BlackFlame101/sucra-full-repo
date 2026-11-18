"""Parse the provider's line-oriented unit draft format."""
from dataclasses import dataclass
import json
import os
import re


TAGGED_INSTRUCTIONS = """Write plain text using only these line-start headers:
@@UNIT <exact unit_id>
@@BLOCK kind=<kind> provenance=<derived|supplementary> sources=<indexes> items=<numbers>
<block text>
@@CALC expression=<dot-decimal expression> expected=<dot-decimal value>
Write one unit header per input, in input order. When its checklist is empty, write the full ordered block skeleton once with items=-.
When the unit has checklist items, write the full ordered block skeleton once per item, in ascending item order.
Every block in a group uses exactly that item's number in items. Finish all kinds for that item before starting the next item.
After each block header, write its full teaching text.
Use comma-separated positive integers with no spaces, or - for an empty list.
Source indexes and checklist numbers are local to the current input unit.
A derived block needs at least one supporting source. Supplementary blocks use sources=-.
Append an optional calculation header after the text of the block it supports.
Separate headers with newlines. Lines starting with @@ are reserved. Do not add fences or a JSON wrapper."""

_UNIT = re.compile(r"@@UNIT ([A-Za-z0-9_.:-]{1,128})")
_INDEX_LIST = r"(?:-|[1-9][0-9]{0,5}(?:,[1-9][0-9]{0,5})*)"
_BLOCK = re.compile(rf"@@BLOCK kind=([a-z][a-z0-9_]{{0,39}}) provenance=(derived|supplementary) "
                    rf"sources=({_INDEX_LIST}) items=({_INDEX_LIST})")
_CALC = re.compile(r"@@CALC expression=(.{1,256}?) expected=([+-]?[0-9]+(?:\.[0-9]+)?)")
_MALFORMED = "malformed_tagged_output"
MAX_TAGGED_BLOCKS = 64


@dataclass(frozen=True)
class TaggedLayout:
    kinds: tuple[str, ...]
    item_count: int
    source_count: int

    @classmethod
    def from_packet(cls, packet):
        return cls(tuple(packet["required_blocks"]), len(packet["checklist"]), len(packet["sources"]))

    @property
    def block_count(self):
        return len(self.kinds) * max(1, self.item_count)

    def failure(self, position, kind, sources, items):
        if position >= self.block_count or position >= MAX_TAGGED_BLOCKS:
            return "tagged_block_limit_exceeded"
        if any(index > self.source_count for index in sources):
            return "invalid_claim_index"
        if any(index > self.item_count for index in items):
            return "invalid_checklist_reference"
        group, slot = divmod(position, len(self.kinds))
        if kind != self.kinds[slot] or items != ([group + 1] if self.item_count else []):
            return "invalid_tagged_skeleton"
        return ""


def generation_format():
    value = os.getenv("EXPLAIN_GENERATION_FORMAT", "json")
    if value not in {"json", "tagged"}:
        raise ValueError("EXPLAIN_GENERATION_FORMAT must be json or tagged")
    return value


def _indexes(value):
    return [] if value == "-" else [int(part) for part in value.split(",")]


def parse_tagged_units(raw, layouts, reason=""):
    """Normalize complete blocks without guessing IDs, references or missing text."""
    found = {}
    duplicates = set()
    unit_id = None
    row = None
    block = None
    body = []
    invalid_envelope = False

    def fail(code):
        row["reason"] = row["reason"] or code

    def finish_unit(interruption=""):
        if row is not None:
            if interruption:
                row["reason"] = interruption
            elif row["slots"] < layouts[unit_id].block_count:
                fail("incomplete_tagged_skeleton")

    def finish_block(calculation=None):
        nonlocal block, body
        if block is not None:
            text = "".join(body).strip("\n\r")
            if text:
                kind, provenance, sources, items = block
                failure = layouts[unit_id].failure(row["slots"], kind, sources, items)
                row["slots"] += 1
                if not failure:
                    row["blocks"].append({
                        "kind": kind, "provenance": provenance, "text": text,
                        "claims": [{"start": 0, "end": len(text), "source_indexes": sources}] if sources else [],
                        "candidate_items": items,
                    } | ({"calculation": calculation} if calculation is not None else {}))
                else:
                    fail(failure)
            else:
                fail(_MALFORMED)
        block, body = None, []

    # Split only on LF. Other Unicode separators and controls remain in the block text.
    for line in re.findall(r"[^\n]*\n|[^\n]+$", raw):
        header = line.removesuffix("\n").removesuffix("\r")
        if match := _UNIT.fullmatch(header):
            finish_block()
            finish_unit()
            unit_id = match[1]
            if unit_id not in layouts:
                invalid_envelope = True
                row = None
            elif unit_id in found:
                duplicates.add(unit_id)
                row = None
            else:
                row = found[unit_id] = {"blocks": [], "reason": "", "slots": 0}
        elif row is None:
            if unit_id is None and header.strip(" \t"):
                invalid_envelope = True
        elif match := _BLOCK.fullmatch(header):
            finish_block()
            kind, provenance, raw_sources, raw_items = match.groups()
            sources = _indexes(raw_sources)
            if bool(sources) != (provenance == "derived"):
                fail(_MALFORMED)
            else:
                block = (kind, provenance, sources, _indexes(raw_items))
        elif (match := _CALC.fullmatch(header)) and block is not None:
            finish_block({"expression": match[1], "expected": match[2]})
        elif header.startswith("@@") or (block is None and header.strip(" \t")):
            fail(_MALFORMED)
            block, body = None, []
        elif block is not None:
            body.append(line)

    if not reason:
        finish_block()
    finish_unit(reason)
    return {
        uid: (("", "duplicate_batch_unit") if uid in duplicates else
              (json.dumps({"blocks": found[uid]["blocks"]}, ensure_ascii=False),
               found[uid]["reason"] or (_MALFORMED if invalid_envelope or not found[uid]["blocks"] else ""))
              if uid in found else ("", reason or (_MALFORMED if invalid_envelope else "missing_batch_unit")))
        for uid in layouts
    }
