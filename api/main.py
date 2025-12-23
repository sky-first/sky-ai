# api/main.py
from __future__ import annotations

from fastapi import FastAPI

from api.routes import connection_query, connection_discover
from api.routes import data_ingestion, pipeline
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