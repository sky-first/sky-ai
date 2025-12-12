# scripts/test_full_pipeline.py
from __future__ import annotations

"""
TESTE COMPLETO DO PIPELINE:
- Carrega DataConnection do Postgres
- Carrega TableMetadata
- Gera retrieval_context via pgvector (opcional)
- Monta AgentConfig automaticamente a partir do TableMetadata
- Executa graph do agente (orchestrator → specialist → formatter)
- Imprime SQL e output final da IA
"""

import os
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.orm import Session

from db.base import SessionLocal
from db.models import DataConnection, TableMetadata
from core.data_sources.factory import DataSourceFactory
from core.llm.providers import LangChainChatOpenAIProvider
from core.agents.generic_sql_agent import (
    AgentConfig,
    TableSchema,
    build_generic_sql_graph,
    AgentState,
)
from core.rag.context_retrieval import build_retrieval_context_for_question
from core.rag.embeddings import OpenAIEmbeddingProvider


# ============== CONFIGURAÇÃO ==============

TEST_SPACE_ID = os.getenv("TEST_SPACE_ID") or "SPACE-ID-AQUI"
TEST_CREW_ID: Optional[str] = os.getenv("TEST_CREW_ID") or None
TEST_CONNECTION_ID = os.getenv("TEST_CONNECTION_ID") or "CONN-ID-AQUI"

USER_QUESTION = os.getenv("TEST_QUESTION") or "Quais são os países dos clientes?"


def load_agent_config(
    db: Session,
    space_id: str,
    crew_id: str | None,
    conn_id: str,
) -> AgentConfig:
    """
    Carrega TableMetadata do banco, agrupa colunas por tabela,
    e monta um AgentConfig automaticamente (agnóstico).
    """
    metas = (
        db.query(TableMetadata)
        .filter(TableMetadata.space_id == space_id)
        .filter(TableMetadata.data_connection_id == conn_id)
        .all()
    )

    if not metas:
        raise RuntimeError("Nenhum metadata encontrado para este Space/Connection")

    tables: dict[str, list[TableMetadata]] = {}
    for m in metas:
        tables.setdefault(m.table_name, []).append(m)

    from core.agents.generic_sql_agent import TableColumn
    
    # Buscar o dataset da connection
    from sqlalchemy import text
    from db.base import engine
    with engine.connect() as raw_conn:
        result = raw_conn.execute(
            text("SELECT config FROM data_connections WHERE id = :id"),
            {"id": conn_id}
        ).first()
        config = result[0] if result else {}
        if isinstance(config, str):
            import json
            config = json.loads(config)
        dataset = config.get("dataset", "data-mesh-gcp.billing_silver")
    
    table_schemas: list[TableSchema] = []
    for tname, cols in tables.items():
        # TableColumn é TypedDict, então criamos dicts
        column_list = [
            {
                "name": c.column_name,
                "type": c.data_type or "STRING",
                "nullable": c.is_nullable or False
            }
            for c in cols
        ]
        # Nome físico completo para BigQuery: dataset.tabela
        physical_name = f"{dataset}.{tname}" if "." not in tname else tname
        schema = TableSchema(
            logical_name=tname,       # nome lógico agnóstico
            physical_name=physical_name,  # nome físico completo (dataset.tabela)
            columns=column_list,
        )
        table_schemas.append(schema)

    agent = AgentConfig(
        id=f"agent-test-{conn_id}",
        name="Agent Test Full Pipeline",
        tables=table_schemas,
    )
    return agent


def main():
    print("\n=== TESTE COMPLETO DO PIPELINE ===\n")
    print(f"Space ID     : {TEST_SPACE_ID}")
    print(f"Crew ID      : {TEST_CREW_ID}")
    print(f"Connection ID: {TEST_CONNECTION_ID}")
    print(f"Pergunta     : {USER_QUESTION}\n")

    db = SessionLocal()

    # ------ BUSCA DATA CONNECTION ------
    # O banco usa tabela de relacionamento space_connections, então buscamos diretamente via SQL raw
    from sqlalchemy import text
    from db.base import engine
    
    with engine.connect() as raw_conn:
        result = raw_conn.execute(
            text("SELECT id, name, connector_id, config FROM data_connections WHERE id = :id"),
            {"id": TEST_CONNECTION_ID}
        ).first()
    
    if not result:
        raise RuntimeError("DataConnection não encontrada no Postgres")
    
    # Criar um objeto DataConnection temporário para compatibilidade
    class TempDataConnection:
        def __init__(self, id, name, type, config):
            self.id = id
            self.name = name
            self.type = type
            self.config = config if isinstance(config, dict) else config
    
    import json
    config_data = result[3] if isinstance(result[3], dict) else (json.loads(result[3]) if isinstance(result[3], str) else {})
    
    conn = TempDataConnection(
        id=str(result[0]),
        name=result[1],
        type=result[2] or "bigquery",  # usar connector_id como type
        config=config_data
    )

    print(f"Conexão encontrada → {conn.name} ({conn.type})")

    # ------ CRIA DATA SOURCE REAL ------
    datasource = DataSourceFactory.build_from_dataconnection(conn)
    print("DataSource criado:", datasource)

    # ------ MONTA AGENT CONFIG A PARTIR DOS METADADOS ------
    agent_config = load_agent_config(db, TEST_SPACE_ID, TEST_CREW_ID, conn.id)
    print(f"\nAgent configurado → {agent_config.name}")
    print(f"Tabelas detectadas: {[t.logical_name for t in agent_config.tables]}")

    # ------ CARREGA LLM PROVIDER ------
    llm = LangChainChatOpenAIProvider(model="gpt-4o", temperature=0.0)

    # ------ CARREGA EMBEDDING PROVIDER ------
    embedding_provider = OpenAIEmbeddingProvider(model="text-embedding-3-large")

    # ------ RECUPERA CONTEXTO VIA RAG ------
    # RAG é opcional - se a tabela embeddings não existir, continua sem contexto
    try:
        retrieval_context = build_retrieval_context_for_question(
            db=db,
            embedding_provider=embedding_provider,
            space_id=TEST_SPACE_ID,
            crew_ids=[TEST_CREW_ID] if TEST_CREW_ID else [],
            question=USER_QUESTION,
            top_k=5,
        )
    except Exception as e:
        print(f"⚠️  RAG não disponível (tabela embeddings não existe): {e}")
        retrieval_context = []

    print("\nContexto recuperado via RAG:")
    if not retrieval_context:
        print(" - (nenhum contexto encontrado, seguindo mesmo assim)")
    else:
        for c in retrieval_context:
            print("-", c[:150])

    # ------ MONTA O GRAPH ------
    def db_session_factory():
        return SessionLocal()
    
    graph = build_generic_sql_graph(
        agent_config=agent_config,
        data_source=datasource,
        db_session_factory=db_session_factory,
        embedding_provider=embedding_provider,
        llm_orchestrator=llm,
        llm_specialist=llm,
        llm_formatter=llm,
    )

    # ------ ESTADO INICIAL ------
    initial_state: AgentState = {
        "question": USER_QUESTION,
        "retrieval_context": retrieval_context,
    }

    # ------ EXECUTA GRAPH ------
    print("\nExecutando pipeline...\n")

    final_state = graph.invoke(
        initial_state,
        config={"configurable": {"thread_id": "test-thread"}},
    )

    print("\n=== RESULTADO FINAL ===")
    print(f"SQL gerado:\n{final_state.get('sql')}\n")
    print(f"Erro: {final_state.get('error')}")
    print(f"\nResposta final da IA:\n{final_state.get('answer')}\n")


if __name__ == "__main__":
    main()
