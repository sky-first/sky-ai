# core/llm/orchestrator.py
from __future__ import annotations

from typing import List, Optional
import re

from sqlalchemy.orm import Session

from core.agents.generic_sql_agent import AgentState, AgentConfig, TableSchema
from core.i18n.i18n import detect_language
from core.logging_utils import log_event
from core.rag.context_retrieval import build_retrieval_context_for_question
from core.rag.embeddings import EmbeddingProvider
from core.llm.providers import LLMProvider
from core.sql.relationships import detect_relationships, find_join_path


def _build_tables_summary(tables: List[TableSchema]) -> str:
    """
    Gera um pequeno resumo dos logical tables pro LLM do orquestrador.
    """
    parts = []
    for t in tables:
        col_desc = ", ".join(
            f"{c.get('name', c.get('name', ''))} ({c.get('type', c.get('type', ''))})" 
            if isinstance(c, dict) else f"{c.name} ({c.type})"
            for c in (t.columns or [])[:8]
        )
        parts.append(
            f"- {t.logical_name} -> physical: {t.physical_name} | columns: {col_desc}"
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

    # match exato
    for name in logical_names:
        if text == name.lower():
            return name

    # match se o modelo colocou mais texto tipo "I choose invoices"
    for name in logical_names:
        if name.lower() in text:
            return name

    # fallback: primeira tabela
    return logical_names[0]


def _extract_multiple_table_choices(raw_llm_response, tables: List[TableSchema]) -> List[str]:
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
    parts = re.split(r'[,;\n]|\sand\s', text)
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        # Match exato
        for name in logical_names:
            if part == name:
                table_name = next(t.logical_name for t in tables if t.logical_name.lower() == name)
                if table_name not in found_tables:
                    found_tables.append(table_name)
                break
        
        # Match parcial
        for name in logical_names:
            if name in part and name not in [t.lower() for t in found_tables]:
                table_name = next(t.logical_name for t in tables if t.logical_name.lower() == name)
                if table_name not in found_tables:
                    found_tables.append(table_name)
                break

    # Se não encontrou múltiplas, retorna lista com uma (compatibilidade)
    if not found_tables:
        return [logical_names[0].title()] if logical_names else []
    
    return found_tables


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

    # 🔤 Detecção de idioma
    try:
        lang = detect_language(question)
    except Exception:
        lang = "en"
    state["detected_language"] = lang

    # 🔍 Garante que o agente tem tabelas configuradas
    if not agent_config.tables:
        state["answer"] = "No tables are configured for this agent."
        log_event("orchestrator_no_tables", {"agent_id": agent_config.id})
        return state

    # 📚 Opcional: se ainda não houver retrieval_context no state e tivermos db + embeddings,
    #               chama diretamente o RAG aqui.
    retrieval_context: List[str] = state.get("retrieval_context") or []

    if not retrieval_context and db is not None and embedding_provider is not None:
        try:
            space_id = state.get("space_id")
            crew_ids = state.get("crew_ids") or []

            if space_id:
                retrieval_context = build_retrieval_context_for_question(
                    db=db,
                    embedding_provider=embedding_provider,
                    space_id=space_id,
                    crew_ids=crew_ids,
                    question=question,
                    top_k=15,
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
            retrieval_context = []

    tables_summary = _build_tables_summary(agent_config.tables)

    # 🔗 Monta bloco de contexto (limitando pra não explodir o prompt)
    context_block = ""
    if retrieval_context:
        joined = "\n\n".join(retrieval_context[:5])
        context_block = (
            "\n\nADDITIONAL CONTEXT (from metadata/docs/query history):\n"
            f"{joined}\n"
        )

    # Detectar relacionamentos entre tabelas
    relationships = detect_relationships(agent_config.tables)
    
    # Decidir se precisa de múltiplas tabelas baseado na pergunta
    # Palavras-chave que sugerem JOIN: "join", "combine", "relate", "together", "both", "and"
    needs_multiple = any(keyword in question.lower() for keyword in [
        "join", "combine", "relate", "together", "both", " and ", "between", "across"
    ]) or question.count("table") > 1

    if needs_multiple and len(agent_config.tables) > 1:
        # Modo múltiplas tabelas
        system_msg = {
            "role": "system",
            "content": (
                "You are a routing assistant. Your job is to choose ONE OR MORE logical tables "
                "from the list to answer the user's question.\n\n"
                "Rules:\n"
                "- You can choose ONE or MULTIPLE logical table names from the list.\n"
                "- If the question requires data from multiple tables, list them separated by commas.\n"
                "- Answer with ONLY the logical table name(s), separated by commas if multiple.\n"
                "- Example responses: 'invoices' or 'invoices, customers' or 'orders, products'\n"
                "- Use the additional semantic context when it clearly points to specific tables.\n"
            ),
        }

        user_msg = {
            "role": "user",
            "content": (
                f"User question:\n{question}\n\n"
                f"Available tables:\n{tables_summary}"
                f"{context_block}\n\n"
                "Respond with the logical table name(s) needed, separated by commas if multiple "
                "(for example: 'invoices' or 'invoices, customers' or 'orders, products')."
            ),
        }
    else:
        # Modo tabela única (compatibilidade)
        system_msg = {
            "role": "system",
            "content": (
                "You are a routing assistant. Your job is to choose exactly ONE logical table "
                "from the list to answer the user's question.\n\n"
                "Rules:\n"
                "- You must choose ONLY ONE logical table name from the list.\n"
                "- Answer with ONLY the logical table name, nothing else.\n"
                "- If more than one table could work, choose the one that seems most directly related.\n"
                "- Use the additional semantic context when it clearly points to a specific table.\n"
            ),
        }

        user_msg = {
            "role": "user",
            "content": (
                f"User question:\n{question}\n\n"
                f"Available tables:\n{tables_summary}"
                f"{context_block}\n\n"
                "Respond with ONLY the logical table name (for example: invoices, customers, events...)."
            ),
        }

    try:
        raw = llm.invoke([system_msg, user_msg])
    except Exception as e:
        state["answer"] = "Error consulting the AI orchestrator. Please try again later."
        state["error"] = str(e)
        log_event(
            "orchestrator_llm_error",
            {"agent_id": agent_config.id, "error": str(e)[:500]},
        )
        return state

    # Extrair escolha(s) de tabela(s)
    if needs_multiple and len(agent_config.tables) > 1:
        chosen_logicals = _extract_multiple_table_choices(raw, agent_config.tables)
        
        # Se encontrou múltiplas tabelas, usar modo JOIN
        if len(chosen_logicals) > 1:
            # Encontrar caminho de JOIN
            join_path = find_join_path(chosen_logicals, relationships)
            
            if join_path:
                state["chosen_tables"] = chosen_logicals
                state["chosen_tables_physical"] = [
                    next((t.physical_name for t in agent_config.tables if t.logical_name == name), name)
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
                    (t.physical_name for t in agent_config.tables if t.logical_name == chosen_logicals[0]),
                    chosen_logicals[0]
                )
                
                log_event(
                    "orchestrator_choice_multiple",
                    {
                        "agent_id": agent_config.id,
                        "question": question[:200],
                        "chosen_tables": chosen_logicals,
                        "join_path_length": len(join_path),
                        "detected_language": lang,
                    },
                )
            else:
                # Não encontrou caminho de JOIN, usar apenas primeira tabela
                chosen_logical = chosen_logicals[0]
                chosen_table_obj = next(
                    (t for t in agent_config.tables if t.logical_name == chosen_logical),
                    agent_config.tables[0],
                )
                state["chosen_table"] = chosen_table_obj.logical_name
                state["chosen_table_physical"] = chosen_table_obj.physical_name
                
                log_event(
                    "orchestrator_choice_multiple_no_path",
                    {
                        "agent_id": agent_config.id,
                        "question": question[:200],
                        "chosen_tables": chosen_logicals,
                        "fallback_to": chosen_table_obj.logical_name,
                        "detected_language": lang,
                    },
                )
        else:
            # Apenas uma tabela escolhida
            chosen_logical = chosen_logicals[0] if chosen_logicals else agent_config.tables[0].logical_name
            chosen_table_obj = next(
                (t for t in agent_config.tables if t.logical_name == chosen_logical),
                agent_config.tables[0],
            )
            state["chosen_table"] = chosen_table_obj.logical_name
            state["chosen_table_physical"] = chosen_table_obj.physical_name
            
            log_event(
                "orchestrator_choice",
                {
                    "agent_id": agent_config.id,
                    "question": question[:200],
                    "chosen_logical": chosen_table_obj.logical_name,
                    "chosen_physical": chosen_table_obj.physical_name,
                    "detected_language": lang,
                },
            )
    else:
        # Modo tabela única (comportamento original)
        chosen_logical = _extract_table_choice(raw, agent_config.tables)
        chosen_table_obj = next(
            (t for t in agent_config.tables if t.logical_name == chosen_logical),
            agent_config.tables[0],
        )

        state["chosen_table"] = chosen_table_obj.logical_name
        state["chosen_table_physical"] = chosen_table_obj.physical_name

        log_event(
            "orchestrator_choice",
            {
                "agent_id": agent_config.id,
                "question": question[:200],
                "chosen_logical": chosen_table_obj.logical_name,
                "chosen_physical": chosen_table_obj.physical_name,
                "detected_language": lang,
            },
        )

    return state
