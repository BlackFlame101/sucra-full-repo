"""Source-only inventory for the twenty-question QCM."""
import re
from dataclasses import dataclass
from typing import Literal


FIRST_FIVE = (1, 2, 3, 4, 5)
ALL_QUESTIONS = tuple(range(1, 21))
_QUESTION = re.compile(r"(?m)^[ \t]*Q[ \t]*(?P<number>[0-9]{1,3})[.):][ \t]*")
_OPTION = re.compile(r"(?m)^[ \t]*(?P<key>[A-Z])[.):][ \t]*")


class QcmSourceError(ValueError):
    """An incomplete or ambiguous inventory must not be passed to generation."""


@dataclass(frozen=True)
class SourceSpan:
    page: int
    start: int
    end: int


@dataclass(frozen=True)
class SourceQcmOption:
    key: str
    exact_text: str
    span: SourceSpan


@dataclass(frozen=True)
class SourceQcmItem:
    question_id: str
    ordinal: int
    exact_question_text: str
    question_span: SourceSpan
    options: tuple[SourceQcmOption, ...]


@dataclass(frozen=True)
class QcmInventory:
    document_id: str
    source_hash: str
    index_version: str
    items: tuple[SourceQcmItem, ...]


@dataclass(frozen=True)
class QcmOptionReason:
    key: str
    principle: str
    application: str


@dataclass(frozen=True)
class GeneratedQcmAnswer:
    question_id: str
    selected_keys: tuple[str, ...]
    option_reasons: tuple[QcmOptionReason, ...]
    answer_basis: Literal["official_key", "source_supported_reasoned", "model_proposed", "unresolved"]


def _source_text(page: int, text: str, start: int, end: int) -> tuple[str, SourceSpan]:
    raw = text[start:end]
    content = raw.strip()
    start += len(raw) - len(raw.lstrip())
    return content, SourceSpan(page, start, start + len(content))


def build_qcm_inventory(
    pages: list[str], document_id: str, source_hash: str, index_version: str,
    ordinals: tuple[int, ...] = FIRST_FIVE,
) -> QcmInventory:
    """Keep exact extracted substrings and zero-based offsets into each PDF page."""
    headings = [
        (page, int(match["number"]), match)
        for page, text in enumerate(pages, 1)
        for match in _QUESTION.finditer(text)
    ]
    if not ordinals or ordinals != tuple(range(ordinals[0], ordinals[-1] + 1)) or not set(ordinals).issubset(ALL_QUESTIONS):
        raise QcmSourceError("La plage du QCM doit être comprise entre Q1 et Q20.")
    last = ordinals[-1]
    prefix = ALL_QUESTIONS[:last]
    if (tuple(number for _, number, _ in headings if number in prefix) != prefix
            or tuple(number for _, number, _ in headings[:last]) != prefix):
        raise QcmSourceError(f"Des questions entre Q1 et Q{last} sont manquantes, dupliquées ou hors ordre.")

    items = []
    for index, (page, number, heading) in enumerate(headings):
        if number not in ordinals:
            continue
        text = pages[page - 1]
        following = headings[index + 1] if index + 1 < len(headings) else None
        if following and following[1] != number + 1:
            raise QcmSourceError(f"La limite de Q{number} est ambiguë.")
        if page < len(pages) and (not following or following[0] != page):
            if not following or following[0] != page + 1:
                raise QcmSourceError(f"La fin de Q{number} avant la page suivante est ambiguë.")
            next_prefix = pages[page][:following[2].start()].strip()
            header = text.splitlines()[0].strip()
            if next_prefix.startswith(header + "\n"):
                next_prefix = next_prefix[len(header):].strip()
            if next_prefix not in ("", str(page + 1)):
                raise QcmSourceError(f"Le dernier choix de Q{number} pourrait continuer sur la page suivante.")
        end = following[2].start() if following and following[0] == page else len(text)
        options = list(_OPTION.finditer(text, heading.end(), end))
        if tuple(option["key"] for option in options) != ("A", "B", "C", "D"):
            raise QcmSourceError(f"Les choix A à D de Q{number} sont incomplets, dupliqués ou hors ordre.")
        question, question_span = _source_text(page, text, heading.end(), options[0].start())
        if not question:
            raise QcmSourceError(f"Le texte de Q{number} est manquant.")
        choices = []
        for option_index, option in enumerate(options):
            option_end = options[option_index + 1].start() if option_index < 3 else end
            choice, span = _source_text(page, text, option.end(), option_end)
            if not choice or re.search(r"\n[ \t]*\n", choice):
                raise QcmSourceError(f"Le choix {option['key']} de Q{number} est manquant ou ambigu.")
            choices.append(SourceQcmOption(option["key"], choice, span))
        items.append(SourceQcmItem(f"q{number}", number, question, question_span, tuple(choices)))
    return QcmInventory(document_id, source_hash, index_version, tuple(items))
