#!/usr/bin/env python3
"""Teste de JOINs com Dados Mockados - Não requer banco de dados"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.agents.generic_sql_agent import AgentConfig, TableSchema
from core.sql.relationships import detect_relationships, find_join_path


def create_mock_tables():
    """Cria tabelas mockadas para teste"""
    users_table = TableSchema(
        logical_name="silver_users_enriquecido",
        physical_name="data-mesh-gcp.web_silver.silver_users_enriquecido",
        columns=[
            {"name": "id", "type": "STRING", "nullable": False, "is_primary_key": True, "is_foreign_key": False},
            {"name": "email", "type": "STRING", "nullable": True, "is_primary_key": False, "is_foreign_key": False},
        ],
    )
    
    pageviews_table = TableSchema(
        logical_name="silver_pageviews_enriquecido",
        physical_name="data-mesh-gcp.web_silver.silver_pageviews_enriquecido",
        columns=[
            {"name": "id", "type": "STRING", "nullable": False, "is_primary_key": True, "is_foreign_key": False},
            {"name": "user_id", "type": "STRING", "nullable": True, "is_primary_key": False, "is_foreign_key": True},
            {"name": "page_url", "type": "STRING", "nullable": True, "is_primary_key": False, "is_foreign_key": False},
        ],
    )
    
    sessions_table = TableSchema(
        logical_name="silver_sessions_enriquecido",
        physical_name="data-mesh-gcp.web_silver.silver_sessions_enriquecido",
        columns=[
            {"name": "id", "type": "STRING", "nullable": False, "is_primary_key": True, "is_foreign_key": False},
            {"name": "user_id", "type": "STRING", "nullable": True, "is_primary_key": False, "is_foreign_key": True},
        ],
    )
    
    return [users_table, pageviews_table, sessions_table]


def main():
    print("="*60)
    print("🚀 TESTE DE JOINs COM DADOS MOCKADOS")
    print("="*60)
    
    try:
        tables = create_mock_tables()
        print(f"\n✅ {len(tables)} tabelas mockadas criadas")
        
        agent_config = AgentConfig(id="test_mock", name="Test Mock", tables=tables)
        
        print("\n🔍 Detectando relacionamentos...")
        relationships = detect_relationships(agent_config.tables)
        print(f"{'✅' if relationships else '❌'} {len(relationships)} relacionamentos detectados")
        
        if relationships:
            for rel in relationships:
                print(f"  - {rel.from_table}.{rel.from_column} -> {rel.to_table}.{rel.to_column}")
        
        print("\n🛤️  Testando caminhos de JOIN...")
        if relationships:
            path = find_join_path(["silver_pageviews_enriquecido", "silver_users_enriquecido"], relationships)
            if path:
                print(f"  ✅ Caminho encontrado: {len(path)} JOIN(s)")
            else:
                print(f"  ❌ Caminho não encontrado")
        
        print("\n✅ Teste concluído!")
        
    except Exception as e:
        print(f"\n❌ ERRO: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
