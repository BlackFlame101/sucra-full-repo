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
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]

    try:
        value = json.loads(text)
    except json.JSONDecodeError as json_error:
        # Some providers emit Python-style single-quoted dicts. Accept only
        # literal syntax; never evaluate model output as executable code.
        try:
            value = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            raise json_error
    if not isinstance(value, dict):
        raise ValueError("Model response must contain a JSON object")
    return value
