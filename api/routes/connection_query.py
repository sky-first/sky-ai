# api/routes/connection_query.py
"""
Endpoint para fazer queries diretamente usando uma DataConnection.
Ideal para integração com backend do produto.
"""
from __future__ import annotations

from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, create_engine
import os
import json
import asyncio
from typing import AsyncGenerator

from api.schemas import (
    QueryRequest,
    QueryResponse,
    QueryResultMeta,
    ChatBootstrapRequest,
    ChatBootstrapResponse,
    ChatBootstrapSuggestion,
    DashboardPlanRequest,
    DashboardPlanResponse,
    DashboardPlanWidget,
)
from core.agents.generic_sql_agent import AgentConfig, TableSchema, run_agent_once
from core.agents.davinci_dashboard_agent import generate_dashboard_plan
from core.agents.factory import _normalize_logical_name
from core.llm.factory import (
    create_llm_orchestrator,
    create_llm_specialist,
    create_llm_formatter,
    create_embedding_provider,
)
from core.rag.context_retrieval import build_retrieval_context_for_question
from core.data_sources.factory import DataSourceFactory
from core.logging_utils import log_event
from core.auth.service import get_user_crew_ids_in_space, resolve_crew_ids_for_context
from db.session import get_db
from db.base import SessionLocal

router = APIRouter(prefix="/connections", tags=["connection_query"])

def _safe_json_loads(text: str) -> Optional[dict]:
    """
    Best-effort JSON parsing for LLM outputs.
    Returns dict on success, None on failure.
    """
    import json as _json

    if not text:
        return None
    try:
        return _json.loads(text)
    except Exception:
        # try extracting first {...} block
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                return _json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


def _fallback_bootstrap(lang: str, max_suggestions: int) -> ChatBootstrapResponse:
    if lang == "pt":
        greeting = "Como posso te ajudar com seus dados?"
        suggestions: list[ChatBootstrapSuggestion] = [
            ChatBootstrapSuggestion(
                title="Criar dashboard",
                kind="action",
                action_id="create_dashboard",
                payload={"default_goal": "Billing overview", "default_max_widgets": 6},
            ),
            ChatBootstrapSuggestion(title="Dados disponíveis", kind="question", question="Quais dados eu tenho acesso?"),
            ChatBootstrapSuggestion(title="Tabelas", kind="question", question="Quais tabelas estão disponíveis neste catálogo?"),
            ChatBootstrapSuggestion(title="Colunas", kind="question", question="Quais colunas tem dentro da tabela customers?"),
            ChatBootstrapSuggestion(title="Exemplo", kind="question", question="Me dê exemplos de perguntas que eu posso fazer com meus dados."),
        ]
    elif lang == "es":
        greeting = "¿Cómo puedo ayudarte con tus datos?"
        suggestions = [
            ChatBootstrapSuggestion(
                title="Crear dashboard",
                kind="action",
                action_id="create_dashboard",
                payload={"default_goal": "Billing overview", "default_max_widgets": 6},
            ),
            ChatBootstrapSuggestion(title="Datos disponibles", kind="question", question="¿A qué datos tengo acceso?"),
            ChatBootstrapSuggestion(title="Tablas", kind="question", question="¿Qué tablas están disponibles en este catálogo?"),
            ChatBootstrapSuggestion(title="Columnas", kind="question", question="¿Qué columnas tiene la tabla customers?"),
            ChatBootstrapSuggestion(title="Ejemplos", kind="question", question="Dame ejemplos de preguntas que puedo hacer con mis datos."),
        ]
    else:
        greeting = "How can I help you with your data?"
        suggestions = [
            ChatBootstrapSuggestion(
                title="Create dashboard",
                kind="action",
                action_id="create_dashboard",
                payload={"default_goal": "Billing overview", "default_max_widgets": 6},
            ),
            ChatBootstrapSuggestion(title="Available data", kind="question", question="What data do I have access to?"),
            ChatBootstrapSuggestion(title="Tables", kind="question", question="Which tables are available in my catalog?"),
            ChatBootstrapSuggestion(title="Columns", kind="question", question="What columns are inside the customers table?"),
            ChatBootstrapSuggestion(title="Examples", kind="question", question="Give me examples of questions I can ask about my data."),
        ]

    out = suggestions[:max_suggestions]
    while len(out) < max_suggestions:
        out.append(ChatBootstrapSuggestion(title="Example", kind="question", question="Show me something interesting from my data."))
    return ChatBootstrapResponse(greeting=greeting, suggestions=out, meta={"fallback": True})


@router.post("/{connection_id}/chat/bootstrap", response_model=ChatBootstrapResponse)
async def chat_bootstrap(
    connection_id: str,
    body: ChatBootstrapRequest,
    db: Session = Depends(get_db),
) -> ChatBootstrapResponse:
    """
    Generate greeting + suggestion cards for a new chat session.

    Called by the product backend (poc-02) only for Personal mode.
    """
    from core.i18n.i18n import detect_language

    lang = body.language or detect_language(body.user_id or "") or "en"
    lang = (lang or "en").lower()
    if lang not in {"pt", "en", "es"}:
        lang = "en"

    # Load AgentConfig (tables/columns) using provided crew_ids (avoid resolving here).
    try:
        agent_config = load_agent_config_from_connection(
            db=db,
            space_id=body.space_id,
            connection_id=connection_id,
            crew_ids=body.crew_ids if body.crew_ids else None,
        )
    except Exception as e:
        return _fallback_bootstrap(lang=lang, max_suggestions=body.max_suggestions)

    tables = agent_config.tables or []
    if not tables:
        return _fallback_bootstrap(lang=lang, max_suggestions=body.max_suggestions)

    # Build a compact schema summary for the LLM.
    max_tables_in_prompt = min(12, len(tables))
    schema_lines: list[str] = []
    for t in tables[:max_tables_in_prompt]:
        cols = getattr(t, "columns", []) or []
        col_names = [c.name for c in cols[:8]] if cols else []
        schema_lines.append(f"- {t.logical_name} (physical: {t.physical_name}) cols: {', '.join(col_names)}")

    schema_summary = "\n".join(schema_lines)

    system = (
        "You generate a greeting and suggestion cards for a data analytics chat.\n"
        "Rules:\n"
        "- Output STRICT JSON only.\n"
        "- JSON schema: {\"greeting\": string, \"suggestions\": [{\"title\": string, \"question\": string}]}\n"
        "- Provide EXACTLY N suggestions.\n"
        "- Suggestions must be answerable using ONLY the provided tables/columns.\n"
        "- Avoid mentioning table physical names; prefer natural questions.\n"
        "- Keep questions short and actionable.\n"
        f"- Language: {lang}\n"
    )

    user = (
        f"N={max(1, body.max_suggestions - 1)}\n"
        f"User has access to {len(tables)} tables. Schema (sample):\n"
        f"{schema_summary}\n\n"
        "Generate greeting + suggestions."
    )

    try:
        llm = create_llm_orchestrator(creativity=15, length=20)
        resp = llm.invoke(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
        parsed = _safe_json_loads(getattr(resp, "content", "") or "")
        if not isinstance(parsed, dict):
            return _fallback_bootstrap(lang=lang, max_suggestions=body.max_suggestions)

        greeting = str(parsed.get("greeting") or "").strip()
        suggestions_raw = parsed.get("suggestions") or []
        suggestions: list[ChatBootstrapSuggestion] = []
        if isinstance(suggestions_raw, list):
            for item in suggestions_raw:
                if isinstance(item, dict):
                    title = str(item.get("title") or "").strip()
                    question = str(item.get("question") or "").strip()
                    if title and question:
                        suggestions.append(ChatBootstrapSuggestion(title=title, kind="question", question=question))

        if not greeting or len(suggestions) == 0:
            return _fallback_bootstrap(lang=lang, max_suggestions=body.max_suggestions)

        # Always prepend the action card as the first suggestion.
        action_title = "Create dashboard" if lang == "en" else ("Criar dashboard" if lang == "pt" else "Crear dashboard")
        action_card = ChatBootstrapSuggestion(
            title=action_title,
            kind="action",
            action_id="create_dashboard",
            payload={"default_goal": "Billing overview", "default_max_widgets": 6},
        )
        suggestions = [action_card] + suggestions

        # Normalize count
        suggestions = suggestions[: body.max_suggestions]
        while len(suggestions) < body.max_suggestions:
            suggestions.append(
                ChatBootstrapSuggestion(title="Example", kind="question", question=(suggestions[-1].question or "Show me something interesting from my data."))
            )

        return ChatBootstrapResponse(
            greeting=greeting,
            suggestions=suggestions,
            meta={
                "fallback": False,
                "num_tables": len(tables),
                "prompt_tables": max_tables_in_prompt,
                "agent_id": agent_config.id,
            },
        )
    except Exception:
        return _fallback_bootstrap(lang=lang, max_suggestions=body.max_suggestions)


@router.post("/{connection_id}/dashboards/plan", response_model=DashboardPlanResponse)
async def dashboards_plan(
    connection_id: str,
    body: DashboardPlanRequest,
    db: Session = Depends(get_db),
) -> DashboardPlanResponse:
    """
    Generate a dashboard plan ("Davinci") for the given connection.
    This does not execute queries; it only proposes widgets/questions.
    """
    lang = (body.language or "en").lower()
    if lang not in {"en", "pt", "es"}:
        lang = "en"

    agent_config = None
    tables = []
    logical_tables: list[str] = []
    schema_summary = ""
    max_tables_in_prompt = 0

    # Resolve crew_ids based on context (personal vs collaborative).
    # If we don't resolve, the metadata query will default to public-only (crew_id IS NULL),
    # which breaks Personal mode dashboards when metadata is scoped to crews.
    resolved_crew_ids: list[str] = []
    try:
        if body.crew_ids:
            resolved_crew_ids = [str(x) for x in body.crew_ids]
        elif body.user_id:
            from uuid import UUID

            resolved = resolve_crew_ids_for_context(
                db=db,
                user_id=UUID(body.user_id),
                space_id=UUID(body.space_id) if body.space_id else None,
                request_crew_ids=None,
                is_personal=bool(getattr(body, "is_personal", False)),
            )
            resolved_crew_ids = [str(x) for x in (resolved or [])]
    except Exception as e:
        log_event(
            "dashboards_plan_resolve_crew_ids_error",
            {
                "connection_id": connection_id,
                "space_id": body.space_id,
                "user_id": body.user_id,
                "is_personal": bool(getattr(body, "is_personal", False)),
                "error": str(e),
            },
        )
        resolved_crew_ids = []

    # Load AgentConfig (tables/columns) using resolved crew_ids.
    # If catalog metadata is not available yet, continue with an empty catalog and let
    # the planner return a safe text-only plan.
    try:
        agent_config = load_agent_config_from_connection(
            db=db,
            space_id=body.space_id,
            connection_id=connection_id,
            crew_ids=resolved_crew_ids if resolved_crew_ids else None,
        )
        tables = agent_config.tables or []
        logical_tables = [
            (t.get("logical_name") if isinstance(t, dict) else getattr(t, "logical_name", None))
            for t in tables
        ]
        logical_tables = [lt for lt in logical_tables if lt]

        # Compact schema summary for the planner.
        max_tables_in_prompt = min(12, len(tables))
        schema_lines: list[str] = []
        for t in tables[:max_tables_in_prompt]:
            t_logical = (
                t.get("logical_name")
                if isinstance(t, dict)
                else getattr(t, "logical_name", None)
            )
            cols = (t.get("columns") if isinstance(t, dict) else getattr(t, "columns", None)) or []

            col_names: list[str] = []
            all_col_names: list[str] = []
            for c in (cols if isinstance(cols, list) else []):
                if isinstance(c, dict):
                    name = c.get("name") or c.get("column_name")
                    if name:
                        all_col_names.append(str(name))
                else:
                    name = getattr(c, "name", None)
                    if name:
                        all_col_names.append(str(name))

            # Show up to 10 columns, but also highlight join-like keys to encourage multi-table questions.
            col_names = all_col_names[:10]
            key_like = [
                n
                for n in all_col_names
                if any(
                    k in n.lower()
                    for k in (
                        "_id",
                        "id",
                        "key",
                        "date",
                        "time",
                        "customer",
                        "user",
                        "account",
                        "invoice",
                        "order",
                        "product",
                    )
                )
            ][:6]

            if t_logical:
                suffix = f" keys: {', '.join(key_like)}" if key_like else ""
                schema_lines.append(f"- {t_logical} cols: {', '.join(col_names)}{suffix}")
        schema_summary = "\n".join(schema_lines)
    except Exception:
        agent_config = None
        tables = []
        logical_tables = []
        schema_summary = ""
        max_tables_in_prompt = 0

    try:
        llm = create_llm_specialist(creativity=10, length=35)  # gpt-4o by default
        plan = generate_dashboard_plan(
            llm=llm,
            goal=body.goal,
            language=lang,
            max_widgets=body.max_widgets,
            logical_tables=logical_tables,
            schema_summary=schema_summary,
        )
        widgets = [DashboardPlanWidget(**w) for w in plan.widgets]
        return DashboardPlanResponse(
            dashboard_name=plan.dashboard_name,
            description=plan.description,
            widgets=widgets,
            meta={
                **(plan.meta or {}),
                "num_tables": len(logical_tables),
                "prompt_tables": max_tables_in_prompt,
                "agent_id": agent_config.id if agent_config else None,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate dashboard plan: {str(e)}")


@router.get("/{connection_id}/tables")
async def list_available_tables(
    connection_id: str,
    space_id: str = Query(..., description="ID do space (obrigatório)"),
    user_id: Optional[str] = Query(None, description="ID do usuário (opcional)"),
    crew_ids: Optional[List[str]] = Query(None, description="Lista de crew_ids (opcional)"),
    is_personal: bool = Query(False, description="Modo personal (acesso a todos os crews)"),
    db: Session = Depends(get_db),
):
    """
    Lista todas as tabelas disponíveis para uma conexão, respeitando permissões do usuário.
    
    Parâmetros:
    - connection_id: ID da conexão
    - space_id: ID do space (query parameter obrigatório)
    - user_id: ID do usuário (opcional, para filtrar por permissões)
    - crew_ids: Lista de crew_ids (opcional, será resolvido automaticamente se user_id fornecido)
    - is_personal: Se True, retorna tabelas de todos os crews do usuário (modo personal)
    
    Retorna:
    - Lista de tabelas com seus schemas (nome, colunas, tipos)
    """
    from core.auth.service import resolve_crew_ids_for_context
    from uuid import UUID
    
    # Resolver crew_ids baseado no contexto (personal vs collaborative)
    resolved_crew_ids = crew_ids or []
    if user_id:
        try:
            resolved_crew_ids = resolve_crew_ids_for_context(
                db=db,
                user_id=UUID(user_id),
                space_id=UUID(space_id) if space_id else None,
                request_crew_ids=crew_ids,
                is_personal=is_personal
            )
            resolved_crew_ids = [str(crew_id) for crew_id in resolved_crew_ids]
        except Exception as e:
            log_event(
                "api_list_tables_resolve_crew_ids_error",
                {
                    "connection_id": connection_id,
                    "user_id": user_id,
                    "space_id": space_id,
                    "error": str(e),
                },
            )
            # Se falhar ao resolver, usar lista vazia (apenas dados públicos)
            resolved_crew_ids = []
    
    # Construir query SQL com filtro de permissões
    query_sql = """
        SELECT DISTINCT table_name
        FROM table_metadata
        WHERE space_id = :space_id AND data_connection_id = :conn_id
    """
    query_params = {"space_id": space_id, "conn_id": connection_id}
    
    # Adicionar filtro de permissões se crew_ids fornecidos
    if resolved_crew_ids:
        query_sql += " AND (crew_id IS NULL OR crew_id = ANY(:crew_ids))"
        query_params["crew_ids"] = resolved_crew_ids
    else:
        # Se não há crew_ids, mostrar apenas dados públicos (crew_id IS NULL)
        query_sql += " AND crew_id IS NULL"
    
    query_sql += " ORDER BY table_name"
    
    # Buscar tabelas via SQL direto
    from db.base import engine
    with engine.connect() as raw_conn:
        result = raw_conn.execute(
            text(query_sql),
            query_params
        ).fetchall()
    
    # Buscar detalhes de cada tabela (colunas)
    tables_info = []
    for row in result:
        table_name = row[0]
        
        # Buscar colunas desta tabela
        columns_sql = """
            SELECT column_name, data_type, is_nullable, description
            FROM table_metadata
            WHERE space_id = :space_id 
              AND data_connection_id = :conn_id 
              AND table_name = :table_name
        """
        columns_params = {
            "space_id": space_id,
            "conn_id": connection_id,
            "table_name": table_name
        }
        
        # Adicionar filtro de permissões para colunas também
        if resolved_crew_ids:
            columns_sql += " AND (crew_id IS NULL OR crew_id = ANY(:crew_ids))"
            columns_params["crew_ids"] = resolved_crew_ids
        else:
            columns_sql += " AND crew_id IS NULL"
        
        columns_sql += " ORDER BY column_name"
        
        with engine.connect() as raw_conn2:
            columns_result = raw_conn2.execute(
                text(columns_sql),
                columns_params
            ).fetchall()
        
        columns = [
            {
                "name": col[0],
                "type": col[1] or "STRING",
                "nullable": col[2] or False,
                "description": col[3] if len(col) > 3 and col[3] else None,
            }
            for col in columns_result
        ]
        
        tables_info.append({
            "name": table_name,
            "columns": columns,
            "num_columns": len(columns),
        })
    
    log_event(
        "api_list_tables_success",
        {
            "connection_id": connection_id,
            "space_id": space_id,
            "user_id": user_id,
            "num_tables": len(tables_info),
            "crew_ids": resolved_crew_ids,
            "is_personal": is_personal,
        },
    )
    
    return {
        "connection_id": connection_id,
        "space_id": space_id,
        "tables": tables_info,
        "total_tables": len(tables_info),
    }


def load_agent_config_from_connection(
    db: Session,
    space_id: str,
    connection_id: str,
    crew_ids: Optional[List[str]] = None,
) -> AgentConfig:
    """
    Carrega TableMetadata e monta AgentConfig automaticamente para uma conexão.
    Compatível com schema real do banco (usa SQL raw).
    
    Args:
        db: Sessão do banco de dados
        space_id: ID do espaço
        connection_id: ID da conexão
        crew_ids: Lista opcional de crew_ids para filtrar por permissões do usuário
    """
    from db.base import engine
    
    log_event(
        "load_agent_config_start",
        {
            "space_id": space_id,
            "connection_id": connection_id,
            "crew_ids": crew_ids,
        },
    )
    
    # Construir query SQL com filtro de permissões
    query_sql = """
        SELECT table_name, column_name, data_type, is_nullable
        FROM table_metadata
        WHERE space_id = :space_id AND data_connection_id = :conn_id
    """
    query_params = {"space_id": space_id, "conn_id": connection_id}
    
    # Adicionar filtro de permissões se crew_ids fornecidos
    if crew_ids:
        query_sql += " AND (crew_id IS NULL OR crew_id = ANY(:crew_ids))"
        query_params["crew_ids"] = crew_ids
    else:
        # Se não há crew_ids, mostrar apenas dados públicos (crew_id IS NULL)
        query_sql += " AND crew_id IS NULL"
    
    query_sql += " ORDER BY table_name, column_name"
    
    # Buscar metadados via SQL direto (compatível com UUID)
    with engine.connect() as raw_conn:
        result = raw_conn.execute(
            text(query_sql),
            query_params
        ).fetchall()
    
    log_event(
        "load_agent_config_metadata_query",
        {
            "space_id": space_id,
            "connection_id": connection_id,
            "num_rows_found": len(result) if result else 0,
        },
    )
    
    if not result:
        log_event(
            "load_agent_config_no_metadata",
            {
                "space_id": space_id,
                "connection_id": connection_id,
            },
        )
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum metadata encontrado para esta conexão. Execute a descoberta de tabelas primeiro."
        )
    
    # Agrupar por tabela
    tables: dict[str, list] = {}
    for row in result:
        table_name = row[0]
        if table_name not in tables:
            tables[table_name] = []
        tables[table_name].append({
            "column_name": row[1],
            "data_type": row[2] or "STRING",
            "is_nullable": row[3] or False
        })
    
    log_event(
        "load_agent_config_tables_grouped",
        {
            "space_id": space_id,
            "connection_id": connection_id,
            "num_unique_tables": len(tables),
            "table_names": list(tables.keys()),
        },
    )
    
    # Detectar dataset baseado no nome da tabela ou config da conexão
    def detect_dataset(table_name: str, conn_config: dict) -> str:
        """Detecta o dataset correto baseado no nome da tabela ou config"""
        # Tabelas do web_silver
        web_tables = [
            "silver_events_enriquecido",
            "silver_pageviews_enriquecido", 
            "silver_sessions_enriquecido",
            "silver_sources_enriquecido",
            "silver_users_enriquecido",
            "silver_web_data_enriquecido"
        ]
        if table_name in web_tables:
            return "data-mesh-gcp.web_silver"
        
        # Usar dataset do config da conexão
        dataset = conn_config.get("dataset", "data-mesh-gcp.billing_silver")
        # Se já tem projeto, usar direto; senão, adicionar projeto
        if "." in dataset and not dataset.startswith("data-mesh-gcp."):
            return dataset
        return dataset
    
    # Buscar config da conexão
    with engine.connect() as raw_conn:
        conn_result = raw_conn.execute(
            text("SELECT config FROM data_connections WHERE id = :id"),
            {"id": connection_id}
        ).first()
        config = conn_result[0] if conn_result else {}
        if isinstance(config, str):
            config = json.loads(config)
        elif config is None:
            config = {}
    
    log_event(
        "load_agent_config_connection_config",
        {
            "connection_id": connection_id,
            "config_dataset": config.get("dataset") if isinstance(config, dict) else None,
            "config_keys": list(config.keys()) if isinstance(config, dict) else [],
        },
    )
    
    # Criar TableSchemas
    table_schemas: list[TableSchema] = []
    for tname, cols in tables.items():
        dataset = detect_dataset(tname, config)
        physical_name = f"{dataset}.{tname}" if "." not in tname else tname
        
        # Normalizar logical_name para nome amigável (remove prefixos/sufixos)
        logical_name = _normalize_logical_name(tname)
        
        log_event(
            "load_agent_config_table_schema",
            {
                "connection_id": connection_id,
                "table_name": tname,
                "logical_name": logical_name,
                "physical_name": physical_name,
                "dataset": dataset,
                "num_columns": len(cols),
            },
        )
        
        schema = TableSchema(
            logical_name=logical_name,
            physical_name=physical_name,
            columns=[
                {
                    "name": c["column_name"],
                    "type": c["data_type"],
                    "nullable": c["is_nullable"]
                }
                for c in cols
            ],
        )
        table_schemas.append(schema)
    
    agent = AgentConfig(
        id=f"agent-conn-{connection_id}",
        name=f"Agent for connection {connection_id}",
        tables=table_schemas,
    )
    
    log_event(
        "load_agent_config_complete",
        {
            "space_id": space_id,
            "connection_id": connection_id,
            "agent_id": agent.id,
            "num_tables": len(table_schemas),
            "table_schemas": [
                {
                    "logical_name": t.logical_name,
                    "physical_name": t.physical_name,
                    "num_columns": len(t.columns),
                }
                for t in table_schemas
            ],
        },
    )
    
    return agent


@router.post("/{connection_id}/query", response_model=QueryResponse)
async def query_connection(
    connection_id: str,
    body: QueryRequest,
    db: Session = Depends(get_db),
) -> QueryResponse:
    """
    Faz uma pergunta usando uma DataConnection diretamente.
    
    Requisitos:
    - A conexão deve ter metadados descobertos (execute /discover primeiro)
    - O space_id no body deve corresponder ao space_id da conexão
    
    Exemplo de uso:
    ```json
    {
        "question": "Qual é a performance de pageviews mensal?",
        "user_id": "user-123",
        "space_id": "00000000-0000-0000-0000-000000000001",
        "thread_id": "thread-456"
    }
    ```
    """
    if not body.space_id:
        raise HTTPException(
            status_code=400,
            detail="space_id é obrigatório no body da requisição"
        )
    
    # Verificar se conexão existe
    conn_result = db.execute(
        # Usar connector_id como alias para type para ser compatível com schemas antigos
        text("SELECT id, name, connector_id AS type, config FROM data_connections WHERE id = :id"),
        {"id": connection_id}
    ).first()
    
    if not conn_result:
        raise HTTPException(status_code=404, detail=f"Conexão {connection_id} não encontrada")
    
    # Resolver crew_ids do usuário baseado no contexto (personal vs collaborative)
    crew_ids = body.crew_ids or []
    if body.user_id:
        try:
            resolved_crew_ids = resolve_crew_ids_for_context(
                db=db,
                user_id=UUID(body.user_id),
                space_id=UUID(body.space_id) if body.space_id else None,
                request_crew_ids=body.crew_ids,
                is_personal=getattr(body, 'is_personal', False)
            )
            crew_ids = [str(crew_id) for crew_id in resolved_crew_ids]
            log_event(
                "api_query_connection_resolved_crew_ids",
                {
                    "connection_id": connection_id,
                    "user_id": body.user_id,
                    "space_id": body.space_id,
                    "is_personal": getattr(body, 'is_personal', False),
                    "resolved_crew_ids": crew_ids,
                },
            )
        except Exception as e:
            log_event(
                "api_query_connection_resolve_crew_ids_error",
                {
                    "connection_id": connection_id,
                    "user_id": body.user_id,
                    "space_id": body.space_id,
                    "error": str(e),
                },
            )
            # Se falhar ao resolver, usar lista vazia (apenas dados públicos)
            crew_ids = []
    
    # Carregar AgentConfig automaticamente com filtro de permissões
    try:
        agent_config = load_agent_config_from_connection(
            db=db,
            space_id=body.space_id,
            connection_id=connection_id,
            crew_ids=crew_ids if crew_ids else None,
        )
        
        log_event(
            "api_query_connection_agent_config_loaded",
            {
                "connection_id": connection_id,
                "space_id": body.space_id,
                "user_id": body.user_id,
                "crew_ids": crew_ids,
                "agent_id": agent_config.id,
                "num_tables": len(agent_config.tables),
                "has_tables": len(agent_config.tables) > 0,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        log_event(
            "api_query_connection_agent_config_error",
            {
                "connection_id": connection_id,
                "space_id": body.space_id,
                "error": str(e),
                "error_type": type(e).__name__,
            },
        )
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao carregar configuração do agente: {str(e)}"
        )

    # Fast-path answers for catalog questions (avoid LLM/SQL for simple metadata requests).
    # This makes the UX consistent in both Portuguese and English.
    try:
        import re

        q_raw = (body.question or "").strip()
        q = q_raw.lower()
        tables = agent_config.tables or []
        logical_tables = [t.logical_name for t in tables if getattr(t, "logical_name", None)]

        is_tables_question = bool(
            re.search(
                r"(\bquais\b.*\btabelas\b)|"
                r"(\btabelas\b.*\bdispon[ií]veis\b)|"
                r"(\bwhat\b.*\btables?\b)|"
                r"(\bwhich\b.*\btables?\b)|"
                r"(\blist\b.*\btables?\b)|"
                r"(\bavailable\b.*\btables?\b)",
                q,
                flags=re.IGNORECASE,
            )
        )

        is_examples_question = bool(
            re.search(
                r"(\bexemplos\b.*\bperguntas?\b)|"
                r"(\bo que\b.*\bperguntas?\b.*\bposso\b)|"
                r"(\bexamples?\b.*\bquestions?\b)|"
                r"(\bexample\b.*\bquestions?\b)|"
                r"(\bwhat can i ask\b)",
                q,
                flags=re.IGNORECASE,
            )
        )

        if is_tables_question and logical_tables:
            answer = (
                f"You have access to **{len(logical_tables)}** table(s) in this connection:\n"
                + "\n".join([f"- `{name}`" for name in logical_tables])
                + "\n\nWhich table would you like to inspect columns for?"
            )
            meta = QueryResultMeta(
                detected_language="en",
                chosen_table=None,
                chosen_datasets=logical_tables,
                sql=None,
                num_rows=0,
                error=None,
            )
            return QueryResponse(answer=answer, data_sample=[], meta=meta)

        if is_examples_question and logical_tables:
            # Generate examples that are guaranteed to be answerable with the available tables.
            # Keep them per-table to avoid assuming joins.
            picked = logical_tables[:6]
            examples: list[str] = []
            for t in picked:
                examples.append(f"How many rows are in the `{t}` table?")
            if len(picked) >= 1:
                examples.append(f"Show me the latest 10 rows from `{picked[0]}`.")
            if len(picked) >= 2:
                examples.append(f"Give me a breakdown (count) by a key column in `{picked[1]}`.")

            examples = examples[:8]
            answer = "Here are some examples of questions you can ask:\n" + "\n".join(
                [f"- {e}" for e in examples]
            )
            meta = QueryResultMeta(
                detected_language="en",
                chosen_table=None,
                chosen_datasets=picked,
                sql=None,
                num_rows=0,
                error=None,
            )
            return QueryResponse(answer=answer, data_sample=[], meta=meta)
    except Exception:
        # Never fail the main query path due to these heuristics.
        pass
    
    # Criar DataSource da conexão
    class TempDataConnection:
        def __init__(self, id, name, type, config):
            self.id = id
            self.name = name
            self.type = type
            self.config = config if isinstance(config, dict) else json.loads(config) if isinstance(config, str) else {}
    
    # Parse config safely
    conn_config = conn_result[3]
    if isinstance(conn_config, str):
        try:
            conn_config = json.loads(conn_config)
        except json.JSONDecodeError:
            conn_config = {}
    elif conn_config is None:
        conn_config = {}
    elif not isinstance(conn_config, dict):
        conn_config = {}
    
    data_conn = TempDataConnection(
        id=str(conn_result[0]),
        name=conn_result[1],
        type=conn_result[2] or "bigquery",
        config=conn_config
    )
    
    try:
        data_source = DataSourceFactory.build_from_dataconnection(data_conn)
    except Exception as e:
        import traceback
        error_detail = f"Erro ao criar DataSource: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(
            status_code=500,
            detail=error_detail
        )
    
    # LLMs usando factory centralizado
    llm_orchestrator = create_llm_orchestrator()
    llm_specialist = create_llm_specialist()
    llm_formatter = create_llm_formatter()
    
    # Provider de embeddings (RAG) usando factory centralizado
    embedding_provider = create_embedding_provider()
    
    # Buscar contexto RAG com crew_ids resolvidos
    retrieval_context: list[str] = []
    try:
        retrieval_context = build_retrieval_context_for_question(
            db=db,
            embedding_provider=embedding_provider,
            space_id=body.space_id,
            crew_ids=crew_ids if crew_ids else None,
            question=body.question,
            top_k=10,
        )
    except Exception:
        # Se RAG falhar, continua sem contexto
        retrieval_context = []
    
    # Executar agente
    try:
        from core.agents.generic_sql_agent import build_generic_sql_graph
        
        state = {
            "question": body.question,
            "user_id": body.user_id,
            "space_id": body.space_id,
            "crew_ids": crew_ids,
            "retrieval_context": retrieval_context,
            # Configurações dinâmicas da IA
            "instructions": body.instructions,
            "creativity": body.creativity,
            "length": body.length,
            "response_format": body.response_format,
            "sql_instructions": body.sql_instructions,
            "selected_datasets": body.selected_datasets,
        }
        
        # Criar factory que retorna uma nova sessão (não reutilizar a sessão do FastAPI)
        def db_session_factory():
            return SessionLocal()
        
        app = build_generic_sql_graph(
            agent_config=agent_config,
            data_source=data_source,
            db_session_factory=db_session_factory,
            embedding_provider=embedding_provider,
            llm_orchestrator=llm_orchestrator,
            llm_specialist=llm_specialist,
            llm_formatter=llm_formatter,
        )
        
        thread_id = body.thread_id or f"{body.user_id or 'anon'}-{connection_id}"
        final_state = app.invoke(
            state,
            config={"configurable": {"thread_id": thread_id}},
        )
        
    except Exception as e:
        import traceback
        error_detail = f"Erro ao executar agente: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(
            status_code=500,
            detail=error_detail
        )
    
    answer = final_state.get("answer") or ""
    data = final_state.get("data") or []
    detected_language = final_state.get("detected_language")
    chosen_table = final_state.get("chosen_table")
    chosen_tables = final_state.get("chosen_tables")  # List of tables (new)
    sql = final_state.get("sql")
    error = final_state.get("error")
    
    # Debug: log all keys in final_state to see what's available
    log_event(
        "api_query_connection_final_state",
        {
            "connection_id": connection_id,
            "final_state_keys": list(final_state.keys()),
            "chosen_table": chosen_table,
            "chosen_tables": chosen_tables,
            "chosen_table_physical": final_state.get("chosen_table_physical"),
            "has_answer": bool(answer),
            "has_sql": bool(sql),
            "sql_preview": sql[:200] if sql else None,
        },
    )
    
    # Fallback: try to extract table name from SQL if chosen_table is not available
    if not chosen_table and not chosen_tables and sql:
        import re
        # Try to extract table name from SQL (FROM clause)
        from_match = re.search(r'FROM\s+([^\s,\(\)]+)', sql, re.IGNORECASE)
        if from_match:
            table_from_sql = from_match.group(1).strip()
            # Remove schema prefix if present (e.g., "dataset.table" -> "table")
            if '.' in table_from_sql:
                table_from_sql = table_from_sql.split('.')[-1]
            chosen_table = table_from_sql
            log_event(
                "api_query_connection_extracted_from_sql",
                {
                    "connection_id": connection_id,
                    "extracted_table": chosen_table,
                    "sql_preview": sql[:200],
                },
            )
    
    # Use chosen_tables if available, otherwise fallback to chosen_table
    chosen_datasets = chosen_tables if chosen_tables else ([chosen_table] if chosen_table else [])
    
    # Debug log
    log_event(
        "api_query_connection_chosen_datasets",
        {
            "connection_id": connection_id,
            "chosen_table": chosen_table,
            "chosen_tables": chosen_tables,
            "final_chosen_datasets": chosen_datasets,
        },
    )
    
    data_sample = data[:15] if isinstance(data, list) else []
    
    meta = QueryResultMeta(
        detected_language=detected_language,
        chosen_table=chosen_table,
        chosen_datasets=chosen_datasets if chosen_datasets else None,
        sql=sql,
        num_rows=len(data),
        error=error,
    )
    
    log_event(
        "api_query_connection",
        {
            "connection_id": connection_id,
            "user_id": body.user_id,
            "space_id": body.space_id,
            "question": body.question[:200],
            "answer_preview": answer[:200],
            "num_rows": len(data),
            "error": error[:200] if error else None,
        },
    )
    
    return QueryResponse(
        answer=answer,
        data_sample=data_sample,
        meta=meta,
    )


async def _stream_connection_query(
    connection_id: str,
    body: QueryRequest,
    db: Session,
) -> AsyncGenerator[str, None]:
    """
    Generator function that yields SSE events for streaming query responses.
    """
    try:
        # Verificar se conexão existe
        conn_result = db.execute(
            text("SELECT id, name, connector_id AS type, config FROM data_connections WHERE id = :id"),
            {"id": connection_id}
        ).first()
        
        if not conn_result:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Conexão {connection_id} não encontrada'})}\n\n"
            return
        
        # Resolver crew_ids
        crew_ids = body.crew_ids or []
        if body.user_id:
            try:
                resolved_crew_ids = resolve_crew_ids_for_context(
                    db=db,
                    user_id=UUID(body.user_id),
                    space_id=UUID(body.space_id) if body.space_id else None,
                    request_crew_ids=body.crew_ids,
                    is_personal=getattr(body, 'is_personal', False)
                )
                crew_ids = [str(crew_id) for crew_id in resolved_crew_ids]
            except Exception as e:
                log_event(
                    "api_query_connection_stream_resolve_crew_ids_error",
                    {
                        "connection_id": connection_id,
                        "error": str(e),
                    },
                )
                crew_ids = []
        
        # Carregar AgentConfig
        try:
            agent_config = load_agent_config_from_connection(
                db=db,
                space_id=body.space_id,
                connection_id=connection_id,
                crew_ids=crew_ids if crew_ids else None,
            )
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return
        
        # Criar DataSource
        conn_config = conn_result[3]
        if isinstance(conn_config, str):
            try:
                conn_config = json.loads(conn_config)
            except json.JSONDecodeError:
                conn_config = {}
        elif conn_config is None:
            conn_config = {}
        elif not isinstance(conn_config, dict):
            conn_config = {}
        
        class TempDataConnection:
            def __init__(self, id, name, type, config):
                self.id = id
                self.name = name
                self.type = type
                self.config = config
        
        data_conn = TempDataConnection(
            id=str(conn_result[0]),
            name=conn_result[1],
            type=conn_result[2] or "bigquery",
            config=conn_config
        )
        
        try:
            data_source = DataSourceFactory.build_from_dataconnection(data_conn)
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Erro ao criar DataSource: {str(e)}'})}\n\n"
            return
        
        # LLMs
        llm_orchestrator = create_llm_orchestrator()
        llm_specialist = create_llm_specialist()
        llm_formatter = create_llm_formatter()
        embedding_provider = create_embedding_provider()
        
        # Buscar contexto RAG
        retrieval_context: list[str] = []
        try:
            retrieval_context = build_retrieval_context_for_question(
                db=db,
                embedding_provider=embedding_provider,
                space_id=body.space_id,
                crew_ids=crew_ids if crew_ids else None,
                question=body.question,
                top_k=10,
            )
        except Exception:
            retrieval_context = []
        
        # Executar agente até o specialist (sem formatter ainda)
        try:
            from core.agents.generic_sql_agent import build_generic_sql_graph
            from core.llm.formatter import _ensure_language, _serialize_for_json, _compute_basic_stats, _stream_llm
            
            state = {
                "question": body.question,
                "user_id": body.user_id,
                "space_id": body.space_id,
                "crew_ids": crew_ids,
                "retrieval_context": retrieval_context,
                # Configurações dinâmicas da IA
                "instructions": body.instructions,
                "creativity": body.creativity,
                "length": body.length,
                "response_format": body.response_format,
                "sql_instructions": body.sql_instructions,
                "selected_datasets": body.selected_datasets,
            }
            
            def db_session_factory():
                return SessionLocal()
            
            app = build_generic_sql_graph(
                agent_config=agent_config,
                data_source=data_source,
                db_session_factory=db_session_factory,
                embedding_provider=embedding_provider,
                llm_orchestrator=llm_orchestrator,
                llm_specialist=llm_specialist,
                llm_formatter=llm_formatter,
            )
            
            thread_id = body.thread_id or f"{body.user_id or 'anon'}-{connection_id}"
            
            # Executar até o specialist (orchestrator -> specialist)
            # Não executamos o formatter ainda, vamos fazer streaming dele
            final_state = None
            for chunk in app.stream(state, config={"configurable": {"thread_id": thread_id}}):
                for node_name, node_state in chunk.items():
                    if node_name in ["orchestrator", "specialist"]:
                        final_state = node_state
                        # Enviar progresso e eventos específicos
                        if node_name == "orchestrator":
                            yield f"data: {json.dumps({'type': 'progress', 'stage': 'orchestrator', 'message': 'Analisando pergunta...'})}\n\n"
                            
                            # Enviar evento quando datasets são escolhidos
                            chosen_table = node_state.get("chosen_table")
                            chosen_tables = node_state.get("chosen_tables")
                            if chosen_table or chosen_tables:
                                chosen_datasets = chosen_tables if chosen_tables else ([chosen_table] if chosen_table else [])
                                yield f"data: {json.dumps({'type': 'datasets_selected', 'datasets': chosen_datasets})}\n\n"
                        
                        elif node_name == "specialist":
                            yield f"data: {json.dumps({'type': 'progress', 'stage': 'specialist', 'message': 'Executando query...'})}\n\n"
                            
                            # Enviar evento quando SQL é gerado
                            sql = node_state.get("sql")
                            if sql:
                                yield f"data: {json.dumps({'type': 'sql_generated', 'sql': sql})}\n\n"
            
            if not final_state:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Erro ao executar agente'})}\n\n"
                return
            
            # Se houve erro, enviar e terminar
            if final_state.get("error"):
                yield f"data: {json.dumps({'type': 'chunk', 'content': str(final_state.get('error'))})}\n\n"
                meta = {
                    "detected_language": final_state.get("detected_language"),
                    "chosen_table": final_state.get("chosen_table"),
                    "sql": final_state.get("sql"),
                    "num_rows": 0,
                    "error": str(final_state.get("error")),
                }
                yield f"data: {json.dumps({'type': 'meta', 'meta': meta, 'data_sample': []})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return
            
            # Se não há dados, enviar mensagem e terminar
            if not final_state.get("data"):
                yield f"data: {json.dumps({'type': 'chunk', 'content': 'No data was found for this query.'})}\n\n"
                meta = {
                    "detected_language": final_state.get("detected_language"),
                    "chosen_table": final_state.get("chosen_table"),
                    "sql": final_state.get("sql"),
                    "num_rows": 0,
                    "error": None,
                }
                yield f"data: {json.dumps({'type': 'meta', 'meta': meta, 'data_sample': []})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return
            
            # Agora fazer streaming da resposta do formatter
            yield f"data: {json.dumps({'type': 'progress', 'stage': 'formatter', 'message': 'Gerando resposta...'})}\n\n"
            
            question = final_state.get("question") or ""
            data = final_state.get("data") or []
            detected_language = final_state.get("detected_language")
            lang = _ensure_language(question, detected_language)
            
            data_sample = data[:15]
            serialized_sample = _serialize_for_json(data_sample)
            sample_json = json.dumps(serialized_sample, ensure_ascii=False, indent=2)
            stats_text = _compute_basic_stats(data_sample)
            
            system_msg = {
                "role": "system",
                "content": (
                    "You are a data analyst assistant.\n"
                    "Your job is to explain query results in clear natural language.\n\n"
                    "CRITICAL LANGUAGE REQUIREMENT:\n"
                    f"- The user question is in language code '{lang}'.\n"
                    "- You MUST answer in the same language as the question.\n"
                    "- Keep the answer SHORT and OBJECTIVE (maximum 4 sentences).\n"
                ),
            }
            
            user_msg = {
                "role": "user",
                "content": (
                    f"User question:\n{question}\n\n"
                    f"Total rows returned (not all shown): {len(data)}\n"
                    f"{stats_text}\n\n"
                    "Sample of the data (up to 15 rows, JSON):\n"
                    f"{sample_json}\n\n"
                    "Explain the main insight(s) from this data in a concise way, "
                    "in the same language as the user's question."
                ),
            }
            
            # Stream do LLM formatter
            accumulated_answer = ""
            try:
                for chunk in _stream_llm(llm_formatter, system_msg, user_msg):
                    accumulated_answer += chunk
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
            except Exception as e:
                # Fallback se streaming falhar
                fallback = "Error formatting the response with the AI. Data was queried successfully, but I could not generate a summary."
                yield f"data: {json.dumps({'type': 'chunk', 'content': fallback})}\n\n"
                accumulated_answer = fallback
            
            # Enviar metadados finais
            chosen_table = final_state.get("chosen_table")
            chosen_tables = final_state.get("chosen_tables")
            sql = final_state.get("sql")
            
            chosen_datasets = chosen_tables if chosen_tables else ([chosen_table] if chosen_table else [])
            
            meta = {
                "detected_language": lang,
                "chosen_table": chosen_table,
                "chosen_datasets": chosen_datasets if chosen_datasets else None,
                "sql": sql,
                "num_rows": len(data),
                "error": None,
            }
            
            yield f"data: {json.dumps({'type': 'meta', 'meta': meta, 'data_sample': data_sample})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
        except Exception as e:
            import traceback
            error_detail = str(e)
            yield f"data: {json.dumps({'type': 'error', 'message': error_detail})}\n\n"
            log_event(
                "api_query_connection_stream_error",
                {
                    "connection_id": connection_id,
                    "error": error_detail,
                },
            )
    
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


@router.post("/{connection_id}/query/stream")
async def query_connection_stream(
    connection_id: str,
    body: QueryRequest,
    db: Session = Depends(get_db),
):
    """
    Faz uma pergunta usando uma DataConnection com streaming de resposta.
    Retorna Server-Sent Events (SSE) com chunks de texto conforme são gerados.
    
    Formato dos eventos:
    - {"type": "chunk", "content": "texto..."} - pedaços da resposta
    - {"type": "meta", "meta": {...}, "data_sample": [...]} - metadados finais
    - {"type": "done"} - fim do stream
    - {"type": "error", "message": "..."} - erro ocorrido
    """
    if not body.space_id:
        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'message': 'space_id é obrigatório no body da requisição'})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")
    
    return StreamingResponse(
        _stream_connection_query(connection_id, body, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Desabilita buffering no nginx
        }
    )
