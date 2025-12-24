# api/routes/connection_discover.py
"""
Backend-compatible connection discovery/status endpoints.

In this project, the **backend** (sky-poc-backend) is the source-of-truth for the
catalog and stores it in `connection_metadata.tables` (JSON).

The AI service must NOT rely on the legacy `table_metadata` or `data_connections` tables
because it shares the backend DB schema, not the original AI Engine schema.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.logging_utils import log_event
from db.base import engine as db_engine
from db.session import get_db

router = APIRouter(prefix="/connections", tags=["connection_discover"])


def _load_connection_metadata_tables(engine, connection_id: str) -> List[Dict[str, Any]]:
    """
    Load tables catalog from backend `connection_metadata.tables` (JSON).
    Returns a list of dicts like: [{name, schema, columns:[...]}]
    """
    try:
        with engine.connect() as conn:
            tables = conn.execute(
                text("SELECT tables FROM connection_metadata WHERE connection_id = :cid"),
                {"cid": connection_id},
            ).scalar_one_or_none()

        if isinstance(tables, list):
            return [t for t in tables if isinstance(t, dict)]
        return []
    except Exception as e:
        log_event(
            "ai_connection_metadata_load_error",
            {"connection_id": connection_id, "error": str(e)[:500]},
        )
        return []


def _count_metadata_rows(tables: List[Dict[str, Any]]) -> int:
    # Count columns across tables (best-effort)
    total = 0
    for t in tables:
        cols = t.get("columns")
        if isinstance(cols, list):
            total += len([c for c in cols if isinstance(c, dict)])
    return total


def _get_last_metadata_update(engine, connection_id: str) -> Optional[datetime]:
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT last_metadata_update FROM connection_metadata WHERE connection_id = :cid"
                ),
                {"cid": connection_id},
            ).first()
        return row[0] if row else None
    except Exception:
        return None


def _discover_tables_sync(connection_id: str) -> dict:
    """
    Discovery is a no-op here: catalog is owned by the backend and already stored in DB.
    We just return current catalog counts, so the backend can treat this as successful.
    """
    engine = db_engine
    tables = _load_connection_metadata_tables(engine, connection_id)
    return {
        "success": True,
        "connection_id": connection_id,
        "source": "backend_connection_metadata",
        "metadata_rows_inserted": 0,
        "tables_discovered": len(tables),
        "metadata_rows": _count_metadata_rows(tables),
    }


@router.post("/{connection_id}/discover")
async def discover_tables(
    connection_id: str,
    space_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    run_in_background: bool = False,
) -> dict:
    """
    Descobre automaticamente todas as tabelas de uma DataConnection.
    
    Parâmetros:
    - connection_id: ID da conexão
    - space_id: ID do space (query parameter)
    - run_in_background: Se True, executa em background (default: False)
    
    Retorna:
    - metadata_rows_inserted: Número de colunas de metadados inseridas
    - tables_discovered: Número de tabelas descobertas
    
    Exemplo:
    POST /connections/{connection_id}/discover?space_id=xxx
    """
    try:
        # `space_id` is required by the backend contract, but catalog is keyed by connection_id.
        if run_in_background:
            background_tasks.add_task(_discover_tables_sync, connection_id=connection_id)
            return {
                "message": "Discovery scheduled (backend catalog source-of-truth).",
                "connection_id": connection_id,
                "space_id": space_id,
                "source": "backend_connection_metadata",
            }

        result = _discover_tables_sync(connection_id=connection_id)
        result["space_id"] = space_id
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao descobrir tabelas: {str(e)}")


@router.get("/{connection_id}/metadata-status")
async def metadata_status(
    connection_id: str,
    space_id: str = Query(..., description="ID do space (obrigatório)"),
    ttl_seconds: int = Query(
        21600,
        ge=0,
        description="TTL de metadados em segundos. Se 0, nunca considera stale.",
    ),
    db: Session = Depends(get_db),
) -> dict:
    """
    Retorna um status simples sobre a existência/freshness dos metadados para uma conexão.

    Usado pelo backend principal para evitar chamar /discover a cada pergunta.

    Retorna:
    - has_metadata: bool
    - metadata_rows: int
    - tables_discovered: int
    - last_metadata_update: ISO string | None
    - age_seconds: float | None
    - is_stale: bool
    - should_discover: bool (true quando não há metadados ou está stale)
    """
    engine = db_engine
    tables = _load_connection_metadata_tables(engine, connection_id)
    tables_discovered = len(tables)
    metadata_rows = _count_metadata_rows(tables)
    has_metadata = tables_discovered > 0

    last_update = _get_last_metadata_update(engine, connection_id)

    # 3) calcular stale
    age_seconds = None
    is_stale = False
    if ttl_seconds == 0:
        is_stale = False
    else:
        if last_update is not None:
            try:
                now = datetime.now(timezone.utc)
                # normaliza timezone
                if getattr(last_update, "tzinfo", None) is None:
                    last_update = last_update.replace(tzinfo=timezone.utc)
                age_seconds = (now - last_update).total_seconds()
                is_stale = age_seconds >= float(ttl_seconds)
            except Exception:
                age_seconds = None
                is_stale = False

    should_discover = (not has_metadata) or is_stale

    log_event(
        "metadata_status",
        {
            "connection_id": connection_id,
            "space_id": space_id,
            "has_metadata": has_metadata,
            "tables_discovered": tables_discovered,
            "metadata_rows": metadata_rows,
            "ttl_seconds": ttl_seconds,
            "is_stale": is_stale,
            "should_discover": should_discover,
        },
    )

    return {
        "connection_id": connection_id,
        "space_id": space_id,
        "has_metadata": has_metadata,
        "metadata_rows": metadata_rows,
        "tables_discovered": tables_discovered,
        "last_metadata_update": last_update.isoformat() if last_update else None,
        "age_seconds": age_seconds,
        "is_stale": is_stale,
        "should_discover": should_discover,
    }
