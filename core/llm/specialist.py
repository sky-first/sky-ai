# core/llm/specialist.py
from __future__ import annotations

import re
from typing import List, Optional

from core.agents.generic_sql_agent import AgentState, AgentConfig, TableSchema
from core.data_sources.base import BaseDataSource
from core.llm.providers import LLMProvider
from core.sql.validator import ensure_safe_select
from core.logging_utils import log_event


# ==================== HELPERS ====================

def _build_schema_text(table: TableSchema) -> str:
    """
    Gera um texto legível do schema da tabela para o LLM.
    Usa logical_name só como rótulo, mas força o uso de physical_name.
    """
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


def _build_multiple_schemas_text(tables: List[TableSchema], join_info: Optional[List[Dict[str, str]]] = None) -> str:
    """
    Gera texto legível para múltiplas tabelas com informações de JOIN.
    """
    lines: List[str] = []
    lines.append("=== TABLES TO JOIN ===\n")
    
    for table in tables:
        lines.append(_build_schema_text(table))
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

    text = _strip_sql_fences(text)

    # às vezes o modelo responde algo tipo:
    # "Here is the query:\nSELECT ..."
    # vamos tentar pegar a primeira linha que começa com SELECT
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.search(r"\bselect\b", line, flags=re.IGNORECASE):
            return "\n".join(lines[i:]).strip()

    # fallback: retorna tudo
    return text.strip()


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

    # Se o orchestrator já respondeu (ex: modo catálogo/metadata), não gerar SQL.
    if state.get("answer"):
        log_event(
            "specialist_skipped_due_to_preanswered_state",
            {"agent_id": agent_config.id, "question": question[:200]},
        )
        return state
    
    # Verificar se há múltiplas tabelas (modo JOIN)
    chosen_tables_logical = state.get("chosen_tables")
    chosen_tables_physical = state.get("chosen_tables_physical")
    join_relationships = state.get("join_relationships")
    
    # Fallback para modo tabela única (compatibilidade)
    chosen_logical = state.get("chosen_table")
    chosen_physical = state.get("chosen_table_physical")
    
    # Determinar modo: múltiplas tabelas ou tabela única
    # Agora permite múltiplas tabelas mesmo sem join_relationships explícitos
    # O LLM pode tentar inferir JOINs baseado nos nomes das colunas
    use_multiple_tables = (
        chosen_tables_logical and 
        len(chosen_tables_logical) > 1
    )
    
    if use_multiple_tables:
        # Modo JOIN: múltiplas tabelas
        tables = [
            next((t for t in agent_config.tables if t.logical_name == name), None)
            for name in chosen_tables_logical
        ]
        
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
        
        schema_text = _build_multiple_schemas_text(tables, join_relationships)
        primary_table = tables[0]  # primeira tabela é a principal (FROM)
        
        # Se não há join_relationships explícitos, adicionar instrução para o LLM inferir
        join_guidance = ""
        if not join_relationships:
            join_guidance = (
                "\n\nIMPORTANT: No explicit JOIN relationships were provided, but you should "
                "try to infer relationships based on column names (e.g., user_id, customer_id, "
                "order_id typically reference id columns in other tables). "
                "Look for columns ending in '_id' that might reference other tables."
            )
        
    else:
        # Modo tabela única (comportamento original)
        if not chosen_logical or not chosen_physical:
            state["error"] = "No table was chosen by the orchestrator."
            log_event(
                "specialist_no_table",
                {"question": question[:200]},
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
                {"agent_id": agent_config.id, "chosen_logical": chosen_logical},
            )
            return state

        schema_text = _build_schema_text(table)
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
    
    if use_multiple_tables:
        # Modo JOIN: instruções para múltiplas tabelas
        physical_names = [t.physical_name for t in tables]
        
        # Se não há join_relationships explícitos, adicionar instrução para o LLM inferir
        join_guidance = ""
        if not join_relationships:
            join_guidance = (
                "\n\nIMPORTANT: No explicit JOIN relationships were provided, but you should "
                "try to infer relationships based on column names (e.g., user_id, customer_id, "
                "order_id typically reference id columns in other tables). "
                "Look for columns ending in '_id' that might reference other tables."
            )
        
        system_msg = {
            "role": "system",
            "content": (
                "You are a SQL expert. Your job is to generate a single SELECT query "
                "with JOINs to answer the user's question using the given table schemas and "
                "the additional context.\n\n"
                "Rules:\n"
                "- Use ONLY the provided physical table names.\n"
                f"- Allowed physical table names: {', '.join(physical_names)}\n"
                f"- Main table (FROM): {physical_names[0]}\n"
                + ("- Use the JOIN relationships provided to connect the tables.\n" if join_relationships else "- Infer JOIN relationships based on column names (e.g., *_id columns).\n")
                + "- Use ONLY existing columns from the schemas.\n"
                "- The query MUST be a single SELECT statement with JOINs.\n"
                "- DO NOT modify data (no INSERT/UPDATE/DELETE/etc.).\n"
                "- If the question cannot be answered with these tables and the provided context, "
                "  respond with exactly:\n"
                "  IMPOSSIBLE: <short explanation>\n"
            ),
        }

        user_msg = {
            "role": "user",
            "content": (
                f"User question:\n{question}\n\n"
                f"Table schemas:\n{schema_text}\n"
                f"{context_block}"
                f"{sql_instructions_block}"
                f"{join_guidance}"
                "Generate only the SQL query with JOINs (or IMPOSSIBLE: <reason>)."
            ),
        }
    else:
        # Modo tabela única (comportamento original)
        system_msg = {
            "role": "system",
            "content": (
                "You are a SQL expert. Your job is to generate a single SELECT query "
                "to answer the user's question using the given table schema and "
                "the additional context.\n\n"
                "Rules:\n"
                "- Use ONLY the provided physical table name.\n"
                f"- The only allowed physical table name is: {primary_table.physical_name}\n"
                "- Use ONLY existing columns from the schema.\n"
                "- The query MUST be a single SELECT statement.\n"
                "- DO NOT modify data (no INSERT/UPDATE/DELETE/etc.).\n"
                "- If the question cannot be answered with this table and the provided context, "
                "  respond with exactly:\n"
                "  IMPOSSIBLE: <short explanation>\n"
            ),
        }

        user_msg = {
            "role": "user",
            "content": (
                f"User question:\n{question}\n\n"
                f"Table schema:\n{schema_text}\n"
                f"{context_block}"
                f"{sql_instructions_block}"
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
                "chosen_logical": chosen_logical,
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

    if not sql:
        state["error"] = "Specialist did not return any SQL."
        log_event(
            "specialist_empty_sql",
            {
                "agent_id": agent_config.id,
                "chosen_logical": chosen_logical,
                "raw_response": content_clean[:500],
            },
        )
        return state

    # === Validação de segurança (só SELECT, sem maldade) ===
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

    # === Execução via data_source ===
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
