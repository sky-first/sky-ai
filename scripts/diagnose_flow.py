#!/usr/bin/env python3
"""
Script de Diagnóstico do Fluxo Completo
Analisa cada etapa do processo para entender como está funcionando.
"""

import os
import sys
from typing import Optional, List
from uuid import UUID

from dotenv import load_dotenv
load_dotenv()

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from sqlalchemy import text
from db.session import SessionLocal, engine
from core.data_sources.factory import DataSourceFactory
from core.llm.providers import LangChainChatOpenAIProvider
from core.agents.generic_sql_agent import (
    AgentConfig,
    TableSchema,
    run_agent_once,
)
from core.rag.embeddings import OpenAIEmbeddingProvider
from core.auth.models import UserContext, User

# IDs de teste
TEST_SPACE_ID = "e409079b-5bbf-4249-a769-2010609c30f2"
TEST_CONNECTION_ID = "9dfec38b-7bec-4ef0-8fb2-8430776b2178"
TEST_CREW_ID: Optional[str] = None


def load_agent_config(db, space_id: str, crew_id: str | None, conn_id: str) -> AgentConfig:
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
    tables: dict[str, List] = {}
    for row in result:
        table_name = row[0]
        if table_name not in tables:
            tables[table_name] = []
        tables[table_name].append({
            "column_name": row[1],
            "data_type": row[2] or "STRING",
            "is_nullable": row[3] or False
        })
    
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


def diagnose_orchestrator_behavior():
    """Diagnostica o comportamento do orchestrator"""
    print("="*80)
    print("🔍 DIAGNÓSTICO DO ORCHESTRATOR")
    print("="*80)
    
    db = SessionLocal()
    
    try:
        # 1. Buscar connection
        with engine.connect() as raw_conn:
            result = raw_conn.execute(
                text("SELECT id, name, connector_id, config FROM data_connections WHERE id = :id"),
                {"id": TEST_CONNECTION_ID}
            ).first()
            
            if not result:
                print("❌ DataConnection não encontrada")
                return
            
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
        
        # 2. Carregar AgentConfig
        agent_config = load_agent_config(db, TEST_SPACE_ID, TEST_CREW_ID, conn.id)
        
        print(f"\n📊 TABELAS DISPONÍVEIS ({len(agent_config.tables)}):")
        for table in agent_config.tables:
            print(f"  - {table.logical_name} -> {table.physical_name}")
        
        # 3. Testar diferentes cenários
        test_cases = [
            {
                "name": "Cenário 1: Sem selected_datasets",
                "question": "Quantos usuários temos?",
                "selected_datasets": None,
            },
            {
                "name": "Cenário 2: Com selected_datasets (tabela existente)",
                "question": "Quantos usuários temos?",
                "selected_datasets": ["silver_customers_enriquecido"],
            },
            {
                "name": "Cenário 3: Com selected_datasets (tabela inexistente)",
                "question": "Quantos usuários temos?",
                "selected_datasets": ["silver_users_enriquecido"],  # Esta tabela não existe no billing
            },
        ]
        
        llm = LangChainChatOpenAIProvider(model="gpt-4o-mini", temperature=0.0)
        
        for test_case in test_cases:
            print(f"\n{'='*80}")
            print(f"🧪 {test_case['name']}")
            print(f"{'='*80}")
            print(f"Pergunta: {test_case['question']}")
            if test_case['selected_datasets']:
                print(f"selected_datasets: {test_case['selected_datasets']}")
            
            # Simular o estado inicial
            from core.agents.generic_sql_agent import AgentState
            
            state: AgentState = {
                "question": test_case['question'],
                "space_id": TEST_SPACE_ID,
                "crew_ids": [],
                "selected_datasets": test_case['selected_datasets'],
            }
            
            # Executar apenas o orchestrator
            from core.llm.orchestrator import run_orchestrator
            
            print("\n📤 Estado ANTES do orchestrator:")
            print(f"  selected_datasets: {state.get('selected_datasets')}")
            print(f"  agent_config.tables (antes): {[t.logical_name for t in agent_config.tables]}")
            
            # Criar uma cópia do agent_config para não modificar o original
            import copy
            agent_config_copy = copy.deepcopy(agent_config)
            
            orchestrator_state = run_orchestrator(
                state=state,
                agent_config=agent_config_copy,
                llm=llm,
                db=db,
                embedding_provider=None,  # Desabilitar RAG para simplificar
            )
            
            print("\n📥 Estado DEPOIS do orchestrator:")
            print(f"  chosen_table: {orchestrator_state.get('chosen_table')}")
            print(f"  chosen_tables: {orchestrator_state.get('chosen_tables')}")
            print(f"  error: {orchestrator_state.get('error')}")
            print(f"  answer: {orchestrator_state.get('answer')}")
            print(f"  agent_config.tables (depois): {[t.logical_name for t in agent_config_copy.tables]}")
            
            if orchestrator_state.get('error'):
                print(f"  ❌ ERRO: {orchestrator_state.get('error')}")
            elif orchestrator_state.get('chosen_table') or orchestrator_state.get('chosen_tables'):
                print(f"  ✅ Tabela(s) escolhida(s) com sucesso!")
            else:
                print(f"  ⚠️  Nenhuma tabela foi escolhida")
    
    finally:
        db.close()


if __name__ == "__main__":
    diagnose_orchestrator_behavior()
