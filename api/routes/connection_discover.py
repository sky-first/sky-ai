# api/routes/connection_discover.py
"""
Backend-compatible connection discovery/status endpoints.

In this project, the **backend** (sky-poc-backend) is the source-of-truth for the
catalog and stores it in `connection_metadata.tables` (JSON).

The AI service must NOT rely on the legacy `table_metadata` or `data_connections` tables
because it shares the backend DB schema, not the original AI Engine schema.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging_utils import log_event
from db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connections", tags=["connection_discover"])


async def _load_connection_metadata_tables(
    db: AsyncSession, connection_id: str
) -> List[Dict[str, Any]]:
    """
    Load tables catalog from backend `connection_metadata.tables` (JSON).
    Returns a list of dicts like: [{name, schema, columns:[...]}]
    """
    try:
        result = await db.execute(
            text("SELECT tables FROM connection_metadata WHERE connection_id = :cid"),
            {"cid": connection_id},
        )
        tables = result.scalar_one_or_none()

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


async def _get_last_metadata_update(
    db: AsyncSession, connection_id: str
) -> Optional[datetime]:
    try:
        result = await db.execute(
            text(
                "SELECT last_metadata_update FROM connection_metadata WHERE connection_id = :cid"
            ),
            {"cid": connection_id},
        )
        row = result.first()
        return row[0] if row else None
    except Exception:
        return None


async def _discover_tables_sync(db: AsyncSession, connection_id: str) -> dict:
    """
    Discovery is a no-op here: catalog is owned by the backend and already stored in DB.
    We just return current catalog counts, so the backend can treat this as successful.
    """
    tables = await _load_connection_metadata_tables(db, connection_id)
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
    background_tasks: BackgroundTasks,
    space_id: Optional[str] = Query(None, description="Optional space ID for scoping"),
    table_names: Optional[List[str]] = Query(
        None, description="Optional list of specific tables to sync (granular sync)"
    ),
    db: AsyncSession = Depends(get_db),
    run_in_background: bool = False,
    auto_generate_embeddings: bool = True,  # ✅ ENABLED: Auto-generate embeddings on discover
    skip_if_recent_seconds: int = Query(
        300,
        description=(
            "Race-protection: skip the discover when connection_metadata "
            "was updated less than N seconds ago. Set to 0 to force a "
            "re-run (e.g. after a manual schema change)."
        ),
    ),
) -> dict:
    """
    Descobre automaticamente todas as tabelas de uma DataConnection.
    Por padrão, também gera embeddings automaticamente após descobrir os metadados.

    Parâmetros:
    - connection_id: ID da conexão
    - space_id: ID do space (query parameter, opcional)
    - run_in_background: Se True, executa em background (default: False)
    - auto_generate_embeddings: Se True, gera embeddings automaticamente após descobrir (default: True)
    """
    try:
        from core.ingestion.service import (
            run_metadata_ingestion,
            run_metadata_embeddings,
        )
        from core.llm.factory import create_embedding_provider

        # Race-protection: when N concurrent demo signups fire
        # discover_connection at the same time, each one would
        # DELETE+INSERT the same NULL-keyed table_metadata rows and
        # leave brief windows of zero rows that an in-flight RAG
        # query could see. Skip when last_metadata_update is fresher
        # than the threshold (default 5min).
        if skip_if_recent_seconds and skip_if_recent_seconds > 0:
            try:
                from sqlalchemy import text as _text

                row = (
                    (
                        await db.execute(
                            _text(
                                "SELECT EXTRACT(EPOCH FROM (NOW() - last_metadata_update))::int AS age "
                                "FROM connection_metadata WHERE connection_id = CAST(:cid AS uuid)"
                            ),
                            {"cid": connection_id},
                        )
                    )
                    .mappings()
                    .first()
                )
                if (
                    row
                    and row["age"] is not None
                    and row["age"] < skip_if_recent_seconds
                ):
                    log_event(
                        "discover_skipped_recent",
                        {
                            "connection_id": connection_id,
                            "space_id": space_id,
                            "age_seconds": int(row["age"]),
                            "threshold": skip_if_recent_seconds,
                        },
                    )
                    return {
                        "message": "Discovery skipped — recent metadata exists.",
                        "connection_id": connection_id,
                        "space_id": space_id,
                        "skipped_reason": "recent_metadata",
                        "age_seconds": int(row["age"]),
                    }
            except Exception:
                # If the freshness check fails (e.g. connection_metadata
                # row doesn't exist yet — first run), fall through to
                # the actual discover. Better to over-run than to
                # silently no-op on a fresh connection.
                try:
                    await db.rollback()
                except Exception:
                    pass

        # `space_id` is required by the backend contract, but catalog is keyed by connection_id.
        if run_in_background:
            # Capture the tenant resolved for THIS request. The tenant
            # middleware resets the contextvar once the response is sent,
            # so the FastAPI BackgroundTask below would otherwise run with
            # the default context and write metadata/embeddings to the
            # platform DB instead of the tenant's own DB (Model B). We
            # re-bind it at the start of the task and open the session via
            # the tenant connection manager.
            from core.tenant_context import current_tenant, set_current_tenant
            from core.tenant_db import tenant_connection_manager

            _tenant_ctx = current_tenant()

            async def _discover_and_embed():
                set_current_tenant(_tenant_ctx)

                async with tenant_connection_manager.async_session_for(
                    _tenant_ctx
                ) as bg_db:
                    try:
                        await _discover_tables_sync(bg_db, connection_id=connection_id)
                        if auto_generate_embeddings:
                            try:
                                # Ingerir metadados na tabela table_metadata (se necessário)
                                await run_metadata_ingestion(
                                    db=bg_db,
                                    connection_id=connection_id,
                                    space_id=space_id,
                                    crew_id=None,
                                    table_names=table_names,
                                )
                                # Gerar embeddings
                                embedding_provider = create_embedding_provider()
                                await run_metadata_embeddings(
                                    db=bg_db,
                                    connection_id=connection_id,
                                    space_id=space_id,
                                    crew_id=None,
                                    embedding_provider=embedding_provider,
                                    table_names=table_names,
                                )
                                # ✅ OPTION 1: Enrich with date ranges
                                from core.ingestion.enrichment import (
                                    enrich_table_date_ranges,
                                )

                                await enrich_table_date_ranges(
                                    db=bg_db, connection_id=connection_id
                                )
                                # Dataset-level description embeddings (item 16)
                                from core.ingestion.service import (
                                    run_dataset_description_embeddings,
                                )

                                await run_dataset_description_embeddings(
                                    db=bg_db,
                                    connection_id=connection_id,
                                    space_id=space_id,
                                    embedding_provider=embedding_provider,
                                )
                                # Item 32: strategic onboarding — suggest OKRs when brain is empty
                                if space_id:
                                    try:
                                        from core.agents.strategic_onboarding import (
                                            is_brain_empty,
                                            suggest_okrs_from_datasets,
                                            save_okr_suggestions,
                                        )

                                        if await is_brain_empty(bg_db, space_id):
                                            _bg_tables = (
                                                await _load_connection_metadata_tables(
                                                    bg_db, connection_id
                                                )
                                            )
                                            _bg_names = [
                                                t.get("name") or t.get("table_name", "")
                                                for t in _bg_tables
                                                if isinstance(t, dict)
                                            ]
                                            from core.llm.factory import (
                                                create_llm_orchestrator,
                                            )

                                            _bg_llm = create_llm_orchestrator()
                                            _bg_sugg = suggest_okrs_from_datasets(
                                                _bg_names, _bg_llm
                                            )
                                            await save_okr_suggestions(
                                                bg_db, space_id, _bg_sugg
                                            )
                                    except Exception as _bg_onb_exc:
                                        logger.debug(
                                            "bg strategic_onboarding failed: %s",
                                            _bg_onb_exc,
                                        )
                            except Exception as e:
                                # ✅ PATCH 2: CRITICAL - Rollback em background task também
                                try:
                                    await bg_db.rollback()
                                except Exception:
                                    pass

                                log_event(
                                    "discover_auto_embed_error",
                                    {
                                        "connection_id": connection_id,
                                        "space_id": space_id,
                                        "error": str(e)[:500],
                                    },
                                )
                    except Exception as e:
                        log_event(
                            "discover_background_error",
                            {
                                "connection_id": connection_id,
                                "space_id": space_id,
                                "error": str(e)[:500],
                            },
                        )

            background_tasks.add_task(_discover_and_embed)

            return {
                "message": "Discovery scheduled (backend catalog source-of-truth).",
                "connection_id": connection_id,
                "space_id": space_id,
                "source": "backend_connection_metadata",
                "auto_generate_embeddings": auto_generate_embeddings,
            }

        result = await _discover_tables_sync(db, connection_id=connection_id)
        result["space_id"] = space_id

        # Gerar embeddings automaticamente se solicitado
        if auto_generate_embeddings:
            try:
                # Ingerir metadados na tabela table_metadata (se necessário)
                inserted = await run_metadata_ingestion(
                    db=db,
                    connection_id=connection_id,
                    space_id=space_id,
                    crew_id=None,
                    table_names=table_names,
                )

                # Gerar embeddings
                embedding_provider = create_embedding_provider()
                created = await run_metadata_embeddings(
                    db=db,
                    connection_id=connection_id,
                    space_id=space_id,
                    crew_id=None,
                    embedding_provider=embedding_provider,
                    table_names=table_names,
                )

                # ✅ OPTION 1: Enrich with date ranges
                from core.ingestion.enrichment import enrich_table_date_ranges

                enriched_count = await enrich_table_date_ranges(
                    db=db, connection_id=connection_id
                )
                # Dataset-level description embeddings (item 16)
                from core.ingestion.service import run_dataset_description_embeddings

                dataset_emb_count = await run_dataset_description_embeddings(
                    db=db,
                    connection_id=connection_id,
                    space_id=space_id,
                    embedding_provider=embedding_provider,
                )

                result["embeddings_created"] = created
                result["metadata_rows_inserted"] = inserted
                result["temporal_enrichment_count"] = enriched_count
                result["dataset_embeddings_created"] = dataset_emb_count

                # Item 32: strategic onboarding — suggest OKRs when brain is empty
                if space_id:
                    try:
                        from core.agents.strategic_onboarding import (
                            is_brain_empty,
                            suggest_okrs_from_datasets,
                            save_okr_suggestions,
                        )

                        if await is_brain_empty(db, space_id):
                            _tables = await _load_connection_metadata_tables(
                                db, connection_id
                            )
                            _table_names = [
                                t.get("name") or t.get("table_name", "")
                                for t in _tables
                                if isinstance(t, dict)
                            ]
                            from core.llm.factory import create_llm_orchestrator

                            _llm = create_llm_orchestrator()
                            _suggestions = suggest_okrs_from_datasets(
                                _table_names, _llm
                            )
                            await save_okr_suggestions(db, space_id, _suggestions)
                            result["okr_suggestions"] = _suggestions
                            log_event(
                                "strategic_onboarding_suggestions",
                                {"space_id": space_id, "count": len(_suggestions)},
                            )
                    except Exception as _onb_exc:
                        logger.debug(
                            "strategic_onboarding failed (non-critical): %s", _onb_exc
                        )

                log_event(
                    "discover_auto_embed_success",
                    {
                        "connection_id": connection_id,
                        "space_id": space_id,
                        "embeddings_created": created,
                        "metadata_inserted": inserted,
                    },
                )
            except Exception as e:
                # ✅ PATCH 2: CRITICAL - Rollback para não deixar transação abortada
                try:
                    await db.rollback()
                except Exception:
                    pass

                log_event(
                    "discover_auto_embed_error",
                    {
                        "connection_id": connection_id,
                        "space_id": space_id,
                        "error": str(e)[:500],
                    },
                )
                # Não falha o discover se embeddings falharem
                result["embeddings_created"] = 0
                result["embedding_error"] = str(e)[:200]

        return result
    except Exception as e:
        # Log technical details internally
        logger.error(
            "Table discovery failed",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "connection_id": connection_id,
                "space_id": space_id,
            },
        )

        # User-friendly message (NO database/connection details)
        raise HTTPException(
            status_code=500,
            detail="Unable to load data source information. Please try again or contact support.",
        )


@router.get("/{connection_id}/metadata-status")
async def metadata_status(
    connection_id: str,
    space_id: str = Query(..., description="ID do space (obrigatório)"),
    ttl_seconds: int = Query(
        21600,
        ge=0,
        description="TTL de metadados em segundos. Se 0, nunca considera stale.",
    ),
    db: AsyncSession = Depends(get_db),
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
    tables = await _load_connection_metadata_tables(db, connection_id)
    tables_discovered = len(tables)
    metadata_rows = _count_metadata_rows(tables)
    has_metadata = tables_discovered > 0

    last_update = await _get_last_metadata_update(db, connection_id)

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
