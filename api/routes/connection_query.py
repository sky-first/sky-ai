# api/routes/connection_query.py
"""
Endpoint para fazer queries diretamente usando uma DataConnection.
Ideal para integração com backend do produto.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text, create_engine
import os
import json

from api.schemas import QueryRequest, QueryResponse, QueryResultMeta
from core.agents.generic_sql_agent import AgentConfig, TableSchema, run_agent_once
from core.llm.providers import LangChainChatOpenAIProvider
from core.rag.embeddings import OpenAIEmbeddingProvider
from core.rag.context_retrieval import build_retrieval_context_for_question
from core.data_sources.factory import DataSourceFactory
from core.logging_utils import log_event
from db.session import get_db
from db.base import SessionLocal

router = APIRouter(prefix="/connections", tags=["connection_query"])


def load_agent_config_from_connection(
    db: Session,
    space_id: str,
    connection_id: str,
) -> AgentConfig:
    """
    Carrega TableMetadata e monta AgentConfig automaticamente para uma conexão.
    Compatível com schema real do banco (usa SQL raw).
    """
    from db.base import engine
    
    # Buscar metadados via SQL direto (compatível com UUID)
    with engine.connect() as raw_conn:
        result = raw_conn.execute(
            text("""
                SELECT table_name, column_name, data_type, is_nullable
                FROM table_metadata
                WHERE space_id = :space_id AND data_connection_id = :conn_id
                ORDER BY table_name, column_name
            """),
            {"space_id": space_id, "conn_id": connection_id}
        ).fetchall()
    
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum metadata encontrado para esta conexão. Execute a descoberta de tabelas primeiro."
        )
    
    # Agrupar por tabela
    tables: dict[str, list] = {}
    for row in result:
        table_name = row[0]
        if table_name not in tables:
            tables[table_name] = []
        tables[table_name].append({
            "column_name": row[1],
            "data_type": row[2] or "STRING",
            "is_nullable": row[3] or False
        })
    
    # Detectar dataset baseado no nome da tabela ou config da conexão
    def detect_dataset(table_name: str, conn_config: dict) -> str:
        """Detecta o dataset correto baseado no nome da tabela ou config"""
        # Tabelas do web_silver
        web_tables = [
            "silver_events_enriquecido",
            "silver_pageviews_enriquecido", 
            "silver_sessions_enriquecido",
            "silver_sources_enriquecido",
            "silver_users_enriquecido",
            "silver_web_data_enriquecido"
        ]
        if table_name in web_tables:
            return "data-mesh-gcp.web_silver"
        
        # Usar dataset do config da conexão
        dataset = conn_config.get("dataset", "data-mesh-gcp.billing_silver")
        # Se já tem projeto, usar direto; senão, adicionar projeto
        if "." in dataset and not dataset.startswith("data-mesh-gcp."):
            return dataset
        return dataset
    
    # Buscar config da conexão
    with engine.connect() as raw_conn:
        conn_result = raw_conn.execute(
            text("SELECT config FROM data_connections WHERE id = :id"),
            {"id": connection_id}
        ).first()
        config = conn_result[0] if conn_result else {}
        if isinstance(config, str):
            config = json.loads(config)
        elif config is None:
            config = {}
    
    # Criar TableSchemas
    table_schemas: list[TableSchema] = []
    for tname, cols in tables.items():
        dataset = detect_dataset(tname, config)
        physical_name = f"{dataset}.{tname}" if "." not in tname else tname
        
        schema = TableSchema(
            logical_name=tname,
            physical_name=physical_name,
            columns=[
                {
                    "name": c["column_name"],
                    "type": c["data_type"],
                    "nullable": c["is_nullable"]
                }
                for c in cols
            ],
        )
        table_schemas.append(schema)
    
    agent = AgentConfig(
        id=f"agent-conn-{connection_id}",
        name=f"Agent for connection {connection_id}",
        tables=table_schemas,
    )
    return agent


@router.post("/{connection_id}/query", response_model=QueryResponse)
async def query_connection(
    connection_id: str,
    body: QueryRequest,
    db: Session = Depends(get_db),
) -> QueryResponse:
    """
    Faz uma pergunta usando uma DataConnection diretamente.
    
    Requisitos:
    - A conexão deve ter metadados descobertos (execute /discover primeiro)
    - O space_id no body deve corresponder ao space_id da conexão
    
    Exemplo de uso:
    ```json
    {
        "question": "Qual é a performance de pageviews mensal?",
        "user_id": "user-123",
        "space_id": "00000000-0000-0000-0000-000000000001",
        "thread_id": "thread-456"
    }
    ```
    """
    if not body.space_id:
        raise HTTPException(
            status_code=400,
            detail="space_id é obrigatório no body da requisição"
        )
    
    # Verificar se conexão existe
    with db.begin():
        conn_result = db.execute(
            text("SELECT id, name, type, config FROM data_connections WHERE id = :id"),
            {"id": connection_id}
        ).first()
        
        if not conn_result:
            raise HTTPException(status_code=404, detail=f"Conexão {connection_id} não encontrada")
    
    # Carregar AgentConfig automaticamente
    try:
        agent_config = load_agent_config_from_connection(
            db=db,
            space_id=body.space_id,
            connection_id=connection_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao carregar configuração do agente: {str(e)}"
        )
    
    # Criar DataSource da conexão
    class TempDataConnection:
        def __init__(self, id, name, type, config):
            self.id = id
            self.name = name
            self.type = type
            self.config = config if isinstance(config, dict) else json.loads(config) if isinstance(config, str) else {}
    
    data_conn = TempDataConnection(
        id=str(conn_result[0]),
        name=conn_result[1],
        type=conn_result[2] or "bigquery",
        config=conn_result[3] if isinstance(conn_result[3], dict) else json.loads(conn_result[3]) if isinstance(conn_result[3], str) else {}
    )
    
    try:
        data_source = DataSourceFactory.build_from_dataconnection(data_conn)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao criar DataSource: {str(e)}"
        )
    
    # LLMs
    llm_orchestrator = LangChainChatOpenAIProvider(model="gpt-4o-mini", temperature=0.0)
    llm_specialist = LangChainChatOpenAIProvider(model="gpt-4o", temperature=0.0)
    llm_formatter = LangChainChatOpenAIProvider(model="gpt-4o", temperature=0.0)
    
    # Provider de embeddings (RAG)
    embedding_provider = OpenAIEmbeddingProvider()
    
    # Buscar contexto RAG
    retrieval_context: list[str] = []
    try:
        retrieval_context = build_retrieval_context_for_question(
            db=db,
            embedding_provider=embedding_provider,
            space_id=body.space_id,
            crew_ids=body.crew_ids or [],
            question=body.question,
            top_k=10,
        )
    except Exception:
        # Se RAG falhar, continua sem contexto
        retrieval_context = []
    
    # Executar agente
    try:
        from core.agents.generic_sql_agent import build_generic_sql_graph
        
        state = {
            "question": body.question,
            "user_id": body.user_id,
            "space_id": body.space_id,
            "crew_ids": body.crew_ids or [],
            "retrieval_context": retrieval_context,
        }
        
        app = build_generic_sql_graph(
            agent_config=agent_config,
            data_source=data_source,
            db_session_factory=lambda: db,
            embedding_provider=embedding_provider,
            llm_orchestrator=llm_orchestrator,
            llm_specialist=llm_specialist,
            llm_formatter=llm_formatter,
        )
        
        thread_id = body.thread_id or f"{body.user_id or 'anon'}-{connection_id}"
        final_state = app.invoke(
            state,
            config={"configurable": {"thread_id": thread_id}},
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao executar agente: {str(e)}"
        )
    
    answer = final_state.get("answer") or ""
    data = final_state.get("data") or []
    detected_language = final_state.get("detected_language")
    chosen_table = final_state.get("chosen_table")
    sql = final_state.get("sql")
    error = final_state.get("error")
    
    data_sample = data[:15] if isinstance(data, list) else []
    
    meta = QueryResultMeta(
        detected_language=detected_language,
        chosen_table=chosen_table,
        sql=sql,
        num_rows=len(data),
        error=error,
    )
    
    log_event(
        "api_query_connection",
        {
            "connection_id": connection_id,
            "user_id": body.user_id,
            "space_id": body.space_id,
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
