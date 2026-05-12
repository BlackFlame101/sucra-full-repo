"""Notes for Agent Mémoire.

Mémoire is mostly **deterministic state-update logic**, not an LLM. We keep
this file for documentation symmetry with the other agents and reserve a
small optional LLM call for narrative summarisation later (not used in
MVP).
"""
from __future__ import annotations


# Thresholds used by the deterministic profile updater.
MASTERY_THRESHOLD = 0.8   # comprehension_score >= -> concept moves to mastered
FRAGILE_THRESHOLD = 0.4   # comprehension_score <= -> add to fragile


# History caps so the JSONB columns don't grow unbounded over a long session.
MAX_MISCONCEPTION_HISTORY = 30
MAX_BLOOM_HISTORY = 50
MAX_MASTERED = 50
MAX_FRAGILE = 50
