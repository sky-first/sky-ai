# api/main.py
from __future__ import annotations

import os
from fastapi import FastAPI
from sqlalchemy import text

# Force local DB for local dev when a remote/stale DATABASE_URL is present.
# This project expects the AI Engine to read the same Postgres as the backend docker-compose.
_db_url = os.getenv("DATABASE_URL", "")
if not _db_url or "44.197.200.153" in _db_url or ":5433/" in _db_url:
    os.environ["DATABASE_URL"] = "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_saas_db"

from api.routes import connection_query, connection_discover  # noqa: E402
from api.routes import data_ingestion, pipeline  # noqa: E402
from core.logging_utils import log_event


app = FastAPI(
    title="DataAssistant API",
    version="0.1.0",
)


@app.on_event("startup")
async def on_startup():
    log_event("app_startup", {"message": "DataAssistant API started"})


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}


@app.get("/debug/db", tags=["debug"])
async def debug_db():
    """
    Local-dev helper to verify which DB the AI Engine is connected to.
    """
    from db.base import DATABASE_URL, engine

    safe_url = DATABASE_URL
    try:
        # redact password
        if "://" in safe_url and "@" in safe_url:
            prefix, rest = safe_url.split("://", 1)
            creds, hostpart = rest.split("@", 1)
            if ":" in creds:
                user, _pwd = creds.split(":", 1)
                safe_url = f"{prefix}://{user}:***@{hostpart}"
    except Exception:
        safe_url = "<redacted>"

    with engine.connect() as conn:
        total_meta = conn.execute(text("select count(*) from connection_metadata")).scalar_one()
        sample = conn.execute(
            text("select count(*) from connection_metadata where connection_id = CAST(:cid AS uuid)"),
            {"cid": "1fd6fee8-bf03-4e82-9c85-419a228ef726"},
        ).scalar_one()

    return {"database_url": safe_url, "connection_metadata_count": int(total_meta), "sample_connection_row": int(sample)}


# ===========================
# Engine-only API surface
# ===========================
# Este serviço (ia-do-projeto) é o "AI Engine" chamado pelo backend do produto.
# Para evitar duplicação com o backend principal (poc-02/backend), aqui expomos
# apenas endpoints necessários para:
# - queries de IA por connection_id
# - catálogo (tabelas/colunas) e refresh de metadados
# - pipeline/ingestion (interno)

# Rotas para queries e descoberta usando conexões diretamente
# IMPORTANTE: connection_query deve vir ANTES de connection_discover e data_ingestion
# para evitar conflitos de roteamento (todos usam prefix="/connections")
app.include_router(connection_query.router)
app.include_router(connection_discover.router)
app.include_router(data_ingestion.router)

# Rotas de pipeline
app.include_router(pipeline.router)