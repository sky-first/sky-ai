# api/routes/pipeline.py
"""
Endpoints para execução de pipeline de IA de forma assíncrona.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid
import json

from api.schemas import QueryRequest, QueryResponse
from core.logging_utils import log_event
from db.session import get_db
from db.models import PipelineJob

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

async def _update_job(job_id: str, updates: Dict[str, Any], db_session: AsyncSession = None):
    """Update job status helper."""
    if db_session:
        stmt = update(PipelineJob).where(PipelineJob.id == job_id).values(**updates)
        await db_session.execute(stmt)
        await db_session.commit()
    else:
        # Create a new session if none provided (for background tasks)
        from db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            stmt = update(PipelineJob).where(PipelineJob.id == job_id).values(**updates)
            await session.execute(stmt)
            await session.commit()

async def _append_log(job_id: str, message: str, level: str = "info", db_session: AsyncSession = None):
    """Append a log entry to the job."""
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "level": level,
        "message": message
    }
    
    # We need to fetch current logs, append, and save back
    # This is not atomic but sufficient for this use case
    if db_session:
        result = await db_session.execute(select(PipelineJob.logs).where(PipelineJob.id == job_id))
        current_logs = result.scalar() or []
        current_logs.append(log_entry)
        
        await _update_job(job_id, {"logs": current_logs}, db_session)
    else:
        from db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(PipelineJob.logs).where(PipelineJob.id == job_id))
            current_logs = result.scalar() or []
            current_logs.append(log_entry)
            
            # Update directly in this session to avoid double commit overhead via _update_job
            stmt = update(PipelineJob).where(PipelineJob.id == job_id).values(logs=current_logs)
            await session.execute(stmt)
            await session.commit()


@router.post("/execute")
async def execute_pipeline(
    body: QueryRequest,
    connection_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = None,
    run_async: bool = True,
) -> dict:
    """
    Executa o pipeline de IA de forma assíncrona ou síncrona.
    Estado é persistido no banco de dados.
    """
    pipeline_id = str(uuid.uuid4())
    
    # Create initial job record
    new_job = PipelineJob(
        id=pipeline_id,
        status="pending",
        user_id=None, # TODO: Extract from auth context if available
        connection_id=uuid.UUID(connection_id) if connection_id else None,
        logs=[],
        created_at=datetime.utcnow()
    )
    
    db.add(new_job)
    await db.commit()
    
    async def _execute_pipeline_task():
        """Executa o pipeline em background"""
        from db.session import AsyncSessionLocal
        
        # Use a fresh session for background execution
        async with AsyncSessionLocal() as bg_db:
            try:
                # Update status to running
                await _update_job(pipeline_id, {"status": "running"}, bg_db)
                await _append_log(pipeline_id, "Pipeline iniciado", "info", bg_db)
                
                # Import here to avoid circular imports
                from api.routes.connection_query import query_connection
                from api.routes.agents import query_agent
                
                result_data = None
                
                if connection_id:
                    # Usar connection_query
                    result = await query_connection(
                        connection_id=connection_id,
                        body=body,
                        db=bg_db,
                    )
                    result_data = {
                        "answer": result.answer,
                        "data_sample": result.data_sample,
                        "meta": result.meta.dict() if hasattr(result.meta, 'dict') else result.meta,
                    }
                elif agent_id:
                    # Usar agent query
                    result = await query_agent(
                        agent_id=agent_id,
                        body=body,
                        db=bg_db,
                    )
                    result_data = {
                        "answer": result.answer,
                        "data_sample": result.data_sample,
                        "meta": result.meta.dict() if hasattr(result.meta, 'dict') else result.meta,
                    }
                else:
                    raise ValueError("connection_id ou agent_id deve ser fornecido")
                
                # Serialização de result_data para JSON compatível
                # Pydantic models need .dict() or .model_dump()
                # Assuming result is QueryResponse pydantic model
                
                await _update_job(pipeline_id, {
                    "status": "completed",
                    "result": result_data
                }, bg_db)
                
                await _append_log(pipeline_id, "Pipeline concluído com sucesso", "info", bg_db)
                
            except Exception as e:
                error_msg = str(e)
                await _update_job(pipeline_id, {
                    "status": "failed", 
                    "error": error_msg
                }, bg_db)
                
                await _append_log(pipeline_id, f"Erro no pipeline: {error_msg}", "error", bg_db)
                
                log_event(
                    "pipeline_execution_error",
                    {
                        "pipeline_id": pipeline_id,
                        "error": error_msg[:500],
                    }
                )
    
    if run_async and background_tasks:
        # Executar em background
        # Como _execute_pipeline_task cria sua própria sessão, podemos chamar direto
        # Mas para garantir contexto async correto no FastAPI BackgroundTasks:
        import asyncio
        
        # Wrapper para rodar logica async se necessario, mas background_tasks aceita coroutines
        background_tasks.add_task(_execute_pipeline_task)
        
        return {
            "pipeline_id": pipeline_id,
            "status": "pending",
            "message": "Pipeline iniciado em background",
        }
    else:
        # Executar síncrono
        await _execute_pipeline_task()
        
        # Recarregar estado atualizado
        result = await db.execute(select(PipelineJob).where(PipelineJob.id == pipeline_id))
        updated_job = result.scalar()
        
        return {
            "pipeline_id": pipeline_id,
            "status": updated_job.status,
            "result": updated_job.result,
            "error": updated_job.error,
        }


@router.get("/{pipeline_id}/status")
async def get_pipeline_status(
    pipeline_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Obtém o status de uma execução de pipeline do banco de dados.
    """
    result = await db.execute(select(PipelineJob).where(PipelineJob.id == pipeline_id))
    job = result.scalar()
    
    if not job:
        raise HTTPException(status_code=404, detail="Pipeline não encontrado")
    
    return {
        "pipeline_id": job.id,
        "status": job.status,
        "created_at": job.created_at,
        "result": job.result,
        "error": job.error,
        "logs": job.logs or [],
    }


@router.get("/{pipeline_id}/logs")
async def get_pipeline_logs(
    pipeline_id: str,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Obtém os logs de uma execução de pipeline.
    """
    result = await db.execute(select(PipelineJob).where(PipelineJob.id == pipeline_id))
    job = result.scalar()
    
    if not job:
        raise HTTPException(status_code=404, detail="Pipeline não encontrado")
    
    logs = job.logs or []
    return {
        "pipeline_id": pipeline_id,
        "logs": logs[-limit:] if len(logs) > limit else logs,
        "total_logs": len(logs),
    }
