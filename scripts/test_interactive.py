#!/usr/bin/env python3
"""
Script Interativo de Testes - Teste perguntas em tempo real

Permite fazer perguntas e ver os resultados imediatamente no terminal.
Ideal para testar e validar o comportamento do sistema.

Uso:
    python3 scripts/test_interactive.py
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

# Adicionar o diretório raiz do projeto ao PYTHONPATH
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from sqlalchemy.orm import Session
from sqlalchemy import text

from db.base import SessionLocal
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

TEST_SPACE_ID = os.getenv("TEST_SPACE_ID") or "00000000-0000-0000-0000-000000000001"
TEST_CREW_ID: Optional[str] = os.getenv("TEST_CREW_ID") or None
TEST_CONNECTION_ID = os.getenv("TEST_CONNECTION_ID") or "00000000-0000-0000-0000-000000000002"


def load_agent_config(
    db: Session,
    space_id: str,
    crew_id: str | None,
    conn_id: str,
) -> AgentConfig:
    """Carrega TableMetadata e monta AgentConfig"""
    from sqlalchemy import text
    from db.base import engine
    
    # Buscar metadados via SQL direto
    with engine.connect() as raw_conn:
        result = raw_conn.execute(
            text("""
                SELECT table_name, column_name, data_type, is_nullable
                FROM table_metadata
                WHERE space_id = :space_id AND data_connection_id = :conn_id
                ORDER BY table_name, column_name
            """),
            {"space_id": space_id, "conn_id": conn_id}
        ).fetchall()
    
    if not result:
        raise RuntimeError("Nenhum metadata encontrado para este Space/Connection")
    
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
    
    # Buscar dataset da connection
    with engine.connect() as raw_conn:
        conn_result = raw_conn.execute(
            text("SELECT config FROM data_connections WHERE id = :id"),
            {"id": conn_id}
        ).first()
        config = conn_result[0] if conn_result else {}
        if isinstance(config, str):
            import json
            config = json.loads(config)
        dataset = config.get("dataset", "data-mesh-gcp.billing_silver")
    
    # Criar TableSchemas
    table_schemas: list[TableSchema] = []
    for tname, cols in tables.items():
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
    
    return AgentConfig(
        id=f"agent-interactive-{conn_id}",
        name="Agent Interactive Test",
        tables=table_schemas,
    )


def setup_pipeline():
    """Configura e retorna os componentes do pipeline"""
    db = SessionLocal()
    
    # Buscar connection
    from sqlalchemy import text
    from db.base import engine
    
    with engine.connect() as raw_conn:
        result = raw_conn.execute(
            text("SELECT id, name, connector_id, config FROM data_connections WHERE id = :id"),
            {"id": TEST_CONNECTION_ID}
        ).first()
        
        if not result:
            raise RuntimeError("DataConnection não encontrada")
        
        import json
        config_data = result[3] if isinstance(result[3], dict) else json.loads(result[3]) if isinstance(result[3], str) else {}
        
        class TempDataConnection:
            def __init__(self, id, name, type, config):
                self.id = id
                self.name = name
                self.type = type
                self.config = config
        
        conn = TempDataConnection(
            id=str(result[0]),
            name=result[1],
            type=result[2] or "bigquery",
            config=config_data
        )
    
    # Criar componentes
    datasource = DataSourceFactory.build_from_dataconnection(conn)
    agent_config = load_agent_config(db, TEST_SPACE_ID, TEST_CREW_ID, conn.id)
    llm = LangChainChatOpenAIProvider(model="gpt-4o", temperature=0.0)
    embedding_provider = OpenAIEmbeddingProvider(model="text-embedding-3-large")
    
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
    
    return {
        "db": db,
        "graph": graph,
        "agent_config": agent_config,
        "embedding_provider": embedding_provider,
    }


def run_question(question: str, pipeline_components: dict) -> dict:
    """Executa uma pergunta e retorna o resultado"""
    db = pipeline_components["db"]
    graph = pipeline_components["graph"]
    embedding_provider = pipeline_components["embedding_provider"]
    
    # Tentar RAG (opcional)
    try:
        retrieval_context = build_retrieval_context_for_question(
            db=db,
            embedding_provider=embedding_provider,
            space_id=TEST_SPACE_ID,
            crew_ids=[TEST_CREW_ID] if TEST_CREW_ID else [],
            question=question,
            top_k=5,
        )
    except Exception:
        retrieval_context = []
    
    # Executar
    initial_state: AgentState = {
        "question": question,
        "retrieval_context": retrieval_context,
    }
    
    start_time = time.time()
    final_state = graph.invoke(
        initial_state,
        config={"configurable": {"thread_id": f"interactive-{int(time.time())}"}},
    )
    execution_time = time.time() - start_time
    
    return {
        "sql": final_state.get("sql"),
        "answer": final_state.get("answer"),
        "error": final_state.get("error"),
        "chosen_table": final_state.get("chosen_table"),
        "chosen_table_physical": final_state.get("chosen_table_physical"),
        "data": final_state.get("data"),
        "execution_time": execution_time,
    }


def print_result(question: str, result: dict):
    """Imprime o resultado formatado"""
    print("\n" + "=" * 80)
    print(f"❓ PERGUNTA: {question}")
    print("=" * 80)
    
    if result["error"]:
        print(f"❌ ERRO: {result['error']}")
        return
    
    if result["chosen_table"]:
        print(f"📊 Tabela escolhida: {result['chosen_table']}")
        if result["chosen_table_physical"]:
            print(f"   (Física: {result['chosen_table_physical']})")
    
    if result["sql"]:
        print(f"\n💻 SQL GERADO:")
        print("-" * 80)
        print(result["sql"])
        print("-" * 80)
    
    if result["data"]:
        num_rows = len(result["data"])
        print(f"\n📈 DADOS RETORNADOS: {num_rows} linha(s)")
        if num_rows > 0:
            print("Primeiras linhas:")
            for i, row in enumerate(result["data"][:3], 1):
                print(f"  {i}. {row}")
            if num_rows > 3:
                print(f"  ... e mais {num_rows - 3} linha(s)")
    
    if result["answer"]:
        print(f"\n🤖 RESPOSTA DA IA:")
        print("-" * 80)
        print(result["answer"])
        print("-" * 80)
    
    print(f"\n⏱️  Tempo de execução: {result['execution_time']:.2f}s")
    print("=" * 80 + "\n")


def main():
    """Função principal - modo interativo"""
    print("=" * 80)
    print("🧪 TESTE INTERATIVO DO PIPELINE DE IA")
    print("=" * 80)
    print(f"Space ID: {TEST_SPACE_ID}")
    print(f"Connection ID: {TEST_CONNECTION_ID}")
    print("\n💡 Digite suas perguntas (ou 'sair' para encerrar)")
    print("   Exemplos:")
    print("   - Quais são os países dos clientes?")
    print("   - Quantos clientes temos?")
    print("   - Mostre os últimos 5 pagamentos")
    print("=" * 80 + "\n")
    
    try:
        # Setup inicial
        print("🔄 Configurando pipeline...")
        pipeline = setup_pipeline()
        print("✅ Pipeline configurado!\n")
        
        # Loop interativo
        while True:
            try:
                question = input("❓ Sua pergunta: ").strip()
                
                if not question:
                    continue
                
                if question.lower() in ["sair", "exit", "quit", "q"]:
                    print("\n👋 Encerrando...")
                    break
                
                if question.lower() == "help":
                    print("\n📖 Comandos disponíveis:")
                    print("   - Digite qualquer pergunta para testar")
                    print("   - 'sair' ou 'exit' para encerrar")
                    print("   - 'help' para ver esta ajuda")
                    print()
                    continue
                
                # Executar pergunta
                print("\n🔄 Processando...")
                result = run_question(question, pipeline)
                print_result(question, result)
                
            except KeyboardInterrupt:
                print("\n\n⚠️  Interrompido. Digite 'sair' para encerrar ou continue fazendo perguntas.\n")
                continue
            except EOFError:
                print("\n\n👋 Encerrando...")
                break
            except Exception as e:
                print(f"\n❌ Erro ao processar pergunta: {e}")
                import traceback
                traceback.print_exc()
                print()
        
    except Exception as e:
        print(f"\n❌ Erro fatal: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if 'pipeline' in locals():
            pipeline["db"].close()


if __name__ == "__main__":
    main()
