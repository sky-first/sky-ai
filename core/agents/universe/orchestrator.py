# core/agents/universe/orchestrator.py
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, desc
from db.models import UniverseInsight
from core.agents.universe.estrategista import HypothesisGenerator
from core.agents.universe.analista import DataAnalystAgent
from core.agents.universe.juiz import JudgeAgent
from core.llm.factory import create_llm_orchestrator, create_llm_specialist, create_llm_formatter
from core.auth.models import UserContext
from core.agents.generic_sql_agent import AgentConfig, TableSchema
from core.data_sources.base import BaseDataSource
from core.rag.embeddings import EmbeddingProvider
from core.rag.context_retrieval import build_retrieval_context_for_question_sync
import logging

logger = logging.getLogger(__name__)

class UniverseDiscoveryManager:
    """Maestro que coordena os agentes de descoberta proativa."""
    
    def __init__(self, db: Session):
        self.db = db
        # Instancia LLMs via factories (suporta Ollama/OpenAI via settings)
        self.llm_orchestrator = create_llm_orchestrator()
        self.llm_specialist = create_llm_specialist()
        self.llm_formatter = create_llm_formatter()
        
        # Instancia Agentes
        self.estrategista = HypothesisGenerator(self.llm_orchestrator)
        self.analista = DataAnalystAgent(self.llm_orchestrator, self.llm_specialist, self.llm_formatter)
        self.juiz = JudgeAgent(self.llm_orchestrator)

    def _get_recent_hashes(self, space_id: str, days: int = 7) -> List[str]:
        """Busca hashes de insights recentes para evitar duplicidade."""
        query = (
            select(UniverseInsight.content_hash)
            .where(UniverseInsight.space_id == space_id)
            .order_by(desc(UniverseInsight.created_at))
            .limit(100)
        )
        result = self.db.execute(query)
        return [row[0] for row in result if row[0]]

    def _save_insight(self, space_id: str, conn_id: str, insight_data: Dict, type: str, mission_id: Optional[str] = None):
        """Persiste o insight aprovado no banco de dados."""
        new_insight = UniverseInsight(
            space_id=space_id,
            data_connection_id=conn_id,
            insight_type=type,
            mission_id=mission_id,
            title=insight_data.get("title"),
            insight=insight_data.get("insight"),
            impact_level=insight_data.get("impact_level", "medium"),
            suggested_action=insight_data.get("suggested_action"),
            source_tables=insight_data.get("source_tables"),
            content_hash=insight_data.get("content_hash")
        )
        self.db.add(new_insight)
        self.db.commit()

    async def run_general_discovery(
        self,
        user_ctx: UserContext,
        agent_config: AgentConfig,
        empresa_contexto: str,
        objetivos_estrategicos: List[str],
        data_source: BaseDataSource,
        embedding_provider: EmbeddingProvider,
        db_session_factory: Any,
    ) -> Optional[Dict]:
        """Executa o ciclo de descoberta proativa geral (Universe Intelligence)."""
        
        # ✅ EXPANSÃO: Busca uma visão 360º (DNA, OKRs, Pilares, Riscos e Iniciativas)
        strategic_context = build_retrieval_context_for_question_sync(
            db=self.db,
            embedding_provider=embedding_provider,
            space_id=str(user_ctx.space_id),
            crew_ids=getattr(user_ctx, "crew_ids", []),
            question="DNA corporativo, OKRs, metas, pilares estratégicos, riscos de negócio e iniciativas em andamento",
            top_k=15 # Aumentamos o limite para cobrir mais áreas
        )
        
        # Consolida contexto (passado via API + o que achou no RAG)
        full_context_text = empresa_contexto + "\n" + "\n".join(objetivos_estrategicos)
        if strategic_context:
            full_context_text += "\n\nCONTEXTO ADICIONAL ENCONTRADO:\n" + "\n".join(strategic_context)

        # 1. Agente Estrategista gera a hipótese com o contexto completo
        # ✅ PRAGMÁTICO: Qualifica nomes físicos para BigQuery se necessário antes de gerar hipótese e passar ao analista
        conn_dataset = agent_config.extra.get("dataset")
        if agent_config.dialect == "bigquery" and conn_dataset:
            for t in agent_config.tables:
                if "." not in t.physical_name:
                    t.physical_name = f"{conn_dataset}.{t.physical_name}"

        hypothesis = await self.estrategista.generate_general_hypothesis(
            empresa_contexto=full_context_text + (f"\nDATASET PADRÃO: {conn_dataset}" if conn_dataset else ""),
            objetivos_estrategicos=objetivos_estrategicos,
            db_schema=agent_config.tables
        )
        
        # 2. Agente Analista processa os dados
        analysis_result = await self.analista.analyze_hypothesis(
            hypothesis=hypothesis,
            user_ctx=user_ctx,
            agent_config=agent_config,
            data_source=data_source,
            db_session_factory=db_session_factory,
            embedding_provider=embedding_provider
        )
        
        if not analysis_result["success"]:
            return None
            
        # 3. Agente Juiz valida e filtra
        recent_hashes = self._get_recent_hashes(str(user_ctx.space_id))
        final_insight = await self.juiz.verify_insight(
            insight_preliminar=analysis_result["insight"],
            raw_data=analysis_result["raw_data"],
            recent_hashes=recent_hashes
        )
        
        if final_insight:
            self._save_insight(
                space_id=str(user_ctx.space_id),
                conn_id=agent_config.extra.get("data_connection_id"),
                insight_data=final_insight,
                type="general"
            )
            return final_insight
            
        return None

    async def run_mission_discovery(
        self,
        user_ctx: UserContext,
        agent_config: AgentConfig,
        mission_id: str,
        mission_description: str,
        expected_results: str,
        data_source: BaseDataSource,
        embedding_provider: EmbeddingProvider,
        db_session_factory: Any,
    ) -> Optional[Dict]:
        """Executa o ciclo de descoberta focado em uma Missão específica."""
        
        # 1. Agente Estrategista foca na missão
        # Tenta extrair dataset para qualificação
        conn_dataset = agent_config.extra.get("dataset")
        hypothesis = await self.estrategista.generate_mission_hypothesis(
            mission_description=mission_description + (f"\nDATASET PADRÃO: {conn_dataset}" if conn_dataset else ""),
            expected_results=expected_results,
            db_schema=agent_config.tables
        )
        
        # 2. Analista processa
        analysis_result = await self.analista.analyze_hypothesis(
            hypothesis=hypothesis,
            user_ctx=user_ctx,
            agent_config=agent_config,
            data_source=data_source,
            db_session_factory=db_session_factory,
            embedding_provider=embedding_provider
        )
        
        if not analysis_result["success"]:
            return None
            
        # 3. Juiz valida (Mêsma lógica de rigor)
        recent_hashes = self._get_recent_hashes(str(user_ctx.space_id))
        final_insight = await self.juiz.verify_insight(
            insight_preliminar=analysis_result["insight"],
            raw_data=analysis_result["raw_data"],
            recent_hashes=recent_hashes
        )
        
        if final_insight:
            self._save_insight(
                space_id=str(user_ctx.space_id),
                conn_id=agent_config.extra.get("data_connection_id"),
                insight_data=final_insight,
                type="mission",
                mission_id=mission_id
            )
            return final_insight
            
        return None
