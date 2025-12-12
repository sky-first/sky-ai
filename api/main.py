# api/main.py
from __future__ import annotations

from fastapi import FastAPI

from api.routes import agents
from api.routes import connection_query, connection_discover
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


# Inclui rotas de agentes
app.include_router(agents.router)
# Rotas para queries e descoberta usando conexões diretamente
app.include_router(connection_query.router)
app.include_router(connection_discover.router)