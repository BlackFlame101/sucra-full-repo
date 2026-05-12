"""End-to-end smoke test for the LangGraph pipeline.

Runs a synthetic 'first message' through Diagnostiqueur → Tuteur (stub) →
END (because should_evaluate is False on the first turn). Then runs a
follow-up where should_evaluate is forced to True so the full pipeline
reaches Évaluateur and Mémoire stubs.

Usage::

    uv run python scripts/smoke_graph.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph.orchestrator import get_compiled_graph  # noqa: E402
from graph.state import SocraState  # noqa: E402


COURSE_ID = "a5159856-5479-4699-9f1b-b76ae04fb818"
SESSION_ID = "38634398-e270-42d8-b01e-e48af8ae73a8"
USER_ID = "83081579-8726-4cba-a30a-85dcc5296845"


async def first_turn() -> None:
    print("\n=== TURN 1 (first message — should hit Diagnostiqueur) ===")
    graph = get_compiled_graph()
    state: SocraState = {
        "session_id": SESSION_ID,
        "course_id": COURSE_ID,
        "user_id": USER_ID,
        "messages": [],
        "student_message": "I want to learn about star schemas in data warehousing.",
        "is_first_message": True,
    }
    final = await graph.ainvoke(state)
    diag = final.get("diagnostic", {})
    print(f"current_node:           {final.get('current_node')!r}")
    print(f"diagnostic.topic:       {diag.get('topic')!r}")
    print(f"diagnostic.level:       {diag.get('initial_level')!r}")
    print(f"diagnostic.gaps:        {diag.get('identified_gaps')}")
    print(f"diagnostic.prereqs:     {diag.get('prerequisite_concepts')}")
    print(f"first_socratic_q:       {diag.get('first_socratic_question')!r}")
    print(f"streamed_response:      {final.get('streamed_response')!r}")


async def follow_up_turn() -> None:
    print("\n=== TURN 2 (follow-up with should_evaluate forced True) ===")
    # Build a custom graph where the tuteur node sets should_evaluate=True
    from graph.state import SocraState as _S

    async def tuteur_with_eval(state: _S) -> _S:
        return {
            **state,
            "tutor_signal": {
                "response_text": "Why might that distinction matter for query speed?",
                "bloom_level": "analyze",
                "should_evaluate": True,
                "key_concepts_mentioned": ["fact table", "dimension table"],
            },
            "streamed_response": "Why might that distinction matter for query speed?",
            "current_node": "tuteur_socratique",
        }

    from langgraph.graph import END, START, StateGraph
    from graph.nodes import diagnostiqueur_node, evaluateur_node, memoire_node

    g = StateGraph(_S)
    g.add_node("diagnostiqueur", diagnostiqueur_node)
    g.add_node("tuteur_socratique", tuteur_with_eval)
    g.add_node("evaluateur", evaluateur_node)
    g.add_node("memoire", memoire_node)

    def _route_entry(state):
        return "diagnostiqueur" if state.get("is_first_message") else "tuteur_socratique"

    def _route_after_tuteur(state):
        sig = state.get("tutor_signal") or {}
        return "evaluateur" if sig.get("should_evaluate") else "__end__"

    g.add_conditional_edges(START, _route_entry, {
        "diagnostiqueur": "diagnostiqueur",
        "tuteur_socratique": "tuteur_socratique",
    })
    g.add_edge("diagnostiqueur", "tuteur_socratique")
    g.add_conditional_edges("tuteur_socratique", _route_after_tuteur, {
        "evaluateur": "evaluateur",
        "__end__": END,
    })
    g.add_edge("evaluateur", "memoire")
    g.add_edge("memoire", END)
    compiled = g.compile()

    state: SocraState = {
        "session_id": SESSION_ID,
        "course_id": COURSE_ID,
        "user_id": USER_ID,
        "messages": [
            {"role": "assistant", "content": "What do you already know about star schemas?"},
            {"role": "user", "content": "A star schema has a central fact table connected to dimension tables."},
        ],
        "student_message": "A star schema has a central fact table connected to dimension tables.",
        "is_first_message": False,
    }
    final = await compiled.ainvoke(state)
    print(f"current_node:    {final.get('current_node')!r}")
    print(f"tutor_signal:    {final.get('tutor_signal')}")
    print(f"evaluation:      {final.get('evaluation')}")
    print(f"profile:         {final.get('profile')}")


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    await first_turn()
    await follow_up_turn()


if __name__ == "__main__":
    asyncio.run(main())
