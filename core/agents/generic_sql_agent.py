# core/agents/generic_sql_agent.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypedDict, Callable

from sqlalchemy.orm import Session
from langgraph.graph import StateGraph, END

# Centralized checkpoint manager
from core.agents.checkpoint_manager import get_checkpointer

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
    
    # User context (from UserContext schema)
    platform_role: Optional[str]  # admin | user | viewer
    crew_role: Optional[str]      # commander | navigator | explorer | guest
    locale: Optional[str]         # User locale (default: "en")
    permissions: List[str]  # User permissions list
    
    # State Memory
    last_suggestions: List[str]  # Stores suggestions from the previous turn

    # Idioma
    detected_language: Optional[str]

    # RAG
    retrieval_context: List[str]

    # Conversational History (Window for LLM context)
    chat_history: List[Dict[str, str]]

    # Configurações de comportamento da IA
    instructions: Optional[str]  # Instruções gerais sobre como a IA deve se comportar
    creativity: Optional[int]  # Nível de criatividade (0-100) -> temperatura
    length: Optional[int]  # Nível de comprimento (0-100) -> max_tokens
    response_format: Optional[str]  # Formato desejado da resposta
    sql_instructions: Optional[str]  # Instruções específicas para SQL
    selected_datasets: Optional[List[str]]  # Datasets/tabelas selecionados manualmente pelo usuário

    # Decisão do orchestrator
    chosen_table: Optional[str]            # logical_name (mantido para compatibilidade)
    chosen_table_physical: Optional[str]   # physical_name (mantido para compatibilidade)
    chosen_tables: Optional[List[str]]     # logical_names de múltiplas tabelas (novo)
    chosen_tables_physical: Optional[List[str]]  # physical_names correspondentes (novo)
    join_relationships: Optional[List[Dict[str, str]]]  # relacionamentos para JOINs (novo)

    # Relacionamentos documentados pelo cliente (explicit) passados pelo AI engine
    # Format: [{from_table, from_column, to_table, to_column, join_type, label}]
    explicit_relationships: Optional[List[Dict[str, str]]]

    # Saída do specialist
    # Multi-source fields
    is_multi_source: bool
    plan: Optional[str]  # Natural language plan from orchestrator
    partial_results: List[Dict[str, Any]]  # Results from parallel executions
    
    # Common fields
    sql: Optional[str]
    generated_title: Optional[str]  # Novo: título gerado pelo specialist
    data: Optional[List[Dict[str, Any]]]
    impossible_reason: Optional[str]
    error: Optional[str]

    # Saída final
    answer: Optional[str]

    # Multi-agent intent classification
    intent: Optional[str]  # "data" | "strategy" | "signals" | "context" | "mixed"
    strategy_data: Optional[Dict[str, Any]]  # Raw strategy tree from backend
    signals_data: Optional[List[Dict[str, Any]]]  # Raw signals from backend


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
    logical_name: nome amigável (ex: "transactions")
    physical_name: nome físico no banco (ex: "project.dataset.table_name")
    """
    logical_name: str
    physical_name: str
    description: Optional[str] = None
    columns: List[TableColumn] = field(default_factory=list)
    # opcional: ID da conexão externa (BigQuery, Postgres do cliente, etc.)
    data_connection_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


from core.dialects import Dialect

@dataclass
class AgentConfig:
    """
    Configuração de um agente genérico:
    - id: identificador lógico (ex: "default_agent", "main_agent")
    - name: nome amigável
    - tables: lista de schemas de tabelas disponíveis
    - dialect: dialeto do banco de dados (default=Dialect.POSTGRES)
    - extra: metadados extras
    """
    id: str
    name: str
    tables: List[TableSchema]
    dialect: Dialect = Dialect.POSTGRES
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
    checkpointer: Optional[Any] = None,
    backend_client: Optional[Any] = None,
):
    """
    Sistema de Query - Executor de Perguntas
    
    Monta o grafo LangGraph com 3 nós que executam perguntas do usuário
    (seja clicando em sugestão do Sherlock ou digitando manualmente):
    
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
        - Cria LLM dinamicamente se houver configurações no estado
        """
        # Importação tardia para evitar circular import
        from core.llm.orchestrator import run_orchestrator
        from core.llm.factory import create_llm_orchestrator
        
        # Criar LLM dinamicamente se houver configurações no estado
        creativity = state.get("creativity")
        length = state.get("length")
        if creativity is not None or length is not None:
            dynamic_llm = create_llm_orchestrator(creativity=creativity, length=length)
        else:
            dynamic_llm = llm_orchestrator
        
        db: Session = db_session_factory()
        try:
            new_state = run_orchestrator(
                state=state,
                agent_config=agent_config,
                llm=dynamic_llm,
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
        - Cria LLM dinamicamente se houver configurações no estado
        """
        # Importação tardia para evitar circular import
        from core.llm.specialist import run_specialist
        from core.llm.factory import create_llm_specialist
        from core.llm.analysis_context_generator import generate_and_save_analysis_context
        
        # Criar LLM dinamicamente se houver configurações no estado
        creativity = state.get("creativity")
        length = state.get("length")
        if creativity is not None or length is not None:
            dynamic_llm = create_llm_specialist(creativity=creativity, length=length)
        else:
            dynamic_llm = llm_specialist
        
        new_state = run_specialist(
            state=state,
            agent_config=agent_config,
            data_source=data_source,
            llm=dynamic_llm,
        )
        
        # 🔗 NEW: Hybrid Context Extraction (Analysis Bridge)
        # We extract intent/context AFTER SQL generation to ensure it matches the actual data query.
        try:
            generate_and_save_analysis_context(new_state, dynamic_llm)
        except Exception:
            # Context generation should never block the main query flow
            pass
            
        return new_state

    def parallel_specialist_node(state: AgentState) -> AgentState:
        """
        [PHASE 2] Parallel Specialist Node:
        - Detects multi-source requirement
        - Spawns threads to run_specialist for each chosen table/connection
        - Aggregates results into state["partial_results"]
        """
        # Importação tardia
        from core.llm.specialist import run_specialist
        from core.llm.factory import create_llm_specialist
        import concurrent.futures

        chosen_tables = state.get("chosen_tables", [])
        if not chosen_tables:
            return state

        # Criar LLM dinamicamente
        creativity = state.get("creativity")
        length = state.get("length")
        if creativity is not None or length is not None:
            dynamic_llm = create_llm_specialist(creativity=creativity, length=length)
        else:
            dynamic_llm = llm_specialist

        # Prepare tasks
        tasks = []
        for tbl_name in chosen_tables:
            # Find the table object to get connection info if needed
            tbl_obj = next((t for t in agent_config.tables if t.logical_name == tbl_name), None)
            
            # Create a localized state for this thread
            thread_state = state.copy()
            thread_state["chosen_table"] = tbl_name
            thread_state["chosen_table_physical"] = tbl_obj.physical_name if tbl_obj else None
            # Nuke the multi-table fields to force single-table mode inside the specialist
            thread_state["chosen_tables"] = None 
            thread_state["join_relationships"] = None
            
            tasks.append({
                "state": thread_state,
                "table": tbl_obj
            })
        
        results = []
        
        # Parallel Execution
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_task = {}
            for task in tasks:
                future = executor.submit(
                    run_specialist, 
                    task["state"], 
                    agent_config, 
                    data_source, 
                    dynamic_llm
                )
                future_to_task[future] = task

            for future in concurrent.futures.as_completed(future_to_task):
                try:
                    res_state = future.result()
                    # Collect data
                    if res_state.get("data"):
                        results.append({
                            "table": res_state.get("chosen_table"),
                            "data": res_state.get("data"),
                            "sql": res_state.get("sql"),
                            "metadata": {
                                "source": "unknown", # placeholder
                                "title": res_state.get("generated_title"),
                                "dialect": "unknown"
                            }
                        })
                except Exception as e:
                    log_event("parallel_specialist_error", {"error": str(e)})

        # Update main state
        state["partial_results"] = results
        return state

    def merger_node(state: AgentState) -> AgentState:
        """
        [PHASE 2] Merger Node:
        - Consolidates partial_results using Python/Pandas
        """
        from core.llm.merger import run_merger
        
        # Use the orchestrator LLM (smart model) for merger
        # If dynamic config exists, we might want to create one, but for now reuse orchestrator
        return run_merger(state, agent_config, llm_orchestrator)

    def formatter_node(state: AgentState) -> AgentState:
        """
        Node formatter:
        - explica os dados ou o motivo de IMPOSSIBLE em linguagem natural
        - Cria LLM dinamicamente se houver configurações no estado
        """
        # Importação tardia para evitar circular import
        from core.llm.formatter import run_formatter
        from core.llm.factory import create_llm_formatter
        
        # Criar LLM dinamicamente se houver configurações no estado
        creativity = state.get("creativity")
        length = state.get("length")
        if creativity is not None or length is not None:
            dynamic_llm = create_llm_formatter(creativity=creativity, length=length)
        else:
            dynamic_llm = llm_formatter
        
        new_state = run_formatter(
            state=state,
            agent_config=agent_config,
            llm=dynamic_llm,
        )
        return new_state

    # ── Multi-agent: Intent Classifier Node ──────────────────
    def intent_classifier_node(state: AgentState) -> AgentState:
        """
        Entry node: classifies the question intent to route to the right specialist.
        Fast regex first, LLM fallback for ambiguous cases.
        """
        from core.intent.question_intent import classify_question_intent
        has_tables = len(agent_config.tables) > 0
        intent = classify_question_intent(
            question=state.get("question", ""),
            has_data_sources=has_tables,
        )
        print(f"[INTENT_CLASSIFIER] question='{state.get('question', '')[:60]}' -> intent={intent.value} (has_tables={has_tables})")
        log_event("intent_classified", {
            "question": state.get("question", "")[:100],
            "intent": intent.value,
            "has_data_sources": has_tables,
        })
        state["intent"] = intent.value
        return state

    # ── Multi-agent: Strategy Specialist Node ──────────────
    def strategy_specialist_node(state: AgentState) -> AgentState:
        """Answers questions about OKRs, goals, pillars, strategy."""
        from core.llm.strategy_specialist import run_strategy_specialist
        from core.llm.factory import create_llm_formatter
        # Use formatter-class LLM (cheaper, good at synthesis)
        creativity = state.get("creativity")
        length = state.get("length")
        if creativity is not None or length is not None:
            dynamic_llm = create_llm_formatter(creativity=creativity, length=length)
        else:
            dynamic_llm = llm_formatter
        client = backend_client
        if client is None:
            from core.clients.backend_client import get_backend_client
            client = get_backend_client()
        return run_strategy_specialist(state=state, llm=dynamic_llm, backend_client=client)

    # ── Multi-agent: Mixed Dispatch Node (Phase D) ──────────
    def mixed_dispatch_node(state: AgentState) -> AgentState:
        """
        Handles 'mixed' intent: decomposes the question into sub-queries,
        runs multiple specialists (with dependency resolution), and merges results.
        """
        from core.agents.interpreter import create_query_plan, resolve_execution_order
        from core.llm.organizer import run_organizer
        from core.llm.factory import create_llm_formatter
        from concurrent.futures import ThreadPoolExecutor, as_completed

        question = state.get("question", "")
        creativity = state.get("creativity")
        length = state.get("length")
        dynamic_llm = create_llm_formatter(creativity=creativity, length=length) if (creativity is not None or length is not None) else llm_formatter

        client = backend_client
        if client is None:
            from core.clients.backend_client import get_backend_client
            client = get_backend_client()

        # Step 1: Create query plan via the Interpreter
        plan = create_query_plan(question, dynamic_llm)

        # Step 2: Build specialist runner functions
        def run_specialist_by_name(name: str, sub_question: str, context: dict = None) -> Dict[str, Any]:
            """Run a single specialist and return its result."""
            sub_state = dict(state)
            sub_state["question"] = sub_question
            if context:
                # Inject context from previous specialist (e.g., strategy targets for data queries)
                sub_state["instructions"] = (sub_state.get("instructions") or "") + f"\n\nContext from previous analysis:\n{json.dumps(context, default=str)[:1000]}"

            try:
                if name == "strategy":
                    from core.llm.strategy_specialist import run_strategy_specialist
                    result = run_strategy_specialist(sub_state, dynamic_llm, client)
                elif name == "events":
                    from core.llm.events_specialist import run_events_specialist
                    result = run_events_specialist(sub_state, dynamic_llm, client)
                elif name == "relationships":
                    from core.llm.relationships_specialist import run_relationships_specialist
                    result = run_relationships_specialist(sub_state, dynamic_llm, client)
                elif name == "people":
                    from core.llm.people_specialist import run_people_specialist
                    result = run_people_specialist(sub_state, dynamic_llm, client)
                elif name == "widgets":
                    from core.llm.widgets_specialist import run_widgets_specialist
                    result = run_widgets_specialist(sub_state, dynamic_llm, client)
                elif name == "data":
                    # For data specialist, run the existing orchestrator + specialist pipeline
                    from core.llm.orchestrator import run_orchestrator
                    from core.llm.specialist import run_specialist as run_sql_specialist
                    from core.llm.factory import create_llm_orchestrator, create_llm_specialist
                    orch_llm = create_llm_orchestrator(creativity=creativity, length=length) if (creativity is not None or length is not None) else llm_orchestrator
                    spec_llm = create_llm_specialist(creativity=creativity, length=length) if (creativity is not None or length is not None) else llm_specialist
                    db = db_session_factory()
                    try:
                        orch_result = run_orchestrator(state=sub_state, agent_config=agent_config, llm=orch_llm, db=db, embedding_provider=embedding_provider)
                        sql_result = run_sql_specialist(state=orch_result, agent_config=agent_config, data_source=data_source, llm=spec_llm)
                        result = sql_result
                    finally:
                        db.close()
                else:
                    return {"answer": f"Unknown specialist: {name}", "data": [], "error": "unknown_specialist"}

                return {
                    "answer": result.get("answer", ""),
                    "data": result.get("data", []),
                    "sql": result.get("sql"),
                    "error": result.get("error"),
                    "strategy_data": result.get("strategy_data"),
                    "signals_data": result.get("signals_data"),
                }
            except Exception as e:
                log_event("mixed_dispatch_specialist_error", {"specialist": name, "error": str(e)})
                return {"answer": "", "data": [], "error": str(e)}

        import json
        # Step 3: Execute waves (respecting dependencies)
        waves = resolve_execution_order(plan)
        specialist_results: Dict[str, Dict[str, Any]] = {}

        for wave_idx, wave in enumerate(waves):
            log_event("mixed_dispatch_wave", {
                "wave": wave_idx,
                "specialists": [sq.specialist for sq in wave],
            })

            # Run specialists in this wave in parallel
            if len(wave) == 1:
                sq = wave[0]
                context = {}
                for dep in sq.depends_on:
                    if dep in specialist_results:
                        context[dep] = specialist_results[dep].get("answer", "")
                specialist_results[sq.specialist] = run_specialist_by_name(sq.specialist, sq.sub_question, context or None)
            else:
                with ThreadPoolExecutor(max_workers=min(len(wave), 4)) as executor:
                    futures = {}
                    for sq in wave:
                        context = {}
                        for dep in sq.depends_on:
                            if dep in specialist_results:
                                context[dep] = specialist_results[dep].get("answer", "")
                        futures[executor.submit(run_specialist_by_name, sq.specialist, sq.sub_question, context or None)] = sq.specialist

                    for future in as_completed(futures):
                        name = futures[future]
                        try:
                            specialist_results[name] = future.result()
                        except Exception as e:
                            specialist_results[name] = {"answer": "", "data": [], "error": str(e)}

        # Step 4: Merge with the Organizer
        answer = run_organizer(
            question=question,
            specialist_results=specialist_results,
            merge_strategy=plan.merge_strategy,
            llm=dynamic_llm,
        )

        log_event("mixed_dispatch_done", {
            "question": question[:100],
            "specialists_used": list(specialist_results.keys()),
            "answer_preview": answer[:200] if answer else "",
        })

        state["answer"] = answer
        state["data"] = []
        state["sql"] = None
        state["generated_title"] = f"Analysis: {question[:50]}"
        return state

    # ── Multi-agent: Relationships Specialist Node ───────────
    def relationships_specialist_node(state: AgentState) -> AgentState:
        """Answers about cross-space/department connections and impacts."""
        from core.llm.relationships_specialist import run_relationships_specialist
        from core.llm.factory import create_llm_formatter
        dynamic_llm = create_llm_formatter(creativity=state.get("creativity"), length=state.get("length")) if state.get("creativity") is not None or state.get("length") is not None else llm_formatter
        client = backend_client or __import__("core.clients.backend_client", fromlist=["get_backend_client"]).get_backend_client()
        return run_relationships_specialist(state=state, llm=dynamic_llm, backend_client=client)

    # ── Multi-agent: People Specialist Node ────────────────
    def people_specialist_node(state: AgentState) -> AgentState:
        """Answers about teams, users, crew membership, activity."""
        from core.llm.people_specialist import run_people_specialist
        from core.llm.factory import create_llm_formatter
        dynamic_llm = create_llm_formatter(creativity=state.get("creativity"), length=state.get("length")) if state.get("creativity") is not None or state.get("length") is not None else llm_formatter
        client = backend_client or __import__("core.clients.backend_client", fromlist=["get_backend_client"]).get_backend_client()
        return run_people_specialist(state=state, llm=dynamic_llm, backend_client=client)

    # ── Multi-agent: Widgets & History Specialist Node ─────
    def widgets_specialist_node(state: AgentState) -> AgentState:
        """Answers about existing dashboards, widgets, past AI insights."""
        from core.llm.widgets_specialist import run_widgets_specialist
        from core.llm.factory import create_llm_formatter
        dynamic_llm = create_llm_formatter(creativity=state.get("creativity"), length=state.get("length")) if state.get("creativity") is not None or state.get("length") is not None else llm_formatter
        client = backend_client or __import__("core.clients.backend_client", fromlist=["get_backend_client"]).get_backend_client()
        return run_widgets_specialist(state=state, llm=dynamic_llm, backend_client=client)

    # ── Multi-agent: Events Specialist Node ──────────────────
    def events_specialist_node(state: AgentState) -> AgentState:
        """Answers questions about market signals, events, trends."""
        from core.llm.events_specialist import run_events_specialist
        from core.llm.factory import create_llm_formatter
        creativity = state.get("creativity")
        length = state.get("length")
        if creativity is not None or length is not None:
            dynamic_llm = create_llm_formatter(creativity=creativity, length=length)
        else:
            dynamic_llm = llm_formatter
        client = backend_client
        if client is None:
            from core.clients.backend_client import get_backend_client
            client = get_backend_client()
        return run_events_specialist(state=state, llm=dynamic_llm, backend_client=client)

    # ── Build the Graph ────────────────────────────────────
    graph = StateGraph(AgentState)

    # Register all nodes
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("specialist", specialist_node)
    graph.add_node("parallel_specialist", parallel_specialist_node)
    graph.add_node("merger", merger_node)
    graph.add_node("formatter", formatter_node)
    graph.add_node("strategy_specialist", strategy_specialist_node)
    graph.add_node("events_specialist", events_specialist_node)
    graph.add_node("relationships_specialist", relationships_specialist_node)
    graph.add_node("people_specialist", people_specialist_node)
    graph.add_node("widgets_specialist", widgets_specialist_node)
    graph.add_node("mixed_dispatch", mixed_dispatch_node)

    # ── Routing: Intent -> Specialist ──────────────────────
    def route_by_intent(state: AgentState):
        intent = state.get("intent", "data")
        routing = {
            "strategy": "strategy_specialist",
            "signals": "events_specialist",
            "relationships": "relationships_specialist",
            "people": "people_specialist",
            "widgets": "widgets_specialist",
            "mixed": "mixed_dispatch",
        }
        return routing.get(intent, "orchestrator")

    def route_orchestrator(state: AgentState):
        if state.get("is_multi_source", False):
            return "parallel_specialist"
        return "specialist"

    # Entry point: always classify intent first
    graph.set_entry_point("intent_classifier")

    # Intent router → strategy specialist OR data pipeline
    graph.add_conditional_edges(
        "intent_classifier",
        route_by_intent,
        {
            "strategy_specialist": "strategy_specialist",
            "events_specialist": "events_specialist",
            "relationships_specialist": "relationships_specialist",
            "people_specialist": "people_specialist",
            "widgets_specialist": "widgets_specialist",
            "mixed_dispatch": "mixed_dispatch",
            "orchestrator": "orchestrator",
        }
    )

    # Non-data specialists -> END (skip formatter — answer is already set by each specialist)
    graph.add_edge("strategy_specialist", END)
    graph.add_edge("events_specialist", END)
    graph.add_edge("relationships_specialist", END)
    graph.add_edge("people_specialist", END)
    graph.add_edge("widgets_specialist", END)
    graph.add_edge("mixed_dispatch", END)

    # Data pipeline (existing, unchanged)
    graph.add_conditional_edges(
        "orchestrator",
        route_orchestrator,
        {
            "specialist": "specialist",
            "parallel_specialist": "parallel_specialist"
        }
    )

    graph.add_edge("specialist", "formatter")
    graph.add_edge("parallel_specialist", "merger")
    graph.add_edge("merger", "formatter")
    graph.add_edge("formatter", END)

    app = graph.compile(checkpointer=checkpointer)

    log_event(
        "generic_sql_graph_built",
        {
            "agent_id": agent_config.id,
            "num_tables": len(agent_config.tables),
            "checkpointer_active": checkpointer is not None
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
    retrieval_context: Optional[List[str]] = None,
    instructions: Optional[str] = None,
    creativity: Optional[int] = None,
    length: Optional[int] = None,
    response_format: Optional[str] = None,
    sql_instructions: Optional[str] = None,
    selected_datasets: Optional[List[str]] = None,
    chat_history: Optional[List[Dict[str, str]]] = None,
    explicit_relationships: Optional[List[Dict[str, str]]] = None,
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
        user_id = getattr(user_ctx, "user_id", None)
        if not user_id and hasattr(user_ctx, "user") and user_ctx.user:
            user_id = str(user_ctx.user.id) if hasattr(user_ctx.user, "id") else None
        thread_id = f"{user_id or 'anon'}-{agent_config.id}"

    # Extrair informações do user_ctx
    user_id_str = getattr(user_ctx, "user_id", None)
    if not user_id_str and hasattr(user_ctx, "user") and user_ctx.user:
        user_id_str = str(user_ctx.user.id) if hasattr(user_ctx.user, "id") else None
    
    space_id_str = None
    if hasattr(user_ctx, "space_id") and user_ctx.space_id:
        space_id_str = str(user_ctx.space_id)
    
    crew_ids_list = getattr(user_ctx, "crew_ids", []) or []
    # Convert UUIDs to strings if needed
    crew_ids_str = [str(cid) for cid in crew_ids_list] if crew_ids_list else []
    
    # Extract new fields from UserContext
    platform_role = getattr(user_ctx, "platform_role", "user")
    crew_role = getattr(user_ctx, "crew_role", "guest")
    locale = getattr(user_ctx, "locale", "en")
    permissions = getattr(user_ctx, "permissions", []) or []

    # Estado inicial
    state: AgentState = {
        "question": question,
        "user_id": user_id_str,
        "space_id": space_id_str,
        "crew_ids": crew_ids_str,
        # User context fields
        "platform_role": platform_role,
        "crew_role": crew_role,
        "locale": locale,
        "permissions": permissions,
        # retrieval_context
        "retrieval_context": retrieval_context or [],
        "chat_history": chat_history or [],
        # Configurações dinâmicas da IA
        "instructions": instructions,
        "creativity": creativity,
        "length": length,
        "response_format": response_format,
        "sql_instructions": sql_instructions,
        "selected_datasets": selected_datasets,
        "explicit_relationships": explicit_relationships or [],  # Relacionamentos documentados pelo cliente
    }

    # Use checkpointer context manager to acquire and release connection
    from core.agents.checkpoint_manager import get_checkpointer
    
    # Multi-agent: get backend client for strategy/signals specialists
    from core.clients.backend_client import get_backend_client
    _backend_client = get_backend_client()

    with get_checkpointer() as checkpointer:
        app = build_generic_sql_graph(
            agent_config=agent_config,
            data_source=data_source,
            db_session_factory=db_session_factory,
            embedding_provider=embedding_provider,
            llm_orchestrator=llm_orchestrator,
            llm_specialist=llm_specialist,
            llm_formatter=llm_formatter,
            checkpointer=checkpointer,
            backend_client=_backend_client,
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
            "platform_role": state.get("platform_role"),
            "crew_role": state.get("crew_role"),
            "locale": state.get("locale"),
            "permissions_count": len(state.get("permissions") or []),
            "has_error": bool(final_state.get("error")),
            "has_answer": bool(final_state.get("answer")),
            "has_plan": bool(final_state.get("plan")),
        },
    )

    return final_state
