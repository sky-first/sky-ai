# core/llm/tools.py
from typing import List, Optional
from langchain_core.tools import tool
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from core.agents.generic_sql_agent import AgentConfig
from core.rag.embeddings import EmbeddingProvider
from core.rag.vector_store import search_embeddings

class ToolFactory:
    """
    Fábrica responsável por criar as ferramentas dinâmicas para o Orquestrador
    (Agentic RAG Tool Calling).
    """

    @staticmethod
    def create_metadata_tool(agent_config: AgentConfig):
        @tool
        def search_database_metadata() -> str:
            """
            OBRIGATÓRIO: Use esta ferramenta para explorar a estrutura do banco de dados, descobrir quais tabelas existem, 
            ler as descrições dos dados e mapear chaves estrangeiras (JOINs). Acione sempre antes de formular perguntas a dados reais
            ou responder sobre a estrutura do banco.
            """
            tables_info = []
            for t in agent_config.tables:
                desc = getattr(t, "description", None) or "No description provided."
                # Build column list with semantic descriptions when available
                col_parts = []
                for c in t.columns:
                    if isinstance(c, dict):
                        name = c.get("name", "")
                        ctype = c.get("type", "")
                        cdesc = c.get("description", "")
                    else:
                        name = getattr(c, "name", "")
                        ctype = getattr(c, "type", "")
                        cdesc = getattr(c, "description", "") or ""
                    # Strip the "TABLE: ... COLUMN: ..." prefix stored by update_semantic_metadata
                    # to keep just the "COLUMN MEANING:" part for brevity
                    if cdesc and "COLUMN MEANING:" in cdesc:
                        cdesc = cdesc.split("COLUMN MEANING:")[-1].strip()
                    col_entry = f"{name} ({ctype})"
                    if cdesc:
                        col_entry += f" — {cdesc}"
                    col_parts.append(col_entry)
                col_list = "\n  - ".join(col_parts)
                tables_info.append(
                    f"Table: {t.logical_name} | Physical: {t.physical_name}\n"
                    f"Description: {desc}\n"
                    f"Columns:\n  - {col_list}"
                )
            
            return "DATABASE SCHEMA AND METADATA:\n\n" + "\n\n".join(tables_info)

        return search_database_metadata

    @staticmethod
    def create_strategy_tool(db: Session, embedding_provider: EmbeddingProvider, space_id: str, crew_ids: Optional[List[str]]):
        @tool
        def search_corporate_strategy(query: str) -> str:
            """
            Busca informações sobre os objetivos (OKRs), metas e pilares estratégicos da empresa. 
            Use apenas quando a intenção do usuário envolver estratégia, negócios corporativos ou viés de longo prazo.
            """
            records = search_embeddings(
                db=db,
                embedding_provider=embedding_provider,
                space_id=space_id,
                crew_ids=crew_ids,
                query_text=query,
                top_k=10
            )

            # Filtramos localmente apenas o que for do tipo business_context ou target
            strategy_contexts = []
            for rec in records:
                meta = rec.extra_metadata if isinstance(rec.extra_metadata, dict) else {}
                kind = meta.get("type", "") or meta.get("kind", "")
                if kind in ("business_context", "objective", "key_result", "target", "pillar"):
                    strategy_contexts.append(f"[STRATEGY] {meta.get('name', 'Unknown')}: {rec.text}")

            if not strategy_contexts:
                return "No strategic documentation found for this query."
            
            return "\\n\\n".join(strategy_contexts)

        return search_corporate_strategy

    @staticmethod
    def create_signals_tool(db: Session, embedding_provider: EmbeddingProvider, space_id: str, crew_ids: Optional[List[str]]):
        @tool
        def search_market_signals(query: str) -> str:
            """
            Recupera anomalias recentes, sinais externos de mercado e eventos atípicos. 
            Acione se a dúvida do usuário estiver ligada a flutuações, quedas repentinas, riscos ou contexto externo de mercado.
            """
            records = search_embeddings(
                db=db,
                embedding_provider=embedding_provider,
                space_id=space_id,
                crew_ids=crew_ids,
                query_text=query,
                top_k=8
            )

            # Filtramos localmente eventos e anomalias
            signals_contexts = []
            for rec in records:
                meta = rec.extra_metadata if isinstance(rec.extra_metadata, dict) else {}
                kind = meta.get("type", "") or meta.get("kind", "")
                if kind in ("signal", "event", "anomaly", "news"):
                    signals_contexts.append(f"[SIGNAL/EVENT] {meta.get('name', 'Unknown')}: {rec.text}")

            if not signals_contexts:
                return "No market signals or events found for this query."
            
            return "\\n\\n".join(signals_contexts)

        return search_market_signals

