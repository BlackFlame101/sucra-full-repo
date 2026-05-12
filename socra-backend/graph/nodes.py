"""LangGraph node functions.

Each node is an ``async`` callable taking the :class:`SocraState` and
returning a (possibly partial) state dict. LangGraph merges that dict back
into the master state.

All four agents are now real implementations (Phases 4-7).
"""
from __future__ import annotations

import logging

from agents.diagnostiqueur import run_diagnostiqueur
from agents.evaluateur import run_evaluateur
from agents.memoire import run_memoire
from agents.tuteur_socratique import run_tuteur
from graph.state import SocraState


logger = logging.getLogger(__name__)


async def diagnostiqueur_node(state: SocraState) -> SocraState:
    return await run_diagnostiqueur(state)


async def tuteur_socratique_node(state: SocraState) -> SocraState:
    return await run_tuteur(state)


async def evaluateur_node(state: SocraState) -> SocraState:
    return await run_evaluateur(state)


async def memoire_node(state: SocraState) -> SocraState:
    return await run_memoire(state)
