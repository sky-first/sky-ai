# scripts/test_universe_flow.py
import asyncio
import sys
import os
from sqlalchemy.orm import Session
from db.session import SyncSessionLocal
from core.agents.universe.orchestrator import UniverseDiscoveryManager
from core.auth.models import UserContext
from core.agents.factory import build_agent_config_for_user_space
from core.data_sources.factory import DataSourceFactory
from core.rag.embeddings import create_embedding_provider
import uuid

async def test_universe():
    print("🚀 Iniciando Teste de Universe Intelligence...")
    db = SyncSessionLocal()
    
    # IDs de exemplo (ajuste conforme seu banco local para um teste real)
    space_id = "00000000-0000-0000-0000-000000000000" # Dummy
    conn_id = "00000000-0000-0000-0000-000000000000" # Dummy
    
    user_ctx = UserContext(
        user_id=uuid.uuid4(),
        space_id=uuid.UUID(space_id),
        crew_ids=[]
    )
    
    # Tenta carregar config real se o banco tiver dados, senão usa mock
    try:
        agent_config = build_agent_config_for_user_space(db, user_ctx, space_id)
    except:
        from core.agents.generic_sql_agent import AgentConfig, TableSchema
        agent_config = AgentConfig(
            id="test_agent",
            name="Test Agent",
            tables=[
                TableSchema(logical_name="vendas", physical_name="silver_vendas", columns=[
                    {"name": "id", "type": "int"},
                    {"name": "valor", "type": "float"},
                    {"name": "data", "type": "date"}
                ])
            ],
            extra={"data_connection_id": conn_id}
        )

    data_source = DataSourceFactory.create_from_id(conn_id) if conn_id != "00000000" else None
    embedding_provider = create_embedding_provider()
    
    manager = UniverseDiscoveryManager(db)
    
    # 1. Teste de Descoberta Geral
    print("\n--- Testando Descoberta Geral (Universe Intelligence) ---")
    print("ℹ️ O sistema agora busca automaticamente Contextos de RAG (DNA/OKRs) para guiar o Estrategista.")
    insight_geral = await manager.run_general_discovery(
        user_ctx=user_ctx,
        agent_config=agent_config,
        empresa_contexto="Empresa de varejo focada em moda sustentável.",
        objetivos_estrategicos=["Aumentar ROI", "Reduzir estoque parado"],
        data_source=data_source,
        embedding_provider=embedding_provider,
        db_session_factory=SyncSessionLocal
    )
    
    if insight_geral:
        print(f"✅ Insight Geral Gerado: {insight_geral['title']}")
    else:
        print("⚠️ Nenhum insight geral gerado (ou reprovado pelo Juiz).")

    # 2. Teste de Missão
    print("\n--- Testando Missão (Monitoramento Específico) ---")
    insight_missao = await manager.run_mission_discovery(
        user_ctx=user_ctx,
        agent_config=agent_config,
        mission_id="missao_apollo_01",
        mission_description="Monitorar queda de vendas repentina em roupas de inverno.",
        expected_results="Detectar se as vendas caírem mais de 20% em comparação à semana anterior.",
        data_source=data_source,
        embedding_provider=embedding_provider,
        db_session_factory=SyncSessionLocal
    )
    
    if insight_missao:
        print(f"✅ Insight de Missão Gerado: {insight_missao['title']}")
    else:
        print("⚠️ Nenhum insight de missão gerado.")

if __name__ == "__main__":
    asyncio.run(test_universe())
