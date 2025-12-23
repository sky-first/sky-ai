#!/usr/bin/env python3
"""
Script de Testes End-to-End Completo

Valida o fluxo completo do sistema:
1. Usuário faz uma pergunta
2. Sistema seleciona datasets automaticamente OU usa selected_datasets
3. Gera SQL
4. Executa query
5. Retorna resposta

Inclui testes para:
- Fluxo normal (seleção automática)
- Seleção manual de datasets (selected_datasets)
- Configurações de UI (instructions, creativity, length, response_format)
- Streaming de respostas

Uso:
    python3 scripts/test_end_to_end.py
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from dotenv import load_dotenv
load_dotenv()

# Adicionar o diretório raiz do projeto ao PYTHONPATH
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from sqlalchemy import text
from db.base import SessionLocal, engine
from core.data_sources.factory import DataSourceFactory
from core.llm.providers import LangChainChatOpenAIProvider
from core.agents.generic_sql_agent import (
    AgentConfig,
    TableSchema,
    build_generic_sql_graph,
    AgentState,
    run_agent_once,
)
from core.rag.context_retrieval import build_retrieval_context_for_question
from core.rag.embeddings import OpenAIEmbeddingProvider
from core.auth.models import UserContext, User
from uuid import UUID


# ============== CONFIGURAÇÃO ==============

# IDs reais do banco de dados
TEST_SPACE_ID = os.getenv("TEST_SPACE_ID") or "e409079b-5bbf-4249-a769-2010609c30f2"
TEST_CREW_ID: Optional[str] = os.getenv("TEST_CREW_ID") or None
TEST_CONNECTION_ID = os.getenv("TEST_CONNECTION_ID") or "9dfec38b-7bec-4ef0-8fb2-8430776b2178"


@dataclass
class TestCase:
    """Caso de teste"""
    name: str
    question: str
    selected_datasets: Optional[List[str]] = None
    instructions: Optional[str] = None
    creativity: Optional[int] = None
    length: Optional[int] = None
    response_format: Optional[str] = None
    sql_instructions: Optional[str] = None
    expected_datasets: Optional[List[str]] = None  # Para validar se os datasets corretos foram usados
    description: str = ""


def load_agent_config(
    db,
    space_id: str,
    crew_id: str | None,
    conn_id: str,
) -> AgentConfig:
    """Carrega TableMetadata e monta AgentConfig"""
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
    tables: Dict[str, List] = {}
    for row in result:
        table_name = row[0]
        if table_name not in tables:
            tables[table_name] = []
        tables[table_name].append({
            "column_name": row[1],
            "data_type": row[2] or "STRING",
            "is_nullable": row[3] or False
        })
    
    # Detectar dataset baseado no nome da tabela
    def detect_dataset(table_name: str) -> str:
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
        return "data-mesh-gcp.billing_silver"
    
    # Criar TableSchemas
    table_schemas: List[TableSchema] = []
    for tname, cols in tables.items():
        dataset = detect_dataset(tname)
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
        id=f"agent-test-{conn_id}",
        name="Agent Test Suite",
        tables=table_schemas,
    )


def run_test_case(test_case: TestCase) -> Dict[str, Any]:
    """Executa um caso de teste"""
    print(f"\n{'='*80}")
    print(f"🧪 TESTE: {test_case.name}")
    print(f"{'='*80}")
    print(f"Pergunta: {test_case.question}")
    if test_case.selected_datasets:
        print(f"📊 Datasets selecionados manualmente: {test_case.selected_datasets}")
    if test_case.instructions:
        print(f"📝 Instructions: {test_case.instructions[:50]}...")
    if test_case.creativity is not None:
        print(f"🎨 Creativity: {test_case.creativity}")
    if test_case.length is not None:
        print(f"📏 Length: {test_case.length}")
    print()
    
    start_time = time.time()
    db = SessionLocal()
    
    try:
        # 1. Buscar connection
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
        
        # 2. Criar DataSource
        print("✅ DataSource criado")
        datasource = DataSourceFactory.build_from_dataconnection(conn)
        
        # 3. Carregar AgentConfig
        print("✅ AgentConfig carregado")
        agent_config = load_agent_config(db, TEST_SPACE_ID, TEST_CREW_ID, conn.id)
        print(f"   Tabelas disponíveis: {[t.logical_name for t in agent_config.tables]}")
        
        # 4. Criar LLM e Embedding providers
        llm = LangChainChatOpenAIProvider(model="gpt-4o-mini", temperature=0.0)
        embedding_provider = OpenAIEmbeddingProvider(model="text-embedding-3-large")
        
        # 5. Criar UserContext
        test_user = User(
            id=UUID("00000000-0000-0000-0000-000000000000"),
            email="test@example.com",
            name="Test User",
            is_active=True
        )
        user_ctx = UserContext(
            user=test_user,
            space_id=UUID(TEST_SPACE_ID) if TEST_SPACE_ID else None,
            crew_id=UUID(TEST_CREW_ID) if TEST_CREW_ID else None,
            permissions=[],
        )
        
        # 6. Executar agente
        print("🚀 Executando agente...")
        final_state = run_agent_once(
            question=test_case.question,
            user_ctx=user_ctx,
            agent_config=agent_config,
            data_source=datasource,
            db_session_factory=lambda: SessionLocal(),
            embedding_provider=embedding_provider,
            llm_orchestrator=llm,
            llm_specialist=llm,
            llm_formatter=llm,
            instructions=test_case.instructions,
            creativity=test_case.creativity,
            length=test_case.length,
            response_format=test_case.response_format,
            sql_instructions=test_case.sql_instructions,
            selected_datasets=test_case.selected_datasets,
        )
        
        execution_time = time.time() - start_time
        
        # 7. Validar resultado
        sql_generated = final_state.get("sql")
        answer = final_state.get("answer")
        error = final_state.get("error")
        chosen_tables = final_state.get("chosen_tables") or []
        
        print(f"\n⏱️  Tempo de execução: {execution_time:.2f}s")
        
        if error:
            print(f"❌ ERRO: {error}")
            return {
                "success": False,
                "error": error,
                "execution_time": execution_time,
            }
        
        if sql_generated:
            print(f"✅ SQL gerado:")
            print(f"   {sql_generated[:200]}...")
        
        if chosen_tables:
            print(f"✅ Tabelas escolhidas: {chosen_tables}")
            if test_case.expected_datasets:
                expected_set = set(test_case.expected_datasets)
                actual_set = set(chosen_tables)
                if expected_set == actual_set:
                    print(f"✅ Datasets corretos! Esperado: {expected_set}, Obtido: {actual_set}")
                else:
                    print(f"⚠️  Datasets diferentes! Esperado: {expected_set}, Obtido: {actual_set}")
        
        if answer:
            print(f"✅ Resposta gerada:")
            print(f"   {answer[:200]}...")
        
        success = bool(sql_generated and answer and not error)
        
        return {
            "success": success,
            "sql": sql_generated,
            "answer": answer,
            "chosen_tables": chosen_tables,
            "execution_time": execution_time,
            "error": error,
        }
        
    except Exception as e:
        execution_time = time.time() - start_time
        print(f"❌ EXCEÇÃO: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "execution_time": execution_time,
        }
    finally:
        db.close()


def main():
    """Função principal"""
    print("="*80)
    print("🧪 TESTES END-TO-END COMPLETOS")
    print("="*80)
    print(f"Space ID: {TEST_SPACE_ID}")
    print(f"Connection ID: {TEST_CONNECTION_ID}")
    print(f"Crew ID: {TEST_CREW_ID or 'None'}")
    print()
    
    # Definir casos de teste
    test_cases = [
        TestCase(
            name="Fluxo Normal - Seleção Automática",
            question="Quantas invoices temos?",
            description="Testa o fluxo normal onde o sistema seleciona automaticamente os datasets",
        ),
        TestCase(
            name="Seleção Manual - Dataset Único",
            question="Quantos clientes temos?",
            selected_datasets=["silver_customers_enriquecido"],
            expected_datasets=["silver_customers_enriquecido"],
            description="Testa seleção manual de um único dataset",
        ),
        TestCase(
            name="Seleção Manual - Múltiplos Datasets",
            question="Qual é a relação entre invoices e payments?",
            selected_datasets=["silver_invoices_enriquecido", "silver_payments_enriquecido"],
            expected_datasets=["silver_invoices_enriquecido", "silver_payments_enriquecido"],
            description="Testa seleção manual de múltiplos datasets",
        ),
        TestCase(
            name="Com Instructions",
            question="Analise os dados de invoices",
            instructions="Sempre inclua gráficos na resposta",
            description="Testa configuração de instructions",
        ),
        TestCase(
            name="Com Creativity",
            question="Descreva os padrões de pagamentos",
            creativity=7,
            description="Testa configuração de creativity (temperature)",
        ),
        TestCase(
            name="Com Length",
            question="Quantos customers temos e qual é o valor total de invoices?",
            length=75,  # Valor válido: 0-100 (75 = resposta longa, ~2500 tokens)
            description="Testa configuração de length (max_tokens)",
        ),
        TestCase(
            name="Com Response Format",
            question="Liste os top 5 customers por valor",
            response_format="markdown",
            description="Testa configuração de response_format",
        ),
        TestCase(
            name="Com SQL Instructions",
            question="Quantos invoices temos?",
            sql_instructions="Use apenas COUNT, não SUM",
            description="Testa configuração de sql_instructions",
        ),
    ]
    
    results = []
    passed = 0
    failed = 0
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n[{i}/{len(test_cases)}]")
        result = run_test_case(test_case)
        result["test_name"] = test_case.name
        result["test_description"] = test_case.description
        results.append(result)
        
        if result["success"]:
            passed += 1
            print(f"✅ TESTE PASSOU")
        else:
            failed += 1
            print(f"❌ TESTE FALHOU")
    
    # Resumo final
    print("\n" + "="*80)
    print("📊 RESUMO FINAL")
    print("="*80)
    print(f"Total de testes: {len(test_cases)}")
    print(f"✅ Passou: {passed}")
    print(f"❌ Falhou: {failed}")
    print(f"📈 Taxa de sucesso: {(passed / len(test_cases) * 100):.1f}%")
    print("="*80)
    
    # Mostrar falhas
    if failed > 0:
        print("\n❌ TESTES QUE FALHARAM:")
        for result in results:
            if not result["success"]:
                print(f"\n  - {result['test_name']}")
                if result.get("error"):
                    print(f"    Erro: {result['error']}")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
