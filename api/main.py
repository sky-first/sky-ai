# api/main.py
from __future__ import annotations

import os
from fastapi import FastAPI
from sqlalchemy import text

# Force local DB for local dev when a remote/stale DATABASE_URL is present.
# This project expects the AI Engine to read the same Postgres as the backend docker-compose.
_db_url = os.getenv("DATABASE_URL", "")
if not _db_url or "44.197.200.153" in _db_url or ":5433/" in _db_url:
    os.environ["DATABASE_URL"] = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_saas_db"
    )

from api.routes import connection_query, connection_discover  # noqa: E402
from api.routes import (
    data_ingestion,
    pipeline,
    widget_titles,
    knowledge_graph,
    embeddings,
)  # noqa: E402
from api.routes import semantic_map, space_seed  # noqa: E402
from api.routes import scan_schedule  # noqa: E402
from core.logging_utils import log_event

app = FastAPI(
    title="DataAssistant API",
    version="0.1.0",
)

# --- OBSERVABILITY: START ---
# This configuration exposes latency metrics, request counts, and errors.
# The endpoint will be served at /metrics
try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
except ImportError:
    # If the lib is not installed in the local environment, it does not break execution
    log_event(
        "observability_init_failed",
        {"message": "prometheus_fastapi_instrumentator not found"},
    )
# --- OBSERVABILITY: FIM ---


@app.on_event("startup")
async def on_startup():
    log_event("app_startup", {"message": "DataAssistant API started"})

    # Initialize database (create tables if they don't exist)
    try:
        from db.base import init_db

        await init_db()
        log_event("db_initialized", {"message": "Database tables ensured"})
    except Exception as e:
        log_event(
            "db_init_error",
            {
                "error": str(e),
                "message": "Failed to initialize DB tables, will retry on demand",
            },
        )

    # Start audit flusher (separate thread, non-blocking)
    from core.security.audit import start_audit_flusher

    start_audit_flusher()
    log_event("audit_flusher_started", {"message": "Audit log flusher started"})

    # Initialize LangGraph Checkpoint Pool
    from core.agents.checkpoint_manager import get_connection_pool

    get_connection_pool()  # Init singleton
    log_event(
        "checkpoint_pool_initialized", {"message": "LangGraph checkpoint pool ready"}
    )


@app.on_event("shutdown")
async def on_shutdown():
    # Parar audit flusher e fazer flush final
    from core.security.audit import stop_audit_flusher

    stop_audit_flusher()
    log_event("audit_flusher_stopped", {"message": "Audit log flusher stopped"})

    # Close LangGraph Checkpoint Pool
    from core.agents.checkpoint_manager import close_pool

    close_pool()
    log_event("checkpoint_pool_closed", {"message": "LangGraph checkpoint pool closed"})


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}


@app.get("/debug/db", tags=["debug"])
async def debug_db():
    """
    Local-dev helper to verify which DB the AI Engine is connected to.
    """
    from db.base import DATABASE_URL, SessionLocal

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

    async with SessionLocal() as db:
        result = await db.execute(text("select count(*) from connection_metadata"))
        total_meta = result.scalar_one()
        result = await db.execute(
            text(
                "select count(*) from connection_metadata where connection_id = CAST(:cid AS uuid)"
            ),
            {"cid": "1fd6fee8-bf03-4e82-9c85-419a228ef726"},
        )
        sample = result.scalar_one()

    return {
        "database_url": safe_url,
        "connection_metadata_count": int(total_meta),
        "sample_connection_row": int(sample),
    }


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

# Widget routes (title suggestions)
app.include_router(widget_titles.router)

# Knowledge Graph (Strategy, Signals & Enterprise Context)
app.include_router(knowledge_graph.router)

# Knowledge Library embeddings (called by backend Celery worker)
app.include_router(embeddings.router)

# Semantic map + search (Universe Intelligence v2 — projects all
# visible embeddings to 2D/3D via UMAP, top-K cosine search for the
# RAG trace overlay). Called by the BE proxy on port 8000.
app.include_router(semantic_map.router)

# Per-Space seed-embeddings endpoint — fire-and-forget'd by the BE
# demo signup so a fresh demo Space lands with all 5 entity kinds
# (metrics + glossary + relationships + connections + agents) already
# embedded and visible on the Universe canvas.
app.include_router(space_seed.router)

# Scan schedule — PUT/GET/DELETE /spaces/{id}/scan-schedule + POST trigger (items 23-24)
app.include_router(scan_schedule.router)


@app.middleware("http")
async def tenant_context_middleware(request, call_next):
    """Bind the tenant (from ``X-Tenant-Slug``) to the contextvar for the
    whole request — Model B / Phase 5.

    Runs before route dependencies, so ``get_db()`` and the embeddings /
    ingestion paths can route their sessions to the tenant's own database
    via ``tenant_connection_manager``. When the flag is off or no slug is
    sent, the default context is bound and behaviour is unchanged.

    The registry lookup itself uses the platform-DB session
    (``AsyncSessionLocal`` from ``db.session``) — ``tenant_registry``
    lives there, not in the tenant DB.
    """
    from core.tenant_context import (
        DEFAULT_TENANT_CONTEXT,
        multi_tenant_enabled,
        reset_current_tenant,
        set_current_tenant,
    )

    slug = request.headers.get("x-tenant-slug")
    ctx = DEFAULT_TENANT_CONTEXT
    if multi_tenant_enabled() and slug:
        try:
            from db.session import AsyncSessionLocal
            from core.tenant_registry_lookup import lookup_tenant_by_slug

            async with AsyncSessionLocal() as session:
                resolved = await lookup_tenant_by_slug(session, slug.strip().lower())
            if resolved is not None:
                ctx = resolved
        except Exception:  # pragma: no cover — never block on tenant resolution
            ctx = DEFAULT_TENANT_CONTEXT

    token = set_current_tenant(ctx)
    try:
        return await call_next(request)
    finally:
        reset_current_tenant(token)
