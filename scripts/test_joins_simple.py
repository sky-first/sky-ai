#!/usr/bin/env python3
"""Teste Simplificado de JOINs - Verifica apenas a lógica sem executar queries"""

import os
import sys
import json
from dotenv import load_dotenv
load_dotenv()

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from sqlalchemy.orm import Session
from sqlalchemy import text
from db.base import SessionLocal
from core.agents.generic_sql_agent import AgentConfig, TableSchema
from core.sql.relationships import detect_relationships, find_join_path, TableRelationship

TEST_SPACE_ID = os.getenv("TEST_SPACE_ID") or "00000000-0000-0000-0000-000000000001"
TEST_CONNECTION_ID = os.getenv("TEST_CONNECTION_ID") or "00000000-0000-0000-0000-000000000002"

def load_agent_config(db: Session, space_id: str, conn_id: str) -> AgentConfig:
    result = db.execute(
        text("SELECT table_name, column_name, data_type, is_nullable, extra FROM table_metadata WHERE space_id = :space_id AND data_connection_id = :conn_id ORDER BY table_name, column_name"),
        {"space_id": space_id, "conn_id": conn_id}
    ).fetchall()
    
    if not result:
        raise ValueError(f"Nenhum metadata encontrado")
    
    tables = {}
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
    
    def detect_dataset(table_name: str) -> str:
        web_tables = ["silver_events_enriquecido", "silver_pageviews_enriquecido", "silver_sessions_enriquecido", "silver_sources_enriquecido", "silver_users_enriquecido", "silver_web_data_enriquecido"]
        return "data-mesh-gcp.web_silver" if table_name in web_tables else "data-mesh-gcp.billing_silver"
    
    table_schemas = []
    for tname, cols in tables.items():
        dataset = detect_dataset(tname)
        physical_name = f"{dataset}.{tname}" if "." not in tname else tname
        schema = TableSchema(
            logical_name=tname,
            physical_name=physical_name,
            columns=[{
                "name": c["column_name"],
                "type": c["data_type"],
                "nullable": c["is_nullable"],
                "is_primary_key": c.get("is_primary_key", False),
                "is_foreign_key": c.get("is_foreign_key", False),
            } for c in cols],
        )
        table_schemas.append(schema)
    
    return AgentConfig(id=f"test_{conn_id}", name="Test Agent", tables=table_schemas)

def main():
    print("="*60)
    print("🚀 TESTES SIMPLIFICADOS DE JOINs")
    print("="*60)
    
    db = SessionLocal()
    try:
        print("\n📦 Carregando configuração...")
        agent_config = load_agent_config(db, TEST_SPACE_ID, TEST_CONNECTION_ID)
        print(f"✅ {len(agent_config.tables)} tabelas carregadas")
        
        print("\n🔍 Detectando relacionamentos...")
        relationships = detect_relationships(agent_config.tables)
        print(f"{'✅' if relationships else '❌'} {len(relationships)} relacionamentos detectados")
        
        if relationships:
            for rel in relationships[:5]:
                print(f"  - {rel.from_table}.{rel.from_column} -> {rel.to_table}.{rel.to_column}")
        
        print("\n🛤️  Testando caminhos de JOIN...")
        if relationships:
            table_names = [t.logical_name for t in agent_config.tables]
            paths_found = 0
            for i, t1 in enumerate(table_names[:3]):
                for t2 in table_names[i+1:min(i+3, len(table_names))]:
                    path = find_join_path([t1, t2], relationships)
                    if path:
                        print(f"  ✅ {t1} <-> {t2}: caminho encontrado")
                        paths_found += 1
            print(f"\n📊 {paths_found} caminhos encontrados")
        else:
            print("  ⚠️  Nenhum relacionamento para testar")
        
        print("\n✅ Testes concluídos!")
        
    except Exception as e:
        print(f"\n❌ ERRO: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    main()
