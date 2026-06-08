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

    # Projeto A (Model B) — tenant the request is operating on. ``None``
    # = default / single-tenant mode, in which case downstream providers
    # use env-driven model IDs. When populated, the Bedrock provider
    # looks up ``bedrock_inference_profile_arn`` and routes through it
    # for per-tenant cost attribution.
    tenant_slug: Optional[str]
    tenant_bedrock_profile_arn: Optional[str]

    # User context (from UserContext schema)
    platform_role: Optional[str]  # admin | user | viewer
    crew_role: Optional[str]  # commander | navigator | explorer | guest
    locale: Optional[str]  # User locale (default: "en")
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
    ai_tone: Optional[
        str
    ]  # User-selected tone (casual/professional/technical/friendly) — shapes form, not substance
    ai_style: Optional[
        str
    ]  # User-selected output structure (concise/detailed/step-by-step)
    sql_instructions: Optional[str]  # Instruções específicas para SQL
    selected_datasets: Optional[
        List[str]
    ]  # Datasets/tabelas selecionados manualmente pelo usuário

    # Decisão do orchestrator
    chosen_table: Optional[str]  # logical_name (mantido para compatibilidade)
    chosen_table_physical: Optional[str]  # physical_name (mantido para compatibilidade)
    chosen_tables: Optional[List[str]]  # logical_names de múltiplas tabelas (novo)
    chosen_tables_physical: Optional[List[str]]  # physical_names correspondentes (novo)
    join_relationships: Optional[
        List[Dict[str, str]]
    ]  # relacionamentos para JOINs (novo)

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

    # Mixed dispatch: raw specialist results saved for mixed_merger_node
    mixed_specialist_results: Optional[Dict[str, Any]]

    # Specialist plan from mixed_planner_node: [{specialist, sub_question, depends_on}]
    specialist_plan: Optional[List[Dict[str, Any]]]

    # Agent mode from backend (scan, sql, context, question)
    agent_mode: Optional[str]

    # Scan mode: logical table names actually queried in this run
    tables_queried: Optional[List[str]]

    # Scan mode: raw SQL strings executed by query_table inside full_context_agent.
    # Used by depth_tracker in connection_query.py to record (dim × metric) combos.
    executed_sqls: Optional[List[str]]

    # Multi-agent intent classification
    intent: Optional[str]  # "data" | "strategy" | "signals" | "context" | "mixed"
    strategy_data: Optional[Dict[str, Any]]  # Raw strategy tree from backend
    signals_data: Optional[List[Dict[str, Any]]]  # Raw signals from backend

    # Context Layer (Phase 2.6b): pre-fetched evidence blend from the
    # brain. Populated by brain_retrieval_node after intent classification
    # and consumed downstream by every specialist that wants grounded
    # answers (without having to run its own retrieval).
    brain_context: List[str]  # formatted evidence blocks, ready to inject into prompts
    brain_doc_ids: List[str]  # context_documents.id of each retrieved doc — audit trail
    brain_doc_kinds: List[str]  # kinds retrieved (parallel to brain_doc_ids)
    context_intent: Optional[
        str
    ]  # copy of `intent` at the moment retrieval ran (for agent_executions)


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
    dispatch_map: Optional[dict] = None,
    briefing: str = "",
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

        # W7 — emit a user-readable step so the transparency panel doesn't
        # collapse to "Safety checks passed" for SQL questions.
        steps = list(new_state.get("reasoning_steps") or [])
        chosen = (
            new_state.get("chosen_table")
            or (new_state.get("chosen_tables") or [None])[0]
        )
        if chosen:
            steps.append(
                {"kind": "router", "summary": f"Picked the `{chosen}` table to answer."}
            )
        elif new_state.get("impossible_reason"):
            steps.append(
                {
                    "kind": "router",
                    "summary": "Decided I don't have data to answer this.",
                }
            )
        else:
            steps.append(
                {"kind": "router", "summary": "Decided how to handle the question."}
            )
        new_state["reasoning_steps"] = steps
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
        from core.llm.analysis_context_generator import (
            generate_and_save_analysis_context,
        )

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

        # W7 — annotate the reasoning trace with what the SQL specialist did.
        steps = list(new_state.get("reasoning_steps") or [])
        if new_state.get("sql"):
            row_count = len(new_state.get("data") or [])
            steps.append(
                {"kind": "sql", "summary": "Wrote a SQL query against your data."}
            )
            steps.append(
                {
                    "kind": "retrieval",
                    "summary": f"Got {row_count} row{'' if row_count == 1 else 's'} back.",
                }
            )
        new_state["reasoning_steps"] = steps

        return new_state

    def parallel_specialist_node(state: AgentState) -> AgentState:
        """
        Unified specialist executor.

        Mixed mode (mixed_planner path): if state["specialist_plan"] is set,
        runs the LLM-planned specialists with wave-based dependency resolution
        and accumulates results into state["mixed_specialist_results"].

        SQL mode (orchestrator path): spawns threads to run_specialist for each
        chosen table and accumulates results into state["partial_results"].
        """
        import concurrent.futures
        import json
        from types import SimpleNamespace

        specialist_plan = state.get("specialist_plan")

        if specialist_plan:
            # ── Mixed mode: wave-based execution ─────────────────────────────
            from core.agents.interpreter import resolve_execution_order
            from core.llm.factory import create_llm_formatter

            question = state.get("question", "")
            creativity = state.get("creativity")
            length = state.get("length")
            dynamic_llm = (
                create_llm_formatter(creativity=creativity, length=length)
                if (creativity is not None or length is not None)
                else llm_formatter
            )

            client = backend_client
            if client is None:
                from core.clients.backend_client import get_backend_client

                client = get_backend_client()

            def _run_specialist(
                name: str, sub_question: str, context: dict = None
            ) -> Dict[str, Any]:
                sub_state = dict(state)
                sub_state["question"] = sub_question
                if context:
                    sub_state["instructions"] = (
                        (sub_state.get("instructions") or "")
                        + f"\n\nContext from previous analysis:\n"
                        + json.dumps(context, default=str)[:1000]
                    )
                try:
                    if name in ("knowledge", "strategy"):
                        from core.llm.knowledge_specialist import (
                            run_knowledge_specialist,
                        )

                        result = run_knowledge_specialist(
                            sub_state, dynamic_llm, client
                        )
                    elif name == "events":
                        from core.llm.events_specialist import run_events_specialist

                        result = run_events_specialist(sub_state, dynamic_llm, client)
                    elif name == "relationships":
                        from core.llm.relationships_specialist import (
                            run_relationships_specialist,
                        )

                        result = run_relationships_specialist(
                            sub_state, dynamic_llm, client
                        )
                    elif name == "people":
                        from core.llm.people_specialist import run_people_specialist

                        result = run_people_specialist(sub_state, dynamic_llm, client)
                    elif name == "widgets":
                        from core.llm.widgets_specialist import run_widgets_specialist

                        result = run_widgets_specialist(sub_state, dynamic_llm, client)
                    elif name == "data":
                        from core.llm.orchestrator import run_orchestrator
                        from core.llm.specialist import run_specialist as _run_sql
                        from core.llm.formatter import run_formatter as _run_fmt
                        from core.llm.factory import (
                            create_llm_orchestrator,
                            create_llm_specialist,
                        )

                        orch_llm = (
                            create_llm_orchestrator(
                                creativity=creativity, length=length
                            )
                            if (creativity is not None or length is not None)
                            else llm_orchestrator
                        )
                        spec_llm = (
                            create_llm_specialist(creativity=creativity, length=length)
                            if (creativity is not None or length is not None)
                            else llm_specialist
                        )
                        db = db_session_factory()
                        try:
                            orch_result = run_orchestrator(
                                state=sub_state,
                                agent_config=agent_config,
                                llm=orch_llm,
                                db=db,
                                embedding_provider=embedding_provider,
                            )
                            # Multi-source: run each chosen table against its own
                            # data source (via dispatch_map), then merge with DuckDB
                            # when 2+ tabular results are available. Without this,
                            # a mixed question spanning multiple databases would only
                            # hit the primary data_source and silently drop all other
                            # connections' data.
                            tbl_names = orch_result.get("chosen_tables") or []
                            if (
                                orch_result.get("is_multi_source")
                                and len(tbl_names) > 1
                            ):
                                from core.llm.merger import run_merger as _run_merger

                                partial_results = []
                                tbl_futures: Dict[Any, str] = {}
                                with concurrent.futures.ThreadPoolExecutor(
                                    max_workers=min(len(tbl_names), 4)
                                ) as tbl_ex:
                                    for tbl_name in tbl_names:
                                        tbl_obj = next(
                                            (
                                                t
                                                for t in agent_config.tables
                                                if t.logical_name == tbl_name
                                            ),
                                            None,
                                        )
                                        if not tbl_obj:
                                            continue
                                        conn_id = str(
                                            getattr(tbl_obj, "data_connection_id", "")
                                        )
                                        src = (dispatch_map or {}).get(
                                            conn_id
                                        ) or data_source
                                        thr = dict(orch_result)
                                        thr["chosen_table"] = tbl_name
                                        thr["chosen_table_physical"] = getattr(
                                            tbl_obj, "physical_name", tbl_name
                                        )
                                        thr["chosen_tables"] = None
                                        thr["chosen_tables_physical"] = None
                                        tbl_futures[
                                            tbl_ex.submit(
                                                _run_sql,
                                                thr,
                                                agent_config,
                                                src,
                                                spec_llm,
                                            )
                                        ] = tbl_name
                                    for fut in concurrent.futures.as_completed(
                                        tbl_futures
                                    ):
                                        tbl_name = tbl_futures[fut]
                                        try:
                                            r = fut.result()
                                            if r.get("data"):
                                                partial_results.append(
                                                    {
                                                        "table": tbl_name,
                                                        "data": r["data"],
                                                        "sql": r.get("sql"),
                                                        "metadata": {
                                                            "source": "unknown",
                                                            "title": r.get(
                                                                "generated_title"
                                                            ),
                                                            "dialect": "unknown",
                                                        },
                                                    }
                                                )
                                        except Exception as tbl_exc:
                                            log_event(
                                                "mixed_data_sub_table_error",
                                                {
                                                    "table": tbl_name,
                                                    "error": str(tbl_exc),
                                                },
                                            )

                                if len(partial_results) >= 2:
                                    merged = _run_merger(
                                        {
                                            **orch_result,
                                            "partial_results": partial_results,
                                        },
                                        agent_config,
                                        orch_llm,
                                    )
                                    result = _run_fmt(
                                        state=merged,
                                        agent_config=agent_config,
                                        llm=dynamic_llm,
                                    )
                                elif partial_results:
                                    r = partial_results[0]
                                    result = _run_fmt(
                                        state={
                                            **orch_result,
                                            "data": r["data"],
                                            "sql": r.get("sql"),
                                        },
                                        agent_config=agent_config,
                                        llm=dynamic_llm,
                                    )
                                else:
                                    result = {
                                        "answer": "No data found across the queried connections.",
                                        "data": [],
                                        "sql": None,
                                        "error": "no_data",
                                    }
                            else:
                                sql_result = _run_sql(
                                    state=orch_result,
                                    agent_config=agent_config,
                                    data_source=data_source,
                                    llm=spec_llm,
                                )
                                result = _run_fmt(
                                    state=sql_result,
                                    agent_config=agent_config,
                                    llm=dynamic_llm,
                                )
                        finally:
                            db.close()
                    else:
                        return {
                            "answer": f"Unknown specialist: {name}",
                            "data": [],
                            "error": "unknown_specialist",
                        }

                    return {
                        "answer": result.get("answer", ""),
                        "data": result.get("data", []),
                        "sql": result.get("sql"),
                        "error": result.get("error"),
                        "strategy_data": result.get("strategy_data"),
                        "signals_data": result.get("signals_data"),
                    }
                except Exception as exc:
                    log_event(
                        "parallel_specialist_mixed_error",
                        {"specialist": name, "error": str(exc)},
                    )
                    return {"answer": "", "data": [], "error": str(exc)}

            # Build SimpleNamespace objects so resolve_execution_order can access .depends_on
            sub_queries = [
                SimpleNamespace(
                    specialist=p["specialist"],
                    sub_question=p["sub_question"],
                    depends_on=p.get("depends_on", []),
                )
                for p in specialist_plan
            ]

            class _Plan:
                def __init__(self, subs):
                    self.sub_queries = subs

            waves = resolve_execution_order(_Plan(sub_queries))
            specialist_results: Dict[str, Dict[str, Any]] = {}

            for wave_idx, wave in enumerate(waves):
                log_event(
                    "parallel_specialist_wave",
                    {"wave": wave_idx, "specialists": [sq.specialist for sq in wave]},
                )
                if len(wave) == 1:
                    sq = wave[0]
                    ctx = {
                        dep: specialist_results[dep].get("answer", "")
                        for dep in sq.depends_on
                        if dep in specialist_results
                    }
                    specialist_results[sq.specialist] = _run_specialist(
                        sq.specialist, sq.sub_question, ctx or None
                    )
                else:
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=min(len(wave), 4)
                    ) as executor:
                        futures = {}
                        for sq in wave:
                            ctx = {
                                dep: specialist_results[dep].get("answer", "")
                                for dep in sq.depends_on
                                if dep in specialist_results
                            }
                            futures[
                                executor.submit(
                                    _run_specialist,
                                    sq.specialist,
                                    sq.sub_question,
                                    ctx or None,
                                )
                            ] = sq.specialist
                        for fut in concurrent.futures.as_completed(futures):
                            spec_name = futures[fut]
                            try:
                                specialist_results[spec_name] = fut.result()
                            except Exception as exc:
                                specialist_results[spec_name] = {
                                    "answer": "",
                                    "data": [],
                                    "error": str(exc),
                                }

            log_event(
                "parallel_specialist_mixed_done",
                {
                    "question": question[:100],
                    "specialists_used": list(specialist_results.keys()),
                },
            )
            state["mixed_specialist_results"] = specialist_results
            return state

        else:
            # ── SQL mode: parallel SQL execution ─────────────────────────────
            from core.llm.specialist import run_specialist
            from core.llm.factory import create_llm_specialist

            chosen_tables = state.get("chosen_tables", [])
            if not chosen_tables:
                return state

            creativity = state.get("creativity")
            length = state.get("length")
            dynamic_llm = (
                create_llm_specialist(creativity=creativity, length=length)
                if (creativity is not None or length is not None)
                else llm_specialist
            )

            tasks = []
            for tbl_name in chosen_tables:
                tbl_obj = next(
                    (t for t in agent_config.tables if t.logical_name == tbl_name), None
                )
                thread_state = state.copy()
                thread_state["chosen_table"] = tbl_name
                thread_state["chosen_table_physical"] = (
                    tbl_obj.physical_name if tbl_obj else None
                )
                thread_state["chosen_tables"] = None
                thread_state["join_relationships"] = None
                tasks.append({"state": thread_state, "table": tbl_obj})

            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_task = {}
                for task in tasks:
                    future = executor.submit(
                        run_specialist,
                        task["state"],
                        agent_config,
                        data_source,
                        dynamic_llm,
                    )
                    future_to_task[future] = task

                for future in concurrent.futures.as_completed(future_to_task):
                    try:
                        res_state = future.result()
                        if res_state.get("data"):
                            results.append(
                                {
                                    "table": res_state.get("chosen_table"),
                                    "data": res_state.get("data"),
                                    "sql": res_state.get("sql"),
                                    "metadata": {
                                        "source": "unknown",
                                        "title": res_state.get("generated_title"),
                                        "dialect": "unknown",
                                    },
                                }
                            )
                    except Exception as e:
                        log_event("parallel_specialist_error", {"error": str(e)})

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

    def mixed_merger_node(state: AgentState) -> AgentState:
        """
        Routes mixed_dispatch results to either DuckDB merger (tabular with
        a detected join) or LLM organizer (contextual / no join).
        """
        from core.llm.organizer import run_organizer
        from core.llm.merger import run_merger
        from core.llm.factory import create_llm_formatter

        specialist_results = state.get("mixed_specialist_results") or {}
        if not specialist_results:
            return state

        question = state.get("question", "")
        merge_strategy = state.get("plan") or "narrative"
        creativity = state.get("creativity")
        length = state.get("length")
        dynamic_llm = (
            create_llm_formatter(creativity=creativity, length=length)
            if (creativity is not None or length is not None)
            else llm_formatter
        )

        tabular = {k: v for k, v in specialist_results.items() if v.get("data")}
        contextual = {k: v for k, v in specialist_results.items() if not v.get("data")}

        def _has_relationship(results_list):
            if state.get("explicit_relationships") or state.get("join_relationships"):
                return True
            if len(results_list) >= 2:
                cols = [
                    set(r["data"][0].keys()) if r.get("data") else set()
                    for r in results_list
                ]
                return bool(len(cols) >= 2 and cols[0] & cols[1])
            return False

        if tabular and not contextual:
            if len(tabular) >= 2 and _has_relationship(list(tabular.values())):
                state["partial_results"] = list(tabular.values())
                return run_merger(state, agent_config, llm_orchestrator)
            elif len(tabular) >= 2:
                # Multiple tabular results but no join — textual narrative
                state["answer"] = run_organizer(
                    question, specialist_results, "narrative", dynamic_llm
                )
                state["data"] = []
                return state
            else:
                # Single tabular result — pass through directly
                res = next(iter(tabular.values()))
                state["data"] = res.get("data", [])
                state["sql"] = res.get("sql")
                state["answer"] = res.get("answer", "")
                title = res.get("generated_title")
                if title:
                    state["generated_title"] = title
                return state
        elif contextual and not tabular:
            state["answer"] = run_organizer(
                question, specialist_results, merge_strategy, dynamic_llm
            )
            state["data"] = []
            return state
        else:
            # Hybrid: inject contextual text into retrieval_context, handle tabular
            ctx_text = "\n\n".join(
                f"[{k}]: {v.get('answer', '')}"
                for k, v in contextual.items()
                if v.get("answer")
            )
            if ctx_text:
                state["retrieval_context"] = [ctx_text] + (
                    state.get("retrieval_context") or []
                )
            if len(tabular) >= 2 and _has_relationship(list(tabular.values())):
                state["partial_results"] = list(tabular.values())
                return run_merger(state, agent_config, llm_orchestrator)
            else:
                res = next(iter(tabular.values()))
                state["data"] = res.get("data", [])
                state["sql"] = res.get("sql")
                state["answer"] = res.get("answer", "")
                title = res.get("generated_title")
                if title:
                    state["generated_title"] = title
                return state

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
        # W7 — last step in the SQL flow: the formatter built the
        # natural-language answer the user actually sees.
        steps = list(new_state.get("reasoning_steps") or [])
        steps.append({"kind": "format", "summary": "Composed the final answer."})
        new_state["reasoning_steps"] = steps
        return new_state

    # ── Multi-agent: Intent Classifier Node ──────────────────
    def intent_classifier_node(state: AgentState) -> AgentState:
        """
        Entry node: classifies the question intent to route to the right specialist.
        Fast regex first, LLM fallback for ambiguous cases.
        """
        from core.intent.question_intent import classify_question_intent

        # When the backend signals a SQL-bound execution mode, force the
        # data path. Exception: "scan" routes to the full_context_agent
        # (autonomous proactive intelligence) — it bypasses the SQL pipeline.
        agent_mode = state.get("agent_mode") or ""
        if agent_mode == "scan":
            print(f"[INTENT_CLASSIFIER] agent_mode='scan' → routing to full_context")
            log_event(
                "intent_classified",
                {
                    "question": state.get("question", "")[:100],
                    "intent": "full_context",
                    "agent_mode": agent_mode,
                    "forced": True,
                },
            )
            state["intent"] = "full_context"
            return state
        if agent_mode in ("sql", "context", "datasource"):
            print(
                f"[INTENT_CLASSIFIER] agent_mode='{agent_mode}' → forcing intent=data"
            )
            log_event(
                "intent_classified",
                {
                    "question": state.get("question", "")[:100],
                    "intent": "data",
                    "agent_mode": agent_mode,
                    "forced": True,
                },
            )
            state["intent"] = "data"
            return state

        has_tables = len(agent_config.tables) > 0
        intent = classify_question_intent(
            question=state.get("question", ""),
            has_data_sources=has_tables,
        )
        print(
            f"[INTENT_CLASSIFIER] question='{state.get('question', '')[:60]}' -> intent={intent.value} (has_tables={has_tables})"
        )
        log_event(
            "intent_classified",
            {
                "question": state.get("question", "")[:100],
                "intent": intent.value,
                "has_data_sources": has_tables,
            },
        )
        state["intent"] = intent.value
        return state

    # ── Full Context Node — Autonomous Proactive Intelligence ─────────────
    def full_context_node(state: AgentState) -> AgentState:
        """Runs the autonomous full-context ReAct agent.

        Triggered when agent_mode='scan'. Bypasses the SQL pipeline
        entirely — the agent investigates, cross-references, and either
        surfaces one insight or stays silent (state['answer'] = None).

        The `briefing` variable is captured from the outer scope of
        build_generic_sql_graph so the scan directional context is
        injected into the agent's system prompt.
        """
        from core.agents.full_context_agent import run_full_context_agent

        db = db_session_factory()
        try:
            return run_full_context_agent(
                state=state,
                agent_config=agent_config,
                llm=llm_orchestrator,
                db=db,
                embedding_provider=embedding_provider,
                data_source=data_source,
                dispatch_map=dispatch_map,
                briefing=briefing,
            )
        finally:
            db.close()

    # ── Context Layer: Brain Retrieval Node (Phase 2.6b) ───
    def brain_retrieval_node(state: AgentState) -> AgentState:
        """Pull a top-k blend from the Context Layer for this question.

        Runs AFTER intent_classifier so it can use the intent to weight
        per-kind ranking. Runs BEFORE any specialist so every downstream
        node sees the same evidence. All failures are non-fatal — the
        specialist just runs without brain context, preserving the
        pre-2.6b behaviour.

        Populates:
          - state['brain_context']  (list of text blocks, ready to inject)
          - state['brain_doc_ids']  (audit trail)
          - state['brain_doc_kinds']
          - state['context_intent'] (what classified intent was)
        """
        import asyncio

        from core.rag.brain_searcher import make_brain_searcher
        from core.rag.context_brain import Scope, format_evidence, retrieve_context

        question = (state.get("question") or "").strip()
        if not question:
            state.setdefault("brain_context", [])
            state.setdefault("brain_doc_ids", [])
            state.setdefault("brain_doc_kinds", [])
            return state

        intent = state.get("intent") or "data"
        # Brain intent weights are keyed slightly differently from the
        # supervisor intent enum — map where they diverge.
        brain_intent = {
            "signals": "events",
            "data": "data",
        }.get(intent, intent)

        space_id = state.get("space_id")
        crew_ids = list(state.get("crew_ids") or [])
        user_id = state.get("user_id")

        state["context_intent"] = intent

        async def _run() -> tuple[list[str], list[str], list[str]]:
            # NullPool engine scoped to *this* loop — see db/isolated.py.
            # The global engine is bound to the FastAPI request loop;
            # asyncio.run() here spawns a fresh loop in LangGraph's
            # worker thread, so a shared pool yields connections whose
            # asyncpg Future is attached to a dead loop.
            from db.isolated import isolated_session

            async with isolated_session() as db:
                searcher = make_brain_searcher(
                    db=db,
                    embedding_provider=embedding_provider,
                    space_id=space_id,
                    crew_ids=crew_ids,
                )

                async def _qe(q: str):
                    try:
                        vec = await embedding_provider.embed_async([q])
                        return vec[0] if vec else None
                    except Exception:
                        return None

                ranked = await retrieve_context(
                    question,
                    Scope(user_id=user_id, space_id=space_id, crew_ids=crew_ids),
                    searcher=searcher,
                    query_embedder=_qe,
                    intent=brain_intent,
                    k=20,
                )

                if not ranked:
                    return [], [], []

                blocks = format_evidence(ranked).split("\n\n") if ranked else []
                ids = [r.doc.id for r in ranked]
                kinds = [r.doc.kind for r in ranked]
                return blocks, ids, kinds

        try:
            blocks, ids, kinds = asyncio.run(_run())
        except Exception as exc:
            log_event("brain_retrieval_failed", {"error": str(exc)[:400]})
            blocks, ids, kinds = [], [], []

        state["brain_context"] = blocks
        state["brain_doc_ids"] = ids
        state["brain_doc_kinds"] = kinds

        log_event(
            "brain_retrieval_done",
            {
                "intent": intent,
                "brain_intent": brain_intent,
                "doc_count": len(ids),
                "kinds_unique": sorted(set(kinds)),
                "question_len": len(question),
            },
        )
        return state

    # ── Multi-agent: Knowledge Specialist Node ─────────────
    # Strategy was folded into Knowledge in the refactor (Phases
    # 1a/1b dropped Pillars/OKRs/Initiatives — now Metrics + Glossary
    # + Relationships). Questions that used to hit the strategy
    # specialist (OKR, goal, KPI) plus the new ones the refactor
    # introduced (define X, formula for Y) all land here.
    def knowledge_specialist_node(state: AgentState) -> AgentState:
        """Answers Knowledge questions (metrics / glossary / relationships)."""
        from core.llm.knowledge_specialist import run_knowledge_specialist
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
        return run_knowledge_specialist(
            state=state, llm=dynamic_llm, backend_client=client
        )

    # Legacy alias — anything that still imports/instantiates the old
    # name (tests, mixed_dispatch sub-router) gets routed to knowledge.
    strategy_specialist_node = knowledge_specialist_node

    # ── Multi-agent: Mixed Planner Node ─────────────────────
    def mixed_planner_node(state: AgentState) -> AgentState:
        """
        Plans which specialists to run for a 'mixed' intent question.
        Calls the LLM interpreter to decompose the question and writes the
        execution plan to state["specialist_plan"]. Actual execution is
        handled by the unified parallel_specialist_node.
        """
        from core.agents.interpreter import create_query_plan
        from core.llm.factory import create_llm_formatter

        question = state.get("question", "")
        creativity = state.get("creativity")
        length = state.get("length")
        dynamic_llm = (
            create_llm_formatter(creativity=creativity, length=length)
            if (creativity is not None or length is not None)
            else llm_formatter
        )

        plan = create_query_plan(question, dynamic_llm)

        state["specialist_plan"] = [
            {
                "specialist": sq.specialist,
                "sub_question": sq.sub_question,
                "depends_on": sq.depends_on,
            }
            for sq in plan.sub_queries
        ]
        state["plan"] = plan.merge_strategy
        state["generated_title"] = f"Analysis: {question[:50]}"

        log_event(
            "mixed_planner_done",
            {
                "question": question[:100],
                "specialists_planned": [sq.specialist for sq in plan.sub_queries],
                "merge_strategy": plan.merge_strategy,
            },
        )
        return state

    # ── Multi-agent: Relationships Specialist Node ───────────
    def relationships_specialist_node(state: AgentState) -> AgentState:
        """Answers about cross-space/department connections and impacts."""
        from core.llm.relationships_specialist import run_relationships_specialist
        from core.llm.factory import create_llm_formatter

        dynamic_llm = (
            create_llm_formatter(
                creativity=state.get("creativity"), length=state.get("length")
            )
            if state.get("creativity") is not None or state.get("length") is not None
            else llm_formatter
        )
        client = (
            backend_client
            or __import__(
                "core.clients.backend_client", fromlist=["get_backend_client"]
            ).get_backend_client()
        )
        return run_relationships_specialist(
            state=state, llm=dynamic_llm, backend_client=client
        )

    # ── Multi-agent: People Specialist Node ────────────────
    def people_specialist_node(state: AgentState) -> AgentState:
        """Answers about teams, users, crew membership, activity."""
        from core.llm.people_specialist import run_people_specialist
        from core.llm.factory import create_llm_formatter

        dynamic_llm = (
            create_llm_formatter(
                creativity=state.get("creativity"), length=state.get("length")
            )
            if state.get("creativity") is not None or state.get("length") is not None
            else llm_formatter
        )
        client = (
            backend_client
            or __import__(
                "core.clients.backend_client", fromlist=["get_backend_client"]
            ).get_backend_client()
        )
        return run_people_specialist(
            state=state, llm=dynamic_llm, backend_client=client
        )

    # ── Multi-agent: Widgets & History Specialist Node ─────
    def widgets_specialist_node(state: AgentState) -> AgentState:
        """Answers about existing dashboards, widgets, past AI insights."""
        from core.llm.widgets_specialist import run_widgets_specialist
        from core.llm.factory import create_llm_formatter

        dynamic_llm = (
            create_llm_formatter(
                creativity=state.get("creativity"), length=state.get("length")
            )
            if state.get("creativity") is not None or state.get("length") is not None
            else llm_formatter
        )
        client = (
            backend_client
            or __import__(
                "core.clients.backend_client", fromlist=["get_backend_client"]
            ).get_backend_client()
        )
        return run_widgets_specialist(
            state=state, llm=dynamic_llm, backend_client=client
        )

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
        return run_events_specialist(
            state=state, llm=dynamic_llm, backend_client=client
        )

    # ── Build the Graph ────────────────────────────────────
    graph = StateGraph(AgentState)

    # Register all nodes
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("full_context", full_context_node)
    graph.add_node("brain_retrieval", brain_retrieval_node)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("specialist", specialist_node)
    graph.add_node("parallel_specialist", parallel_specialist_node)
    graph.add_node("merger", merger_node)
    graph.add_node("formatter", formatter_node)
    graph.add_node("knowledge_specialist", knowledge_specialist_node)
    graph.add_node("events_specialist", events_specialist_node)
    graph.add_node("relationships_specialist", relationships_specialist_node)
    graph.add_node("people_specialist", people_specialist_node)
    graph.add_node("widgets_specialist", widgets_specialist_node)
    graph.add_node("mixed_planner", mixed_planner_node)
    graph.add_node("mixed_merger", mixed_merger_node)

    # ── Routing: Intent -> Specialist ──────────────────────
    def route_by_intent(state: AgentState):
        intent = state.get("intent", "data")
        routing = {
            "full_context": "full_context",
            # Knowledge layer (Metrics + Glossary + Relationships)
            # replaced the old Strategy entities — both intents
            # land on the same specialist now.
            "knowledge": "knowledge_specialist",
            "strategy": "knowledge_specialist",
            "signals": "events_specialist",
            "relationships": "relationships_specialist",
            "people": "people_specialist",
            "widgets": "widgets_specialist",
            "mixed": "mixed_planner",
        }
        return routing.get(intent, "orchestrator")

    def route_orchestrator(state: AgentState):
        # Orchestrator already set a final answer (CLARIFY, OUT_OF_SCOPE, catalog, error)
        # Skip specialist entirely and go straight to END
        if state.get("answer") and not state.get("chosen_tables"):
            return END
        if state.get("is_multi_source", False):
            return "parallel_specialist"
        return "specialist"

    # Entry point: always classify intent first
    graph.set_entry_point("intent_classifier")

    # Intent classifier always feeds into the brain — every specialist
    # then gets the same evidence blend to work from.
    graph.add_edge("intent_classifier", "brain_retrieval")

    # Brain retrieval → intent router
    graph.add_conditional_edges(
        "brain_retrieval",
        route_by_intent,
        {
            "full_context": "full_context",
            "knowledge_specialist": "knowledge_specialist",
            "events_specialist": "events_specialist",
            "relationships_specialist": "relationships_specialist",
            "people_specialist": "people_specialist",
            "widgets_specialist": "widgets_specialist",
            "mixed_planner": "mixed_planner",
            "orchestrator": "orchestrator",
        },
    )

    # full_context → END (answer already set by the autonomous agent)
    graph.add_edge("full_context", END)

    # Non-data specialists -> END (skip formatter — answer is already set by each specialist)
    graph.add_edge("knowledge_specialist", END)
    graph.add_edge("events_specialist", END)
    graph.add_edge("relationships_specialist", END)
    graph.add_edge("people_specialist", END)
    graph.add_edge("widgets_specialist", END)

    # mixed_planner → parallel_specialist (unified executor)
    graph.add_edge("mixed_planner", "parallel_specialist")

    # mixed_merger → formatter (when DuckDB merger ran) or END (answer already set)
    def route_mixed_merger(state: AgentState):
        if state.get("data") and not state.get("answer"):
            return "formatter"
        return END

    graph.add_conditional_edges(
        "mixed_merger",
        route_mixed_merger,
        {"formatter": "formatter", END: END},
    )

    # parallel_specialist → mixed_merger (mixed mode) or merger (SQL mode)
    def route_parallel_specialist(state: AgentState):
        if state.get("mixed_specialist_results") is not None:
            return "mixed_merger"
        return "merger"

    graph.add_conditional_edges(
        "parallel_specialist",
        route_parallel_specialist,
        {"mixed_merger": "mixed_merger", "merger": "merger"},
    )

    # Data pipeline
    graph.add_conditional_edges(
        "orchestrator",
        route_orchestrator,
        {
            "specialist": "specialist",
            "parallel_specialist": "parallel_specialist",
            END: END,
        },
    )

    graph.add_edge("specialist", "formatter")
    graph.add_edge("merger", "formatter")
    graph.add_edge("formatter", END)

    app = graph.compile(checkpointer=checkpointer)

    log_event(
        "generic_sql_graph_built",
        {
            "agent_id": agent_config.id,
            "num_tables": len(agent_config.tables),
            "checkpointer_active": checkpointer is not None,
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
    ai_tone: Optional[str] = None,
    ai_style: Optional[str] = None,
    sql_instructions: Optional[str] = None,
    selected_datasets: Optional[List[str]] = None,
    chat_history: Optional[List[Dict[str, str]]] = None,
    explicit_relationships: Optional[List[Dict[str, str]]] = None,
    agent_mode: Optional[str] = None,
    dispatch_map: Optional[dict] = None,
    briefing: str = "",
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
    locale = getattr(user_ctx, "locale", None)
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
        "ai_tone": ai_tone,
        "ai_style": ai_style,
        "sql_instructions": sql_instructions,
        "selected_datasets": selected_datasets,
        "explicit_relationships": explicit_relationships
        or [],  # Relacionamentos documentados pelo cliente
        "agent_mode": agent_mode,
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
            dispatch_map=dispatch_map,
            briefing=briefing,
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
