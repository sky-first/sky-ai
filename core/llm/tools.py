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
    def create_list_tables_tool(
        agent_config: AgentConfig,
        connection_labels: Optional[dict] = None,
    ):
        """Compact catalogue — name + 1-line description, ~800 tokens for 77 tables.

        connection_labels: {connection_id: "label"} — when provided, tables are
        grouped by data source so the agent knows which DB to query.
        """
        @tool
        def list_tables() -> str:
            """List all available database tables with a one-line description.
            Call this FIRST to understand what data exists. Returns logical name,
            physical name, and a brief description for each table.
            Tables are grouped by data source when multiple connections are available.
            Use get_table_schema(table_name) afterwards to see full column details.
            """
            if not agent_config.tables:
                return "No tables available in this data space."

            labels = connection_labels or {}

            # Group tables by connection_id when labels are provided
            if labels:
                from collections import defaultdict
                groups: dict = defaultdict(list)
                for t in agent_config.tables:
                    conn_id = str(getattr(t, "data_connection_id", "") or "")
                    groups[conn_id].append(t)

                lines = ["AVAILABLE TABLES (grouped by data source)\n"]
                for conn_id, tables in groups.items():
                    label = labels.get(conn_id, f"source:{conn_id[:8]}")
                    lines.append(f"\n[{label}]")
                    for t in tables:
                        desc = getattr(t, "description", None) or "No description."
                        if len(desc) > 100:
                            desc = desc[:97] + "..."
                        lines.append(f"  - {t.logical_name} → {t.physical_name}: {desc}")
            else:
                lines = ["AVAILABLE TABLES (logical → physical: description)\n"]
                for t in agent_config.tables:
                    desc = getattr(t, "description", None) or "No description."
                    if len(desc) > 120:
                        desc = desc[:117] + "..."
                    lines.append(f"- {t.logical_name} → {t.physical_name}: {desc}")

            return "\n".join(lines)

        return list_tables

    @staticmethod
    def create_table_schema_tool(agent_config: AgentConfig):
        """Full column detail for a single table — called on demand."""
        class _Input(BaseModel):
            table_name: str = Field(
                ...,
                description="Logical table name as returned by list_tables(). "
                            "Also accepts the physical name.",
            )

        @tool(args_schema=_Input)
        def get_table_schema(table_name: str) -> str:
            """Return the full column schema for a specific table.
            Call list_tables() first to discover valid table names, then call
            this for the 1-2 tables you actually want to query.
            """
            target = None
            for t in agent_config.tables:
                if t.logical_name == table_name or t.physical_name == table_name:
                    target = t
                    break

            if target is None:
                available = ", ".join(t.logical_name for t in agent_config.tables)
                return (
                    f"Table '{table_name}' not found. "
                    f"Available logical names: {available}"
                )

            desc = getattr(target, "description", None) or "No description provided."
            col_parts = []
            for c in target.columns:
                if isinstance(c, dict):
                    name = c.get("name", "")
                    ctype = c.get("type", "")
                    cdesc = c.get("description", "") or ""
                else:
                    name = getattr(c, "name", "")
                    ctype = getattr(c, "type", "")
                    cdesc = getattr(c, "description", "") or ""
                if cdesc and "COLUMN MEANING:" in cdesc:
                    cdesc = cdesc.split("COLUMN MEANING:")[-1].strip()
                entry = f"  - {name} ({ctype})"
                if cdesc:
                    entry += f": {cdesc}"
                col_parts.append(entry)

            return (
                f"Table: {target.logical_name} | Physical: {target.physical_name}\n"
                f"Description: {desc}\n"
                f"Columns:\n" + "\n".join(col_parts)
            )

        return get_table_schema

    @staticmethod
    def create_strategy_tool(db: Session, embedding_provider: EmbeddingProvider, space_id: str, crew_ids: Optional[List[str]]):
        @tool
        def search_corporate_strategy(query: str) -> str:
            """
            Busca informações sobre os objetivos (OKRs), metas e pilares estratégicos da empresa.
            Use apenas quando a intenção do usuário envolver estratégia, negócios corporativos ou viés de longo prazo.
            """
            try:
                records = search_embeddings(
                    db=db,
                    embedding_provider=embedding_provider,
                    space_id=space_id or None,
                    crew_ids=crew_ids,
                    query_text=query,
                    top_k=10
                )
            except Exception:
                return "No strategic documentation found for this query."

            # Filtramos localmente apenas o que for do tipo business_context ou target
            strategy_contexts = []
            for rec in records:
                meta = rec.extra_metadata if isinstance(rec.extra_metadata, dict) else {}
                kind = meta.get("type", "") or meta.get("kind", "")
                if kind in ("business_context", "objective", "key_result", "target", "pillar"):
                    strategy_contexts.append(f"[STRATEGY] {meta.get('name', 'Unknown')}: {rec.text}")

            if not strategy_contexts:
                return "No strategic documentation found for this query."

            return "\n\n".join(strategy_contexts)

        return search_corporate_strategy

    @staticmethod
    def create_signals_tool(db: Session, embedding_provider: EmbeddingProvider, space_id: str, crew_ids: Optional[List[str]]):
        @tool
        def search_market_signals(query: str) -> str:
            """
            Recupera anomalias recentes, sinais externos de mercado e eventos atípicos.
            Acione se a dúvida do usuário estiver ligada a flutuações, quedas repentinas, riscos ou contexto externo de mercado.
            """
            try:
                records = search_embeddings(
                    db=db,
                    embedding_provider=embedding_provider,
                    space_id=space_id or None,
                    crew_ids=crew_ids,
                    query_text=query,
                    top_k=8
                )
            except Exception:
                return "No market signals or events found for this query."

            # Filtramos localmente eventos e anomalias
            signals_contexts = []
            for rec in records:
                meta = rec.extra_metadata if isinstance(rec.extra_metadata, dict) else {}
                kind = meta.get("type", "") or meta.get("kind", "")
                if kind in ("signal", "event", "anomaly", "news"):
                    signals_contexts.append(f"[SIGNAL/EVENT] {meta.get('name', 'Unknown')}: {rec.text}")

            if not signals_contexts:
                return "No market signals or events found for this query."

            return "\n\n".join(signals_contexts)

        return search_market_signals

