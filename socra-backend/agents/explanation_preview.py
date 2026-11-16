"""Expose only readable fields from an in-progress explanation JSON object."""
from __future__ import annotations

import json
import re


_TOKEN = re.compile(r'"(?:[^"\\]|\\[\s\S])*"|[{}\[\]:,]')
_ROOT_FIELDS = {"definition", "intuition", "course_example", "check_question"}
_SECTION_FIELDS = {"heading", "content", "code"}
_WALKTHROUGH_FIELDS = {"explanation"}


def explanation_preview(raw: str) -> str:
    parts: list[str] = []
    tokens = iter(_TOKEN.finditer(raw))
    field = ""
    previous = ""
    end = 0
    scopes: list[str] = []
    language = ""

    def append(value: str, *, complete: bool = True) -> None:
        fields = (
            _ROOT_FIELDS if scopes == ["{"] else
            _SECTION_FIELDS if scopes == ["{", "sections", "{"] else
            _WALKTHROUGH_FIELDS if scopes == ["{", "sections", "{", "walkthrough", "{"] else
            ()
        )
        if field in fields and value.strip():
            parts.append(_format_field(field, value, complete=complete, language=language))

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
            if previous == ":":
                if field == "code_language" and scopes == ["{", "sections", "{"]:
                    tag = value.strip().split(maxsplit=1)[0] if value.strip() else ""
                    language = tag if re.fullmatch(r"[\w+.-]{1,32}", tag) else ""
                append(value)
            field = value if previous != ":" else ""
        elif token in ("{", "["):
            scopes.append(field if previous == ":" else token)
        elif token in ("}", "]") and scopes:
            if scopes == ["{", "sections", "{"]:
                language = ""
            scopes.pop()
        previous = token if not token.startswith('"') else "string"

    tail = raw[end:].lstrip()
    if previous == ":" and tail.startswith('"'):
        # Remove an incomplete escape so the visible prefix remains valid JSON.
        partial = re.sub(r'(?<!\\)(?:\\\\)*\\(?:u[0-9a-fA-F]{0,3})?$', '', tail[1:])
        try:
            value = json.loads('"' + partial + '"')
        except ValueError:
            value = ""
        append(value, complete=False)
    return "".join(parts).encode("utf-8", errors="ignore").decode("utf-8")


def _format_field(field: str, value: str, *, complete: bool = True, language: str = "") -> str:
    if field == "heading":
        return f"\n\n## {value}"
    if field == "code":
        return f"\n\n```{language}\n{value}" + ("\n```" if complete else "")
    return f"\n\n{value}"
