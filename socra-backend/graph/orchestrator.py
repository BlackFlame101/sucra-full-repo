"""LangGraph state machine connecting the four Socra agents.

Edges::

    START
      ├─(is_first_message=True)──► diagnostiqueur ──► tuteur_socratique
      └─(is_first_message=False)─► tuteur_socratique
                                          │
                                  (should_evaluate=True)
                                          │
                                     evaluateur ──► memoire ──► END
                                          │
                                  (should_evaluate=False)
                                          │
                                         END
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from langgraph.graph import END, START, StateGraph

from graph.nodes import (
    diagnostiqueur_node,
    evaluateur_node,
    memoire_node,
    tuteur_socratique_node,
)
from graph.state import SocraState


def _route_entry(state: SocraState) -> Literal["diagnostiqueur", "tuteur_socratique"]:
    return "diagnostiqueur" if state.get("is_first_message") else "tuteur_socratique"


def _route_after_tuteur(state: SocraState) -> Literal["evaluateur", "__end__"]:
    signal = state.get("tutor_signal") or {}
    return "evaluateur" if signal.get("should_evaluate") else "__end__"


def build_graph():
    g = StateGraph(SocraState)

    g.add_node("diagnostiqueur", diagnostiqueur_node)
    g.add_node("tuteur_socratique", tuteur_socratique_node)
    g.add_node("evaluateur", evaluateur_node)
    g.add_node("memoire", memoire_node)

    g.add_conditional_edges(
        START,
        _route_entry,
        {
            "diagnostiqueur": "diagnostiqueur",
            "tuteur_socratique": "tuteur_socratique",
        },
    )

    g.add_edge("diagnostiqueur", "tuteur_socratique")

    g.add_conditional_edges(
        "tuteur_socratique",
        _route_after_tuteur,
        {
            "evaluateur": "evaluateur",
            "__end__": END,
        },
    )

    g.add_edge("evaluateur", "memoire")
    g.add_edge("memoire", END)

    return g.compile()


@lru_cache(maxsize=1)
def get_compiled_graph():
    return build_graph()
