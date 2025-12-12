# api/routes/connection_discover.py
"""
Endpoint para descobrir automaticamente tabelas de uma DataConnection.
Pode ser chamado manualmente ou automaticamente após criar uma conexão.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text, create_engine
import os
import json

from core.ingestion.db_metadata import ingest_metadata_for_connection
from core.logging_utils import log_event
from db.session import get_db

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
    engine = create_engine(os.getenv('DATABASE_URL'), future=True)
    
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
