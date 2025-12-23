# api/routes/pipeline.py
"""
Endpoints para execução de pipeline de IA de forma assíncrona.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
from datetime import datetime
import uuid

from api.schemas import QueryRequest, QueryResponse
from core.logging_utils import log_event
from db.session import get_db

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

# Armazenamento simples em memória para status de pipeline
# Em produção, isso deveria ser armazenado no banco de dados
_pipeline_status: Dict[str, Dict[str, Any]] = {}


@router.post("/execute")
async def execute_pipeline(
    body: QueryRequest,
    connection_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = None,
    run_async: bool = True,
) -> dict:
    """
    Executa o pipeline de IA de forma assíncrona ou síncrona.
    
    Parâmetros:
    - body: QueryRequest com question, space_id, etc.
    - connection_id: ID da conexão (opcional, se não usar agent_id)
    - agent_id: ID do agente (opcional, se não usar connection_id)
    - run_async: Se True, executa em background (default: True)
    
    Retorna:
    - pipeline_id: ID da execução do pipeline
    - status: "pending" ou "completed"
    - Se síncrono: resultado completo
    """
    pipeline_id = str(uuid.uuid4())
    
    # Inicializar status
    _pipeline_status[pipeline_id] = {
        "id": pipeline_id,
        "status": "pending",
        "question": body.question,
        "space_id": body.space_id,
        "connection_id": connection_id,
        "agent_id": agent_id,
        "created_at": datetime.utcnow().isoformat(),
        "logs": [],
        "result": None,
        "error": None,
    }
    
    async def _execute_pipeline_task():
        """Executa o pipeline em background"""
        try:
            _pipeline_status[pipeline_id]["status"] = "running"
            _pipeline_status[pipeline_id]["logs"].append({
                "timestamp": datetime.utcnow().isoformat(),
                "level": "info",
                "message": "Pipeline iniciado"
            })
            
            # Importar aqui para evitar circular imports
            from api.routes.connection_query import query_connection
            from api.routes.agents import query_agent
            
            # Criar uma nova sessão para o background task
            from db.base import SessionLocal
            bg_db = SessionLocal()
            
            try:
                if connection_id:
                    # Usar connection_query
                    result = await query_connection(
                        connection_id=connection_id,
                        body=body,
                        db=bg_db,
                    )
                elif agent_id:
                    # Usar agent query
                    result = await query_agent(
                        agent_id=agent_id,
                        body=body,
                        db=bg_db,
                    )
                else:
                    raise ValueError("connection_id ou agent_id deve ser fornecido")
                
                _pipeline_status[pipeline_id]["status"] = "completed"
                _pipeline_status[pipeline_id]["result"] = {
                    "answer": result.answer,
                    "data_sample": result.data_sample,
                    "meta": result.meta.dict() if hasattr(result.meta, 'dict') else result.meta,
                }
                _pipeline_status[pipeline_id]["logs"].append({
                    "timestamp": datetime.utcnow().isoformat(),
                    "level": "info",
                    "message": "Pipeline concluído com sucesso"
                })
            finally:
                bg_db.close()
                
        except Exception as e:
            _pipeline_status[pipeline_id]["status"] = "failed"
            _pipeline_status[pipeline_id]["error"] = str(e)
            _pipeline_status[pipeline_id]["logs"].append({
                "timestamp": datetime.utcnow().isoformat(),
                "level": "error",
                "message": f"Erro no pipeline: {str(e)}"
            })
            log_event(
                "pipeline_execution_error",
                {
                    "pipeline_id": pipeline_id,
                    "error": str(e)[:500],
                }
            )
    
    if run_async and background_tasks:
        # Executar em background usando asyncio
        import asyncio
        def run_async_task():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_execute_pipeline_task())
            finally:
                loop.close()
        
        background_tasks.add_task(run_async_task)
        return {
            "pipeline_id": pipeline_id,
            "status": "pending",
            "message": "Pipeline iniciado em background",
        }
    else:
        # Executar síncrono
        import asyncio
        asyncio.run(_execute_pipeline_task())
        return {
            "pipeline_id": pipeline_id,
            "status": _pipeline_status[pipeline_id]["status"],
            "result": _pipeline_status[pipeline_id].get("result"),
            "error": _pipeline_status[pipeline_id].get("error"),
        }


@router.get("/{pipeline_id}/status")
async def get_pipeline_status(
    pipeline_id: str,
) -> dict:
    """
    Obtém o status de uma execução de pipeline.
    
    Retorna:
    - status: "pending", "running", "completed", "failed"
    - result: Resultado (se completed)
    - error: Erro (se failed)
    - logs: Lista de logs
    """
    if pipeline_id not in _pipeline_status:
        raise HTTPException(status_code=404, detail="Pipeline não encontrado")
    
    status = _pipeline_status[pipeline_id]
    return {
        "pipeline_id": pipeline_id,
        "status": status["status"],
        "question": status["question"],
        "created_at": status["created_at"],
        "result": status.get("result"),
        "error": status.get("error"),
        "logs": status.get("logs", []),
    }


@router.get("/{pipeline_id}/logs")
async def get_pipeline_logs(
    pipeline_id: str,
    limit: int = 100,
) -> dict:
    """
    Obtém os logs de uma execução de pipeline.
    
    Parâmetros:
    - limit: Número máximo de logs a retornar (default: 100)
    
    Retorna:
    - logs: Lista de logs ordenados por timestamp
    """
    if pipeline_id not in _pipeline_status:
        raise HTTPException(status_code=404, detail="Pipeline não encontrado")
    
    logs = _pipeline_status[pipeline_id].get("logs", [])
    return {
        "pipeline_id": pipeline_id,
        "logs": logs[-limit:] if len(logs) > limit else logs,
        "total_logs": len(logs),
    }
