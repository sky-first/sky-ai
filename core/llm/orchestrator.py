# core/llm/orchestrator.py
from __future__ import annotations

from typing import List, Optional, Dict, Any
import re
from datetime import datetime

from sqlalchemy.orm import Session

from core.agents.generic_sql_agent import AgentState, AgentConfig, TableSchema
from core.i18n.i18n import detect_language
from core.logging_utils import log_event
from core.rag.user_profiler import get_user_table_profile, format_profile_for_prompt
from core.rag.context_retrieval import build_retrieval_context_for_question, build_retrieval_context_for_question_sync
from core.rag.embeddings import EmbeddingProvider
from core.llm.providers import LLMProvider
from core.sql.relationships import detect_relationships, find_join_path
from config.settings import settings


# ==================== ROLE-BASED REASONING ====================
# Role profiles define how the AI behaves based on user role

ROLE_PROFILES: Dict[str, Dict[str, Any]] = {
    # Platform roles (global level)
    "admin": {
        "label": "Administrator",
        "focus": ["revenue", "profit", "cost", "roi", "trend", "summary", "kpi"],
        "style": "Provide executive summaries with key financial metrics and strategic insights",
        "table_priority": ["invoices", "revenue", "sales", "payments", "customers"],
        "detail_level": "high_level",
    },
    "cfo": {
        "label": "CFO",
        "focus": ["reconciliation", "net settlement", "cash flow", "burn rate", "auditing"],
        "style": "Apply strict financial audit logic (Platinum Auditor). Focus on accuracy and net impact.",
        "table_priority": ["payments", "refunds", "credit_memos", "invoices"],
        "detail_level": "analytical_deep",
    },
    "user": {
        "label": "Standard User",
        "focus": [],
        "style": "Provide balanced, clear responses",
        "table_priority": [],
        "detail_level": "medium",
    },
    "viewer": {
        "label": "Viewer",
        "focus": ["overview", "summary"],
        "style": "Provide simplified overviews",
        "table_priority": [],
        "detail_level": "low",
    },
    # Crew roles (team level - takes precedence over platform roles)
    "commander": {
        "label": "Team Leader",
        "focus": ["performance", "team", "kpi", "comparison", "target", "growth"],
        "style": "Focus on team metrics, performance indicators, and management insights",
        "table_priority": [],
        "detail_level": "managerial",
    },
    "navigator": {
        "label": "Team Member",
        "focus": ["detail", "breakdown", "analysis", "drill-down", "specific"],
        "style": "Provide detailed analytical responses with actionable data",
        "table_priority": [],
        "detail_level": "detailed",
    },
    "explorer": {
        "label": "Basic User",
        "focus": ["simple", "overview", "basic"],
        "style": "Keep responses clear and straightforward",
        "table_priority": [],
        "detail_level": "simple",
    },
    "guest": {
        "label": "Guest",
        "focus": [],
        "style": "Provide minimal necessary information",
        "table_priority": [],
        "detail_level": "minimal",
    },
}


def _build_role_context(platform_role: str, crew_role: str, role_label: Optional[str] = None) -> str:
    """
    Build role-specific context for LLM prompt injection.
    
    Crew role takes precedence over platform role for behavior,
    but platform admin/cfo always gets financial priority.
    
    Args:
        platform_role: Platform-level role (admin/user/viewer/cfo)
        crew_role: Crew-level role (commander/navigator/explorer/guest)
        role_label: Specific override label (e.g. "CFO Logic")
        
    Returns:
        Role context string to inject into system prompt
    """
    # Get profiles (crew_role takes precedence for behavior)
    crew_profile = ROLE_PROFILES.get(crew_role, {})
    platform_profile = ROLE_PROFILES.get(platform_role, {})

    # Merge: crew_role behavior, but admin always gets table priority
    label = crew_profile.get("label") or platform_profile.get("label", "User")
    style = crew_profile.get("style") or platform_profile.get("style", "")

    # Admin always gets financial table priority
    priority = []
    if platform_role in ["admin", "cfo"]:
        priority = platform_profile.get("table_priority", [])

    # Build context block
    context_parts = [f"USER ROLE: {label}"]

    if style:
        context_parts.append(f"RESPONSE STYLE: {style}")

    if priority:
        context_parts.append(
            f"TABLE PRIORITY: When multiple tables could answer the question, "
            f"prefer tables related to: {', '.join(priority)}"
        )

    return "\n".join(context_parts)


def _build_tables_summary(tables: List[TableSchema]) -> str:
    """
    Gera um pequeno resumo dos logical tables pro LLM do orquestrador.
    """
    parts = []
    for t in tables:
        col_desc = ", ".join(
            f"{c.get('name')} ({c.get('type')})"
            if isinstance(c, dict)
            else f"{c.name} ({c.type})"
            for c in (t.columns or [])[:8]
        )
        desc_part = f" | description: {t.description}" if getattr(t, "description", None) else ""
        parts.append(
            f"- {t.logical_name} -> physical: {t.physical_name}{desc_part} | columns: {col_desc}"
        )
    return "\n".join(parts)


def _extract_table_choice(raw_llm_response, tables: List[TableSchema]) -> str:
    """
    Extrai o logical_name retornado pelo LLM.
    Se não bater exatamente, tenta match parcial; senão, volta o primeiro.
    """
    text = ""
    if isinstance(raw_llm_response, str):
        text = raw_llm_response
    else:
        # LangChain/OpenAI style: objeto com .content
        text = getattr(raw_llm_response, "content", "") or ""

    text = text.strip().lower()
    text = re.sub(r"[\"'`]", "", text)

    logical_names = [t.logical_name for t in tables]

    # fuzzy match: se o que o modelo respondeu (text) é parte de algum nome lógico
    # OU se algum nome lógico é parte do que o modelo respondeu
    for name in logical_names:
        lname = name.lower()
        if text and (text in lname or lname in text):
            return name

    # Check for IMPOSSIBLE
    if "impossible" in text:
        return "IMPOSSIBLE"

    # Fallback: do not return a random table. Return empty string to signal no match.
    return ""


def _extract_multiple_table_choices(
    raw_llm_response, tables: List[TableSchema]
) -> List[str]:
    """
    Extrai múltiplos logical_names retornados pelo LLM.
    Suporta formatos como: "table1, table2" ou "table1 and table2" ou lista separada por vírgulas.
    """
    text = ""
    if isinstance(raw_llm_response, str):
        text = raw_llm_response
    else:
        text = getattr(raw_llm_response, "content", "") or ""

    text = text.strip().lower()
    text = re.sub(r"[\"'`]", "", text)

    logical_names = [t.logical_name.lower() for t in tables]
    found_tables = []

    # Tentar separar por vírgula, "and", ou nova linha
    parts = re.split(r"[,;\n]|\sand\s", text)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Match exato
        for name in logical_names:
            if part == name:
                table_name = next(
                    t.logical_name for t in tables if t.logical_name.lower() == name
                )
                if table_name not in found_tables:
                    found_tables.append(table_name)
                break

        # Match parcial
        for name in logical_names:
            if name in part and name not in [t.lower() for t in found_tables]:
                table_name = next(
                    t.logical_name for t in tables if t.logical_name.lower() == name
                )
                if table_name not in found_tables:
                    found_tables.append(table_name)
                break

    return found_tables


# ==================== CATALOG (METADATA) MODE ====================

_CATALOG_LIST_PATTERNS = [
    r"\bwhat\s+(data|tables|datasets)\b",
    r"\bwhat\s+data\s+can\s+i\s+access\b",
    r"\bwhat\s+tables\s+do\s+i\s+have\s+access\s+to\b",
    r"\bwhat\s+can\s+i\s+see\b",
]

_CATALOG_COLUMNS_PATTERNS = [
    r"\bwhat\s+columns\b",
    r"\bcolumns?\s+in\b",
    r"\bshow\s+.*schema\b",
]

_CATALOG_CAPABILITIES_PATTERNS = [
    r"\bwhat\s+can\s+you\s+(do|answer)\b",
    r"\bwhat\s+are\s+you\s+able\s+to\s+answer\b",
]


def _looks_like_catalog_question(question: str) -> Optional[str]:
    """
    Retorna o intent de catálogo (metadata) ou None.
    intents:
      - catalog.list_access
      - catalog.describe_table
      - catalog.capabilities
    """
    q = (question or "").strip().lower()
    if not q:
        return None

    for pat in _CATALOG_CAPABILITIES_PATTERNS:
        if re.search(pat, q, flags=re.IGNORECASE):
            return "catalog.capabilities"

    for pat in _CATALOG_COLUMNS_PATTERNS:
        if re.search(pat, q, flags=re.IGNORECASE):
            return "catalog.describe_table"

    for pat in _CATALOG_LIST_PATTERNS:
        if re.search(pat, q, flags=re.IGNORECASE):
            return "catalog.list_access"

    return None


def _normalize_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _extract_table_name_from_question(
    question: str, tables: List[TableSchema]
) -> Optional[str]:
    """
    Tenta extrair o nome da tabela da pergunta, de forma robusta:
    - conteúdo entre aspas/backticks
    - padrões "de X" / "da tabela X" / "table X" / "columns in X"
    - fallback: match por substring com as tabelas disponíveis
    """
    q = (question or "").strip()
    q_norm = _normalize_name(q)
    available = [t.logical_name for t in tables]
    available_norm = {_normalize_name(t.logical_name): t.logical_name for t in tables}

    # 1) quoted/backticked
    m = re.search(r"[`\"']([^`\"']+)[`\"']", q)
    if m:
        candidate = _normalize_name(m.group(1))
        if candidate in available_norm:
            return available_norm[candidate]

    # 2) common patterns
    patterns = [
        r"(?:table)\s+([a-zA-Z0-9_\.]+)",
        r"(?:columns?\s+in)\s+([a-zA-Z0-9_\.]+)",
    ]
    for pat in patterns:
        m2 = re.search(pat, q_norm, flags=re.IGNORECASE)
        if m2:
            candidate = _normalize_name(m2.group(1))
            # match exact logical name
            if candidate in available_norm:
                return available_norm[candidate]
            # allow user to include physical/dataset prefix; match by suffix
            for norm_name, original in available_norm.items():
                if candidate.endswith(norm_name):
                    return original

    # 3) fallback substring match
    for logical in available:
        if _normalize_name(logical) in q_norm:
            return logical

    return None


def _format_catalog_list_access(tables: List[TableSchema], lang: str) -> str:
    # SECURITY: do not enumerate schema/tables from the orchestrator.
    # Keep chat focused on business questions and prevent schema abuse.
    return (
        "I can't help with that request. Please rephrase your question about your data."
    )


def _format_catalog_describe_table(table: TableSchema, lang: str) -> str:
    # SECURITY: do not enumerate columns from the orchestrator.
    return (
        "I can't help with that request. Please rephrase your question about your data."
    )


def _format_catalog_capabilities(lang: str) -> str:
    # SECURITY: keep responses focused on business outcomes, not schema exploration.
    # Domain agnostic: generic examples work for any business type.
    return "Tell me an analysis goal (e.g., monthly performance, top results, time-based analysis) and I will generate SQL."


def run_orchestrator(
    state: AgentState,
    agent_config: AgentConfig,
    llm: LLMProvider,
    db: Optional[Session] = None,
    embedding_provider: Optional[EmbeddingProvider] = None,
) -> AgentState:
    """
    Node de orquestração:
    - garante pergunta válida
    - detecta idioma
    - (opcional) chama RAG para montar retrieval_context se ainda não existir
    - escolhe UMA logical table com base em pergunta + contexto
    """
    question = (state.get("question") or "").strip()

    if not question:
        state["answer"] = "Question cannot be empty."
        log_event("orchestrator_empty_question", {})
        return state
    # 🧠 CONTEXT RECALL: Handle short follow-up confirmations
    # Handles: "yes", "sure", "show me" -> uses first suggestion
    # Handles: "1", "2", "3" -> uses the corresponding numbered suggestion
    last_suggestions = state.get("last_suggestions")
    if last_suggestions and len(question.split()) <= 4:
        q_lower = question.strip().lower()

        # Check for numeric selection (1, 2, 3)
        numeric_map = {"1": 0, "2": 1, "3": 2}
        if q_lower in numeric_map:
            idx = numeric_map[q_lower]
            if idx < len(last_suggestions):
                original_q = question
                question = last_suggestions[idx]
                state["question"] = question
                log_event(
                    "orchestrator_context_recall",
                    {
                        "original": original_q,
                        "replaced_with": question,
                        "reason": "numeric_selection",
                        "index": idx,
                    },
                )
        else:
            # ONLY English affirmations -> uses first suggestion
            affirmations = [
                "yes",
                "sure",
                "ok",
                "okay",
                "please",
                "confirm",
                "show me",
                "do it",
                "i want to see",
                "go ahead",
            ]

            is_affirmation = any(w == q_lower for w in affirmations) or (
                q_lower in affirmations
            )

            if is_affirmation:
                original_q = question
                question = last_suggestions[0]
                state["question"] = question
                log_event(
                    "orchestrator_context_recall",
                    {
                        "original": original_q,
                        "replaced_with": question,
                        "reason": "affirmation_match",
                    },
                )

    # 🔤 Detecção de idioma
    try:
        lang = detect_language(question)
    except Exception:
        lang = "en"
    state["detected_language"] = lang

    # 🔒 GATEKEEPER: English Only
    if not lang.startswith("en"):
        state["answer"] = (
            "I'm sorry, but I currently only understand English. "
            "Please rephrase your question in English so I can analyze your data accurately."
        )
        log_event(
            "orchestrator_booted_language",
            {"detected": lang, "question": question[:50]},
        )
        return state

    # 🔍 Garante que o agente tem tabelas configuradas
    if not agent_config.tables:
        state["answer"] = "No tables are configured for this agent."
        log_event("orchestrator_no_tables", {"agent_id": agent_config.id})
        return state

    # ✅ NOVA: Validação prévia da pergunta usando QuestionValidator
    try:
        from core.validation.question_validator import (
            QuestionValidator,
            ValidationSeverity,
        )

        # Preparar metadados para o validador
        available_tables_meta = [
            {
                "name": t.logical_name,
                "logical_name": t.logical_name,
                "columns": [
                    c.get("name") if isinstance(c, dict) else getattr(c, "name", "")
                    for c in (t.columns or [])
                ],
            }
            for t in agent_config.tables
        ]
        available_columns = {
            t.logical_name: [
                c.get("name") if isinstance(c, dict) else getattr(c, "name", "")
                for c in (t.columns or [])
            ]
            for t in agent_config.tables
        }

        validator = QuestionValidator(available_tables_meta, available_columns)
        validation_results = validator.validate_question(question)

        # Logar métricas de validação
        errors = [
            r for r in validation_results if r.severity == ValidationSeverity.ERROR
        ]
        warnings = [
            r for r in validation_results if r.severity == ValidationSeverity.WARNING
        ]

        infos = [r for r in validation_results if r.severity == ValidationSeverity.INFO]

        log_event(
            "orchestrator_validation_metrics",
            {
                "agent_id": agent_config.id,
                "question_length": len(question),
                "question_words": len(question.split()),
                "num_errors": len(errors),
                "num_warnings": len(warnings),
                "num_infos": len(infos),
                "error_codes": [e.code for e in errors],
                "warning_codes": [w.code for w in warnings],
                "info_codes": [i.code for i in infos],
                "was_blocked": len(errors) > 0,
            },
        )

        # Se houver erros críticos, retornar erro amigável
        critical_errors = errors
        if critical_errors:
            error_msg = critical_errors[0].message
            if critical_errors[0].suggestion:
                if lang.startswith("pt"):
                    error_msg += f"\n\n💡 Sugestão: {critical_errors[0].suggestion}"
                else:
                    error_msg += f"\n\n💡 Suggestion: {critical_errors[0].suggestion}"

            state["answer"] = error_msg
            state["error"] = critical_errors[0].code
            log_event(
                "orchestrator_validation_error",
                {
                    "agent_id": agent_config.id,
                    "question": question[:200],
                    "error_code": critical_errors[0].code,
                    "error_message": critical_errors[0].message,
                },
            )
            return state

        # Warnings podem ser logados mas não bloqueiam
        warnings = [
            r for r in validation_results if r.severity == ValidationSeverity.WARNING
        ]
        if warnings:
            log_event(
                "orchestrator_validation_warnings",
                {
                    "agent_id": agent_config.id,
                    "question": question[:200],
                    "warnings": [
                        {"code": w.code, "message": w.message} for w in warnings
                    ],
                },
            )

        # Infos são apenas informativos
        infos = [r for r in validation_results if r.severity == ValidationSeverity.INFO]
        if infos:
            log_event(
                "orchestrator_validation_info",
                {
                    "agent_id": agent_config.id,
                    "question": question[:200],
                    "infos": [{"code": i.code, "message": i.message} for i in infos],
                },
            )
    except Exception as e:
        # Se a validação falhar, não quebra o fluxo - apenas loga
        log_event(
            "orchestrator_validation_exception",
            {
                "agent_id": agent_config.id,
                "error": str(e)[:500],
            },
        )
        # Continua normalmente sem validação

    # ==================== CATALOG EARLY RETURN ====================
    # Para perguntas genéricas de dados ("quais dados eu posso ver?", "quais colunas tem na tabela X?",
    # "o que você pode responder?"), não faz sentido gerar SQL. Respondemos diretamente com base no
    # AgentConfig (que já deve estar filtrado por permissões no nível de API/factory).
    catalog_intent = _looks_like_catalog_question(question)
    if catalog_intent:
        if catalog_intent == "catalog.list_access":
            state["answer"] = _format_catalog_list_access(agent_config.tables, lang)
        elif catalog_intent == "catalog.describe_table":
            tname = _extract_table_name_from_question(question, agent_config.tables)
            if not tname:
                if lang.startswith("pt"):
                    state["answer"] = (
                        "Qual tabela você quer ver? Ex: `quais colunas tem dentro de [nome_da_tabela]?`"
                    )
                else:
                    state["answer"] = (
                        "Which table do you want to inspect? Example: `what columns are in [table_name]?`"
                    )
            else:
                table_obj = next(
                    (t for t in agent_config.tables if t.logical_name == tname), None
                )
                if not table_obj:
                    # fallback: listar tabelas
                    state["answer"] = _format_catalog_list_access(
                        agent_config.tables, lang
                    )
                else:
                    state["answer"] = _format_catalog_describe_table(table_obj, lang)
        elif catalog_intent == "catalog.capabilities":
            state["answer"] = _format_catalog_capabilities(lang)
        else:
            state["answer"] = _format_catalog_capabilities(lang)

        state["catalog_intent"] = catalog_intent
        log_event(
            "orchestrator_catalog_answer",
            {
                "agent_id": agent_config.id,
                "intent": catalog_intent,
                "lang": lang,
                "num_tables": len(agent_config.tables),
            },
        )
        return state

    # 📚 Opcional: se ainda não houver retrieval_context no state e tivermos db + embeddings,
    #               chama diretamente o RAG aqui.
    retrieval_context: List[str] = state.get("retrieval_context") or []

    if not retrieval_context and db is not None and embedding_provider is not None:
        try:
            space_id = state.get("space_id")
            crew_ids = state.get("crew_ids") or []

            if space_id:
                connection_id = None
                if agent_config.tables:
                    connection_id = agent_config.tables[0].data_connection_id
                
                retrieval_context = build_retrieval_context_for_question_sync(
                    db=db,
                    embedding_provider=embedding_provider,
                    space_id=space_id,
                    crew_ids=crew_ids,
                    question=question,
                    top_k=15,
                    connection_id=connection_id,
                )
                state["retrieval_context"] = retrieval_context
                log_event(
                    "orchestrator_rag_context_built",
                    {
                        "agent_id": agent_config.id,
                        "space_id": space_id,
                        "num_chunks": len(retrieval_context),
                    },
                )
        except Exception as e:
            # Se der erro no RAG, não quebra o fluxo de orquestração
            log_event(
                "orchestrator_rag_error",
                {
                    "agent_id": agent_config.id,
                    "error": str(e)[:500],
                },
            )
            # ✅ Fazer rollback se transação falhar para evitar "InFailedSqlTransaction"
            try:
                if db is not None:
                    db.rollback()
            except Exception:
                pass
            retrieval_context = []

    # 🔒 SECURITY FIX: Intersect frontend selection with authorized tables
    # This allows users to narrow scope (intent) without accessing unauthorized data.
    selected_datasets = state.get("selected_datasets")

    if selected_datasets:
        # Create lookups for authorized tables (support both logical and physical names)
        # We use a case-insensitive match for robustness if needed, but strict for now
        authorized_map = {t.physical_name: t for t in agent_config.tables}
        authorized_map.update({t.logical_name: t for t in agent_config.tables})

        valid_selection = []
        # Filter agent_config.tables to only include what the user selected
        # BUT only if it is in the authorized list.
        unique_selected_names = set()

        for name in selected_datasets:
            if name in authorized_map:
                table_obj = authorized_map[name]
                if table_obj.logical_name not in unique_selected_names:
                    valid_selection.append(table_obj)
                    unique_selected_names.add(table_obj.logical_name)

        if valid_selection:
            # ✅ REFACTOR (Non-destructive): Instead of deleting other tables,
            # we store the preferred ones and pass them as context to the LLM.
            # This prevents session/dashboard context from blocking necessary tables.
            state["preferred_tables"] = [t.logical_name for t in valid_selection]
            log_event(
                "orchestrator_frontend_selection_noted",
                {
                    "agent_id": agent_config.id,
                    "original_count": len(authorized_map) // 2,
                    "selected_requested": selected_datasets,
                    "selected_applied": state["preferred_tables"],
                },
            )
        else:
            log_event(
                "orchestrator_frontend_selection_invalid",
                {
                    "agent_id": agent_config.id,
                    "reason": "No selected tables were found in authorized list",
                    "selected_requested": selected_datasets,
                    "authorized_tables": [t.logical_name for t in agent_config.tables],
                },
            )

    # 🎯 Otimização Legada: Se há apenas 1 tabela disponível, no modo Agentic RAG 
    # queremos que o agente PENSE antes, pois ele pode precisar de outros contextos.
    # Só fazemos o auto-select se o Agentic RAG não estiver disponível.
    chat_model = getattr(llm, "_chat", None)
    can_use_agentic = chat_model is not None and hasattr(chat_model, "bind_tools")

    if not can_use_agentic and len(agent_config.tables) == 1:
        table = agent_config.tables[0]
        state["chosen_table"] = table.logical_name
        state["chosen_table_physical"] = table.physical_name
        state["chosen_tables"] = [table.logical_name]
        state["chosen_tables_physical"] = [table.physical_name]

        log_event(
            "orchestrator_auto_selected_single_table",
            {
                "agent_id": agent_config.id,
                "chosen_logical": table.logical_name,
                "reason": "Legacy auto-select (Single Table)",
            },
        )
        return state 


    # 🎯 NEW: Build Context Bundle (if enabled)
    use_context_bundle = getattr(settings, "use_context_bundle", False)

    if use_context_bundle:
        try:
            from core.llm.context.builder import build_context_bundle

            context_bundle = build_context_bundle(
                state=state, agent_config=agent_config, db=db
            )
            state["_context_bundle"] = context_bundle  # Store for reuse by specialist

            log_event(
                "orchestrator_context_bundle_built",
                {
                    "agent_id": agent_config.id,
                    "bundle_summary": context_bundle.summary(),
                },
            )
        except Exception as e:
            log_event(
                "orchestrator_context_bundle_error",
                {"agent_id": agent_config.id, "error": str(e)[:300]},
            )
            use_context_bundle = False  # Fallback to legacy

    tables_summary = _build_tables_summary(agent_config.tables)

    # 🔗 Monta bloco de contexto (limitando pra não explodir o prompt)
    context_block = ""

    # NEW: Chat History Context
    chat_history = state.get("chat_history") or []
    if chat_history:
        # Limit to last 6 messages to save tokens
        recent_history = chat_history[-6:]
        history_str = "\n".join(
            [f"{msg['role'].upper()}: {msg['content']}" for msg in recent_history]
        )
        context_block += (
            f"\n\nPREVIOUS CONVERSATION HISTORY:\n{history_str}\n"
            "Use this history to understand references like 'it', 'previous', 'add filter', etc.\n"
        )

    if retrieval_context:
        joined = "\n\n".join(retrieval_context[:5])
        context_block += (
            "\n\nADDITIONAL CONTEXT (from metadata/docs/query history):\n"
            f"{joined}\n"
        )

    # Detectar relacionamentos entre tabelas
    # NEW: Pass explicit relationships from state (loaded from backend)
    explicit_rels = state.get("explicit_relationships") or []
    relationships = detect_relationships(agent_config.tables, explicit_relationships=explicit_rels)

    # Obter instruções personalizadas do estado
    instructions = state.get("instructions")
    instructions_block = ""
    if instructions:
        instructions_block = f"\n\nADDITIONAL INSTRUCTIONS:\n{instructions}\n"

    # 🎭 ROLE-BASED REASONING: Build context based on user role
    platform_role = state.get("platform_role", "user")
    crew_role = state.get("crew_role", "guest")
    role_label = state.get("role_label")
    role_context = _build_role_context(platform_role, crew_role, role_label)
    role_context_block = ""
    if role_context:
        role_context_block = f"\n\n{role_context}\n"

    log_event(
        "orchestrator_role_context",
        {
            "agent_id": agent_config.id,
            "platform_role": platform_role,
            "crew_role": crew_role,
            "has_role_context": bool(role_context),
        },
    )

    # 📊 USER PREFERENCE PROFILE: Load user's table usage history
    user_profile_block = ""
    if db is not None and state.get("user_id"):
        try:
            user_profile = get_user_table_profile(
                db=db,
                user_id=state.get("user_id"),
                space_id=state.get("space_id"),
                days=30,
                limit=5,
            )
            if user_profile:
                user_profile_block = format_profile_for_prompt(user_profile)
                log_event(
                    "orchestrator_user_profile_loaded",
                    {
                        "agent_id": agent_config.id,
                        "user_id": state.get("user_id"),
                        "profile": user_profile,
                    },
                )
        except Exception as e:
            log_event(
                "orchestrator_user_profile_error",
                {"agent_id": agent_config.id, "error": str(e)[:200]},
            )

    # Construir informações sobre relacionamentos disponíveis para o LLM
    relationships_info = ""
    if relationships and len(agent_config.tables) > 1:
        rel_summary = []
        for rel in relationships[:10]:  # Limitar para não explodir o prompt
            rel_summary.append(
                f"- {rel.from_table}.{rel.from_column} -> {rel.to_table}.{rel.to_column}"
            )
        if rel_summary:
            relationships_info = (
                "\n\nAVAILABLE TABLE RELATIONSHIPS (for JOINs):\n"
                + "\n".join(rel_summary)
                + "\n- You can use these relationships to join tables when needed.\n"
            )

    # ✅ REFACTOR: Build preferred tables hint if available
    preferred_tables_hint = ""
    preferred_tables = state.get("preferred_tables")
    if preferred_tables:
        preferred_tables_hint = (
            "\n\nUSER FOCUS TIPS:\n"
            f"- The user is currently focusing on these tables: {', '.join(preferred_tables)}\n"
            "- Favor these tables if they can answer the question, but feel free to include "
            "OTHER tables from the catalog below if they are necessary for a complete or better answer.\n"
        )

    # SEMPRE permitir múltiplas tabelas - deixar o LLM decidir baseado no contexto
    # Isso melhora a capacidade de responder perguntas complexas que precisam de JOINs
    chat_model = getattr(llm, "_chat", None)
    use_agentic_rag = chat_model is not None and hasattr(chat_model, "bind_tools")

    if use_agentic_rag:
        try:
            from langgraph.prebuilt import create_react_agent
            from core.llm.tools import ToolFactory
            from langchain_core.messages import HumanMessage
            
            # Instanciar as ferramentas
            tools = [
                ToolFactory.create_metadata_tool(agent_config),
                ToolFactory.create_strategy_tool(db, embedding_provider, state.get("space_id", ""), state.get("crew_ids", [])),
                ToolFactory.create_signals_tool(db, embedding_provider, state.get("space_id", ""), state.get("crew_ids", []))
            ]
            
            # A "Regra de Ouro" rigorosa (System Prompt Agentic)
            agentic_system_msg = (
                f"{role_context_block}"
                f"{user_profile_block}"
                "You are a Senior Data Analyst Orchestrator. Your primary job is to choose ONE OR MORE logical tables from the database to answer the user's question.\n\n"
                "🛡️ THE GOLDEN RULES:\n"
                "1. Your ONLY source of truth for the database structure is the 'search_database_metadata' tool.\n"
                "2. It is STRICTLY FORBIDDEN to assume column names or table existence without consulting the metadata tool first, even if you think you know the name (e.g., do not assume 'sales', verify if it's 'fct_sales').\n"
                "3. Use the 'search_corporate_strategy' tool ONLY if the user asks about business goals, targets, OKRs, or long-term strategy.\n"
                "4. Use the 'search_market_signals' tool ONLY if the user asks about anomalies, market events, news, or sudden drops/spikes.\n"
                "5. THINK OUT LOUD (Chain of Thought): Explain your reasoning step-by-step before outputting the final tables.\n"
                "6. QUESTION SCOPE — before selecting tables, classify the question:\n"
                "   a) If the question has NOTHING to do with business data (weather, jokes, math, IT support, etc.) → respond ONLY with: OUT_OF_SCOPE\n"
                "   b) If the question IS business-related but after checking the metadata no available table can answer it, AND you need a specific parameter from the user to proceed → respond ONLY with: CLARIFY: <one specific, concise question to ask the user>\n"
                "   c) If the question is vague but you can attempt an answer with the available data (e.g. 'how are we doing?' → use revenue/orders tables) → select the tables and proceed normally.\n\n"
                "FINAL OUTPUT FORMAT:\n"
                "After thinking and using the tools, finish your response with ONLY ONE of:\n"
                "  - The logical table name(s) separated by commas (e.g. 'table1, table2')\n"
                "  - OUT_OF_SCOPE\n"
                "  - CLARIFY: <your question>\n\n"
                f"{preferred_tables_hint}\n"
                f"Conversation Handling: Infer missing contexts from PREVIOUS CONVERSATION.\n"
                f"{relationships_info}"
                f"{instructions_block}"
            )
            
            user_prompt = (
                f"User question:\n{question}\n\n"
                f"{context_block}\n"
                "Remember: Use your tools to investigate, think step-by-step, and end your response with the logical table name(s) needed."
            )
            
            # Loop Agentic (ReAct)
            react_agent = create_react_agent(chat_model, tools=tools, state_modifier=agentic_system_msg)
            result = react_agent.invoke({"messages": [HumanMessage(content=user_prompt)]})
            final_msg_content = result["messages"][-1].content
            
            # Salvar o rationale (Chain of Thought) no state para streaming futuro
            state["plan"] = final_msg_content

            # ── Scope & Clarify detection ──────────────────────────────────
            if re.search(r'\bOUT_OF_SCOPE\b', final_msg_content, re.IGNORECASE):
                state["answer"] = (
                    "I'm designed to answer questions about your business data. "
                    "That question doesn't seem related to your data. "
                    "Feel free to ask me about your orders, customers, revenue, products, or other business metrics!"
                )
                log_event("orchestrator_out_of_scope", {"question": question[:100]})
                return state

            clarify_match = re.search(
                r'CLARIFY:\s*(.+?)(?:\n\n|\Z)', final_msg_content, re.IGNORECASE | re.DOTALL
            )
            if clarify_match:
                clarification = clarify_match.group(1).strip()
                state["answer"] = clarification
                log_event("orchestrator_clarify", {"question": question[:100], "clarification": clarification[:200]})
                return state
            # ──────────────────────────────────────────────────────────────

            # Criar um mock para manter compatibilidade com o parser legado _extract_table_choice
            class RawResponseMimic:
                def __init__(self, content):
                    self.content = content
            raw = RawResponseMimic(content=final_msg_content)

            log_event("orchestrator_agentic_rag_success", {"agent_id": agent_config.id})

            
        except Exception as e:
            state["answer"] = "Error consulting the AI orchestrator (Agentic Loop). Please try again later."
            state["error"] = str(e)
            log_event("orchestrator_agentic_llm_error", {"agent_id": agent_config.id, "error": str(e)[:500]})
            return state

    else:
        # Fallback Legacy (RAG Estático / Ollama local sem tools suporte)
        if len(agent_config.tables) > 1:
            system_msg = {
                "role": "system",
                "content": (
                    f"{role_context_block}"
                    f"{user_profile_block}"
                    "You are a routing assistant. Your job is to choose ONE OR MORE logical tables "
                    "from the list to answer the user's question.\n\n"
                    f"Rules:\n"
                    f"- You can choose ONE or MULTIPLE logical table names from the list.\n"
                    f"- Answer with ONLY the logical table name(s), separated by commas if multiple.\n"
                    f"{preferred_tables_hint}\n"
                    f"{relationships_info}"
                    f"{instructions_block}"
                ),
            }

            user_msg = {
                "role": "user",
                "content": (
                    f"User question:\n{question}\n\n"
                    f"Available tables:\n{tables_summary}"
                    f"{context_block}"
                    f"{relationships_info}"
                    "\nRespond with the logical table name(s) needed, separated by commas if multiple."
                ),
            }
        else:
            system_msg = {
                "role": "system",
                "content": (
                    f"{role_context_block}"
                    "You are a routing assistant. Your job is to choose the logical table.\n\n"
                    "Rules:\n- Answer with ONLY the logical table name, nothing else.\n"
                ),
            }

            user_msg = {
                "role": "user",
                "content": (
                    f"User question:\n{question}\n\n"
                    f"Available tables:\n{tables_summary}"
                    f"{context_block}\n\n"
                    "Respond with ONLY the logical table name."
                ),
            }

        try:
            raw = llm.invoke([system_msg, user_msg])
            print(f"DEBUG ORCHESTRATOR LEGACY RAW: {raw.content if hasattr(raw, 'content') else raw}")
        except Exception as e:
            state["answer"] = "Error consulting the AI orchestrator. Please try again later."
            state["error"] = str(e)
            log_event("orchestrator_llm_error", {"agent_id": agent_config.id, "error": str(e)[:500]})
            return state

    # Extrair escolha(s) de tabela(s)
    # Sempre tentar extrair múltiplas tabelas quando há mais de uma disponível
    if len(agent_config.tables) > 1:
        # Tentar extrair múltiplas tabelas primeiro
        chosen_logicals = _extract_multiple_table_choices(raw, agent_config.tables)

        # Se encontrou múltiplas tabelas, tentar usar modo JOIN
        if len(chosen_logicals) > 1:
            # Encontrar caminho de JOIN
            join_path = find_join_path(chosen_logicals, relationships)

            if join_path:
                # Caminho de JOIN encontrado - usar múltiplas tabelas com JOINs
                state["chosen_tables"] = chosen_logicals
                state["chosen_tables_physical"] = [
                    next(
                        (
                            t.physical_name
                            for t in agent_config.tables
                            if t.logical_name == name
                        ),
                        name,
                    )
                    for name in chosen_logicals
                ]
                state["join_relationships"] = [
                    {
                        "from_table": rel.from_table,
                        "from_column": rel.from_column,
                        "to_table": rel.to_table,
                        "to_column": rel.to_column,
                    }
                    for rel in join_path
                ]

                # Manter compatibilidade com código antigo
                state["chosen_table"] = chosen_logicals[0]
                state["chosen_table_physical"] = next(
                    (
                        t.physical_name
                        for t in agent_config.tables
                        if t.logical_name == chosen_logicals[0]
                    ),
                    chosen_logicals[0]
                )

                log_event(
                    "orchestrator_choice_multiple_with_joins",
                    {
                        "agent_id": agent_config.id,
                        "question": question[:200],
                        "chosen_tables": chosen_logicals,
                        "join_path_length": len(join_path),
                        "join_relationships": [
                            f"{r.from_table}.{r.from_column} -> {r.to_table}.{r.to_column}"
                            for r in join_path
                        ],
                        "detected_language": lang,
                    },
                )
            else:
                # Não encontrou caminho de JOIN explícito, mas ainda pode tentar usar múltiplas tabelas
                # O specialist pode tentar gerar JOINs mesmo sem caminho explícito
                state["chosen_tables"] = chosen_logicals
                state["chosen_tables_physical"] = [
                    next(
                        (
                            t.physical_name
                            for t in agent_config.tables
                            if t.logical_name == name
                        ),
                        name,
                    )
                    for name in chosen_logicals
                ]
                # Não definir join_relationships - deixar o specialist tentar inferir
                state["join_relationships"] = None

                # Manter compatibilidade
                state["chosen_table"] = chosen_logicals[0]
                state["chosen_table_physical"] = next(
                    (
                        t.physical_name
                        for t in agent_config.tables
                        if t.logical_name == chosen_logicals[0]
                    ),
                    chosen_logicals[0]
                )

                log_event(
                    "orchestrator_choice_multiple_no_explicit_path",
                    {
                        "agent_id": agent_config.id,
                        "question": question[:200],
                        "chosen_tables": chosen_logicals,
                        "available_relationships": len(relationships),
                        "note": "Specialist will attempt to generate JOINs based on column names",
                        "detected_language": lang,
                    },
                )
        elif len(chosen_logicals) == 1:
            # ✅ FIX: Handle single table choice when multiple are available
            chosen_logical = chosen_logicals[0]
            chosen_table_obj = next(
                (t for t in agent_config.tables if t.logical_name == chosen_logical),
                agent_config.tables[0],
            )



            # For compatibility with specialist multi-table path
            state["chosen_tables"] = [chosen_table_obj.logical_name]
            state["chosen_tables_physical"] = [chosen_table_obj.physical_name]



        # Multi-connection check on chosen logicals
        # Even if no JOIN path is found, we might be in a multi-source scenario (e.g. Car vs House)
        # This runs for all cases where len(chosen_logicals) > 1
        chosen_schemas_chk = []
        for name in chosen_logicals:
            t = next(
                (tbl for tbl in agent_config.tables if tbl.logical_name == name), None
            )
            if t:
                chosen_schemas_chk.append(t)

        # Check distinct connections
        connection_ids = set()
        for t in chosen_schemas_chk:
            conn_id = getattr(t, "data_connection_id", "default")
            connection_ids.add(conn_id)

        is_multi_source = len(connection_ids) > 1

        # Populate new fields
        state["is_multi_source"] = is_multi_source
        if is_multi_source:
            state["plan"] = (
                f"Query {len(chosen_schemas_chk)} tables across {len(connection_ids)} connections: {chosen_logicals}"
            )

        log_event(
            "orchestrator_choice_multiple_check",
            {
                "agent_id": agent_config.id,
                "chosen_tables": chosen_logicals,
                "is_multi_source": is_multi_source,
                "num_connections": len(connection_ids),
            },
        )

    else:
        # Modo tabela única (quando há apenas uma tabela disponível)
        chosen_logical = _extract_table_choice(raw, agent_config.tables)

        if not chosen_logical:
            state["impossible_reason"] = (
                "I couldn't find any relevant tables to answer your question."
            )
            log_event("orchestrator_choice_impossible", {"question": question})
            return state

        if chosen_logical == "IMPOSSIBLE":
            content_clean = raw.content if hasattr(raw, "content") else str(raw)
            reason = re.sub(
                r"^\s*IMPOSSIBLE:?\s*", "", content_clean, flags=re.IGNORECASE
            ).strip()
            state["impossible_reason"] = (
                reason or "I don't have enough data to answer this question."
            )

            return state

        chosen_table_obj = next(
            (t for t in agent_config.tables if t.logical_name == chosen_logical),
            None,
        )

        if not chosen_table_obj:
            state["impossible_reason"] = "The selected table is not available."
            return state

        state["chosen_table"] = chosen_table_obj.logical_name
        state["chosen_table_physical"] = chosen_table_obj.physical_name

        log_event(
            "orchestrator_choice_single",
            {
                "agent_id": agent_config.id,
                "question": question[:200],
                "chosen_logical": chosen_table_obj.logical_name,
                "chosen_physical": chosen_table_obj.physical_name,
                "detected_language": lang,
            },
        )

    return state
