# core/llm/specialist.py
from __future__ import annotations

import re
from typing import List, Optional, Dict, Any

from core.agents.generic_sql_agent import AgentState, AgentConfig, TableSchema
from core.data_sources.base import BaseDataSource
from core.llm.providers import LLMProvider
from core.sql.validator import ensure_safe_select
from core.sql.validator_advanced import AdvancedSQLValidator
from core.logging_utils import log_event

# Import security config functions
from core.security.security_config import (
    SecurityConfig,
    get_default_security_config,
    filter_columns_by_security,
    inject_row_filters_in_sql,
    validate_sql_against_security,
    build_security_prompt_instructions,
)


# ==================== HELPERS ====================

def _build_secure_system_prompt(
    physical_names: List[str],
    use_multiple_tables: bool,
    max_limit: int = 100,
    max_columns: int = 10
) -> dict:
    """
    Constrói system prompt com regras de segurança explícitas.
    """
    
    security_rules = (
        "⚠️ CRITICAL SECURITY RULES - YOU MUST FOLLOW ALL (NON-NEGOTIABLE):\n\n"
        "🔴 MANDATORY - YOUR QUERY WILL BE REJECTED IF YOU VIOLATE THESE:\n"
        "1. ALWAYS end your query with LIMIT {max_limit} - THIS IS REQUIRED, even for GROUP BY queries\n"
        "   Example: SELECT year, SUM(amount) FROM data_table GROUP BY year ORDER BY year LIMIT {max_limit}\n"
        "2. NEVER use SELECT * - always specify columns explicitly (max {max_columns} columns)\n"
        "3. NEVER use UNION, UNION ALL, or any UNION variant\n"
        "4. NEVER use ; (semicolon) except at the very end - only one query\n"
        "5. NEVER use comments -- or /* */\n"
        "6. NEVER use INFORMATION_SCHEMA, pg_catalog, sys, mysql, or system tables\n"
        "7. NEVER use DROP, DELETE, UPDATE, INSERT, ALTER, CREATE, TRUNCATE\n"
        "8. NEVER use subqueries that access unauthorized tables\n"
        "9. NEVER use functions like pg_read_file, exec, system, etc.\n\n"
        "⚠️ REMEMBER: Your SQL MUST end with 'LIMIT {max_limit}' or it will be automatically rejected!\n"
        "If you cannot follow these rules, respond: IMPOSSIBLE: <reason>\n\n"
    ).format(max_limit=max_limit, max_columns=max_columns)
    
    if use_multiple_tables:
        return {
            "role": "system",
            "content": (
                "You are a SQL expert. Your job is to generate a single SELECT query "
                "with JOINs to answer the user's question.\n\n"
                f"{security_rules}"
                f"Allowed physical table names: {', '.join(physical_names)}\n"
                f"Main table (FROM): {physical_names[0]}\n"
                "Use ONLY existing columns from the schemas provided.\n"
                "Generate only the SQL query (or IMPOSSIBLE: <reason>)."
            )
        }
    else:
        return {
            "role": "system",
            "content": (
                "You are a SQL expert. Your job is to generate a single SELECT query "
                "to answer the user's question.\n\n"
                f"{security_rules}"
                f"The only allowed physical table name is: {physical_names[0]}\n"
                "Use ONLY existing columns from the schema provided.\n"
                "Generate only the SQL query (or IMPOSSIBLE: <reason>)."
            )
        }


def _filter_table_schema_by_security(
    table: TableSchema,
    security_config: Optional[SecurityConfig]
) -> TableSchema:
    """
    Filtra as colunas de uma tabela baseado nas regras de segurança.
    Retorna uma cópia da tabela com apenas as colunas permitidas.
    """
    if not security_config:
        return table
    
    if not getattr(table, "columns", None):
        return table
    
    filtered_columns = filter_columns_by_security(
        columns=table.columns,
        table_name=table.logical_name,
        security_config=security_config
    )
    
    # Criar nova TableSchema com colunas filtradas
    return TableSchema(
        logical_name=table.logical_name,
        physical_name=table.physical_name,
        columns=filtered_columns,
        description=getattr(table, "description", None),
    )


def _build_schema_text(table: TableSchema, security_config: Optional[SecurityConfig] = None) -> str:
    """
    Gera um texto legível do schema da tabela para o LLM.
    Usa logical_name só como rótulo, mas força o uso de physical_name.
    
    Se security_config for fornecido, filtra as colunas antes de gerar o texto.
    """
    # Filtrar colunas se security_config foi fornecido
    if security_config:
        table = _filter_table_schema_by_security(table, security_config)
    
    lines: List[str] = []
    lines.append(f"Logical table: {table.logical_name}")
    lines.append(f"Physical table: {table.physical_name}")

    if getattr(table, "description", None):
        lines.append(f"Description: {table.description}")

    if getattr(table, "columns", None):
        lines.append("Columns:")
        for col in table.columns:
            # Suporta tanto dict quanto objeto com atributos
            if isinstance(col, dict):
                col_name = col.get("name", "")
                col_type = col.get("type", "")
                col_nullable = col.get("nullable", col.get("is_nullable", True))
                col_description = col.get("description", "")
                col_is_pk = col.get("is_primary_key", False)
                col_is_fk = col.get("is_foreign_key", False)
            else:
                col_name = col.name
                col_type = col.type
                col_nullable = getattr(col, "is_nullable", getattr(col, "nullable", True))
                col_description = getattr(col, "description", "") or ""
                col_is_pk = getattr(col, "is_primary_key", False)
                col_is_fk = getattr(col, "is_foreign_key", False)
            
            nullable = "NULLABLE" if col_nullable else "NOT NULL"
            extra = []
            if col_is_pk:
                extra.append("PK")
            if col_is_fk:
                extra.append("FK")
            extras_str = f" [{' | '.join(extra)}]" if extra else ""
            if col_description:
                lines.append(
                    f"  - {col_name} ({col_type}, {nullable}){extras_str} – {col_description}"
                )
            else:
                lines.append(
                    f"  - {col_name} ({col_type}, {nullable}){extras_str}"
                )

    return "\n".join(lines)


def _build_multiple_schemas_text(
    tables: List[TableSchema],
    join_info: Optional[List[Dict[str, str]]] = None,
    security_config: Optional[SecurityConfig] = None
) -> str:
    """
    Gera texto legível para múltiplas tabelas com informações de JOIN.
    
    Se security_config for fornecido, filtra as colunas de cada tabela.
    """
    lines: List[str] = []
    lines.append("=== TABLES TO JOIN ===\n")
    
    for table in tables:
        lines.append(_build_schema_text(table, security_config))
        lines.append("")  # linha em branco entre tabelas
    
    if join_info:
        lines.append("=== JOIN RELATIONSHIPS ===\n")
        for rel in join_info:
            lines.append(
                f"{rel['from_table']}.{rel['from_column']} -> {rel['to_table']}.{rel['to_column']}"
            )
        lines.append("\nUse these relationships to create JOIN clauses in your SQL query.")
    
    return "\n".join(lines)


def _strip_sql_fences(text: str) -> str:
    """
    Remove blocos ```sql ... ``` ou ``` ... ``` da resposta do modelo.
    """
    text = text.strip()
    # remove ```sql ... ```
    text = re.sub(r"```sql\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```", "", text)
    return text.strip()


def _parse_specialist_output(raw, table: TableSchema) -> str:
    """
    Extrai o SQL da resposta do LLM, cuidando de casos como:
    - resposta vem em objeto com .content
    - vem com bloco ```sql
    - vem com prefixos/explicações
    """
    if hasattr(raw, "content"):
        text = raw.content or ""
    else:
        text = str(raw or "")

    if not text or not text.strip():
        return ""

    text = _strip_sql_fences(text)

    # Remover linhas vazias do início
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    # Estratégia 1: Procurar por linha que começa com SELECT (case-insensitive)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^\s*select\b", stripped, flags=re.IGNORECASE):
            # Encontrou SELECT, retornar daqui até o fim
            result = "\n".join(lines[i:]).strip()
            # Remover trailing semicolon se existir (pode ter sido adicionado)
            if result.endswith(";"):
                result = result[:-1].strip()
            return result
    
    # Estratégia 2: Procurar por qualquer linha que contenha SELECT como palavra completa
    for i, line in enumerate(lines):
        if re.search(r"\bselect\b", line, flags=re.IGNORECASE):
            result = "\n".join(lines[i:]).strip()
            if result.endswith(";"):
                result = result[:-1].strip()
            return result
    
    # Estratégia 3: Se o texto inteiro parece SQL (contém palavras-chave SQL comuns)
    sql_keywords = ["from", "where", "group by", "order by", "limit", "join", "inner", "left", "right"]
    has_sql_keywords = any(re.search(rf"\b{kw}\b", text, flags=re.IGNORECASE) for kw in sql_keywords)
    
    if has_sql_keywords:
        # Pode ser SQL sem SELECT explícito ou em formato diferente
        result = text.strip()
        if result.endswith(";"):
            result = result[:-1].strip()
        return result

    # Fallback: retornar tudo se tiver mais de 10 caracteres (provavelmente não é apenas texto explicativo)
    result = text.strip()
    if len(result) > 10:
        if result.endswith(";"):
            result = result[:-1].strip()
        return result
    
    return ""


# ==================== SPECIALIST NODE ====================

def run_specialist(
    state: AgentState,
    agent_config: AgentConfig,
    data_source: BaseDataSource,
    llm: LLMProvider,
) -> AgentState:
    """
    Node especialista:
    - recebe a tabela escolhida pelo orchestrator (logical + physical)
    - usa schema + retrieval_context (RAG) + pergunta
    - pede ao LLM um único SELECT
    - valida segurança do SQL
    - executa via data_source
    - preenche state["sql"], state["data"] (ou state["impossible_reason"])
    """
    question = (state.get("question") or "").strip()
    
    # Log de entrada PRIMEIRO para debug
    log_event(
        "specialist_entered",
        {
            "agent_id": agent_config.id,
            "question": question[:200],
            "has_answer_in_state": bool(state.get("answer")),
            "answer_preview": (state.get("answer") or "")[:100],
            "has_chosen_table": bool(state.get("chosen_table")),
            "has_chosen_tables": bool(state.get("chosen_tables")),
            "state_keys": list(state.keys())[:20],
        },
    )
    
    # Obter security_config do state (enviado pelo backend via request)
    security_config: Optional[SecurityConfig] = state.get("security_config")
    if not security_config:
        # Usar configuração padrão se não foi enviada
        security_config = get_default_security_config()

    # Se o orchestrator já respondeu (ex: modo catálogo/metadata), não gerar SQL.
    if state.get("answer"):
        log_event(
            "specialist_skipped_due_to_preanswered_state",
            {
                "agent_id": agent_config.id,
                "question": question[:200],
                "answer": state.get("answer")[:200],
            },
        )
        return state
    
    # Verificar se há múltiplas tabelas (modo JOIN)
    chosen_tables_logical = state.get("chosen_tables")
    chosen_tables_physical = state.get("chosen_tables_physical")
    join_relationships = state.get("join_relationships")
    
    # Fallback para modo tabela única (compatibilidade)
    chosen_logical = state.get("chosen_table")
    chosen_physical = state.get("chosen_table_physical")
    
    # Log de entrada para debug
    log_event(
        "specialist_start",
        {
            "agent_id": agent_config.id,
            "question": question[:200],
            "chosen_tables_logical": chosen_tables_logical,
            "chosen_tables_physical": chosen_tables_physical,
            "chosen_logical": chosen_logical,
            "chosen_physical": chosen_physical,
            "has_answer": bool(state.get("answer")),
        },
    )
    
    # Determinar modo: múltiplas tabelas ou tabela única
    # Agora permite múltiplas tabelas mesmo sem join_relationships explícitos
    # O LLM pode tentar inferir JOINs baseado nos nomes das colunas
    use_multiple_tables = (
        chosen_tables_logical and 
        len(chosen_tables_logical) > 1
    )
    
    log_event(
        "specialist_mode_determined",
        {
            "agent_id": agent_config.id,
            "use_multiple_tables": use_multiple_tables,
            "num_chosen_tables": len(chosen_tables_logical) if chosen_tables_logical else 0,
        },
    )
    
    # Detectar se a pergunta requer agregação/temporal (antes de determinar modo)
    requires_aggregation = any(term in question.lower() for term in [
        "performance", "desempenho", "métrica", "total", "soma", "média", "média", 
        "contagem", "count", "sum", "avg", "máximo", "mínimo", "max", "min",
        "mensal", "monthly", "anual", "yearly", "diário", "daily", "por mês", "por ano",
        "distribuição", "distribution", "agrupar", "group", "agrupado", "grouped"
    ])
    
    if use_multiple_tables:
        # Modo JOIN: múltiplas tabelas
        tables = [
            next((t for t in agent_config.tables if t.logical_name == name), None)
            for name in chosen_tables_logical
        ]
        
        # Log das tabelas encontradas
        log_event(
            "specialist_multiple_tables_lookup",
            {
                "agent_id": agent_config.id,
                "requested_tables": chosen_tables_logical,
                "found_tables": [t.logical_name if t else None for t in tables],
                "available_tables": [t.logical_name for t in agent_config.tables],
            },
        )
        
        # Verificar se todas as tabelas foram encontradas
        if any(t is None for t in tables):
            missing = [
                name for name, t in zip(chosen_tables_logical, tables) if t is None
            ]
            state["error"] = f"Tables not found in agent configuration: {missing}"
            log_event(
                "specialist_tables_not_found",
                {"agent_id": agent_config.id, "missing": missing},
            )
            return state
        
        schema_text = _build_multiple_schemas_text(tables, join_relationships, security_config)
        primary_table = tables[0]  # primeira tabela é a principal (FROM)
        
    else:
        # Modo tabela única (comportamento original)
        # Se não temos chosen_logical mas temos chosen_tables com uma tabela, usar essa
        if not chosen_logical and chosen_tables_logical and len(chosen_tables_logical) == 1:
            chosen_logical = chosen_tables_logical[0]
            if chosen_tables_physical and len(chosen_tables_physical) > 0:
                chosen_physical = chosen_tables_physical[0]
        
        if not chosen_logical:
            state["error"] = "No table was chosen by the orchestrator."
            log_event(
                "specialist_no_table",
                {
                    "question": question[:200],
                    "chosen_tables_logical": chosen_tables_logical,
                    "chosen_logical": chosen_logical,
                },
            )
            return state

        table = next(
            (t for t in agent_config.tables if t.logical_name == chosen_logical),
            None,
        )
        if table is None:
            state["error"] = f"Table '{chosen_logical}' not found in agent configuration."
            log_event(
                "specialist_table_not_found",
                {
                    "agent_id": agent_config.id,
                    "chosen_logical": chosen_logical,
                    "available_tables": [t.logical_name for t in agent_config.tables],
                },
            )
            return state

        schema_text = _build_schema_text(table, security_config)
        primary_table = table

    # 🔹 CONTEXTO DE RAG: metadados, docs, histórico etc.
    retrieval_context: List[str] = state.get("retrieval_context") or []
    context_block = ""
    if retrieval_context:
        # limita alguns pedaços pra não estourar token
        joined = "\n\n".join(retrieval_context[:10])
        context_block = (
            "\n\nADDITIONAL CONTEXT (from metadata/docs/query history):\n"
            f"{joined}\n"
        )
    
    # 🔹 INSTRUÇÕES SQL PERSONALIZADAS
    sql_instructions = state.get("sql_instructions")
    sql_instructions_block = ""
    if sql_instructions:
        sql_instructions_block = (
            "\n\nSQL-SPECIFIC INSTRUCTIONS:\n"
            f"{sql_instructions}\n"
        )
    
    # 🔒 INSTRUÇÕES DE SEGURANÇA (RLS, colunas bloqueadas, etc.)
    security_instructions_block = build_security_prompt_instructions(security_config)
    
    # Preparar orientações de agregação (comum para ambos os modos)
    aggregation_guidance = ""
    if requires_aggregation:
        aggregation_guidance = (
            "\n\nIMPORTANT INTERPRETATION GUIDANCE:\n"
            "- Questions about 'performance', 'metrics', 'monthly', 'yearly', or 'distribution' "
            "typically require aggregation (SUM, COUNT, AVG, etc.) and GROUP BY.\n"
            "- Look for date/month/year columns in the schema(s) to group by.\n"
            "- For 'monthly performance', use GROUP BY with month/year columns and aggregate "
            "relevant numeric columns (amounts, counts, etc.).\n"
            "- DO NOT just return all rows with LIMIT - always aggregate when the question "
            "asks for metrics, totals, or temporal analysis.\n"
            "- Examples:\n"
            "  * 'performance mensal' → GROUP BY month/year, aggregate amounts/counts\n"
            "  * 'total por categoria' → GROUP BY category, SUM amounts\n"
            "  * 'distribuição' → GROUP BY relevant dimension, COUNT or SUM\n"
        )
    
    if use_multiple_tables:
        # Modo JOIN: instruções para múltiplas tabelas
        physical_names = [t.physical_name for t in tables]
        
        # Se não há join_relationships explícitos, adicionar instrução para o LLM inferir
        join_guidance = ""
        if not join_relationships:
            join_guidance = (
                "\n\nIMPORTANT: No explicit JOIN relationships were provided, but you should "
                "try to infer relationships based on column names (e.g., entity_id, foreign_id, "
                "reference_id typically reference id columns in other tables). "
                "Look for columns ending in '_id' that might reference other tables."
            )
        
        system_msg = _build_secure_system_prompt(
            physical_names=physical_names,
            use_multiple_tables=True,
            max_limit=100,
            max_columns=10
        )
        
        # Adicionar instruções específicas de JOIN
        join_instruction = (
            "- Use the JOIN relationships provided to connect the tables.\n"
            if join_relationships 
            else "- Infer JOIN relationships based on column names (e.g., *_id columns).\n"
        )
        
        # Adicionar instruções de agregação
        aggregation_instruction = (
                "- When the question asks for metrics, totals, performance, or temporal analysis, "
                "use aggregation functions (SUM, COUNT, AVG, MAX, MIN) and GROUP BY.\n"
                "- DO NOT use SELECT * with LIMIT when the question requires aggregation.\n"
        )
        
        # Atualizar content com instruções adicionais
        system_msg["content"] += join_instruction + aggregation_instruction

        user_msg = {
            "role": "user",
            "content": (
                f"User question:\n{question}\n\n"
                f"Table schemas:\n{schema_text}\n"
                f"{context_block}"
                f"{sql_instructions_block}"
                f"{security_instructions_block}"
                f"{join_guidance}"
                f"{aggregation_guidance}"
                "Generate only the SQL query with JOINs (or IMPOSSIBLE: <reason>)."
            ),
        }
    else:
        # Modo tabela única (comportamento original)
        system_msg = _build_secure_system_prompt(
            physical_names=[primary_table.physical_name],
            use_multiple_tables=False,
            max_limit=100,
            max_columns=10
        )
        
        # Adicionar instruções de agregação
        aggregation_instruction = (
                "- When the question asks for metrics, totals, performance, or temporal analysis, "
                "use aggregation functions (SUM, COUNT, AVG, MAX, MIN) and GROUP BY.\n"
                "- DO NOT use SELECT * with LIMIT when the question requires aggregation.\n"
        )
        
        # Atualizar content com instruções adicionais
        system_msg["content"] += aggregation_instruction

        user_msg = {
            "role": "user",
            "content": (
                f"User question:\n{question}\n\n"
                f"Table schema:\n{schema_text}\n"
                f"{context_block}"
                f"{sql_instructions_block}"
                f"{security_instructions_block}"
                f"{aggregation_guidance}"
                "Generate only the SQL query (or IMPOSSIBLE: <reason>)."
            ),
        }

    try:
        raw = llm.invoke([system_msg, user_msg])
    except Exception as e:
        state["error"] = "Error calling the SQL specialist LLM."
        log_event(
            "specialist_llm_error",
            {
                "agent_id": agent_config.id,
                "chosen_logical": chosen_logical or (chosen_tables_logical[0] if chosen_tables_logical else None),
                "error": str(e)[:500],
            },
        )
        return state

    # === Trata IMPOSSIBLE ===
    if hasattr(raw, "content"):
        content = raw.content or ""
    else:
        content = str(raw or "")

    content_clean = content.strip()
    
    # Log da resposta bruta do LLM
    log_event(
        "specialist_llm_response",
        {
            "agent_id": agent_config.id,
            "response_preview": content_clean[:500],
            "response_length": len(content_clean),
            "starts_with_impossible": bool(re.match(r"^\s*IMPOSSIBLE", content_clean, flags=re.IGNORECASE)),
        },
    )
    
    if re.match(r"^\s*IMPOSSIBLE", content_clean, flags=re.IGNORECASE):
        # extrai a razão se existir
        reason = re.sub(
            r"^\s*IMPOSSIBLE:?\s*",
            "",
            content_clean,
            flags=re.IGNORECASE,
        ).strip()
        state["impossible_reason"] = reason or "Specialist marked this as impossible with the current table and context."
        log_event(
            "specialist_impossible",
            {
                "agent_id": agent_config.id,
                "chosen_logical": chosen_logical,
                "reason": state["impossible_reason"],
            },
        )
        # deixa para o formatter transformar isso em mensagem amigável
        return state

    # === Extrai SQL ===
    sql = _parse_specialist_output(raw, primary_table)
    
    # Log do parsing
    log_event(
        "specialist_sql_parsed",
        {
            "agent_id": agent_config.id,
            "sql_extracted": bool(sql),
            "sql_preview": sql[:200] if sql else None,
            "sql_length": len(sql) if sql else 0,
        },
    )

    if not sql:
        state["error"] = "Specialist did not return any SQL."
        log_event(
            "specialist_empty_sql",
            {
                "agent_id": agent_config.id,
                "chosen_logical": chosen_logical or (chosen_tables_logical[0] if chosen_tables_logical else None),
                "raw_response": content_clean[:1000],  # Aumentar para ver mais da resposta
            },
        )
        return state

    # === Validação de segurança básica (só SELECT, sem maldade) ===
    safe_error = ensure_safe_select(sql)
    if safe_error:
        state["error"] = safe_error
        state["sql"] = sql
        log_event(
            "specialist_unsafe_sql",
            {
                "agent_id": agent_config.id,
                "chosen_logical": chosen_logical,
                "sql": sql[:500],
                "error": safe_error,
            },
        )
        return state
    
    # Log: validação básica passou
    log_event(
        "specialist_basic_validation_passed",
        {
            "agent_id": agent_config.id,
            "sql_preview": sql[:200],
        },
    )

    # === Validação avançada (AST + permissões) ANTES de executar ===
    try:
        allowed_tables: List[str] = []
        for t in (agent_config.tables or []):
            if getattr(t, "physical_name", None):
                allowed_tables.append(t.physical_name)
            if getattr(t, "logical_name", None):
                allowed_tables.append(t.logical_name)

        # Heurística simples para tipo de conexão (BigQuery tende a ter project.dataset.table)
        connection_type = "bigquery"
        if allowed_tables and all(str(x).count(".") <= 1 for x in allowed_tables):
            # schema.table (ou table) é mais típico de SQLAlchemy/Postgres
            connection_type = "postgres"

        validator = AdvancedSQLValidator(
            allowed_tables=allowed_tables,
            allowed_columns=None,
            max_limit=100,
            max_columns=10,
            max_group_by=3,
        )
        ok, validation_error = validator.validate(sql, connection_type)
        if not ok:
            state["error"] = validation_error or "SQL validation failed."
            state["sql"] = sql
            log_event(
                "specialist_advanced_sql_rejected",
                {
                    "agent_id": agent_config.id,
                    "chosen_logical": chosen_logical,
                    "sql": sql[:500],
                    "error": (validation_error or "")[:300],
                    "connection_type": connection_type,
                },
            )
            return state
        
        # Log: validação avançada passou
        log_event(
            "specialist_advanced_validation_passed",
            {
                "agent_id": agent_config.id,
                "connection_type": connection_type,
                "sql_preview": sql[:200],
            },
        )
    except Exception as e:
        # Falha no validador: fail closed (melhor seguro)
        state["error"] = f"SQL validation error: {str(e)[:300]}"
        state["sql"] = sql
        log_event(
            "specialist_advanced_sql_validator_error",
            {
                "agent_id": agent_config.id,
                "chosen_logical": chosen_logical,
                "error": str(e)[:500],
            },
        )
        return state

    # === Injetar Row-Level Security (RLS) filters ===
    # Isso adiciona cláusulas WHERE automáticas baseadas no security_config
    if security_config:
        sql_with_rls = inject_row_filters_in_sql(sql, security_config)
        if sql_with_rls != sql:
            log_event(
                "specialist_rls_injected",
                {
                    "agent_id": agent_config.id,
                    "original_sql": sql[:300],
                    "sql_with_rls": sql_with_rls[:300],
                },
            )
            sql = sql_with_rls

        # === Validação de segurança contra security_config (colunas, keywords, RLS) ===
        # Construir lista de tabelas permitidas
        allowed_tables_for_validation = [primary_table.physical_name]
        if use_multiple_tables and 'tables' in locals():
            allowed_tables_for_validation.extend([t.physical_name for t in tables])
        
        # Log: antes da validação de security_config
        log_event(
            "specialist_before_security_validation",
            {
                "agent_id": agent_config.id,
                "sql_preview": sql[:200],
                "allowed_tables": allowed_tables_for_validation[:5],
            },
        )
        
        is_valid, security_error = validate_sql_against_security(
            sql=sql,
            security_config=security_config,
            allowed_tables=allowed_tables_for_validation
        )
        if not is_valid:
            state["error"] = f"Security validation failed: {security_error}"
            state["sql"] = sql
            log_event(
                "specialist_security_validation_failed",
                {
                    "agent_id": agent_config.id,
                    "sql": sql[:500],
                    "error": security_error,
            },
        )
            return state
        
        # Log: validação de security_config passou
        log_event(
            "specialist_security_validation_passed",
            {
                "agent_id": agent_config.id,
                "sql_preview": sql[:200],
            },
        )
    else:
        # Log: sem security_config
        log_event(
            "specialist_no_security_config",
            {
                "agent_id": agent_config.id,
                "sql_preview": sql[:200],
            },
        )

    # === Execução via data_source ===
    # Log: antes da execução
    log_event(
        "specialist_before_execution",
        {
            "agent_id": agent_config.id,
            "sql_preview": sql[:500],
            "sql_length": len(sql),
        },
    )
    
    try:
        rows = data_source.run_query(sql)
    except Exception as e:
        state["error"] = f"Error executing SQL: {str(e)[:500]}"
        state["sql"] = sql
        log_event(
            "specialist_query_error",
            {
                "agent_id": agent_config.id,
                "chosen_logical": chosen_logical,
                "sql": sql[:500],
                "error": str(e)[:500],
            },
        )
        return state

    # Sucesso: preenche state com sql + dados
    state["sql"] = sql
    state["data"] = rows

    log_event(
        "specialist_query_success",
        {
            "agent_id": agent_config.id,
            "chosen_logical": chosen_tables_logical if use_multiple_tables else chosen_logical,
            "chosen_physical": chosen_tables_physical if use_multiple_tables else chosen_physical,
            "num_tables": len(chosen_tables_logical) if use_multiple_tables else 1,
            "has_joins": use_multiple_tables,
            "num_rows": len(rows) if isinstance(rows, list) else None,
        },
    )

    return state
