"""Extract source-grounded educational requirements from indexed PDF text."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, replace

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_LABELS = {
    "section": r"sections?|parts?|parties?|chapters?|chapitres?|الفصل|فصل|القسم|قسم|الوحدة|وحدة|المبحث",
    "step": r"steps?|etapes?|خطوات?|الخطوات?|خطوة|الخطوة",
    "exercise": r"exercises?|exercices?|problems?|problemes?|تمارين|التمارين|تمرين|التمرين|مسالة|المسالة",
    "question": r"questions?|اسئلة|الاسئلة|سوال|السوال|اسئله",
    "subquestion": r"sub[- ]questions?|sous[- ]questions?|السوال الفرعي|سوال فرعي",
    "screenshot": r"screenshots?|screen shots?|captures?(?: d['’]ecran)?|لقطة (?:من )?الشاشة|لقطات الشاشة",
    "appendix": r"appendix|appendices|annex(?:e|es)?|الملحق|ملحق",
    "bonus": r"bonus|optional exercises?|exercices? facultatifs?|تمرين اختياري|تمارين اختيارية|مكافاة|اضافي",
    "figure": r"figures?|fig[.]|الشكل|شكل|الرسم",
    "table": r"tables?|tableaux?|الجدول|جدول",
    "formula": r"formulas?|formulae|formules?|equations?|المعادلة|معادلة|الصيغة|صيغة",
}
_INDEXED = [
    (kind, re.compile(r"^(?:" + label + r")[ \t]*(?:n[°ºo][ \t]*|#[ \t]*)?"
                      + (r"([0-9]+(?:[.\-][0-9]+)*[a-z]?|[ivxlcdm]+|[a-z])" if kind in {"section", "appendix", "bonus", "subquestion"}
                         else r"([0-9]+(?:[.\-][0-9]+)*[a-z]?)")
                      + r"(?=$|[\s.:)\-–—])"))
    for kind, label in sorted(_LABELS.items(), key=lambda item: item[0] != "subquestion")
]
_REQUIRED = re.compile(r"\b(?:mandatory|required|obligatoires?|exiges?|requis(?:es)?|a respecter|ملزم|الزامي|الزامية|مطلوب|مطلوبة|واجبة)\b")
_OPTIONAL = re.compile(r"\b(?:optional|bonus|facultatifs?|si vous avez|اختياري(?:ة)?|اضافي(?:ة)?)\b")
_DELIVERABLE = re.compile(r"\b(?:deliverables?|livrables?|files? to submit|submit|a rendre|rendre les|remettre|a remettre|التسليم|ملفات التسليم|سلم|المخرجات المطلوبة)\b")
_REQUIRED_FILE = re.compile(r"\b(?:required files?|fichiers requis|nom du fichier a respecter|الملفات المطلوبة|ملفات مطلوبة)\b")
_FILES = re.compile(
    r"""(?<![\w.-])[\w][\w./\\-]*\.(?:ows|knwf|knar|pdf|docx?|xlsx?|csv|tsv|json|ya?ml|xml|zip|md|txt|"""
    r"""py|ipynb|sql|js|ts|c|cpp|java|r|mat|tex|png|jpe?g|svg|pptx?|sh|ps1)(?![\w-]|\.[\w-])""", re.IGNORECASE,
)
_TOPIC_LABELS = {
    "expected_result": r"expected (?:results?|outputs?)|resultats? attendus?|المخرجات المتوقعة|النتائج المتوقعة|النتيجة المتوقعة",
    "installation": r"installation(?: requirements)?|install(?:er)?|prerequisites?|prerequis|setup|configuration requise|التثبيت|تثبيت|المتطلبات المسبقة",
    "troubleshooting": r"troubleshooting|depannage|problemes frequents|استكشاف الاخطاء|حل المشكلات|حل المشاكل",
    "warning": r"warnings?|caution|attention|avertissements?|تحذير|تنبيه",
    "deliverable": _DELIVERABLE.pattern,
    "file": _REQUIRED_FILE.pattern,
}
_TOPIC_START = {kind: re.compile(r"^(?:" + labels + r")(?=$|[\s.:)\-–—])")
                for kind, labels in _TOPIC_LABELS.items()}
_CONTAINER = re.compile(r"^(?:required questions|mandatory questions|questions?(?: d['’]analyse)?|الاسئلة(?: الالزامية)?)\b")
_NUMERIC_STEP = re.compile(r"^(\d+(?:\.\d+)*)[.)]\s+\S")
_SUB = re.compile(r"^(?:\(([a-zء-ي])\)|([a-zء-ي])[.)])\s+\S")
_BONUS_CODE = re.compile(r"^(b[0-9]+)\s*[:–—-]")
_TASK_BLOCK = re.compile(r"^(?:a faire|to do|required tasks|المطلوب|مهام مطلوبة)\s*[:–—-]?\s*$")
_ARABIC_ORDINALS = dict(zip(
    ("الاول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع", "الثامن", "التاسع", "العاشر"),
    map(str, range(1, 11)),
))
_ARABIC_ORDINALS.update(dict(zip(
    ("الاولى", "الثانية", "الثالثة", "الرابعة", "الخامسة", "السادسة", "السابعة", "الثامنة", "التاسعة", "العاشرة"),
    map(str, range(1, 11)),
)))
_ARABIC_HEADING_ORDINAL = re.compile(
    r"^((?:الفصل|القسم|الوحدة|التمرين|السوال|الخطوة|الملحق|لقطة (?:من )?الشاشة)\s+)("
    + "|".join(_ARABIC_ORDINALS) + r")\b"
)
_SUPPORT_KINDS = {"expected_result", "troubleshooting", "warning"}
_SUPPORT_START = re.compile(
    r"^(?:reference (?:results?|metrics)|verification (?:results?|checks)|"
    r"si ca coince|(?:if|si)\s.{4,100}(?:fails?|echoue|reste|n'apparait pas))\b"
)
_INSTALL_SECTION_ACTION = re.compile(r"^[\s.:)\-\u2013\u2014]*(?:install(?:er)?|set[ -]up|configurer?)\s+\S")
_MARKDOWN_TABLE_ROW = re.compile(r"^\s*\|.+\|\s*$")


def _table_rows(lines: list[str], offset: int) -> list[str]:
    if offset and lines[offset - 1].strip().startswith("|"):
        return []
    rows: list[str] = []
    current = ""
    for line in lines[offset:offset + 24]:
        line = line.strip()
        if not line:
            if current:
                break
            continue
        if not current and not line.startswith("|"):
            break
        current += (" " if current else "") + line
        if _MARKDOWN_TABLE_ROW.match(current):
            rows.append(current)
            current = ""
    if len(rows) < 2 or not re.fullmatch(r"\|[\s|:-]+\|", rows[1]):
        return []
    return rows


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c)).translate(_DIGITS)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


@dataclass(frozen=True)
class Requirement:
    id: str
    key: str
    kind: str
    document_id: str
    page_number: int
    chunk_id: str
    original_heading: str
    evidence_anchor: str
    status: str
    status_basis: str
    parent_key: str | None


@dataclass(frozen=True)
class DocumentInventory:
    scope: str
    requirements: tuple[Requirement, ...]

    def as_state(self) -> dict:
        return {"inventory_scope": self.scope, "requirements": [asdict(item) for item in self.requirements]}


def build_inventory(chunks: list[dict], scope: str = "retrieved_only") -> DocumentInventory:
    requirements: list[Requirement] = []
    seen: dict[tuple[str, int, str, str, str | None], tuple[str, int]] = {}
    current_document = None
    section = parent = procedure_key = None
    block_status = parent_status = None
    deliverables = procedure = False

    ordered = sorted(chunks, key=lambda row: (
        str(row.get("document_id") or ""), row.get("page_number") or 0,
        row.get("chunk_index") or 0, str(row.get("id") or ""),
    ))
    for chunk in ordered:
        doc, page, chunk_id = str(chunk.get("document_id") or ""), chunk.get("page_number"), str(chunk.get("id") or "")
        if not doc or type(page) is not int or page < 1 or not chunk_id:
            continue
        if doc != current_document:
            current_document = doc
            section = parent = procedure_key = None
            block_status = parent_status = None
            deliverables = procedure = False

        def add(kind: str, identifier: str, original: str, status: str, parent_key: str | None = None) -> str:
            requirement_id = f"{kind}:{identifier}"
            identity = (doc, page, requirement_id, _fold(original), parent_key)
            old_chunk, count = seen.get(identity, (chunk_id, 0))
            fingerprint = _digest(f"{parent_key or ''}|{identity[3]}")
            if count and old_chunk != chunk_id:
                return f"{doc}:{page}:{requirement_id}:{fingerprint}"
            seen[identity] = (chunk_id, count + 1)
            key = f"{doc}:{page}:{requirement_id}:{fingerprint}" + (f":{count + 1}" if count else "")
            line_evidence = _fold(original)
            basis = (
                "unspecified" if status == "unspecified" else
                "line" if _REQUIRED.search(line_evidence) or _OPTIONAL.search(line_evidence) else "heading_or_context"
            )
            requirements.append(Requirement(
                requirement_id, key, kind, doc, page, chunk_id, original[:220],
                " ".join(original.split())[:280], status, basis, parent_key,
            ))
            return key

        lines = str(chunk.get("content") or "").splitlines()
        for offset, raw in enumerate(lines):
            original = raw.strip().lstrip("#*•-–— \t").strip()
            if not original:
                continue
            line = _fold(original)
            line = _ARABIC_HEADING_ORDINAL.sub(lambda m: m[1] + _ARABIC_ORDINALS[m[2]], line, count=1)
            required = bool(_REQUIRED.search(line))
            optional = bool(_OPTIONAL.search(line))
            explicit_status = "optional" if optional else "required" if required else None
            if raw.lstrip().startswith("|") and (table := _table_rows(lines, offset)):
                status = "optional" if block_status == "optional" else "supporting"
                key = add("reference_table", _digest(line), original, status, procedure_key or section)
                if requirements[-1].key == key:
                    requirements[-1] = replace(requirements[-1], evidence_anchor="\n".join(table)[:700])

            matched = next(((kind, match) for kind, pattern in _INDEXED if (match := pattern.match(line))), None)
            if not matched and (m := _BONUS_CODE.match(line)) and block_status == "optional":
                matched = ("bonus", m)

            if matched and matched[0] in {"section", "appendix"}:
                kind, match = matched
                section = add(kind, match[1].upper(), original,
                              "structural" if kind == "section" else explicit_status or "unspecified")
                procedure_key = None
                parent = None
                block_status = explicit_status
                deliverables = bool(_DELIVERABLE.search(line))
                procedure = bool(re.search(r"\b(?:procedure|instructions|installation|etapes|خطوات|اجراءات)\b", line))
            elif _TASK_BLOCK.match(line):
                block_status = "required"
                parent = None
            elif not matched and (_CONTAINER.match(line) or re.match(r"^(?:bonus|optional exercises|exercices facultatifs|تمارين اختيارية)\b", line)):
                block_status = explicit_status
                parent = None
                procedure_key = None
            elif not matched and _TOPIC_START["deliverable"].match(line):
                deliverables = True
                block_status = "required"

            if not matched and parent and (m := _SUB.match(line)):
                add("subquestion", (m[1] or m[2]).upper(), original,
                    explicit_status or parent_status or block_status or "unspecified", parent)
            elif not matched and procedure and (m := _NUMERIC_STEP.match(line)):
                procedure_key = add("step", m[1], original, explicit_status or block_status or "unspecified", section)
            elif matched and matched[0] not in {"section", "appendix"}:
                kind, match = matched
                identifier = match[1].upper() if kind in {"appendix", "bonus", "subquestion"} else match[1]
                status = "optional" if kind == "bonus" else explicit_status or block_status or "unspecified"
                key = add(kind, identifier, original, status, parent if kind == "subquestion" else section)
                if kind == "step":
                    procedure_key = key
                if kind in {"exercise", "question"}:
                    parent = key
                    parent_status = status

            for kind, pattern in _TOPIC_START.items():
                support = _SUPPORT_START.match(line)
                alt = "expected_result" if line.startswith(("reference ", "verification ")) else "troubleshooting"
                installation_step = kind == "installation" and matched and (
                    matched[0] == "step" and re.search(_TOPIC_LABELS[kind], line)
                    or matched[0] == "section" and _INSTALL_SECTION_ACTION.match(line[matched[1].end():])
                )
                if pattern.match(line) or (support and kind == alt) or installation_step:
                    if kind in _SUPPORT_KINDS:
                        following = []
                        for subsequent in lines[offset + 1:offset + 18]:
                            candidate = subsequent.strip()
                            folded = _fold(candidate)
                            if (candidate.startswith("#") or any(pattern.match(folded) for _, pattern in _INDEXED)
                                    or any(pattern.match(folded) for pattern in _TOPIC_START.values())
                                    or _SUPPORT_START.match(folded) or _TASK_BLOCK.match(folded)):
                                break
                            if not candidate and following and kind != "expected_result":
                                break
                            if candidate:
                                following.append(candidate)
                        key = add(kind, _digest(line), original,
                                  explicit_status or ("optional" if block_status == "optional" else "supporting"),
                                  procedure_key or section)
                        if following and requirements[-1].key == key:
                            requirements[-1] = replace(requirements[-1], evidence_anchor="\n".join([original, *following])[:650])
                    else:
                        if kind in {"file", "deliverable"} and _FILES.search(original):
                            continue  # The named artifact below is the requirement.
                        key = add(kind, _digest(line), original,
                                  explicit_status or "required", procedure_key or section)
                        if kind == "installation":
                            procedure_key = key

            file_status = explicit_status or ("required" if deliverables or _REQUIRED_FILE.search(line) or
                                              _DELIVERABLE.search(line) else block_status or "unspecified")
            for filename in dict.fromkeys(_FILES.findall(original)):
                basename = re.split(r"[/\\]", filename)[-1]
                kind = "deliverable" if deliverables or _DELIVERABLE.search(line) or "a respecter" in line else "file"
                add(kind, unicodedata.normalize("NFC", basename).casefold(), original, file_status, section)

    return DocumentInventory(scope, tuple(requirements))
