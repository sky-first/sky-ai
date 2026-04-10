# api/routes/agents.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
import json
from typing import AsyncGenerator

from api.schemas import QueryRequest, QueryResponse, QueryResultMeta
from agent_registry.loader import get_agent_config, AgentNotFoundError
from core.agents.generic_sql_agent import run_agent_once, build_generic_sql_graph
from core.llm.factory import (
    create_llm_orchestrator,
    create_llm_specialist,
    create_llm_formatter,
    create_embedding_provider,
)
from core.rag.context_retrieval import build_retrieval_context_for_question
from core.auth.service import resolve_crew_ids_for_context
from core.logging_utils import log_event
from db.session import get_db
from db.base import SyncSessionLocal

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/{agent_id}/query", response_model=QueryResponse)
async def query_agent(
    agent_id: str,
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    try:
        agent_config = get_agent_config(agent_id)
    except AgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # LLMs usando factory centralizado
    llm_orchestrator = create_llm_orchestrator()
    llm_specialist = create_llm_specialist()
    llm_formatter = create_llm_formatter()

    # Provider de embeddings (RAG) usando factory centralizado
    embedding_provider = create_embedding_provider()

    # Resolver crew_ids baseado no contexto (personal vs collaborative)
    resolved_crew_ids = body.crew_ids or []
    if body.user_id:
        try:
            resolved_crew_ids = await resolve_crew_ids_for_context(
                db=db,
                user_id=UUID(body.user_id),
                space_id=UUID(body.space_id) if body.space_id else None,
                request_crew_ids=body.crew_ids,
                is_personal=getattr(body, 'is_personal', False)
            )
        except Exception as e:
            log_event(
                "api_query_agent_resolve_crew_ids_error",
                {
                    "agent_id": agent_id,
                    "user_id": body.user_id,
                    "space_id": body.space_id,
                    "error": str(e),
                },
            )
            resolved_crew_ids = []

    retrieval_context: list[str] = []
    if body.space_id:
        retrieval_context = await build_retrieval_context_for_question(
            db=db,
            embedding_provider=embedding_provider,
            space_id=body.space_id,
            crew_ids=resolved_crew_ids,
            question=body.question,
            top_k=10,
        )

    # Criar UserContext simples para compatibilidade
    from core.auth.models import UserContext, User
    from uuid import UUID as UUIDType
    
    # Criar um UserContext mínimo (pode ser melhorado depois)
    user_ctx = UserContext(
        user=User(
            id=UUIDType(body.user_id) if body.user_id else UUIDType('00000000-0000-0000-0000-000000000000'),
            email="",
            name="",
            is_active=True,
        ),
        space_id=UUIDType(body.space_id) if body.space_id else None,
        crew_id=None,  # crew_ids são passados separadamente
    )
    # Adicionar crew_ids como atributo dinâmico
    user_ctx.crew_ids = resolved_crew_ids
    user_ctx.user_id = body.user_id
    
    # Criar factory de sessão síncrona (para LangGraph)
    def db_session_factory():
        return SyncSessionLocal()
    
    # Obter data_source do agent_config
    if not hasattr(agent_config, 'data_source') or agent_config.data_source is None:
        raise HTTPException(status_code=500, detail="Data source not configured for this agent")
    data_source = agent_config.data_source

    state = run_agent_once(
        question=body.question,
        user_ctx=user_ctx,
        agent_config=agent_config,
        data_source=data_source,
        db_session_factory=db_session_factory,
        embedding_provider=embedding_provider,
        llm_orchestrator=llm_orchestrator,
        llm_specialist=llm_specialist,
        llm_formatter=llm_formatter,
        thread_id=body.thread_id,
        retrieval_context=retrieval_context,
        instructions=body.instructions,
        creativity=body.creativity,
        length=body.length,
        response_format=body.response_format,
        sql_instructions=body.sql_instructions,
        selected_datasets=body.selected_datasets,
        chat_history=body.chat_history,  # ✅ Pass history
    )

    answer = state.get("answer") or ""
    data = state.get("data") or []
    detected_language = state.get("detected_language")
    chosen_table = state.get("chosen_table")
    sql = state.get("sql")
    error = state.get("error")

    data_sample = data[:15] if isinstance(data, list) else []

    meta = QueryResultMeta(
        detected_language=detected_language,
        chosen_table=chosen_table,
        sql=sql,
        num_rows=len(data),
        error=error,
    )

    log_event(
        "api_query_agent",
        {
            "agent_id": agent_id,
            "user_id": body.user_id,
            "space_id": body.space_id,
            "crew_ids": resolved_crew_ids,
            "is_personal": getattr(body, 'is_personal', False),
            "question": body.question[:200],
            "answer_preview": answer[:200],
            "num_rows": len(data),
            "error": error[:200] if error else None,
        },
    )

    return QueryResponse(
        answer=answer,
        data_sample=data_sample,
        meta=meta,
    )


async def _stream_agent_query(
    agent_id: str,
    body: QueryRequest,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """
    Generator function that yields SSE events for streaming agent query responses.
    """
    try:
        # Obter agent config
        try:
            agent_config = get_agent_config(agent_id)
        except AgentNotFoundError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return
        
        # Verificar se agent_config tem data_source
        if not hasattr(agent_config, 'data_source') or agent_config.data_source is None:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Agent {agent_id} não tem data_source configurado'})}\n\n"
            return
        
        data_source = agent_config.data_source
        
        # Resolver crew_ids
        resolved_crew_ids = body.crew_ids or []
        if body.user_id:
            try:
                resolved_crew_ids = await resolve_crew_ids_for_context(
                    db=db,
                    user_id=UUID(body.user_id),
                    space_id=UUID(body.space_id) if body.space_id else None,
                    request_crew_ids=body.crew_ids,
                    is_personal=getattr(body, 'is_personal', False)
                )
            except Exception as e:
                log_event(
                    "api_query_agent_stream_resolve_crew_ids_error",
                    {
                        "agent_id": agent_id,
                        "error": str(e),
                    },
                )
                resolved_crew_ids = []
        
        # LLMs
        llm_orchestrator = create_llm_orchestrator()
        llm_specialist = create_llm_specialist()
        llm_formatter = create_llm_formatter()
        embedding_provider = create_embedding_provider()
        
        # Buscar contexto RAG
        retrieval_context: list[str] = []
        if body.space_id:
            try:
                retrieval_context = await build_retrieval_context_for_question(
                    db=db,
                    embedding_provider=embedding_provider,
                    space_id=body.space_id,
                    crew_ids=resolved_crew_ids,
                    question=body.question,
                    top_k=10,
                )
            except Exception:
                retrieval_context = []
        
        # Executar agente até o specialist (sem formatter ainda)
        try:
            from core.llm.formatter import _ensure_language, _serialize_for_json, _compute_basic_stats, _stream_llm
            
            state = {
                "question": body.question,
                "user_id": body.user_id,
                "space_id": body.space_id,
                "crew_ids": resolved_crew_ids,
                "retrieval_context": retrieval_context,
                # Configurações dinâmicas da IA
                "instructions": body.instructions,
                "creativity": body.creativity,
                "length": body.length,
                "response_format": body.response_format,
                "sql_instructions": body.sql_instructions,
                "selected_datasets": body.selected_datasets,
            }
            
            def db_session_factory():
                return SyncSessionLocal()
            
            app = build_generic_sql_graph(
                agent_config=agent_config,
                data_source=data_source,
                db_session_factory=db_session_factory,
                embedding_provider=embedding_provider,
                llm_orchestrator=llm_orchestrator,
                llm_specialist=llm_specialist,
                llm_formatter=llm_formatter,
            )
            
            thread_id = body.thread_id or f"{body.user_id or 'anon'}-{agent_id}"
            
            # Executar até o specialist (orchestrator -> specialist)
            final_state = None
            for chunk in app.stream(state, config={"configurable": {"thread_id": thread_id}}):
                for node_name, node_state in chunk.items():
                    if node_name in ["orchestrator", "specialist"]:
                        final_state = node_state
                        # Enviar progresso e eventos específicos
                        if node_name == "orchestrator":
                            yield f"data: {json.dumps({'type': 'progress', 'stage': 'orchestrator', 'message': 'Analisando pergunta...'})}\n\n"
                            
                            # Enviar evento quando datasets são escolhidos
                            chosen_table = node_state.get("chosen_table")
                            chosen_tables = node_state.get("chosen_tables")
                            if chosen_table or chosen_tables:
                                chosen_datasets = chosen_tables if chosen_tables else ([chosen_table] if chosen_table else [])
                                yield f"data: {json.dumps({'type': 'datasets_selected', 'datasets': chosen_datasets})}\n\n"
                        
                        elif node_name == "specialist":
                            yield f"data: {json.dumps({'type': 'progress', 'stage': 'specialist', 'message': 'Executando query...'})}\n\n"
                            
                            # Enviar evento quando SQL é gerado
                            sql = node_state.get("sql")
                            if sql:
                                yield f"data: {json.dumps({'type': 'sql_generated', 'sql': sql})}\n\n"
            
            if not final_state:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Erro ao executar agente'})}\n\n"
                return
            
            # Se houve erro, enviar e terminar
            if final_state.get("error"):
                yield f"data: {json.dumps({'type': 'chunk', 'content': str(final_state.get('error'))})}\n\n"
                meta = {
                    "detected_language": final_state.get("detected_language"),
                    "chosen_table": final_state.get("chosen_table"),
                    "sql": final_state.get("sql"),
                    "num_rows": 0,
                    "error": str(final_state.get("error")),
                }
                yield f"data: {json.dumps({'type': 'meta', 'meta': meta, 'data_sample': []})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return
            
            # Se não há dados, enviar mensagem e terminar
            if not final_state.get("data"):
                yield f"data: {json.dumps({'type': 'chunk', 'content': 'No data was found for this query.'})}\n\n"
                meta = {
                    "detected_language": final_state.get("detected_language"),
                    "chosen_table": final_state.get("chosen_table"),
                    "sql": final_state.get("sql"),
                    "num_rows": 0,
                    "error": None,
                }
                yield f"data: {json.dumps({'type': 'meta', 'meta': meta, 'data_sample': []})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return
            
            # Agora fazer streaming da resposta do formatter
            yield f"data: {json.dumps({'type': 'progress', 'stage': 'formatter', 'message': 'Gerando resposta...'})}\n\n"
            
            question = final_state.get("question") or ""
            data = final_state.get("data") or []
            detected_language = final_state.get("detected_language")
            lang = _ensure_language(question, detected_language)
            
            data_sample = data[:15]
            serialized_sample = _serialize_for_json(data_sample)
            sample_json = json.dumps(serialized_sample, ensure_ascii=False, indent=2)
            stats_text = _compute_basic_stats(data_sample)
            
            system_msg = {
                "role": "system",
                "content": (
                    "You are a data analyst assistant.\n"
                    "Your job is to explain query results in clear natural language.\n\n"
                    "CRITICAL LANGUAGE REQUIREMENT:\n"
                    f"- The user question is in language code '{lang}'.\n"
                    "- You MUST answer in the same language as the question.\n"
                    "- Keep the answer SHORT and OBJECTIVE (maximum 4 sentences).\n"
                ),
            }
            
            user_msg = {
                "role": "user",
                "content": (
                    f"User question:\n{question}\n\n"
                    f"Total rows returned (not all shown): {len(data)}\n"
                    f"{stats_text}\n\n"
                    "Sample of the data (up to 15 rows, JSON):\n"
                    f"{sample_json}\n\n"
                    "Explain the main insight(s) from this data in a concise way, "
                    "in the same language as the user's question."
                ),
            }
            
            # Stream do LLM formatter
            accumulated_answer = ""
            try:
                for chunk in _stream_llm(llm_formatter, system_msg, user_msg):
                    accumulated_answer += chunk
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
            except Exception as e:
                # Fallback se streaming falhar
                fallback = "Error formatting the response with the AI. Data was queried successfully, but I could not generate a summary."
                yield f"data: {json.dumps({'type': 'chunk', 'content': fallback})}\n\n"
                accumulated_answer = fallback
            
            # Enviar metadados finais
            chosen_table = final_state.get("chosen_table")
            chosen_tables = final_state.get("chosen_tables")
            sql = final_state.get("sql")
            
            chosen_datasets = chosen_tables if chosen_tables else ([chosen_table] if chosen_table else [])
            
            meta = {
                "detected_language": lang,
                "chosen_table": chosen_table,
                "chosen_datasets": chosen_datasets if chosen_datasets else None,
                "sql": sql,
                "num_rows": len(data),
                "error": None,
            }
            
            yield f"data: {json.dumps({'type': 'meta', 'meta': meta, 'data_sample': data_sample})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
        except Exception as e:
            import traceback
            error_detail = str(e)
            yield f"data: {json.dumps({'type': 'error', 'message': error_detail})}\n\n"
            log_event(
                "api_query_agent_stream_error",
                {
                    "agent_id": agent_id,
                    "error": error_detail,
                },
            )
    
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


@router.post("/{agent_id}/query/stream")
async def query_agent_stream(
    agent_id: str,
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Faz uma pergunta usando um Agent com streaming de resposta.
    Retorna Server-Sent Events (SSE) com chunks de texto conforme são gerados.
    
    Formato dos eventos:
    - {"type": "progress", "stage": "...", "message": "..."} - progresso das etapas
    - {"type": "chunk", "content": "texto..."} - pedaços da resposta
    - {"type": "meta", "meta": {...}, "data_sample": [...]} - metadados finais
    - {"type": "done"} - fim do stream
    - {"type": "error", "message": "..."} - erro ocorrido
    """
    return StreamingResponse(
        _stream_agent_query(agent_id, body, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Desabilita buffering no nginx
        }
    )
