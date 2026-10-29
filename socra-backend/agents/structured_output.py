"""Helpers for extracting and validating JSON returned by chat models."""
from __future__ import annotations

import ast
import json
import re
from typing import Any


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


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
    match = _FENCE_RE.search(text)
    if match:
        text = match.group(1).strip()
    else:
        if text.lstrip().startswith("["):
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
