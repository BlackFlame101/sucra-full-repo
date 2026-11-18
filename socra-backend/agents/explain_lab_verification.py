"""Source-specific approval contract for the annotated Spark environment step."""

import ast
from hashlib import sha256
import json
import re

from agents.structured_output import has_control_characters


SPARK_SETUP_VERSION = "e19305e110ed6ec763612d643c0bfb3991fd3456f81e486853aa6d7982204441"
CONTRACT = "spark-setup-v1"
KINDS = ("action", "command_or_ui", "expected_result", "checkpoint")
COMMANDS = (
    ('import os, sys', 'os.environ["PYSPARK_PYTHON"] = sys.executable',
     'os.environ["PYSPARK_DRIVER_PYTHON"] = sys.executable', 'from pyspark.sql import SparkSession, functions as F',
     'from pyspark.ml import Pipeline, PipelineModel', 'from pyspark.ml.feature import VectorAssembler, StandardScaler',
     'spark = (SparkSession.builder'),
    ('.master("local[2]")',),
    ('.appName("TP3_MLlib_VersionB")',),
    ('.getOrCreate())', 'spark.sparkContext.setLogLevel("WARN")', 'print("Version Spark :", spark.version)'),
    (),
)
OPERATIONS = (
    ("python_executable", COMMANDS[0][:2]),
    ("driver_executable", COMMANDS[0][2:3]),
    ("spark_imports", COMMANDS[0][3:6]),
    ("local_master", COMMANDS[1]),
    ("application_name", COMMANDS[2]),
    ("session_creation", (COMMANDS[0][-1], COMMANDS[3][0])),
    ("warn_logging", COMMANDS[3][1:2]),
    ("runtime_version_command", COMMANDS[3][2:]),
)
CHECK_IDS = tuple(key for key, _ in OPERATIONS) + (
    "complete_execution_order", "python_cell_syntax", "separate_blocks",
    "runtime_qualification", "source_grounding", "control_characters",
)
PEDAGOGY = (
    ("python_environment", 0, "Explain why both Python interpreter settings use the notebook interpreter."),
    ("imports", 0, "Explain the roles of the SQL and ML imports rather than listing them."),
    ("session_builder", 0, "Explain why the builder starts the session configuration."),
    ("local_master_purpose", 1, "Explain why local mode is suitable for this exercise."),
    ("application_identity", 2, "Explain what the application name identifies."),
    ("session_lifecycle", 3, "Explain what obtaining the session makes available to the notebook."),
    ("log_control", 3, "Explain the purpose and effect of selecting WARN."),
    ("runtime_observation", 3, "Explain why the installed Spark version is observed at runtime."),
    ("two_local_threads", 4, "Explain that local[2] uses two threads on the local machine."),
    ("distributed_limits", 4, "Explain why a local run does not establish distributed cluster performance."),
)
NO_COMMAND = {"French": "Aucune commande supplémentaire.", "English": "No additional command."}
RUNTIME = {
    "French": "La version affichée par spark.version est relevée à l’exécution.",
    "English": "The version displayed by spark.version is observed at runtime.",
}
_FENCE = re.compile(r"```(?:python|py)?[ \t]*\r?\n(.*?)\r?\n```", re.S)
_FIXED_VERSION = re.compile(
    r"(?i)\d+\.\d+|\b(?:version(?:\s+(?:de|of))?(?:\s+spark)?|spark)\s*"
    r"(?:[:=]|(?:est|is)\s+)?\s*v?\d+\b",
)


def requires_lab_check(unit):
    return unit.get("content_version") == SPARK_SETUP_VERSION


def _lines(text):
    return tuple(line.strip() for line in text.split("\n") if line.strip())


def _source_group(item):
    anchors = item.get("anchors", [])
    if len(anchors) != 1 or anchors[0]["page"] != 1 or item.get("type") != "command" or item.get("facts"):
        return None
    quote = anchors[0]["quote"]
    lines = _lines(quote)
    if lines in COMMANDS[:-1]:
        return COMMANDS.index(lines)
    if (quote.startswith("En mode local[2], Spark utilise deux threads sur la machine.")
            and "permet pas de conclure sur les performances d’un cluster distribué." in quote):
        return len(COMMANDS) - 1
    return None


def lab_generation_rules(items, language, packet_checklist):
    language = language if language in NO_COMMAND else "English"
    groups = []
    for item, packet_item in zip(items, packet_checklist, strict=True):
        group = _source_group(item)
        if group is None:
            continue
        rules = {"item_id": packet_item["id"], "command_lines": COMMANDS[group],
                 "derived_sources": packet_item["sources"]}
        if group == 3:
            rules["expected_result_must_include"] = RUNTIME[language]
            rules["expected_result_instruction"] = (
                "In expected_result, put expected_result_must_include on its own plain-text line. "
                "Copy the whole sentence exactly, including capitalization, accents, apostrophe and period. "
                "Do not join it to another sentence with a conjunction or lowercase its initial letter. "
                "Explain that spark.version reports the Spark version installed in the runtime environment. "
                "Describe what the student should observe when they run the cell. "
                "Do not give a fixed version or claim the cell already ran."
            )
        if not COMMANDS[group]:
            rules["local_mode_instruction"] = (
                "For action, expected_result and checkpoint, use derived provenance and this group's derived_sources. "
                "The cited passage supports both the two threads on one machine and the limit on judging distributed "
                "cluster performance. Explain both in your own words. In the checkpoint, tell the student what to "
                "inspect or verify. Only the no-command placeholder is supplementary."
            )
        groups.append(rules)
    return {"groups": groups, "no_command_marker": NO_COMMAND[language],
            "instructions": (
                "For each item emit action, command_or_ui, expected_result and checkpoint, in that order, with its "
                "item number on every block. The first four command blocks are consecutive fragments of one Python "
                "cell. Copy only the listed lines into a Python code fence in each command_or_ui block, in order, "
                "exactly once. Use derived provenance and the group's packet-local derived_sources on every block "
                "except the command_or_ui block with empty command_lines: that block contains only no_command_marker "
                "and uses supplementary provenance with no sources. The source indexes are not the item numbers. "
                "Outside command blocks, use prose without code fences. Teach why each command is needed."
            )}


def draft_fingerprint(output):
    bound = [output.get(key) for key in ("logical_id", "content_version", "blocks", "sources")]
    return sha256(json.dumps(bound, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def verify_spark_setup(output, items, required_ids, candidates_by_block, *, raw_control=False):
    """Use exact PDF operations, per-block original IDs and already verified citation indexes."""
    ids = [item["item_id"] for item in items]
    blocks = output["blocks"]
    source_groups = [_source_group(item) for item in items]
    original = [item["anchors"][0] for item, group in zip(items, source_groups) if group is not None]
    canonical_sources = output["sources"]
    shape = (len(ids) == len(COMMANDS) and set(ids) == set(required_ids) and len(set(ids)) == len(ids)
             and source_groups == list(range(len(COMMANDS))) and len(blocks) == len(ids) * len(KINDS)
             and len({block["block_id"] for block in blocks}) == len(blocks)
             and all(block["kind"] == kind and candidates_by_block.get(block["block_id"]) == [item_id]
                     and bool(block["text"].strip()) and not block["hypothetical"] and not block["calculation"]
                     for block, (item_id, kind) in zip(blocks, ((i, k) for i in ids for k in KINDS))))
    language = output.get("language")
    language = language if language in NO_COMMAND else "English"
    actual, cell_parts = [], []
    for block in blocks:
        if block["kind"] != "command_or_ui":
            continue
        match = _FENCE.fullmatch(block["text"].strip())
        actual.append(_lines(match[1]) if match else () if block["text"].strip() == NO_COMMAND[language] else None)
        if match:
            cell_parts.append(match[1])
    flat = [line for group in actual if group is not None for line in group]
    checks = {key: all(flat.count(line) == 1 for line in lines) for key, lines in OPERATIONS}
    code_lines = {line for group in COMMANDS for line in group}
    clean_separation = all("```" not in block["text"] and not code_lines.intersection(_lines(block["text"]))
                           for block in blocks if block["kind"] != "command_or_ui")
    grounded = shape and all(
        (not block["source_indexes"] and not block["claims"] and block["provenance"] == "supplementary")
        if i == 17 else
        (block["provenance"] == "derived" and block["claims"] and
         all(type(index) is int and 1 <= index <= len(canonical_sources)
             and canonical_sources[index - 1] == original[i // len(KINDS)] for index in block["source_indexes"])
         and bool(block["source_indexes"]))
        for i, block in enumerate(blocks)
    )
    valid_syntax = bool(cell_parts)
    try:
        ast.parse("\n".join(cell_parts))
    except (SyntaxError, ValueError):
        valid_syntax = False
    checks.update({
        "complete_execution_order": actual == list(COMMANDS),
        "python_cell_syntax": valid_syntax,
        "separate_blocks": shape and clean_separation,
        "runtime_qualification": shape and RUNTIME[language] in blocks[14]["text"]
        and not any(_FIXED_VERSION.search(b["text"]) for b in blocks),
        "source_grounding": bool(grounded) and not (output["missing_item_ids"] or output["unverifiable_source"]
                              or output["interruptions"] or any(f["severity"] != "heuristic" for f in output["findings"])),
        "control_characters": not raw_control and not has_control_characters(blocks),
    })
    return {"contract": CONTRACT, "checks": checks, "original_item_ids": ids,
            "block_items": {b["block_id"]: candidates_by_block[b["block_id"]][0] for b in blocks} if shape else {},
            "draft_fingerprint": draft_fingerprint(output)}


def deterministic_passed(output):
    receipt = output.get("lab_verification") or {}
    checks = receipt.get("checks", {})
    return (receipt.get("contract") == CONTRACT and set(checks) == set(CHECK_IDS)
            and all(value is True for value in checks.values())
            and receipt.get("draft_fingerprint") == draft_fingerprint(output)
            and len(set(receipt.get("original_item_ids", ()))) == len(COMMANDS))


def lab_approval_passed(output):
    review = output.get("independent_review") or {}
    evidence = review.get("lab_evidence") or []
    verification = output.get("lab_verification") or {}
    ids = verification.get("original_item_ids", [])
    blocks = {block["block_id"]: block for block in output.get("blocks", ())}
    return (deterministic_passed(output) and review.get("provider_verified") is True and bool(review.get("provider_model"))
            and review.get("lab_evidence_reason") is None and review.get("pedagogy_score", 0) >= 2
            and output.get("verification") == "reviewed" and not review.get("findings")
            and not any(finding["severity"] != "heuristic" for finding in output.get("findings", ()))
            and not (output.get("missing_item_ids") or output.get("unverifiable_source") or output.get("interruptions"))
            and len(evidence) == len(PEDAGOGY)
            and all(row.get("item_id") == verification["block_items"].get(row.get("block_id"))
                    and (block := blocks.get(row.get("block_id"))) and block["kind"] != "command_or_ui"
                    and isinstance(row.get("quote"), str) and row["quote"] and row["quote"] in block["text"]
                    for row in evidence)
            and {(row.get("criterion"), row.get("item_id")) for row in evidence}
                == {(criterion, ids[group]) for criterion, group, _ in PEDAGOGY})
