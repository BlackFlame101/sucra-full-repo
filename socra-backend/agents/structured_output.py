"""Helpers for extracting and validating JSON returned by chat models."""
from __future__ import annotations

import ast
import json
import re
from typing import Any


_FENCE_RE = re.compile(r"^[ \t]*\x60{3}(?:json)?[ \t]*(?:\r?\n|(?=[{\[]))(.*?)^[ \t]*\x60{3}[ \t]*(?:\r?$)", re.IGNORECASE | re.DOTALL | re.MULTILINE)
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def has_control_characters(value: Any) -> bool:
    if isinstance(value, str):
        return CONTROL.search(value) is not None
    if isinstance(value, dict):
        return any(has_control_characters(key) or has_control_characters(item) for key, item in value.items())
    if isinstance(value, list):
        return any(has_control_characters(item) for item in value)
    return False


def gemini_response_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Avoid expanding nested array limits in Gemini's decoding constraint."""
    result = schema.copy()
    if result.get("type") == "array":
        result.pop("maxItems", None)
    for key in ("properties", "$defs"):
        if key in result:
            result[key] = {name: gemini_response_schema(child) for name, child in result[key].items()}
    if "DraftClaim" in result.get("$defs", {}):
        claim = result["$defs"]["DraftClaim"]
        result["$defs"]["DraftClaim"] = {
            "type": "object", "required": ["output_quote", "source_indexes"], "additionalProperties": False,
            "properties": {"output_quote": {"type": "string"}, "source_indexes": claim["properties"]["source_indexes"]},
        }
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        if key in result:
            result[key] = [gemini_response_schema(child) for child in result[key]]
    for key in ("items", "additionalProperties"):
        if isinstance(result.get(key), dict):
            result[key] = gemini_response_schema(result[key])
    return result


def message_text(content: Any) -> str:
    """Extract readable text from LangChain string or multimodal content."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part).strip()
    return str(content or "").strip()


def parse_json_object(content: Any) -> dict[str, Any]:
    """Parse a model response as an object, tolerating fences and wrappers."""
    text = message_text(content)
    # Fences within JSON string values are part of the response, not its wrapper.
    if not text.startswith(("{", "[")):
        match = _FENCE_RE.search(text)
        if match:
            text = match.group(1).strip()
    if text.startswith("["):
        raise ValueError("Model response must contain an object, not an array")

    decoder = json.JSONDecoder()
    starts = [index for index, char in enumerate(text) if char == "{"]
    last_error: Exception | None = None
    for start in starts:
        candidate = text[start:].lstrip()
        try:
            value, _end = decoder.raw_decode(candidate)
        except json.JSONDecodeError as json_error:
            last_error = json_error
            # Some providers emit Python-style single-quoted dicts. Accept only
            # literal syntax; never evaluate model output as executable code.
            try:
                value = ast.literal_eval(candidate)
            except (SyntaxError, ValueError):
                continue
        if isinstance(value, dict):
            return value

    if last_error:
        raise last_error
    raise ValueError("Model response must contain a JSON object")


def recover_json_prefix(content: Any, partial_arrays: frozenset[str]) -> dict[str, Any]:
    """Recover complete top-level fields and complete items of selected arrays."""
    text = re.sub(r"^\x60\x60\x60(?:json)?\s*", "", message_text(content), count=1, flags=re.IGNORECASE)
    if not text.startswith("{"):
        return {}
    decoder = json.JSONDecoder()
    recovered: dict[str, Any] = {}

    def skip_space(position: int) -> int:
        while position < len(text) and text[position].isspace():
            position += 1
        return position

    position = skip_space(1)
    while text[position:position + 1] == '"':
        try:
            key, end = decoder.raw_decode(text, position)
            colon = skip_space(end)
            if text[colon:colon + 1] != ":":
                break
            position = skip_space(colon + 1)
            if key in partial_arrays and text[position:position + 1] == "[":
                items = []
                recovered[key] = items
                position = skip_space(position + 1)
                while text[position:position + 1] != "]":
                    item, end = decoder.raw_decode(text, position)
                    position = skip_space(end)
                    delimiter = text[position:position + 1]
                    # An object has an explicit ending. A bare numeric index
                    # at EOF could still be the prefix of a larger index.
                    if delimiter in {",", "]"} or (not delimiter and isinstance(item, dict)):
                        items.append(item)
                    if delimiter != ",":
                        break
                    position = skip_space(position + 1)
                if text[position:position + 1] != "]":
                    break
                position = skip_space(position + 1)
            else:
                value, end = decoder.raw_decode(text, position)
                position = skip_space(end)
                if text[position:position + 1] in {"", ",", "}"}:
                    recovered[key] = value
            if text[position:position + 1] != ",":
                break
            position = skip_space(position + 1)
        except json.JSONDecodeError:
            break
    return recovered
