"""FastAPI entry point for the Socra multi-agent backend.

Run locally with::

    uv run uvicorn main:app --reload
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import websocket as ws_routes
from api.routes import health
from api.routes import documents
from api.routes import exams
from config import get_settings


settings = get_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("socra-backend")


app = FastAPI(
    title="Socra Backend",
    version="0.1.0",
    description=(
        "Multi-agent Socra tutoring backend. FastAPI + LangGraph orchestrating "
        "Diagnostiqueur, Tuteur Socratique, Évaluateur, Générateur d'exercices, "
        "Correcteur, and Mémoire agents."
    ),
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(health.router)
app.include_router(documents.router)
app.include_router(exams.router)
app.include_router(ws_routes.router)


@app.on_event("startup")
async def _on_startup() -> None:
    logger.info("Socra backend starting on port %s", settings.backend_port)
    logger.info("Frontend allowed origin: %s", settings.frontend_url)
    logger.info("Chat model: %s | embedding: %s (%d-dim)", settings.chat_model,
                settings.embedding_model, settings.embedding_dim)
