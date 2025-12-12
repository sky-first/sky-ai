# core/agents/generic_sql_agent.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypedDict, Callable

from sqlalchemy.orm import Session
from langgraph.graph import StateGraph, END

from core.auth.models import UserContext  # ajuste se o caminho for outro
from core.llm.providers import LLMProvider
from core.data_sources.base import BaseDataSource
from core.rag.embeddings import EmbeddingProvider
from core.logging_utils import log_event

# Importações tardias para evitar circular imports
# Essas importações serão feitas dentro das funções onde são usadas


# ==================== STATE DO AGENTE ====================

class AgentState(TypedDict, total=False):
    # Entrada
    question: str

    # Contexto de permissão / multitenant
    user_id: Optional[str]
    space_id: Optional[str]
    crew_ids: Optional[List[str]]

    # Idioma
    detected_language: Optional[str]

    # RAG
    retrieval_context: List[str]

    # Decisão do orchestrator
    chosen_table: Optional[str]            # logical_name (mantido para compatibilidade)
    chosen_table_physical: Optional[str]   # physical_name (mantido para compatibilidade)
    chosen_tables: Optional[List[str]]     # logical_names de múltiplas tabelas (novo)
    chosen_tables_physical: Optional[List[str]]  # physical_names correspondentes (novo)
    join_relationships: Optional[List[Dict[str, str]]]  # relacionamentos para JOINs (novo)

    # Saída do specialist
    sql: Optional[str]
    data: Optional[List[Dict[str, Any]]]
    impossible_reason: Optional[str]
    error: Optional[str]

    # Saída final
    answer: Optional[str]


# ==================== CONFIG DO AGENTE ====================

class TableColumn(TypedDict, total=False):
    name: str
    type: str
    is_nullable: bool
    description: Optional[str]
    is_primary_key: bool
    is_foreign_key: bool


@dataclass
class TableSchema:
    """
    Representa uma tabela que o agente pode usar.
    logical_name: nome amigável (ex: "invoices")
    physical_name: nome físico no banco (ex: "billing_silver.invoices_enriched")
    """
    logical_name: str
    physical_name: str
    description: Optional[str] = None
    columns: List[TableColumn] = field(default_factory=list)
    # opcional: ID da conexão externa (BigQuery, Postgres do cliente, etc.)
    data_connection_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentConfig:
    """
    Configuração de um agente genérico:
    - id: identificador lógico (ex: "default_billing_agent")
    - name: nome amigável
    - tables: lista de TableSchema que esse agente conhece
    """
    id: str
    name: str
    tables: List[TableSchema] = field(default_factory=list)
    # lugar para configs extras (limites, instruções, etc.)
    extra: Dict[str, Any] = field(default_factory=dict)


# ==================== SESSION FACTORY TYPE ====================

# Uma factory simples que retorna uma Session do SQLAlchemy
SessionFactory = Callable[[], Session]


# ==================== GRAFO GENÉRICO (LangGraph) ====================

def build_generic_sql_graph(
    agent_config: AgentConfig,
    data_source: BaseDataSource,
    db_session_factory: SessionFactory,
    embedding_provider: EmbeddingProvider,
    llm_orchestrator: LLMProvider,
    llm_specialist: LLMProvider,
    llm_formatter: LLMProvider,
):
    """
    Monta o grafo LangGraph com 3 nós:
    - orchestrator → escolhe logical table
    - specialist  → gera SQL + executa
    - formatter   → gera resposta natural language

    Cada nó fecha sobre suas dependências (agent_config, data_source, LLMs, etc.).
    """

    def orchestrator_node(state: AgentState) -> AgentState:
        """
        Node de orquestração:
        - abre uma Session
        - chama run_orchestrator com RAG ligado (db + embedding_provider)
        """
        # Importação tardia para evitar circular import
        from core.llm.orchestrator import run_orchestrator
        
        db: Session = db_session_factory()
        try:
            new_state = run_orchestrator(
                state=state,
                agent_config=agent_config,
                llm=llm_orchestrator,
                db=db,
                embedding_provider=embedding_provider,
            )
        finally:
            db.close()
        return new_state

    def specialist_node(state: AgentState) -> AgentState:
        """
        Node especialista:
        - usa a tabela escolhida
        - gera SQL
        - executa via data_source
        """
        # Importação tardia para evitar circular import
        from core.llm.specialist import run_specialist
        
        new_state = run_specialist(
            state=state,
            agent_config=agent_config,
            data_source=data_source,
            llm=llm_specialist,
        )
        return new_state

    def formatter_node(state: AgentState) -> AgentState:
        """
        Node formatter:
        - explica os dados ou o motivo de IMPOSSIBLE em linguagem natural
        """
        # Importação tardia para evitar circular import
        from core.llm.formatter import run_formatter
        
        new_state = run_formatter(
            state=state,
            agent_config=agent_config,
            llm=llm_formatter,
        )
        return new_state

    graph = StateGraph(AgentState)

    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("specialist", specialist_node)
    graph.add_node("formatter", formatter_node)

    graph.set_entry_point("orchestrator")
    graph.add_edge("orchestrator", "specialist")
    graph.add_edge("specialist", "formatter")
    graph.add_edge("formatter", END)

    app = graph.compile()

    log_event(
        "generic_sql_graph_built",
        {
            "agent_id": agent_config.id,
            "num_tables": len(agent_config.tables),
        },
    )

    return app


# ==================== FUNÇÃO DE ALTO NÍVEL ====================

def run_agent_once(
    question: str,
    user_ctx: UserContext,
    agent_config: AgentConfig,
    data_source: BaseDataSource,
    db_session_factory: SessionFactory,
    embedding_provider: EmbeddingProvider,
    llm_orchestrator: LLMProvider,
    llm_specialist: LLMProvider,
    llm_formatter: LLMProvider,
    thread_id: Optional[str] = None,
) -> AgentState:
    """
    Função de alto nível:
    - Monta o estado inicial (question + contexto de usuário)
    - Constrói o grafo
    - Executa uma vez
    - Retorna o AgentState final (answer, sql, data, etc.)

    Isso é o que sua API vai chamar dentro de uma rota.
    """
    if thread_id is None:
        # você pode usar algo do user_ctx, ou gerar uuid, etc.
        thread_id = f"{user_ctx.user_id or 'anon'}-{agent_config.id}"

    # Estado inicial
    state: AgentState = {
        "question": question,
        "user_id": getattr(user_ctx, "user_id", None),
        "space_id": getattr(user_ctx, "space_id", None),
        "crew_ids": getattr(user_ctx, "crew_ids", []) or [],
        # retrieval_context começa vazio – o orchestrator pode populá-lo via RAG
        "retrieval_context": [],
    }

    app = build_generic_sql_graph(
        agent_config=agent_config,
        data_source=data_source,
        db_session_factory=db_session_factory,
        embedding_provider=embedding_provider,
        llm_orchestrator=llm_orchestrator,
        llm_specialist=llm_specialist,
        llm_formatter=llm_formatter,
    )

    final_state: AgentState = app.invoke(
        state,
        config={"configurable": {"thread_id": thread_id}},
    )

    log_event(
        "run_agent_once_done",
        {
            "agent_id": agent_config.id,
            "user_id": state.get("user_id"),
            "space_id": state.get("space_id"),
            "crew_ids": state.get("crew_ids"),
            "has_error": bool(final_state.get("error")),
            "has_answer": bool(final_state.get("answer")),
        },
    )

    return final_state
