"""Expose only readable fields from an in-progress explanation JSON object."""
from __future__ import annotations

import json
import re


_TOKEN = re.compile(r'"(?:[^"\\]|\\[\s\S])*"|[{}\[\]:,]')
_FIELDS = {"definition", "intuition", "heading", "content", "code", "course_example", "check_question"}


def explanation_preview(raw: str) -> str:
    parts: list[str] = []
    tokens = iter(_TOKEN.finditer(raw))
    field = ""
    previous = ""
    end = 0
    for match in tokens:
        token = match.group()
        # An unmatched quote before a token belongs to a partial string.
        if '"' in raw[end:match.start()]:
            break
        end = match.end()
        if token.startswith('"'):
            try:
                value = json.loads(token)
            except ValueError:
                break
            if previous == ":" and field in _FIELDS and value.strip():
                parts.append(_format_field(field, value))
            field = value if previous != ":" else ""
        previous = token if not token.startswith('"') else "string"

    tail = raw[end:].lstrip()
    if previous == ":" and field in _FIELDS and tail.startswith('"'):
        # Remove an incomplete escape so the visible prefix remains valid JSON.
        partial = re.sub(r'(?<!\\)(?:\\\\)*\\(?:u[0-9a-fA-F]{0,3})?$', '', tail[1:])
        try:
            value = json.loads('"' + partial + '"')
        except ValueError:
            value = ""
        if value.strip():
            parts.append(_format_field(field, value, complete=False))
    return "".join(parts).encode("utf-8", errors="ignore").decode("utf-8")


def _format_field(field: str, value: str, *, complete: bool = True) -> str:
    if field == "heading":
        return f"\n\n## {value}"
    if field == "code":
        return f"\n\n```\n{value}" + ("\n```" if complete else "")
    return f"\n\n{value}"
