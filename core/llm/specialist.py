# core/llm/specialist.py
from __future__ import annotations

import re
from typing import List, Optional, Dict, Any, Tuple

from config.settings import settings

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
from core.dialects import Dialect, get_dialect_specifics


# ==================== HELPERS ====================

def _build_secure_system_prompt(
    physical_names: List[str],
    max_limit: int = 100,
    max_columns: int = 50,
    use_multiple_tables: bool = False,
    security_rules: str = "",

    # detected_language removed
    dialect: Dialect = Dialect.POSTGRES,
    use_local_models: bool = False,
) -> Dict[str, str]:
    """
    Constrói system prompt com regras de segurança explícitas.
    """

    # Se estivermos usando modelos locais (SQLCoder), usamos um prompt específico
    # sem regras de título e sem comentários forçados.
    if use_local_models:
        if use_multiple_tables:
            content = (
                "### Task\\n"
                f"Generate a SQL query for {dialect.value.upper()} to answer the user's question.\\n\\n"
                "### Instructions\\n"
                f"- Use ONLY these tables: {', '.join(physical_names)}\\n"
                f"- Main table (FROM): {physical_names[0]}\\n"
                "- Use ONLY existing columns from the schemas provided\\n"
                f"- ALWAYS end with LIMIT {max_limit}\\n"
                "- NEVER use SELECT *\\n"
                "- Output ONLY the SQL code, no explanations\\n\\n"
                "### SQL Query\\n"
            )
        else:
            content = (
                "### Task\\n"
                f"Generate a SQL query for {dialect.value.upper()} to answer the user's question.\\n\\n"
                "### Instructions\\n"
                f"- Use ONLY this table: {physical_names[0]}\\n"
                "- Use ONLY existing columns from the schema\\n"
                f"- ALWAYS end with LIMIT {max_limit}\\n"
                "- NEVER use SELECT *\\n"
                "- Output ONLY the SQL code, no explanations\\n\\n"
                "### SQL Query\\n"
            )
        
        return {"role": "system", "content": content}
    
    # Use the passed security_rules string directly
    # If security_rules is empty, use a default set of rules
    if not security_rules:
        security_rules = (
            "⚠️ CRITICAL SECURITY RULES - YOU MUST FOLLOW ALL (NON-NEGOTIABLE):\n\n"
            "🔴 MANDATORY - YOUR QUERY WILL BE REJECTED IF YOU VIOLATE THESE:\n"
            "1. GOLDEN RULE: Before generating SQL, check if requested columns are SENSITIVE.\n"
            "   - If SENSITIVE and user lacks permission: Respond IMPOSSIBLE: Security Restriction.\n"
            "   - DO NOT provide aggregated stats for unauthorized sensitive columns.\n"
            "2. ALWAYS end your query with LIMIT {max_limit} - THIS IS REQUIRED, even for GROUP BY queries\n"
            "   Example: SELECT year, SUM(amount) FROM data_table GROUP BY year ORDER BY year LIMIT {max_limit}\n"
            "3. NEVER use SELECT * - always specify columns explicitly (max {max_columns} columns)\n"
            "4. NEVER use UNION, UNION ALL, or any UNION variant\n"
            "5. NEVER use ; (semicolon) except at the very end - only one query\n"
            "6. NEVER use comments -- or /* */\n"
            "7. NEVER use INFORMATION_SCHEMA, pg_catalog, sys, mysql, or system tables\n"
            "8. NEVER use DROP, DELETE, UPDATE, INSERT, ALTER, CREATE, TRUNCATE\n"
            "9. NEVER use subqueries that access unauthorized tables\n"
            "10. 🔴 CRITICAL: NEVER use WHERE with DATE_SUB, INTERVAL, or temporal filters like 'last X days/weeks'\n"
            "    - Data might not exist in recent ranges → EMPTY RESULTS\n"
            "    - For 'recent' data, use ORDER BY date_column DESC LIMIT N\n"
            "    - Example BAD: WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)\n"
            "    - Example GOOD: ORDER BY date DESC LIMIT 15\n\n"
            "🛡️ PRIVACY & COMPARISON RULES:\n"
            "- If user asks to compare specific individuals (e.g. 'Is Customer X the highest?'), DO NOT confirm specific values.\n"
            "- REFUSE to 'list names' of other entities in comparisons. Use 'The top customer' instead.\n"
            "- If user asks to 'list all' or 'display full database', YOU MUST AGGREGATE (COUNT, AVG, MAX) instead of listing rows.\n\n"
            "⚠️ REMEMBER: Your SQL MUST end with 'LIMIT {max_limit}' or it will be automatically rejected!\n"
            "If you cannot follow these rules, respond: IMPOSSIBLE: <reason>\n\n"
        ).format(max_limit=max_limit, max_columns=max_columns)
    
    # Get dialect specifics
    dialect_info = get_dialect_specifics(dialect)
    details = dialect_info.get("details", {})
    type_ = dialect_info.get("type", "sql")

    if type_ == "nosql":
        # Strategy for NoSQL (MongoDB, etc.)
        # This overrides the standard SQL prompt construction
        query_lang = details.get("query_language", "NoSQL")
        output_fmt = details.get("output_format", "JSON")
        example = details.get("example", "")
        
        return {
            "role": "system",
            "content": (
                f"You are a database expert in {dialect.value.upper()} ({query_lang}).\n"
                f"Your task is to generate a VALID {query_lang} query/command.\n"
                f"Output format: {output_fmt}\n\n"
                f"Rules:\n"
                f"Rules:\n"
                f"- Language: English (always)\n"
                f"- Do NOT generate SQL if the dialect is NoSQL.\n"
                f"- Example valid query: {example}\n"
                f"IMPORTANT: You MUST generate a descriptive title as a comment (or field if JSON) on the FIRST LINE.\n"
                f"Format: -- TITLE: <Title Text> (if text) or field 'title' if JSON.\n"
            )
        }

    # SQL Strategy (default)
    id_quote = details.get("identifier_quote", '"')
    string_quote = details.get("string_quote", "'")
    date_func = details.get("date_func", "CURRENT_DATE")

    if use_multiple_tables:
        return {
            "role": "system",
            "content": (
                "You are a SQL expert. Your job is to generate a single SELECT query "
                "with JOINs to answer the user's question.\n"
                f"Dialect: {dialect.value.upper()}\n"
                f"Rules: Use {id_quote} for identifiers, {string_quote} for strings. Date func: {date_func}.\n\n"
                f"{security_rules}"
                f"Allowed physical table names: {', '.join(physical_names)}\n"
                f"Main table (FROM): {physical_names[0]}\n"
                "Use ONLY existing columns from the schemas provided.\n"
                "Generate only the SQL query (or IMPOSSIBLE: <reason>).\n"
                "IMPORTANT: You MUST generate a descriptive title for this query as a comment on the VERY FIRST LINE.\n"
                "Format: -- TITLE: <Title Text>\n"
                "Rules for Title:\n"
                "- Language: English (always) - EVEN IF USER SPEAKS ANOTHER LANGUAGE\n"
                "- Max 60 chars\n"
                "- Be specific (include region, product, year if in query)\n"
                "- Example: -- TITLE: Sales by Region 2024"
            )
        }
    else:
        return {
            "role": "system",
            "content": (
                "You are a SQL expert. Your job is to generate a single SELECT query "
                "to answer the user's question.\n"
                f"Dialect: {dialect.value.upper()}\n"
                f"Rules: Use {id_quote} for identifiers, {string_quote} for strings. Date func: {date_func}.\n\n"
                f"{security_rules}"
                f"The only allowed physical table name is: {physical_names[0]}\n"
                "Use ONLY existing columns from the schema provided.\n"
                "\n"
                "SPECIAL CASES:\n"
                "- If the question asks 'how many rows' or 'count of rows', use: SELECT COUNT(*) FROM table\n"
                "- For simple counts, you don't need to specify columns, COUNT(*) is sufficient\n"
                "\n"
                "Generate only the SQL query (or IMPOSSIBLE: <reason>).\n"
                "IMPORTANT: You MUST generate a descriptive title for this query as a comment on the VERY FIRST LINE.\n"
                "Format: -- TITLE: <Title Text>\n"
                "Rules for Title:\n"
                "- Language: English (always) - EVEN IF USER SPEAKS ANOTHER LANGUAGE\n"
                "- Max 60 chars\n"
                "- Be specific (include region, product, year if in query)\n"
                "- Example: -- TITLE: Sales by Region 2024"
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


def _extract_title_from_sql(sql_text: str) -> Tuple[Optional[str], str]:
    """
    Extrai o título do comentário na primeira linha do SQL.
    Retorna (titulo, sql_sem_titulo).
    """
    if not sql_text:
        return None, ""
    
    lines = sql_text.splitlines()
    if not lines:
        return None, sql_text

    first_line = lines[0].strip()
    # Procura por -- TITLE: ...
    match = re.search(r"^--\s*TITLE:\s*(.*)", first_line, flags=re.IGNORECASE)
    
    if match:
        title = match.group(1).strip()
        # Remove a primeira linha e junta o resto
        clean_sql = "\n".join(lines[1:]).strip()
        return title, clean_sql
    
    return None, sql_text


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
        "performance", "metric", "total", "sum", "avg", "average", "count",
        "max", "min", "monthly", "yearly", "daily", "per month", "per year",
        "distribution", "group", "grouped"
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
            "  * 'monthly performance' → GROUP BY month/year, aggregate amounts/counts\n"
            "  * 'total by category' → GROUP BY category, SUM amounts\n"
            "  * 'distribution' → GROUP BY relevant dimension, COUNT or SUM\n"
        )
    
    # Identificar idioma - REMOVED, now defaulting to English
    # detected_language detected_languages logic removed
    detected_language = "English"

    # Define the security rules string to pass to _build_secure_system_prompt
    # This allows _build_secure_system_prompt to use it directly
    security_rules_str = (
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
        
        # Constrói prompt
        system_msg = _build_secure_system_prompt(
            physical_names=physical_names,
            max_limit=150,  # Aumentei um pouco caso precise
            max_columns=50, # Updated max_columns
            use_multiple_tables=True,
            security_rules=security_rules_str.format(max_limit=150, max_columns=50), # Pass formatted rules
            dialect=getattr(data_source, "dialect", Dialect.POSTGRES),
            use_local_models=settings.use_local_models,
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
        
        # Adicionar instruções de colunas
        column_guidance = (
            "- For status or category columns, prefer using columns containing human-readable labels "
            "(e.g., suffixes like '_name', '_desc', '_label', '_clean', '_pt') instead of IDs.\n"
        )
        
        # ✅ CRITICAL: Adicionar instruções sobre filtros temporais
        temporal_filter_guidance = (
            "\n\nCRITICAL: AVOID EMPTY RESULTS FROM TEMPORAL FILTERS:\n"
            "- DO NOT use WHERE clauses with DATE_SUB, INTERVAL, or 'last X days/weeks/months'\n"
            "- Data might not exist in recent time ranges (e.g., last 30 days might be empty)\n"
            "- For 'recent' or 'latest' data, use ORDER BY date_column DESC LIMIT N instead\n"
            "- Examples:\n"
            "  * BAD: WHERE invoice_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) → might be EMPTY\n"
            "  * GOOD: ORDER BY invoice_date DESC LIMIT 15 → always returns data\n"
            "  * BAD: WHERE created_at >= '2024-01-01' AND created_at < '2024-02-01' → might be EMPTY\n"
            "  * GOOD: ORDER BY created_at DESC LIMIT 20 → always returns data\n"
            "- If you MUST filter by date, use broader ranges (e.g., last 12 months, last year)\n"
            "- Prefer aggregation over filtering: COUNT, SUM, AVG work on all data\n"
        )
        
        # Atualizar content com instruções adicionais
        system_msg["content"] += join_instruction + aggregation_instruction + column_guidance + temporal_filter_guidance

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
            max_limit=100,
            max_columns=10,
            use_multiple_tables=False,
            security_rules=security_rules_str.format(max_limit=100, max_columns=10),
            dialect=getattr(data_source, "dialect", Dialect.POSTGRES),
            use_local_models=settings.use_local_models,
        )
        
        # Adicionar instruções de agregação
        aggregation_instruction = (
                "- When the question asks for metrics, totals, performance, or temporal analysis, "
                "use aggregation functions (SUM, COUNT, AVG, MAX, MIN) and GROUP BY.\n"
                "- DO NOT use SELECT * with LIMIT when the question requires aggregation.\n"
        )
        
        # Adicionar instruções de colunas
        column_guidance = (
            "- For status or category columns, prefer using columns containing human-readable labels "
            "(e.g., suffixes like '_name', '_desc', '_label', '_clean', '_pt') instead of IDs.\n"
        )
        
        # ✅ CRITICAL: Adicionar instruções sobre filtros temporais
        temporal_filter_guidance = (
            "\n\nCRITICAL: AVOID EMPTY RESULTS FROM TEMPORAL FILTERS:\n"
            "- DO NOT use WHERE clauses with DATE_SUB, INTERVAL, or 'last X days/weeks/months'\n"
            "- Data might not exist in recent time ranges (e.g., last 30 days might be empty)\n"
            "- For 'recent' or 'latest' data, use ORDER BY date_column DESC LIMIT N instead\n"
            "- Examples:\n"
            "  * BAD: WHERE invoice_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) → might be EMPTY\n"
            "  * GOOD: ORDER BY invoice_date DESC LIMIT 15 → always returns data\n"
            "  * BAD: WHERE created_at >= '2024-01-01' AND created_at < '2024-02-01' → might be EMPTY\n"
            "  * GOOD: ORDER BY created_at DESC LIMIT 20 → always returns data\n"
            "- If you MUST filter by date, use broader ranges (e.g., last 12 months, last year)\n"
            "- Prefer aggregation over filtering: COUNT, SUM, AVG work on all data\n"
        )
        
        # Atualizar content com instruções adicionais
        system_msg["content"] += aggregation_instruction + column_guidance + temporal_filter_guidance

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
    raw_sql = _parse_specialist_output(raw, primary_table)
    
    # Extrair título e limpar SQL
    generated_title, sql = _extract_title_from_sql(raw_sql)

    # 🔄 AUTO-CORRECTION: Verificar filtros temporais proibidos e fazer RETRY
    # Se detectar DATE_SUB, CURRENT_DATE, etc., forçar reescrita
    temporal_forbidden = ["DATE_SUB", "CURRENT_DATE", "NOW()", "INTERVAL", "current_date", "now()"]
    has_temporal_filter = any(term in sql.upper() for term in temporal_forbidden) and "WHERE" in sql.upper()
    
    # 🔄 AUTO-CORRECTION: Verificar filtro de categoria 'High' que retorna vazio
    # Detecta várias variações: `column` = 'High', column = 'High', column = "High"
    sql_normalized = sql.upper().replace("`", "").replace('"', "'")
    has_high_value_filter = "INVOICE_VALUE_CATEGORY = 'HIGH'" in sql_normalized
    
    # Só faz retry se não for a segunda tentativa (evitar loop infinito)
    retry_count = state.get("specialist_retry_count", 0)
    
    if (has_temporal_filter or has_high_value_filter) and retry_count < 1:
        reason_msg = ""
        if has_temporal_filter:
            reason_msg = "Detected prohibited temporal filter (DATE_SUB/CURRENT_DATE)"
            error_details = (
                "⚠️ SYSTEM ERROR: You used prohibited temporal filters (DATE_SUB, CURRENT_DATE, INTERVAL, NOW).\n"
                "The dataset is HISTORICAL (from 2023-2024). Using 'last 30 days' from today (2026) returns EMPTY results.\n"
                "rules violation: 10. NEVER use WHERE with temporal filters.\n"
            )
        else:
             reason_msg = "Detected problematic 'High' category filter"
             error_details = (
                "⚠️ SYSTEM ERROR: Do not filter by invoice_value_category = 'High' - this value does not exist or returns empty data.\n"
                "Instead of filtering by category, SORT by the amount to show the highest values.\n"
             )

        log_event(
            "specialist_retry_triggered",
            {
                "agent_id": agent_config.id,
                "bad_sql": sql,
                "reason": reason_msg
            }
        )
        
        # Criar mensagem de erro para o LLM
        retry_msg = (
            f"{error_details}\n"
            "👉 FIX: Rewrite the query specifically using 'ORDER BY {amount_col} DESC LIMIT {limit}' instead of WHERE ...\n"
            "Example: SELECT ... FROM ... ORDER BY total_amount DESC LIMIT 15"
        )
        
        # Adicionar ao histórico e chamar novamente
        new_messages = [system_msg, user_msg, {"role": "assistant", "content": raw.content if hasattr(raw, "content") else str(raw)}, {"role": "user", "content": retry_msg}]
        
        try:
            log_event("specialist_retrying", {"attempt": 2})
            raw_retry = llm.invoke(new_messages)
            
            # ✅ FIX: Verificar se retry retornou IMPOSSIBLE antes de processar
            retry_content = raw_retry.content if hasattr(raw_retry, "content") else str(raw_retry)
            retry_content_clean = retry_content.strip()
            
            if re.match(r"^\s*IMPOSSIBLE", retry_content_clean, flags=re.IGNORECASE):
                # LLM não conseguiu evitar filtro temporal - retornar mensagem amigável
                reason = re.sub(
                    r"^\s*IMPOSSIBLE:?\s*",
                    "",
                    retry_content_clean,
                    flags=re.IGNORECASE,
                ).strip()
                
                # Criar mensagem amigável para o usuário
                friendly_message = (
                    "I cannot filter by specific time periods with the current data constraints. "
                    "Would you like to see the overall trend or recent data instead?"
                )
                
                state["impossible_reason"] = reason or friendly_message
                state["answer"] = friendly_message
                
                log_event(
                    "specialist_impossible_after_retry",
                    {
                        "agent_id": agent_config.id,
                        "question": question[:200],
                        "reason": reason,
                        "action": "returning_friendly_message",
                    },
                )
                return state
            
            # Reprocessar saída
            raw_sql_retry = _parse_specialist_output(raw_retry, primary_table)
            generated_title_retry, sql_retry = _extract_title_from_sql(raw_sql_retry)
            
            if sql_retry:
                sql = sql_retry
                generated_title = generated_title_retry
                log_event("specialist_retry_success", {"new_sql": sql})
            
            # Atualizar contador para não tentar de novo
            state["specialist_retry_count"] = retry_count + 1
            
        except Exception as e:
            log_event("specialist_retry_failed", {"error": str(e)})
            # Continua com o SQL original se falhar o retry
            pass

    state["generated_title"] = generated_title
    
    
    # Log do parsing
    log_event(
        "specialist_sql_parsed",
        {
            "agent_id": agent_config.id,
            "sql_extracted": bool(sql),
            "title_extracted": generated_title,
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
            max_limit=5000,
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
            # ✅ SECURITY FIX: Don't expose table/column names to client
            # User-friendly message (NO schema details)
            state["error"] = "You don't have permission to access this information."
            state["sql"] = sql
            
            # Log violation evento (para logs em tempo real) - COM detalhes técnicos
            import logging
            logger = logging.getLogger(__name__)
            
            logger.warning(
                "Security validation failed - RLS violation",
                extra={
                    "agent_id": agent_config.id,
                    "user_id": state.get("user_id"),
                    "sql": sql[:500],
                    "security_error": security_error,  # Detalhes aqui (tabelas/colunas)
                    "blocked_tables": "extracted from error if needed",
                }
            )
            
            log_event(
                "specialist_security_validation_failed",
                {
                    "agent_id": agent_config.id,
                    "sql": sql[:500],
                    "error": security_error,  # Mantém detalhes nos logs
                },
            )
            
            # Log violation persistente (para audit trail no banco)
            from core.security.audit import log_query_audit
            log_query_audit(
                connection_id=agent_config.id,
                user_id=state.get("user_id"),
                space_id=state.get("space_id"),
                crew_ids=state.get("crew_ids"),
                thread_id=state.get("thread_id"),
                question=state.get("question", ""),
                platform_role=state.get("platform_role"),
                crew_role=state.get("crew_role"),
                sql_generated=sql,
                sql_validated=False,
                validation_error=security_error,  # Detalhes completos no audit log
                has_error=True,
                error_message=f"RLS Security Violation: {security_error}",
                chosen_tables=state.get("chosen_tables", []),
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
        # Tenta usar fluxo Arrow Otimizado se disponível (BaseDataSource define, mas checamos para segurança)
        if hasattr(data_source, "run_query_arrow"):
             rows = data_source.run_query_arrow(sql)
        else:
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

    real_num_rows = 0
    if hasattr(rows, "num_rows"): # Arrow Table
        real_num_rows = rows.num_rows
    elif isinstance(rows, list):
        real_num_rows = len(rows)

    log_event(
        "specialist_query_success",
        {
            "agent_id": agent_config.id,
            "chosen_logical": chosen_tables_logical if use_multiple_tables else chosen_logical,
            "chosen_physical": chosen_tables_physical if use_multiple_tables else chosen_physical,
            "num_tables": len(chosen_tables_logical) if use_multiple_tables else 1,
            "has_joins": use_multiple_tables,
            "num_rows": real_num_rows,
        },
    )

    return state
