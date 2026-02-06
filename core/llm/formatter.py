# core/llm/formatter.py
from __future__ import annotations

from typing import Dict, Any, List, Optional
import json

from core.agents.generic_sql_agent import AgentState, AgentConfig
from core.llm.providers import LLMProvider
from core.i18n.i18n import detect_language, get_message
from core.logging_utils import log_event
from config.settings import settings
from core.suggestions.engine import suggestion_engine
from core.llm.prompts.formatter_prompts import build_formatter_prompt
from core.llm.context.builder import build_context_bundle


def _extract_topic(question: str) -> str:
    """
    Tenta extrair o tópico principal da pergunta para mensagens de 'dados não encontrados'.
    """
    import re
    # Remove palavras comuns de pergunta
    patterns = [
        r'^(qual|quais|como|quem|onde|quando|quanto|quantos|por que|me mostra|me mostre|mostre-me|mostre|mostra|me diga|diga|liste|busque|traz|traga|encontre)\s+',
        r'^(show|list|find|search|tell|what|how|where|when|which|who|why|can you|could you)\s+',
        r'^(o|a|os|as|um|uma|uns|umas|de|do|da|dos|das|sobre|pelo|pela|pelas|pelos|no|na|nos|nas)\s+',
        r'^(about|the|a|an|on|of|in|at|for|to|with|by|from)\s+'
    ]
    
    q = question
    for p in patterns:
        q = re.sub(p, '', q, flags=re.IGNORECASE)
    
    q = q.strip()
    
    # Pega as primeiras 3-4 palavras se for longo
    words = q.split()
    if len(words) > 4:
        return " ".join(words[:4]) + "..."
    return q or "este assunto"


def _serialize_for_json(obj: Any) -> Any:
    """Converte objetos não-serializáveis (date, datetime) para strings."""
    from datetime import date, datetime

    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_for_json(v) for v in obj]
    return obj


def _compute_basic_stats(data_sample: List[Dict[str, Any]]) -> str:
    """
    Gera um pequeno texto com estatísticas básicas da primeira coluna numérica encontrada.
    """
    if not data_sample:
        return ""

    first_row = data_sample[0]
    numeric_cols = [
        k for k, v in first_row.items() if isinstance(v, (int, float))
    ]
    if not numeric_cols:
        return ""

    col = numeric_cols[0]
    values = [
        row[col] for row in data_sample
        if isinstance(row.get(col), (int, float))
    ]
    if not values:
        return ""

    total = len(data_sample)
    mean_val = sum(values) / len(values)
    min_val = min(values)
    max_val = max(values)

    return (
        f"Basic statistics for '{col}': total_rows_sample={total}, "
        f"mean={mean_val:.2f}, min={min_val:.2f}, max={max_val:.2f}"
    )


def _ensure_language(question: str, detected_language: Optional[str]) -> str:
    """
    Garante um código de idioma (lang) consistente.
    """
    if detected_language:
        return detected_language
    try:
        return detect_language(question or "")
    except Exception:
        return "en"


def _invoke_llm(llm: LLMProvider, system_msg: dict, user_msg: dict) -> str:
    """
    Chama o LLM e sempre retorna string de conteúdo.
    """
    raw = llm.invoke([system_msg, user_msg])
    if hasattr(raw, "content"):
        return (raw.content or "").strip()
    return str(raw or "").strip()


def _stream_llm(llm: LLMProvider, system_msg: dict, user_msg: dict):
    """
    Stream tokens from LLM response.
    Yields string chunks as they are generated.
    """
    try:
        for chunk in llm.stream([system_msg, user_msg]):
            yield chunk
    except Exception as e:
        log_event(
            "formatter_stream_error",
            {
                "error": str(e)[:500],
            },
        )
        raise


def run_formatter(
    state: AgentState,
    agent_config: AgentConfig,
    llm: LLMProvider,
) -> AgentState:
    """
    Cria a resposta final para o usuário em linguagem natural.
    Usa:
      - state.question
      - state.data
      - state.error (se existir)
      - state.impossible_reason (se o especialista marcou IMPOSSIBLE)
      - state.detected_language (se não existir, detecta)
    """
    question = state.get("question") or ""
    data = state.get("data") or []
    error = state.get("error")
    impossible_reason = state.get("impossible_reason")
    
    # ✅ FIX: Preserve Orchestrator answer if already present (e.g. refusals, conversational)
    # This prevents overwriting valid answers with "No data found".
    if state.get("answer") and not data:
        log_event(
            "formatter_skipped_preservation",
            {
                "agent_id": agent_config.id,
                "reason": "Orchestrator answer preserved",
                "answer_preview": state["answer"][:100]
            }
        )
        return state

    impossible_reason = state.get("impossible_reason")
    detected_language = state.get("detected_language")

    # Tratamento de Arrow Table (se houver)
    total_rows = 0
    data_sample_list = []
    
    is_arrow = False
    try:
        import pyarrow as pa
        if isinstance(data, pa.Table):
            is_arrow = True
            total_rows = data.num_rows
            # ✅ CORREÇÃO: Converter e atualizar estado para lista de dicts
            data_list = data.to_pylist()
            state["data"] = data_list
            data = data_list # Atualiza local para uso nas samples
            
            # Amostra para o prompt
            data_sample_list = data[:15]
        else:
            total_rows = len(data) if data else 0
            data_sample_list = data[:15] if data else []
    except ImportError:
        total_rows = len(data) if data else 0
        data_sample_list = data[:15] if data else []

    # Garante idioma base
    lang = _ensure_language(question, detected_language)
    state["detected_language"] = lang

    # 1) Se houve erro técnico (SQL, conexão, etc.) -> passa amigável
    if error:
        # Se for um erro do validador ou execução, usamos mensagem amigável
        state["answer"] = get_message('TECHNICAL_ERROR', lang)
        # Log the error separately for debugging but don't show it to the user
        state["debug_error"] = str(error)
        log_event(
            "formatter_error_passthrough",
            {
                "agent_id": agent_config.id,
                "error_raw": str(error)[:300],
                "lang": lang,
            },
        )
        return state

    # 2) Caso o especialista tenha marcado como IMPOSSIBLE
    if impossible_reason and not data:
        # Tenta ser amigável quando não entende/não encontra dados
        topic = _extract_topic(question)
        state["answer"] = get_message("NO_DATA_FOUND", lang, topic=topic)
        
        log_event(
            "formatter_impossible_success",
            {
                "agent_id": agent_config.id,
                "reason": impossible_reason[:200],
                "topic": topic,
                "lang": lang,
            },
        )
        return state

    # 3) Sem dados e sem impossible_reason → resposta simples
    if not data:
        topic = _extract_topic(question)
        state["answer"] = get_message("NO_DATA_FOUND", lang, topic=topic)
        log_event(
            "formatter_no_data",
            {
                "agent_id": agent_config.id,
                "question": question[:200],
                "topic": topic,
                "lang": lang,
            },
        )
        return state

    # 4) Dados retornados: gera explicação em linguagem natural
    
    # 📦 BUILD CONTEXT BUNDLE (CPU Optimization & Unification)
    # We build the bundle once to ensure consistency in role/intent/history.
    context_bundle = build_context_bundle(state, agent_config)

    # Preparar amostra de dados para o prompt
    data_sample = data_sample_list
    serialized_sample = _serialize_for_json(data_sample)
    sample_json = json.dumps(serialized_sample, ensure_ascii=False, indent=2)
    stats_text = _compute_basic_stats(data_sample_list)
    
    # Obter orientações de comprimento amigáveis
    length = state.get("length")
    length_guidance = ""
    if length is not None:
        if length < 30:
            length_guidance = "- Keep the answer VERY SHORT (maximum 2 sentences).\n"
        elif length < 70:
            length_guidance = "- Keep the answer SHORT and OBJECTIVE (maximum 4 sentences).\n"
        else:
            length_guidance = "- You can provide a MORE DETAILED answer (up to 8 sentences).\n"
    
    # 🏗️ BUILD PROMPTS (Unified Logic)
    # This replaces the dual legacy blocks (OpenAI/Local) with a single source of truth.
    system_msg, user_msg = build_formatter_prompt(
        context_bundle=context_bundle,
        question=question,
        sql=state.get("sql", "N/A"),
        data_preview=sample_json,
        stats_summary=stats_text,
        has_data=True,
        response_format=state.get("response_format"),
        length_guidance=length_guidance,
        extra_instructions=state.get("instructions")
    )

    try:
        if settings.use_local_models:
             # Para modelos locais (phi3), forçamos o título se não estiver no prompt central
             if "-- TITLE:" not in system_msg["content"]:
                  system_msg["content"] += "\n- Output MUST start with '-- TITLE: <English Title>'\n"

        answer = _invoke_llm(llm, system_msg, user_msg)
    except Exception as e:
        fallback = (
            "Error formatting the response with the AI. "
            "Data was queried successfully, but I could not generate a summary."
        )
        state["answer"] = fallback
        log_event(
            "formatter_llm_error",
            {
                "agent_id": agent_config.id,
                "error": str(e)[:500],
                "lang": lang,
            },
        )
        return state

    if settings.use_local_models:
        # Some local models return literal \n
        answer = answer.replace('\\n', '\n')
        lines = answer.strip().split('\n')
        title = None
        answer_lines = []
        for line in lines:
            if line.strip().upper().startswith("-- TITLE:"):
                title = line.split(":", 1)[1].strip()
            elif line.strip():
                answer_lines.append(line)
        
        if title:
            state["generated_title"] = title
        answer = "\n".join(answer_lines).strip()

    answer = answer.strip() or "No explanation available."
    
    # 🎯 FOLLOW-UP SUGGESTIONS: Generate smart suggestions based on available schema
    followup_suggestions = []
    try:
        # Extract available tables from agent_config
        available_tables = [t.logical_name for t in agent_config.tables]
        
        # Extract columns from the tables that were used
        chosen_tables = state.get("chosen_tables") or [state.get("chosen_table")]
        available_columns = []
        for table in agent_config.tables:
            if table.logical_name in chosen_tables:
                for col in (table.columns or []):
                    col_name = col.get("name") if isinstance(col, dict) else getattr(col, "name", "")
                    if col_name:
                        available_columns.append(col_name)
        
        # Generate suggestions (only if we have data and answer)
        if data and answer and len(answer) > 50:
            # 🎯 ZERO-COST SUGGESTIONS: Use static engine
            user_crew_role = state.get("crew_role", "guest")
            
            followup_suggestions = suggestion_engine.get_suggestions(
                tables=chosen_tables, # Use the tables actually used in the query
                role=user_crew_role,
                max_suggestions=3
            )
    except Exception as e:
        log_event(
            "formatter_followup_error",
            {"error": str(e)[:200]},
        )
        followup_suggestions = []
    
    # Append suggestions as markdown if we have any
    if followup_suggestions:
        # Clean formatting without markdown separators
        suggestions_md = "\n\n💡 Suggested Follow-up:\n"
        for i, suggestion in enumerate(followup_suggestions, 1):
            suggestions_md += f"{i}. {suggestion}\n"
        answer = answer + suggestions_md
        
        log_event(
            "formatter_added_followup_suggestions",
            {
                "agent_id": agent_config.id,
                "num_suggestions": len(followup_suggestions),
            },
        )
    
    state["answer"] = answer
    state["last_suggestions"] = followup_suggestions

    log_event(
        "formatter_success",
        {
            "agent_id": agent_config.id,
            "answer_preview": answer[:200],
            "num_rows": len(data),
            "lang": lang,
            "has_followup_suggestions": len(followup_suggestions) > 0,
        },
    )

    return state

