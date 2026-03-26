# scripts/test_universe_flow_real.py
import asyncio
import sys
import os

# Adiciona o diretório raiz ao path para encontrar os módulos
sys.path.append(os.getcwd())

from sqlalchemy.orm import Session
from sqlalchemy import text, select
from db.session import AsyncSessionLocal
from db.base import SyncSessionLocal
from db.models import DataConnection
from core.agents.universe.orchestrator import UniverseDiscoveryManager
from core.auth.models import UserContext, User
from core.agents.factory import build_agent_config_for_user_space
from core.data_sources.factory import DataSourceFactory
from core.llm.factory import create_embedding_provider
import uuid

async def run_real_test():
    print("🚀 Iniciando Teste REAL de Universe Intelligence...")
    
    db_async = AsyncSessionLocal()
    db_sync = SyncSessionLocal()
    
    # 1. Recupera IDs reais para o teste (Focando no Space billing com 100 tabelas)
    space_id = uuid.UUID('4931f6dc-145f-487a-8166-47c0e503b741')
    conn_id = uuid.UUID('c9207911-8f8d-4fcd-86a8-1fe77aa2ed25')
        
    if not space_id or not conn_id:
        print("❌ Erro: Não foram encontrados Spaces ou Conexões no banco de dados.")
        return

    print(f"📍 Usando Space: {space_id} | Conn: {conn_id}")
    
    user_obj = User(
        id=uuid.uuid4(),
        email="test@universe.ai",
        name="Universe Tester",
        is_active=True
    )
    
    user_ctx = UserContext(
        user=user_obj,
        space_id=space_id,
        crew_ids=[]
    )
    
    from core.dialects import Dialect
    
    # 2. Prepara Conexão e Dialeto
    conn_obj = db_sync.query(DataConnection).filter(DataConnection.id == conn_id).first()
    if not conn_obj:
        print(f"❌ Erro: DataConnection {conn_id} não encontrada no banco.")
        return
        
    data_source = DataSourceFactory.build_from_dataconnection(conn_obj)
    dialect = getattr(data_source, "dialect", Dialect.POSTGRES)
    
    # 3. Carrega AgentConfig REAL com dialeto detectado
    try:
        agent_config = build_agent_config_for_user_space(
            db=db_sync, 
            user_ctx=user_ctx, 
            space_id=str(space_id),
            dialect=dialect
        )
        print(f"📊 Tabelas Carregadas: {len(agent_config.tables)} | Dialeto: {agent_config.dialect}")
    except Exception as e:
        print(f"❌ Erro ao carregar AgentConfig: {e}")
        return

    embedding_provider = create_embedding_provider()
    manager = UniverseDiscoveryManager(db_sync)
    
    # --- TESTE 1: DESCOBERTA GERAL ---
    print("\n--- [PASSO 1] Testando Descoberta Geral (Universe Intelligence) ---")
    print("ℹ️ Aguardando orquestração proativa (Hypothesis -> Analysis -> Judge)...")
    
    insight_geral = await manager.run_general_discovery(
        user_ctx=user_ctx,
        agent_config=agent_config,
        empresa_contexto="Empresa de software e infraestrutura cloud.",
        objetivos_estrategicos=["Aumentar eficiência operacional", "Reduzir churn tecnico"],
        data_source=data_source,
        embedding_provider=embedding_provider,
        db_session_factory=SyncSessionLocal
    )
    
    if insight_geral:
        print(f"✅ Insight Geral GERADO e APROVADO: {insight_geral['title']}")
        print(f"💡 Resumo: {insight_geral['insight'][:100]}...")
    else:
        print("⚠️ Ciclo encerrado: Nenhum insight relevante encontrado ou reprovado pelo Juiz.")

    # --- TESTE 2: MISSÃO ---
    print("\n--- [PASSO 2] Testando Missão (Focado em Alvos) ---")
    insight_missao = await manager.run_mission_discovery(
        user_ctx=user_ctx,
        agent_config=agent_config,
        mission_id="test_mission_99",
        mission_description="Monitorar a adesão de novos planos premium.",
        expected_results="Detectar crescimento em assinaturas no último mês.",
        data_source=data_source,
        embedding_provider=embedding_provider,
        db_session_factory=SyncSessionLocal
    )
    
    if insight_missao:
        print(f"✅ Insight de Missão GERADO: {insight_missao['title']}")
    else:
        print("⚠️ Missão concluída sem insights relevantes agora.")

if __name__ == "__main__":
    asyncio.run(run_real_test())
