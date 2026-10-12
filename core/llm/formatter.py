# core/llm/formatter.py
from __future__ import annotations

from typing import Dict, Any, List, Optional
import json
import re

from core.agents.generic_sql_agent import AgentState, AgentConfig
from core.llm.providers import LLMProvider
from core.i18n.i18n import detect_language, get_message, resolve_language
from core.logging_utils import log_event
from config.settings import settings
from core.llm.prompts.formatter_prompts import (
    build_formatter_prompt,
    sql_executado,
)
from core.llm.nomes import regras_de_nomes
from core.llm.numeros import (
    corrigir_resposta,
    descricoes_das_colunas,
    regras_de_numeros,
    unidades_do_resultado,
)
from core.llm.conceito_em_falta import conceito_em_falta, traduzir_conceito
from core.llm.context.builder import build_context_bundle


def _mask_result_columns(
    rows: List[Dict[str, Any]],
    security_config: Any,
    table_name: str = "",
) -> List[Dict[str, Any]]:
    """Mask blocked/disallowed columns in query results (defense in depth).

    Even if the SQL generation stage allowed a blocked column through,
    this post-processing step ensures it is masked before reaching the user.
    """
    if not rows or not security_config:
        return rows

    # Extract blocked and allowed columns from security_config
    global_blocked = set()
    table_blocked = set()
    table_allowed = None

    if hasattr(security_config, "global_blocked_columns"):
        global_blocked = {
            c.lower() for c in (security_config.global_blocked_columns or [])
        }
    elif isinstance(security_config, dict):
        global_blocked = {
            c.lower() for c in (security_config.get("global_blocked_columns") or [])
        }

    tables_cfg = getattr(security_config, "tables", None) or (
        security_config.get("tables") if isinstance(security_config, dict) else {}
    )
    if table_name and tables_cfg:
        tc = tables_cfg.get(table_name, {})
        if hasattr(tc, "blocked_columns"):
            table_blocked = {c.lower() for c in (tc.blocked_columns or [])}
            if tc.allowed_columns:
                table_allowed = {c.lower() for c in tc.allowed_columns}
        elif isinstance(tc, dict):
            table_blocked = {c.lower() for c in (tc.get("blocked_columns") or [])}
            if tc.get("allowed_columns"):
                table_allowed = {c.lower() for c in tc["allowed_columns"]}

    all_blocked = global_blocked | table_blocked
    if not all_blocked and table_allowed is None:
        return rows

    masked = []
    for row in rows:
        new_row = {}
        for col, val in row.items():
            col_lower = col.lower()
            if col_lower in all_blocked:
                new_row[col] = None
            elif table_allowed is not None and col_lower not in table_allowed:
                new_row[col] = None
            else:
                new_row[col] = val
        masked.append(new_row)
    return masked


#: Palavras que abrem ou fecham uma pergunta e não são o assunto dela.
#: Comparadas sem acentos. Visto em produção (10/10): «¿Cuántos clientes
#: tengo?» virava «No encontré datos sobre cuántos clientes tengo» e
#: «¿Quantos clientes eu tenho?» virava «…sobre clientes tenho».
_PALAVRAS_DE_PERGUNTA = {
    # pt
    "qual",
    "quais",
    "como",
    "quem",
    "onde",
    "quando",
    "quanto",
    "quanta",
    "quantos",
    "quantas",
    "que",
    "o",
    "a",
    "os",
    "as",
    "um",
    "uma",
    "uns",
    "umas",
    "de",
    "do",
    "da",
    "dos",
    "das",
    "sobre",
    "pelo",
    "pela",
    "pelos",
    "pelas",
    "no",
    "na",
    "nos",
    "nas",
    "eu",
    "nos",
    "tenho",
    "temos",
    "tem",
    "ha",
    "existem",
    "existe",
    "mostra",
    "mostre",
    "me",
    "diga",
    "diz",
    "liste",
    "lista",
    "busque",
    "traz",
    "traga",
    "encontre",
    "por",
    "foi",
    "foram",
    "sao",
    "e",
    "meus",
    "minhas",
    "meu",
    "minha",
    "nossos",
    "nossas",
    # es
    "cual",
    "cuales",
    "cuanto",
    "cuanta",
    "cuantos",
    "cuantas",
    "quien",
    "donde",
    "cuando",
    "el",
    "la",
    "los",
    "las",
    "un",
    "unos",
    "unas",
    "del",
    "yo",
    "nosotros",
    "tengo",
    "tenemos",
    "tiene",
    "tienen",
    "hay",
    "existen",
    "muestra",
    "muestrame",
    "dime",
    "mis",
    "mi",
    "nuestros",
    "nuestras",
    "son",
    "es",
    "fue",
    "fueron",
    "he",
    "hemos",
    # en
    "show",
    "list",
    "find",
    "search",
    "tell",
    "what",
    "how",
    "many",
    "much",
    "where",
    "when",
    "which",
    "who",
    "why",
    "can",
    "could",
    "you",
    "the",
    "an",
    "on",
    "of",
    "in",
    "at",
    "for",
    "to",
    "with",
    "by",
    "from",
    "about",
    "i",
    "we",
    "do",
    "does",
    "have",
    "has",
    "there",
    "are",
    "is",
    "my",
    "our",
}


def _sem_acentos(p: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFD", p) if unicodedata.category(c) != "Mn"
    )


def _extract_topic(question: str) -> str:
    """O assunto da pergunta, como substantivo limpo, para «não encontrei
    dados sobre {topic}».

    Tira as palavras de pergunta, pronomes e verbos de posse do início E do
    fim — «¿Cuántos clientes tengo?» → «clientes». Se nada sobrar, devolve
    vazio e quem chama usa a mensagem genérica.
    """
    q = re.sub(r"[¿¡?!.,;:«»\"']", " ", question or "")
    words = q.split()
    while words and _sem_acentos(words[0].lower()) in _PALAVRAS_DE_PERGUNTA:
        words.pop(0)
    while words and _sem_acentos(words[-1].lower()) in _PALAVRAS_DE_PERGUNTA:
        words.pop()
    if len(words) > 4:
        return " ".join(words[:4]) + "..."
    return " ".join(words)


def mensagem_sem_dados(
    question: str, impossible_reason: Optional[str], lang: str
) -> str:
    """A resposta quando não há dados — a mesma na escrita, no streaming e na voz.

    Se o especialista (ou `conceito_ausente`) disse o que falta, diz-se isso,
    com o mais próximo, na língua da resposta. Senão, «não encontrei dados
    sobre <assunto>», com o assunto limpo, ou a genérica.
    """
    falta = conceito_em_falta(impossible_reason)
    if falta:
        o_que, proximo = traduzir_conceito(falta[0], falta[1], lang)
        if proximo:
            return get_message("MISSING_CONCEPT", lang, falta=o_que, proximo=proximo)
        return get_message("MISSING_CONCEPT_NO_NEAREST", lang, falta=o_que)
    topic = _extract_topic(question)
    if not topic:
        return get_message("NO_DATA_GENERIC", lang)
    return get_message("NO_DATA_FOUND", lang, topic=topic)


_CONJUNCAO = {"es": " y ", "pt": " e ", "en": " and "}


def mensagem_sem_resultados(sql: Optional[str], lang: str) -> Optional[str]:
    """0 linhas com filtros de TEXTO por literal: «no hay resultados para
    origem = BADAJOZ y destino = MADRID» — o caso em que um literal errado é
    plausível (depois da tentativa de correcção no especialista).

    Devolve None quando o SQL não tem filtros desses (só datas, números…):
    aí «0 linhas» é a resposta certa e quem a redige é o modelo, com a regra
    REGRA_ZERO_LINHAS («No hay lotes a punto de caducar en los próximos 7
    días» lê-se bem no fio de um agente; uma frase fixa lê-se como sistema).
    A mesma decisão na escrita e no streaming."""
    try:
        from core.sql.correcao_de_literais import descrever_filtros

        pares = descrever_filtros(sql)
    except Exception:
        pares = []
    if not pares:
        return None
    filtro = _CONJUNCAO.get(lang, " and ").join(f"{c} = {v}" for c, v in pares)
    return get_message("NO_ROWS_FOR_FILTER", lang, filtro=filtro)


def _serialize_for_json(obj: Any) -> Any:
    """Converte objetos não-serializáveis (date, datetime, decimal) para strings/floats."""
    from datetime import date, datetime
    from decimal import Decimal

    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _serialize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_for_json(v) for v in obj]
    return obj


_NUM_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


def _as_number(value: Any) -> Optional[float]:
    """Número, ou texto que é um número (as APIs públicas espanholas mandam
    preços como ``"1,749"`` — vírgula decimal). Códigos com zero à esquerda
    (``"06713"``, código postal) não são números."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value else None  # NaN fora
    if isinstance(value, str):
        s = value.strip()
        if not _NUM_RE.match(s):
            return None
        digits = s.lstrip("+-")
        if len(digits) > 1 and digits[0] == "0" and digits[1].isdigit():
            return None
        return float(s.replace(",", "."))
    return None


_COORD_NAMES = ("lat", "lon", "lng", "latitude", "longitude", "latitud", "longitud")


def _is_id_column(name: str) -> bool:
    """Colunas sem média que interesse: identificadores (``IDEESS``,
    ``user_id``, ``orderId``, ``@id``) e coordenadas (``Latitud``,
    ``Longitud (WGS84)``) — ocupavam os lugares do preço."""
    raw = str(name).rsplit(".", 1)[-1].lstrip("@")
    low = raw.lower().replace(" ", "_")
    if low.split("_(")[0].split("(")[0].strip("_") in _COORD_NAMES:
        return True
    return (
        low in ("id", "version")
        or low.startswith("id_")
        or low.endswith("_id")
        or raw.startswith("ID")
        or raw.endswith("Id")
    )


def _fmt_num(x: float) -> str:
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return f"{x:.4f}".rstrip("0").rstrip(".")


def _full_result_stats(rows: List[Dict[str, Any]], shown: int) -> str:
    """Aviso de amostra + estatísticas sobre TODAS as linhas (Anexo C, D4).

    O prompt só leva as primeiras ``shown`` linhas. Sem isto, «o mais
    barato», «quantos» ou «o próximo» sobre 277 postos ou 32 feriados eram
    respondidos com as 15 primeiras, sem aviso nenhum.
    """
    total = len(rows)
    columns: List[str] = []
    for row in rows[:50]:
        if isinstance(row, dict):
            for key in row:
                if key not in columns:
                    columns.append(key)

    lines = [
        f"SAMPLE NOTICE: the result has {total} rows; the DATA PREVIEW above shows "
        f"only the first {shown}. Say in the answer that the listed rows are a sample "
        f"of {total}. For counts, totals, minimums, maximums and averages use ONLY the "
        f"statistics below, computed over ALL {total} rows — never the preview."
    ]
    numeric = 0
    for col in columns:
        if numeric >= 8 or _is_id_column(col):
            continue
        present = [
            r.get(col)
            for r in rows
            if isinstance(r, dict) and r.get(col) not in (None, "")
        ]
        values = [(i, _as_number(v)) for i, v in enumerate(present)]
        nums = [(i, v) for i, v in values if v is not None]
        if len(nums) < 2 or len(nums) < 0.8 * len(present):
            continue
        numeric += 1
        vals = [v for _, v in nums]
        lo = min(nums, key=lambda t: t[1])
        hi = max(nums, key=lambda t: t[1])
        lines.append(
            f"- {col}: count={len(vals)}, min={_fmt_num(min(vals))}, "
            f"max={_fmt_num(max(vals))}, avg={_fmt_num(sum(vals) / len(vals))}, "
            f"sum={_fmt_num(sum(vals))}"
        )
        if numeric <= 3:
            # A linha do mínimo e a do máximo: «o mais barato» precisa do
            # nome do posto, não só do preço.
            with_col = [
                r for r in rows if isinstance(r, dict) and r.get(col) not in (None, "")
            ]
            for label, (idx, _) in (("min", lo), ("max", hi)):
                row_txt = json.dumps(
                    _serialize_for_json(with_col[idx]), ensure_ascii=False, default=str
                )
                lines.append(f"  row with {label} {col}: {row_txt[:400]}")
    return "\n".join(lines)


def _compute_basic_stats(
    data_sample: List[Dict[str, Any]],
    all_rows: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Gera um pequeno texto com estatísticas básicas da primeira coluna numérica encontrada.

    Com ``all_rows`` maior do que a amostra, devolve o aviso de amostra e as
    estatísticas calculadas sobre o resultado inteiro (ver
    ``_full_result_stats``).
    """
    if (
        isinstance(all_rows, list)
        and data_sample is not None
        and len(all_rows) > len(data_sample)
    ):
        return _full_result_stats(all_rows, len(data_sample))
    if not data_sample:
        return ""

    first_row = data_sample[0]
    numeric_cols = [k for k, v in first_row.items() if isinstance(v, (int, float))]
    if not numeric_cols:
        return ""

    col = numeric_cols[0]
    values = [row[col] for row in data_sample if isinstance(row.get(col), (int, float))]
    if not values:
        return ""

    total = len(data_sample)

    # A single value (almost always an AGGREGATE — COUNT/SUM/AVG) has mean==min
    # ==max trivially. Emitting them makes the formatter narrate "no variation /
    # all values are the same", which is misleading: one aggregated row says
    # nothing about the spread of the underlying rows. Suppress the spread stats
    # and flag it instead.
    if len(values) <= 1:
        return (
            f"'{col}' is a single aggregated value, not a distribution — "
            "do NOT describe variation, uniformity, or min/max."
        )

    mean_val = sum(values) / len(values)
    min_val = min(values)
    max_val = max(values)

    return (
        f"Basic statistics for '{col}': total_rows_sample={total}, "
        f"mean={mean_val:.2f}, min={min_val:.2f}, max={max_val:.2f}"
    )


def _ensure_language(
    question: str,
    detected_language: Optional[str],
    locale: Optional[str] = None,
) -> str:
    """Resolve the response language.

    Delegates to :func:`resolve_language`, the single source of truth, so the
    account/platform preference wins over per-message statistical detection.
    This used to detect from the question alone, which answered a Portuguese
    account in English whenever one short question failed to trip the
    detector — the user saw the language flip mid-conversation.

    ``detected_language`` is passed as the thread language: it is the language
    already established in the conversation, so short follow-ups stay sticky.
    """
    # ``detected_language`` chega aqui JÁ DECIDIDO pelo orquestrador, com a
    # regra inteira (locale → pergunta clara → conversa). Voltar a detectar
    # a pergunta deixava-a ganhar a essa decisão — e a pergunta que o
    # formatador vê pode já não ser a da pessoa (recontextualizada).
    if not (locale or "").strip():
        _ja = (detected_language or "").strip().lower()[:2]
        if _ja in ("en", "pt", "es"):
            return _ja
    try:
        return resolve_language(
            question or "",
            locale=locale,
            thread_language=detected_language,
        )
    except Exception:
        # Never let language resolution break an answer.
        return detected_language or "en"


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
    # UNLESS we have RAG context that might provide a better answer.
    retrieval_context = state.get("retrieval_context") or []
    if state.get("answer") and not data and not retrieval_context:
        log_event(
            "formatter_skipped_preservation",
            {
                "agent_id": agent_config.id,
                "reason": "Orchestrator answer preserved",
                "answer_preview": state["answer"][:100],
            },
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
            data = data_list  # Atualiza local para uso nas samples

            # Amostra para o prompt
            data_sample_list = data[:15]
        else:
            total_rows = len(data) if data else 0
            data_sample_list = data[:15] if data else []
    except ImportError:
        total_rows = len(data) if data else 0
        data_sample_list = data[:15] if data else []

    # === Column-level masking (defense in depth) ===
    # Even if the LLM bypassed schema filtering, mask blocked columns
    # in the result data before returning to the user.
    security_config = state.get("security_config")
    if security_config and data_sample_list:
        chosen_table = state.get("chosen_table", "")
        data_sample_list = _mask_result_columns(
            data_sample_list, security_config, chosen_table
        )
        # Also mask the full data in state
        if data:
            state["data"] = _mask_result_columns(data, security_config, chosen_table)

    # Garante idioma base
    lang = _ensure_language(question, detected_language)
    state["detected_language"] = lang

    # 1) Se houve erro técnico (SQL, conexão, etc.) -> passa amigável
    if error:
        # Se for um erro do validador ou execução, usamos mensagem amigável
        state["answer"] = get_message("TECHNICAL_ERROR", lang)
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

    # 1b) Os dados nao tem o que se perguntou: dize-lo, com o mais proximo.
    # Antes do RAG de proposito — um documento sobre clientes nao responde a
    # «quantos clientes temos» quando a base nao os regista.
    _falta = conceito_em_falta(impossible_reason) if not data else None
    if _falta:
        falta, proximo = _falta
        state["answer"] = mensagem_sem_dados(question, impossible_reason, lang)
        log_event(
            "formatter_missing_concept",
            {
                "agent_id": agent_config.id,
                "falta": falta[:120],
                "proximo": (proximo or "")[:120],
                "lang": lang,
            },
        )
        return state

    # 1c) A consulta CORREU, não devolveu nada e filtrava texto por literal:
    # diz-se o filtro que não encontrou nada. Antes caía no LLM com o RAG e
    # saía «Lo siento, pero no puedo proporcionar esa lista» (11/10/2026).
    # Sem filtros de texto, segue para o LLM com a regra das 0 linhas.
    _sem_resultados = (
        mensagem_sem_resultados(state.get("sql"), lang)
        if not data and state.get("sql") and not impossible_reason
        else None
    )
    if _sem_resultados:
        state["answer"] = _sem_resultados
        log_event(
            "formatter_zero_rows",
            {
                "agent_id": agent_config.id,
                "question": question[:200],
                "lang": lang,
            },
        )
        return state

    # 2) Caso o especialista tenha marcado como IMPOSSIBLE ou não houver dados,
    # mas temos contexto de recuperação (RAG), usamos o LLM para tentar responder.
    retrieval_context = state.get("retrieval_context") or []

    if (impossible_reason or not data) and retrieval_context:
        log_event(
            "formatter_using_rag_fallback",
            {
                "agent_id": agent_config.id,
                "impossible_reason": impossible_reason,
                "num_rag_chunks": len(retrieval_context),
            },
        )
        # Prossegue para o passo 4 (invocação do LLM)
    elif impossible_reason and not data:
        # Tenta ser amigável quando não entende/não encontra dados e NÃO TEM RAG
        topic = _extract_topic(question)
        state["answer"] = mensagem_sem_dados(question, None, lang)

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

    # 3) Sem dados e sem impossible_reason e NÃO TEM RAG -> resposta simples.
    # Excepto quando houve SQL executado: «0 linhas» é a resposta e o modelo
    # redige-a nos termos da pergunta (REGRA_ZERO_LINHAS), em vez de «no
    # encontré datos… pruebe a reformular».
    if not data and not retrieval_context and not sql_executado(state.get("sql")):
        topic = _extract_topic(question)
        state["answer"] = mensagem_sem_dados(question, None, lang)
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
    # Estatísticas sobre o resultado INTEIRO (já mascarado) quando a amostra
    # não o mostra todo.
    stats_text = _compute_basic_stats(
        data_sample_list, all_rows=state.get("data") or data
    )

    # Obter orientações de comprimento amigáveis
    length = state.get("length")
    length_guidance = ""
    if length is not None:
        if length < 30:
            length_guidance = "- Keep the answer VERY SHORT (maximum 2 sentences).\n"
        elif length < 70:
            length_guidance = (
                "- Keep the answer SHORT and OBJECTIVE (maximum 4 sentences).\n"
            )
        else:
            length_guidance = (
                "- You can provide a MORE DETAILED answer (up to 8 sentences).\n"
            )

    # Unidades das colunas (nome, linhagem do SQL, descrição): «36,81» de
    # service_sec é «36,81 s» (12/10/2026).
    _colunas_resultado = (
        list(data[0].keys()) if data and isinstance(data[0], dict) else []
    )
    try:
        _descricoes = descricoes_das_colunas(
            getattr(agent_config, "tables", None),
            list(state.get("chosen_tables") or []) + [state.get("chosen_table")],
        )
        _unidades = unidades_do_resultado(
            _colunas_resultado, state.get("sql"), _descricoes
        )
    except Exception as _e:  # nunca partir uma resposta por causa disto
        log_event("formatter_unidades_falhou", {"error": str(_e)[:300]})
        _unidades = {}

    # 🏗️ BUILD PROMPTS (Unified Logic)
    # This replaces the dual legacy blocks (OpenAI/Local) with a single source of truth.
    system_msg, user_msg = build_formatter_prompt(
        context_bundle=context_bundle,
        question=question,
        sql=state.get("sql", "N/A"),
        data_preview=sample_json if data else "[]",
        stats_summary=stats_text if data else None,
        has_data=bool(data),
        is_impossible=bool(impossible_reason),
        impossible_reason=impossible_reason or "",
        response_format=state.get("response_format"),
        length_guidance=length_guidance,
        extra_instructions=state.get("instructions"),
        ai_tone=state.get("ai_tone"),
        ai_style=state.get("ai_style"),
        detected_language=lang,
        # As colunas decidem se ha dinheiro na resposta, e portanto se os
        # numeros levam simbolo de moeda. E o ESQUEMA que sabe: a pergunta nao
        # sabe — «quantas faturas» tem «fatura» e e uma contagem.
        regras_dos_numeros=regras_de_numeros(
            lang,
            colunas=_colunas_resultado,
            moeda_pedida=state.get("currency"),
            unidades=_unidades,
        )
        + regras_de_nomes(),
    )

    try:
        if settings.use_local_models:
            # Para modelos locais (phi3), forçamos o título se não estiver no prompt central
            if "-- TITLE:" not in system_msg["content"]:
                system_msg[
                    "content"
                ] += "\n- Output MUST start with '-- TITLE: <English Title>'\n"

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
        answer = answer.replace("\\n", "\n")
        lines = answer.strip().split("\n")
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

    # O modelo nem sempre segue as regras dos números nem fala com quem
    # pergunta («El usuario ha facturado un total de 6 153 185,72.», 10/10).
    # A correcção determinística vê o resultado e sabe o que é dinheiro.
    try:
        answer = corrigir_resposta(
            answer,
            lang,
            state.get("data") or data,
            state.get("currency"),
            pergunta=question,
            unidades=_unidades,
        )
    except Exception as _e:  # nunca partir uma resposta por causa disto
        log_event("formatter_correcao_falhou", {"error": str(_e)[:300]})

    # FOLLOW-UP SUGGESTIONS: disabled by product decision — the chat shows only
    # the answer, with no appended "Suggested Follow-up" questions. Kept as an
    # empty list so the downstream state (``last_suggestions``) and the
    # ``has_followup_suggestions`` meta flag stay consistent.
    followup_suggestions = []

    # Prepend period fallback warning — must come before the number, never silent
    periodo_aviso = state.get("periodo_aviso")
    if periodo_aviso and state.get("periodo_modo") == "fallback":
        answer = f"{periodo_aviso}\n\n{answer}"

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
