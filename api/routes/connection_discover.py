# api/routes/connection_discover.py
"""
Endpoint para descobrir automaticamente tabelas de uma DataConnection.
Pode ser chamado manualmente ou automaticamente após criar uma conexão.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
import os
import json
from datetime import datetime, timezone

from core.ingestion.db_metadata import ingest_metadata_for_connection
from core.logging_utils import log_event
from db.session import get_db
from db.base import engine as db_engine

router = APIRouter(prefix="/connections", tags=["connection_discover"])


def _discover_tables_sync(
    db: Session,
    space_id: str,
    connection_id: str,
) -> dict:
    """
    Função síncrona para descobrir tabelas.
    Pode ser chamada em background ou diretamente.
    """
    # Reuse the app's configured SQLAlchemy engine (it loads .env defaults safely).
    engine = db_engine
    
    # Buscar conexão e space via SQL raw
    with engine.connect() as conn:
        conn_result = conn.execute(
            text("SELECT id, name, connector_id, config FROM data_connections WHERE id = :id"),
            {"id": connection_id}
        ).first()
        
        if not conn_result:
            raise ValueError(f"Conexão {connection_id} não encontrada")
        
        space_result = conn.execute(
            text("SELECT id, name FROM spaces WHERE id = :id"),
            {"id": space_id}
        ).first()
        
        if not space_result:
            raise ValueError(f"Space {space_id} não encontrado")
    
    # Criar objetos temporários
    class TempDataConnection:
        def __init__(self, id, name, type, config):
            self.id = id
            self.name = name
            self.type = type
            self.config = config if isinstance(config, dict) else json.loads(config) if isinstance(config, str) else {}
    
    class TempSpace:
        def __init__(self, id, name):
            self.id = id
            self.name = name
    
    data_conn = TempDataConnection(
        id=str(conn_result[0]),
        name=conn_result[1],
        type=conn_result[2] or "bigquery",
        config=conn_result[3] if isinstance(conn_result[3], dict) else json.loads(conn_result[3]) if isinstance(conn_result[3], str) else {}
    )
    
    space = TempSpace(id=str(space_result[0]), name=space_result[1])
    
    # Executar descoberta
    try:
        num_inserted = ingest_metadata_for_connection(
            db=db,
            data_connection=data_conn,
            space=space,
            crew_id=None
        )

        # Atualizar timestamp de metadados (se a coluna existir no schema real)
        try:
            db.execute(
                text(
                    """
                    UPDATE data_connections
                    SET last_metadata_update = NOW()
                    WHERE id = :id
                    """
                ),
                {"id": connection_id},
            )
            db.commit()
        except Exception:
            # Alguns ambientes podem não ter a coluna; não quebrar o fluxo.
            db.rollback()

        # Limpar erro/status quando a descoberta roda com sucesso
        try:
            db.execute(
                text(
                    """
                    UPDATE data_connections
                    SET status = 'active',
                        error = NULL,
                        updated_at = NOW()
                    WHERE id = :id
                    """
                ),
                {"id": connection_id},
            )
            db.commit()
        except Exception:
            db.rollback()
        
        # Contar tabelas descobertas
        result = db.execute(
            text("""
                SELECT COUNT(DISTINCT table_name) as num_tables
                FROM table_metadata 
                WHERE space_id = :space_id AND data_connection_id = :conn_id
            """),
            {"space_id": space_id, "conn_id": connection_id}
        ).first()
        
        num_tables = result[0] if result else 0
        
        return {
            "success": True,
            "connection_id": connection_id,
            "space_id": space_id,
            "metadata_rows_inserted": num_inserted,
            "tables_discovered": num_tables,
        }
    except Exception as e:
        log_event(
            "discover_tables_error",
            {
                "connection_id": connection_id,
                "space_id": space_id,
                "error": str(e)[:500],
            },
        )
        # Persistir erro na connection para a UI/backend enxergarem o motivo
        try:
            db.execute(
                text(
                    """
                    UPDATE data_connections
                    SET status = 'error',
                        error = :err,
                        updated_at = NOW()
                    WHERE id = :id
                    """
                ),
                {
                    "id": connection_id,
                    "err": json.dumps(
                        {
                            "message": str(e)[:500],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ),
                },
            )
            db.commit()
        except Exception:
            db.rollback()
        raise


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
        if run_in_background:
            # Executar em background
            background_tasks.add_task(
                _discover_tables_sync,
                db=db,
                space_id=space_id,
                connection_id=connection_id,
            )
            return {
                "message": "Descoberta iniciada em background",
                "connection_id": connection_id,
                "space_id": space_id,
            }
        else:
            # Executar síncrono
            result = _discover_tables_sync(
                db=db,
                space_id=space_id,
                connection_id=connection_id,
            )
            return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao descobrir tabelas: {str(e)}"
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
    # 1) Contagens em table_metadata (fonte de verdade do catálogo)
    row = db.execute(
        text(
            """
            SELECT
              COUNT(*) AS metadata_rows,
              COUNT(DISTINCT table_name) AS tables_discovered
            FROM table_metadata
            WHERE space_id = :space_id AND data_connection_id = :conn_id
            """
        ),
        {"space_id": space_id, "conn_id": connection_id},
    ).first()

    metadata_rows = int(row[0] or 0) if row else 0
    tables_discovered = int(row[1] or 0) if row else 0
    has_metadata = tables_discovered > 0

    # 2) last_metadata_update (se existir no schema)
    last_update = None
    try:
        upd = db.execute(
            text("SELECT last_metadata_update FROM data_connections WHERE id = :id"),
            {"id": connection_id},
        ).first()
        if upd:
            last_update = upd[0]
    except Exception:
        # coluna pode não existir em alguns schemas antigos
        last_update = None

    # 3) calcular stale
    age_seconds = None
    is_stale = False
    if ttl_seconds == 0:
        is_stale = False
    else:
        if last_update is None:
            # se não temos timestamp, mas já tem metadados, não marca stale automaticamente
            # (evita discover infinito em ambientes que não têm last_metadata_update).
            is_stale = False
        else:
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
