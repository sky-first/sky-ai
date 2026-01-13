# core/llm/formatter.py
from __future__ import annotations

from typing import Dict, Any, List, Optional
import json

from core.agents.generic_sql_agent import AgentState, AgentConfig
from core.llm.providers import LLMProvider
from core.i18n.i18n import detect_language, get_message
from core.logging_utils import log_event


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
            # Converter apenas as primeiras 15 linhas para dicts para o prompt
            data_sample_list = data.slice(0, 15).to_pylist()
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
        state["answer"] = f"{get_message('TECHNICAL_ERROR', lang)} | DEBUG: {str(error)}"
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
    
    # data_sample_list e total_rows já foram calculados acima
    serialized_sample = _serialize_for_json(data_sample_list)
    sample_json = json.dumps(serialized_sample, ensure_ascii=False, indent=2)
    stats_text = _compute_basic_stats(data_sample_list)

    # Obter configurações de formato e instruções do estado
    response_format = state.get("response_format")
    instructions = state.get("instructions")
    length = state.get("length")
    
    # Determinar diretrizes de formato
    format_guidance = ""
    if response_format:
        format_guidance = f"\n- RESPONSE FORMAT: You MUST format your response as {response_format}.\n"
        if response_format.lower() == "json":
            format_guidance += "- Return a valid JSON object with your analysis.\n"
        elif response_format.lower() == "markdown":
            format_guidance += "- Use Markdown formatting (headers, lists, etc.) in your response.\n"
    
    # Determinar diretrizes de comprimento
    length_guidance = ""
    if length is not None:
        if length < 30:
            length_guidance = "- Keep the answer VERY SHORT (maximum 2 sentences).\n"
        elif length < 70:
            length_guidance = "- Keep the answer SHORT and OBJECTIVE (maximum 4 sentences).\n"
        else:
            length_guidance = "- You can provide a MORE DETAILED answer (up to 8 sentences).\n"
    else:
        length_guidance = "- Keep the answer SHORT and OBJECTIVE (maximum 4 sentences).\n"
    
    # Instruções personalizadas
    instructions_block = ""
    if instructions:
        instructions_block = f"\n\nADDITIONAL INSTRUCTIONS:\n{instructions}\n"

    system_msg = {
        "role": "system",
        "content": (
            "You are a data response narrator.\n"
            "Your ONLY job: translate query results into natural language.\n\n"
            "CRITICAL RULES:\n"
            "YOU MUST NOT:\n"
            "- Mention SQL, tables, columns, or technical database terms\n"
            "- Infer data beyond what was provided in the results\n"
            "- Create new queries or suggest queries\n"
            "- Explain how data was retrieved\n"
            "- Answer questions not answered by the results\n"
            "- Mention table names, column names, or database structure\n\n"
            "YOU MUST:\n"
            "- Only use the data provided in the results\n"
            "- Answer ONLY in English - THIS IS A STRICT REQUIREMENT\n"
            "- If data is insufficient, say 'Insufficient data to answer this question'\n"
            "- Keep the answer concise and objective\n\n"
            "CRITICAL LANGUAGE REQUIREMENT:\n"
            "- You MUST answer in English, even if the user question is in another language.\n"
            f"{length_guidance}"
            f"{format_guidance}"
            f"{instructions_block}"
        ),
    }

    user_msg = {
        "role": "user",
        "content": (
            f"User question:\n{question}\n\n"
            f"Total rows returned (not all shown): {total_rows}\n"
            f"{stats_text}\n\n"
            "Sample of the data (up to 15 rows, JSON):\n"
            f"{sample_json}\n\n"
            "Explain the main insight(s) from this data in a concise way, "
            "in the same language as the user's question."
        ),
    }

    try:
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

    answer = answer.strip() or "No explanation available."
    state["answer"] = answer

    log_event(
        "formatter_success",
        {
            "agent_id": agent_config.id,
            "answer_preview": answer[:200],
            "num_rows": len(data),
            "lang": lang,
        },
    )

    return state
