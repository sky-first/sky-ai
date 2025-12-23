#!/usr/bin/env python3
"""
Script de Testes para Funcionalidade de JOINs

Testa se o sistema consegue:
1. Detectar quando múltiplas tabelas são necessárias
2. Identificar relacionamentos entre tabelas
3. Gerar SQL com JOINs corretamente
4. Executar queries com JOINs

Uso:
    python3 scripts/test_joins.py
"""

from __future__ import annotations

import os
import sys
import json
from typing import Optional, List, Dict, Any

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
    AgentState,
    run_agent_once,
)
from core.auth.models import UserContext
from core.rag.embeddings import OpenAIEmbeddingProvider
from core.sql.relationships import detect_relationships, find_join_path


# ============== CONFIGURAÇÃO ==============

TEST_SPACE_ID = os.getenv("TEST_SPACE_ID") or "00000000-0000-0000-0000-000000000001"
TEST_CREW_ID: Optional[str] = os.getenv("TEST_CREW_ID") or None
TEST_CONNECTION_ID = os.getenv("TEST_CONNECTION_ID") or "00000000-0000-0000-0000-000000000002"

# Perguntas que devem requerer JOINs
JOIN_TEST_QUESTIONS = [
    {
        "question": "Quais são os pageviews por país e dispositivo?",
        "description": "Deve usar pageviews + sources (ou similar) com JOIN",
        "expected_tables": 2,
    },
    {
        "question": "Como se relacionam eventos e sessões?",
        "description": "Deve usar events + sessions com JOIN",
        "expected_tables": 2,
    },
    {
        "question": "Quais usuários têm mais pageviews?",
        "description": "Deve usar users + pageviews com JOIN",
        "expected_tables": 2,
    },
    {
        "question": "Mostre pageviews e eventos juntos",
        "description": "Deve usar pageviews + events com JOIN",
        "expected_tables": 2,
    },
]


def load_agent_config(
    db: Session,
    space_id: str,
    crew_id: str | None,
    conn_id: str,
) -> AgentConfig:
    """
    Carrega AgentConfig a partir de TableMetadata no banco.
    Compatível com schema real (usa SQL raw).
    """
    from core.agents.generic_sql_agent import TableColumn
    
    # Buscar metadados via SQL direto
    result = db.execute(
        text("""
            SELECT table_name, column_name, data_type, is_nullable, extra
            FROM table_metadata
            WHERE space_id = :space_id AND data_connection_id = :conn_id
            ORDER BY table_name, column_name
        """),
        {"space_id": space_id, "conn_id": conn_id}
    ).fetchall()
    
    if not result:
        raise ValueError(f"Nenhum metadata encontrado para connection {conn_id}")
    
    # Agrupar por tabela
    tables: dict[str, list] = {}
    for row in result:
        table_name = row[0]
        if table_name not in tables:
            tables[table_name] = []
        
        extra = row[4] if row[4] else {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except:
                extra = {}
        
        tables[table_name].append({
            "column_name": row[1],
            "data_type": row[2] or "STRING",
            "is_nullable": row[3] or False,
            "is_primary_key": extra.get("is_primary_key", False),
            "is_foreign_key": extra.get("is_foreign_key", False),
        })
    
    # Detectar dataset baseado no nome da tabela
    def detect_dataset(table_name: str) -> str:
        """Detecta o dataset correto baseado no nome da tabela"""
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
                    "nullable": c["is_nullable"],
                    "is_primary_key": c.get("is_primary_key", False),
                    "is_foreign_key": c.get("is_foreign_key", False),
                }
                for c in cols
            ],
        )
        table_schemas.append(schema)
    
    agent_config = AgentConfig(
        id=f"test_join_agent_{conn_id}",
        name="Test Join Agent",
        tables=table_schemas,
    )
    
    return agent_config


def test_relationship_detection(agent_config: AgentConfig) -> Dict[str, Any]:
    """Testa se os relacionamentos estão sendo detectados corretamente"""
    print("\n" + "="*60)
    print("🔍 TESTE 1: Detecção de Relacionamentos")
    print("="*60)
    
    relationships = detect_relationships(agent_config.tables)
    
    print(f"\n📊 Tabelas disponíveis: {len(agent_config.tables)}")
    for table in agent_config.tables:
        print(f"  - {table.logical_name} ({len(table.columns)} colunas)")
    
    print(f"\n🔗 Relacionamentos detectados: {len(relationships)}")
    for rel in relationships:
        print(f"  - {rel.from_table}.{rel.from_column} -> {rel.to_table}.{rel.to_column}")
    
    if not relationships:
        print("\n⚠️  NENHUM relacionamento detectado!")
        print("   Isso pode significar que:")
        print("   1. As tabelas não têm FKs explícitas")
        print("   2. As convenções de nomenclatura não estão sendo seguidas")
        print("   3. Os metadados não estão marcando FKs corretamente")
    
    return {
        "tables_count": len(agent_config.tables),
        "relationships_count": len(relationships),
        "relationships": [
            {
                "from_table": rel.from_table,
                "from_column": rel.from_column,
                "to_table": rel.to_table,
                "to_column": rel.to_column,
            }
            for rel in relationships
        ],
    }


def test_join_path_finding(agent_config: AgentConfig, relationships: List) -> Dict[str, Any]:
    """Testa se consegue encontrar caminhos de JOIN entre tabelas"""
    print("\n" + "="*60)
    print("🛤️  TESTE 2: Busca de Caminhos de JOIN")
    print("="*60)
    
    from core.sql.relationships import TableRelationship
    
    # Converter para objetos TableRelationship
    rel_objects = [
        TableRelationship(
            from_table=r["from_table"],
            from_column=r["from_column"],
            to_table=r["to_table"],
            to_column=r["to_column"],
        )
        for r in relationships
    ]
    
    # Testar alguns pares de tabelas
    table_names = [t.logical_name for t in agent_config.tables]
    
    print(f"\n📋 Testando caminhos entre pares de tabelas...")
    
    test_results = []
    for i, table1 in enumerate(table_names[:3]):  # Limitar para não explodir
        for table2 in table_names[i+1:min(i+4, len(table_names))]:
            path = find_join_path([table1, table2], rel_objects)
            if path:
                print(f"  ✅ {table1} <-> {table2}: Caminho encontrado ({len(path)} JOINs)")
                test_results.append({
                    "tables": [table1, table2],
                    "path_found": True,
                    "path_length": len(path),
                })
            else:
                print(f"  ❌ {table1} <-> {table2}: Sem caminho")
                test_results.append({
                    "tables": [table1, table2],
                    "path_found": False,
                })
    
    return {
        "tested_pairs": len(test_results),
        "paths_found": sum(1 for r in test_results if r.get("path_found")),
        "results": test_results,
    }


def test_join_query(question: str, description: str, agent_config: AgentConfig, 
                   data_source, db: Session, llm_orch, llm_spec, llm_fmt, 
                   embedding_provider) -> Dict[str, Any]:
    """Testa uma pergunta que deve gerar JOIN"""
    print("\n" + "="*60)
    print(f"🧪 TESTE: {description}")
    print("="*60)
    print(f"❓ Pergunta: {question}")
    
    user_ctx = UserContext(
        user_id="test_user",
        space_id=TEST_SPACE_ID,
        crew_ids=[TEST_CREW_ID] if TEST_CREW_ID else [],
    )
    
    try:
        state = run_agent_once(
            question=question,
            user_ctx=user_ctx,
            agent_config=agent_config,
            data_source=data_source,
            db_session_factory=lambda: db,
            embedding_provider=embedding_provider,
            llm_orchestrator=llm_orch,
            llm_specialist=llm_spec,
            llm_formatter=llm_fmt,
        )
        
        # Verificar resultados
        chosen_tables = state.get("chosen_tables")
        join_relationships = state.get("join_relationships")
        sql = state.get("sql", "")
        error = state.get("error")
        impossible = state.get("impossible_reason")
        
        print(f"\n📊 Resultados:")
        print(f"  - Tabelas escolhidas: {chosen_tables or state.get('chosen_table', 'N/A')}")
        print(f"  - Relacionamentos JOIN: {len(join_relationships) if join_relationships else 0}")
        print(f"  - SQL gerado: {'SIM' if sql else 'NÃO'}")
        print(f"  - Erro: {error or 'Nenhum'}")
        print(f"  - Impossível: {impossible or 'Não'}")
        
        if sql:
            print(f"\n📝 SQL:")
            print(f"```sql")
            print(sql[:500] + ("..." if len(sql) > 500 else ""))
            print(f"```")
            
            # Verificar se tem JOIN
            has_join = "join" in sql.lower()
            print(f"\n  {'✅' if has_join else '❌'} Contém JOIN: {has_join}")
        
        # Verificar se múltiplas tabelas foram escolhidas
        multiple_tables = (
            chosen_tables and len(chosen_tables) > 1
        ) or (
            not chosen_tables and "," in (state.get("chosen_table") or "")
        )
        
        success = (
            not error and 
            not impossible and 
            sql and 
            (has_join if sql else False) and
            multiple_tables
        )
        
        return {
            "question": question,
            "success": success,
            "chosen_tables": chosen_tables or [state.get("chosen_table")],
            "join_relationships": join_relationships,
            "has_join": has_join if sql else False,
            "sql": sql[:200] if sql else None,
            "error": error,
            "impossible": impossible,
            "answer": state.get("answer", "")[:200] if state.get("answer") else None,
        }
        
    except Exception as e:
        print(f"\n❌ ERRO ao executar teste: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "question": question,
            "success": False,
            "error": str(e),
        }


def main():
    """Executa todos os testes de JOIN"""
    print("="*60)
    print("🚀 TESTES DE FUNCIONALIDADE DE JOINs")
    print("="*60)
    
    db = SessionLocal()
    try:
        # Carregar configuração
        print("\n📦 Carregando configuração do agente...")
        agent_config = load_agent_config(
            db=db,
            space_id=TEST_SPACE_ID,
            crew_id=TEST_CREW_ID,
            conn_id=TEST_CONNECTION_ID,
        )
        print(f"✅ Configuração carregada: {len(agent_config.tables)} tabelas")
        
        # Criar data source
        print("\n🔌 Criando data source...")
        from core.data_sources.factory import build_data_source_for_connection
        from db.models import DataConnection
        
        conn_result = db.execute(
            text("SELECT id, config FROM data_connections WHERE id = :id"),
            {"id": TEST_CONNECTION_ID}
        ).first()
        
        if not conn_result:
            print(f"❌ Conexão {TEST_CONNECTION_ID} não encontrada!")
            return
        
        conn_config = conn_result[1]
        if isinstance(conn_config, str):
            conn_config = json.loads(conn_config)
        
        temp_conn = DataConnection(
            id=conn_result[0],
            space_id=TEST_SPACE_ID,
            name="Test Connection",
            type="bigquery",
            config=conn_config,
        )
        
        data_source = build_data_source_for_connection(temp_conn)
        print("✅ Data source criado")
        
        # Criar LLMs
        print("\n🤖 Criando LLMs...")
        llm_orch = LangChainChatOpenAIProvider(model="gpt-4o-mini")
        llm_spec = LangChainChatOpenAIProvider(model="gpt-4o-mini")
        llm_fmt = LangChainChatOpenAIProvider(model="gpt-4o-mini")
        embedding_provider = OpenAIEmbeddingProvider()
        print("✅ LLMs criados")
        
        # TESTE 1: Detecção de relacionamentos
        rel_result = test_relationship_detection(agent_config)
        
        # TESTE 2: Busca de caminhos
        if rel_result["relationships_count"] > 0:
            path_result = test_join_path_finding(agent_config, rel_result["relationships"])
        else:
            print("\n⚠️  Pulando teste de caminhos (nenhum relacionamento detectado)")
            path_result = {"tested_pairs": 0, "paths_found": 0}
        
        # TESTE 3: Queries com JOINs
        print("\n" + "="*60)
        print("🔬 TESTE 3: Execução de Queries com JOINs")
        print("="*60)
        
        query_results = []
        for test_case in JOIN_TEST_QUESTIONS:
            result = test_join_query(
                question=test_case["question"],
                description=test_case["description"],
                agent_config=agent_config,
                data_source=data_source,
                db=db,
                llm_orch=llm_orch,
                llm_spec=llm_spec,
                llm_fmt=llm_fmt,
                embedding_provider=embedding_provider,
            )
            query_results.append(result)
        
        # Resumo final
        print("\n" + "="*60)
        print("📊 RESUMO DOS TESTES")
        print("="*60)
        print(f"\n1. Relacionamentos detectados: {rel_result['relationships_count']}")
        print(f"2. Caminhos de JOIN encontrados: {path_result['paths_found']}/{path_result['tested_pairs']}")
        print(f"3. Queries com JOIN bem-sucedidas: {sum(1 for r in query_results if r.get('success'))}/{len(query_results)}")
        
        print("\n📋 Detalhes das queries:")
        for i, result in enumerate(query_results, 1):
            status = "✅" if result.get("success") else "❌"
            print(f"  {status} {i}. {result['question'][:50]}...")
            if result.get("has_join"):
                print(f"     → JOIN detectado no SQL")
            if result.get("error"):
                print(f"     → Erro: {result['error']}")
        
        # Salvar resultados
        results = {
            "timestamp": str(db.execute(text("SELECT NOW()")).scalar()),
            "relationship_detection": rel_result,
            "path_finding": path_result,
            "query_tests": query_results,
        }
        
        with open("test_joins_report.json", "w") as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\n💾 Resultados salvos em: test_joins_report.json")
        
    except Exception as e:
        print(f"\n❌ ERRO GERAL: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()
