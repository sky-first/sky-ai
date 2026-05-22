# api/routes/data_ingestion.py
"""
Endpoints para ingestão de dados, metadados e geração de embeddings.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional

from api.schemas import IngestMetadataRequest, GenerateEmbeddingsRequest
from core.ingestion.service import (
    run_metadata_ingestion,
    run_metadata_embeddings,
    run_full_refresh_for_connection,
    ConnectionNotFoundError,
    SpaceNotFoundError,
)
from core.llm.factory import create_embedding_provider
from core.logging_utils import log_event
from db.session import get_db

router = APIRouter(prefix="/connections", tags=["data_ingestion"])


@router.post("/{connection_id}/ingest-metadata")
async def ingest_metadata(
    connection_id: str,
    space_id: str,
    request: Optional[IngestMetadataRequest] = None,
    db: Session = Depends(get_db),
    run_in_background: bool = False,
    background_tasks: BackgroundTasks = None,
) -> dict:
    """
    Ingere metadados de tabelas de uma conexão.

    Parâmetros:
    - connection_id: ID da conexão
    - space_id: ID do space (query parameter)
    - crew_id: ID do crew (opcional, no body)
    - run_in_background: Se True, executa em background (default: False)

    Retorna:
    - metadata_rows_inserted: Número de linhas de metadados inseridas
    """
    crew_id = request.crew_id if request else None

    try:
        if run_in_background and background_tasks:
            # Executar em background
            background_tasks.add_task(
                run_metadata_ingestion,
                db=db,
                space_id=space_id,
                connection_id=connection_id,
                crew_id=crew_id,
            )
            return {
                "message": "Ingestão de metadados iniciada em background",
                "connection_id": connection_id,
                "space_id": space_id,
            }
        else:
            # Executar síncrono
            inserted = await run_metadata_ingestion(
                db=db,
                space_id=space_id,
                connection_id=connection_id,
                crew_id=crew_id,
            )
            return {
                "success": True,
                "connection_id": connection_id,
                "space_id": space_id,
                "metadata_rows_inserted": inserted,
            }
    except ConnectionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except SpaceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Erro ao ingerir metadados: {str(e)}"
        )


@router.post("/{connection_id}/generate-embeddings")
async def generate_embeddings(
    connection_id: str,
    space_id: str,
    request: Optional[GenerateEmbeddingsRequest] = None,
    db: Session = Depends(get_db),
    run_in_background: bool = False,
    background_tasks: BackgroundTasks = None,
) -> dict:
    """
    Gera embeddings para metadados de uma conexão.

    Parâmetros:
    - connection_id: ID da conexão
    - space_id: ID do space (query parameter)
    - crew_id: ID do crew (opcional, no body)
    - run_in_background: Se True, executa em background (default: False)

    Retorna:
    - embeddings_created: Número de embeddings criados
    """
    crew_id = request.crew_id if request else None
    embedding_provider = create_embedding_provider()

    try:
        if run_in_background and background_tasks:
            # Executar em background
            background_tasks.add_task(
                run_metadata_embeddings,
                db=db,
                space_id=space_id,
                connection_id=connection_id,
                crew_id=crew_id,
                embedding_provider=embedding_provider,
            )
            return {
                "message": "Geração de embeddings iniciada em background",
                "connection_id": connection_id,
                "space_id": space_id,
            }
        else:
            # Executar síncrono
            created = await run_metadata_embeddings(
                db=db,
                space_id=space_id,
                connection_id=connection_id,
                crew_id=crew_id,
                embedding_provider=embedding_provider,
            )
            return {
                "success": True,
                "connection_id": connection_id,
                "space_id": space_id,
                "embeddings_created": created,
            }
    except ConnectionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except SpaceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Erro ao gerar embeddings: {str(e)}"
        )


@router.post("/{connection_id}/full-refresh")
async def full_refresh(
    connection_id: str,
    space_id: str,
    request: Optional[IngestMetadataRequest] = None,
    db: Session = Depends(get_db),
    run_in_background: bool = False,
    background_tasks: BackgroundTasks = None,
) -> dict:
    """
    Executa refresh completo: ingestão de metadados + geração de embeddings.

    Parâmetros:
    - connection_id: ID da conexão
    - space_id: ID do space (query parameter)
    - crew_id: ID do crew (opcional, no body)
    - run_in_background: Se True, executa em background (default: False)

    Retorna:
    - metadata_rows_inserted: Número de linhas de metadados inseridas
    - embeddings_created: Número de embeddings criados
    """
    crew_id = request.crew_id if request else None
    embedding_provider = create_embedding_provider()

    try:
        if run_in_background and background_tasks:
            # Executar em background
            background_tasks.add_task(
                run_full_refresh_for_connection,
                db=db,
                space_id=space_id,
                connection_id=connection_id,
                crew_id=crew_id,
                embedding_provider=embedding_provider,
            )
            return {
                "message": "Refresh completo iniciado em background",
                "connection_id": connection_id,
                "space_id": space_id,
            }
        else:
            # Executar síncrono
            summary = await run_full_refresh_for_connection(
                db=db,
                space_id=space_id,
                connection_id=connection_id,
                crew_id=crew_id,
                embedding_provider=embedding_provider,
            )
            return {
                "success": True,
                "connection_id": connection_id,
                "space_id": space_id,
                **summary,
            }
    except ConnectionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except SpaceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Erro ao executar refresh completo: {str(e)}"
        )
