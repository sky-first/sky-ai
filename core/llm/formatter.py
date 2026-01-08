# core/llm/formatter.py
from __future__ import annotations

from typing import Dict, Any, List, Optional
import json

from core.agents.generic_sql_agent import AgentState, AgentConfig
from core.llm.providers import LLMProvider
from core.i18n.i18n import detect_language
from core.logging_utils import log_event


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
    detected_language = state.get("detected_language")

    # Se já existe uma answer preenchida, não mexe
    if state.get("answer"):
        return state

    # Garante idioma base
    lang = _ensure_language(question, detected_language)
    state["detected_language"] = lang

    # 1) Se houve erro técnico (SQL, conexão, etc.) → passa direto
    if error:
        # Aqui poderíamos usar LLM para formatar erro bonito no idioma,
        # mas por simplicidade mantemos o erro cru.
        state["answer"] = str(error)
        log_event(
            "formatter_error_passthrough",
            {
                "agent_id": agent_config.id,
                "error": str(error)[:300],
                "lang": lang,
            },
        )
        return state

    # 2) Caso o especialista tenha marcado como IMPOSSIBLE
    if impossible_reason and not data:
        # Detectar se a pergunta é sobre permissões/schema (resposta mais amigável)
        question_lower = question.lower()
        is_permission_question = any([
            "permiss" in question_lower,
            "permission" in question_lower,
            "acesso" in question_lower,
            "access" in question_lower,
            "pode ver" in question_lower,
            "can see" in question_lower,
            "pode acessar" in question_lower,
            "can access" in question_lower,
        ])
        
        if is_permission_question:
            # Resposta direta e amigável para perguntas sobre permissões (agnóstico de domínio)
            if lang.startswith("pt"):
                state["answer"] = (
                    "Não tenho acesso a informações sobre permissões de usuários ou quem pode ver quais tabelas. "
                    "Posso ajudar com perguntas sobre seus dados e análises. "
                    "Por exemplo: 'Qual é a performance mensal?' ou 'Quais são os principais resultados?'"
                )
            elif lang.startswith("es"):
                state["answer"] = (
                    "No tengo acceso a información sobre permisos de usuarios o quién puede ver qué tablas. "
                    "Puedo ayudar con preguntas sobre tus datos y análisis. "
                    "Por ejemplo: '¿Cuál es el rendimiento mensual?' o '¿Cuáles son los principales resultados?'"
                )
            else:
                state["answer"] = (
                    "I don't have access to information about user permissions or who can see which tables. "
                    "I can help with questions about your data and analysis. "
                    "For example: 'What is the monthly performance?' or 'What are the top results?'"
                )
            log_event(
                "formatter_impossible_permission_question",
                {
                    "agent_id": agent_config.id,
                    "question": question[:200],
                    "lang": lang,
                },
            )
            return state
        
        # Para outros casos de IMPOSSIBLE, usar LLM para gerar resposta
        system_msg = {
            "role": "system",
            "content": (
                "You are a helpful assistant.\n"
                "The model tried to answer a question with the available data/schema, "
                "but it was marked as IMPOSSIBLE.\n\n"
                "Your job is to explain this to the user in a SHORT, FRIENDLY, and OBJECTIVE way "
                f"(maximum 2-3 sentences) in the same language as the user's question "
                f"(language code '{lang}').\n\n"
                "IMPORTANT: Do NOT mention technical terms like 'schemas', 'metadata', 'permissions', or 'system tables'. "
                "Instead, suggest what kind of business questions the user CAN ask about their data.\n"
            ),
        }

        user_msg = {
            "role": "user",
            "content": (
                f"User question:\n{question}\n\n"
                f"Reason why it was impossible to answer:\n{impossible_reason}\n\n"
                "Explain briefly why it's not possible to answer this question. "
                "Then suggest 1-2 examples of questions the user CAN ask about their data (performance, metrics, analysis, etc.)."
            ),
        }

        try:
            answer = _invoke_llm(llm, system_msg, user_msg) or ""
        except Exception as e:
            fallback = (
                "It was not possible to answer this question with the current data/context. "
                "If you provide more specific data or connect the right sources, "
                "I can try again."
            )
            state["answer"] = fallback
            log_event(
                "formatter_impossible_llm_error",
                {
                    "agent_id": agent_config.id,
                    "error": str(e)[:500],
                    "lang": lang,
                },
            )
            return state

        if not answer:
            answer = (
                "It was not possible to answer this question with the current data/context. "
                "If you provide more specific data or connect the right sources, "
                "I can try again."
            )

        state["answer"] = answer
        log_event(
            "formatter_impossible_success",
            {
                "agent_id": agent_config.id,
                "answer_preview": answer[:200],
                "lang": lang,
            },
        )
        return state

    # 3) Sem dados e sem impossible_reason → resposta simples
    if not data:
        # Poderíamos pedir pro LLM gerar uma mensagem no idioma, mas por simplicidade:
        msg = "No data was found for this query."
        state["answer"] = msg
        log_event(
            "formatter_no_data",
            {
                "agent_id": agent_config.id,
                "question": question[:200],
                "lang": lang,
            },
        )
        return state

    # 4) Dados retornados: gera explicação em linguagem natural

    data_sample = data[:15]
    serialized_sample = _serialize_for_json(data_sample)
    sample_json = json.dumps(serialized_sample, ensure_ascii=False, indent=2)
    stats_text = _compute_basic_stats(data_sample)

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
            "- Answer in the same language as the question\n"
            "- If data is insufficient, say 'Insufficient data to answer this question'\n"
            "- Keep the answer concise and objective\n\n"
            f"CRITICAL LANGUAGE REQUIREMENT:\n"
            f"- The user question is in language code '{lang}'.\n"
            "- You MUST answer in the same language as the question.\n"
            f"{length_guidance}"
            f"{format_guidance}"
            f"{instructions_block}"
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
