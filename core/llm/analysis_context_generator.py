import re
import json
from typing import Dict, Any, Optional, List
from core.agents.generic_sql_agent import AgentState
from core.llm.providers import LLMProvider
from core.contracts.analysis_context import AnalysisContext
from core.context.analysis_session_store import AnalysisSessionStore
from core.logging_utils import log_event


def _extract_metric_dimension_from_sql(sql: str) -> Dict[str, Optional[str]]:
    """
    Deterministically extracts primary metric and dimension from SQL.
    Simple heuristic:
    - Metric: First aggregated column (SUM, COUNT, AVG, etc.)
    - Dimension: First column in GROUP BY or first non-aggregated column
    """
    sql = sql.lower()

    # 1. Extract SELECT clause
    select_match = re.search(r"select\s+(.*?)\s+from", sql, re.DOTALL)
    if not select_match:
        return {"metric": None, "dimension": None}

    select_part = select_match.group(1).strip()
    columns = [c.strip() for c in select_part.split(",")]

    metric = None
    dimension = None

    # regex for aggregation
    agg_pattern = re.compile(r"(sum|count|avg|min|max)\s*\(", re.IGNORECASE)

    for col in columns:
        # Check if it's an aggregation
        if agg_pattern.search(col):
            if not metric:
                # Clean up alias (AS ...)
                metric = re.split(r"\s+as\s+", col, flags=re.IGNORECASE)[-1].strip()
        else:
            if not dimension and "*" not in col:
                # Clean up alias
                dimension = re.split(r"\s+as\s+", col, flags=re.IGNORECASE)[-1].strip()
                # Remove table prefix if present
                if "." in dimension:
                    dimension = dimension.split(".")[-1]

    # Fallback if no specific dimension found but group by exists
    if not dimension:
        group_match = re.search(
            r"group\s+by\s+(.+?)(\s+order|\s+limit|$)", sql, re.DOTALL | re.IGNORECASE
        )
        if group_match:
            # use first group by col
            dimension = group_match.group(1).split(",")[0].strip()

    return {"metric": metric, "dimension": dimension}


#: Nomes de coluna que dizem «tempo».
_COLUNA_DE_TEMPO = re.compile(
    r"(?:^|_)(?:date|data|fecha|dia|day|week|semana|month|mes|year|ano|"
    r"quarter|trimestre|hour|hora|time|timestamp|period|periodo)(?:$|_)"
    r"|_at$|_on$|^dt_|_dt$",
    re.IGNORECASE,
)
_FUNCAO_DE_TEMPO = re.compile(
    r"\b(?:date_trunc|date_part|extract|to_char|strftime|date|year|month|week)\s*\(",
    re.IGNORECASE,
)


def _lista_do_select(baixo: str) -> List[str]:
    """As expressões do SELECT de topo, separadas por vírgulas fora de
    parêntesis (para resolver ``GROUP BY 1``)."""
    m = re.search(r"\bselect\s+(.*?)\bfrom\b", baixo, re.DOTALL)
    if not m:
        return []
    partes, nivel, atual = [], 0, ""
    for ch in m.group(1):
        if ch == "(":
            nivel += 1
        elif ch == ")":
            nivel -= 1
        if ch == "," and nivel == 0:
            partes.append(atual.strip())
            atual = ""
        else:
            atual += ch
    if atual.strip():
        partes.append(atual.strip())
    return partes


def _infer_analysis_type(sql: str) -> Dict[str, Any]:
    """Tipo de análise e coluna de tempo, lidos do SQL — sem modelo.

    Até 12/10/2026 isto era uma chamada ao modelo do especialista, no caminho
    do pedido, DEPOIS de a resposta estar pronta e ANTES do formatador: mais
    uma ida ao qwen em cada pergunta (286 ms na de «Lista las 5
    gasolineras…», segundos quando o fornecedor está lento). O resultado só
    alimenta o plano de dashboards e cabia em cinco regras sobre o SQL.
    """
    baixo = (sql or "").lower()
    group = re.search(
        r"\bgroup\s+by\s+(.+?)(?:\border\s+by\b|\blimit\b|\bhaving\b|$)",
        baixo,
        re.DOTALL,
    )
    agrupadas: List[str] = []
    if group:
        do_select = _lista_do_select(baixo)
        for c in (c.strip() for c in group.group(1).split(",")):
            if not c:
                continue
            if c.isdigit() and 0 < int(c) <= len(do_select):
                c = do_select[int(c) - 1]
            agrupadas.append(c)

    def colunas_de_tempo(expr: str) -> List[str]:
        expr = re.split(r"\s+as\s+", expr)[0]
        nomes = [n.split(".")[-1] for n in re.findall(r"[a-z_][a-z0-9_.]*", expr)]
        return [n for n in nomes if _COLUNA_DE_TEMPO.search(n)]

    def e_tempo(expr: str) -> bool:
        return bool(_FUNCAO_DE_TEMPO.search(expr) or colunas_de_tempo(expr))

    tempo = next((c for c in agrupadas if e_tempo(c)), None)
    time_column = None
    if tempo:
        candidatas = colunas_de_tempo(tempo)
        time_column = candidatas[-1] if candidatas else None

    agregada = bool(re.search(r"\b(?:sum|count|avg|min|max)\s*\(", baixo))
    if tempo:
        tipo = "trend"
    elif agrupadas and re.search(r"\border\s+by\b", baixo) and re.search(
        r"\blimit\s+\d+", baixo
    ):
        tipo = "comparison"
    elif agrupadas:
        tipo = "distribution"
    elif agregada:
        tipo = "kpi"
    elif re.search(r"\bselect\b", baixo):
        tipo = "list"
    else:
        tipo = "other"
    return {"analysis_type": tipo, "time_column": time_column}


def generate_and_save_analysis_context(
    state: AgentState, llm: Optional[LLMProvider] = None
) -> None:
    """
    Main entry point. Extracts context from state/SQL and saves to session store.

    ``llm`` já não é usado (o tipo de análise lê-se do SQL); fica na
    assinatura para não partir quem o passa.
    """
    # 1. Validate inputs
    if not state.get("sql") or not state.get("user_id"):
        return

    try:
        sql = state.get("sql")
        question = state.get("question")
        user_id = state.get("user_id")
        # Connection ID is not explicitly in AgentState, we typically use 'default' or derive from agent_config if available.
        # Ideally, we should pass agent_config here, but for now let's use a default or assume single connection scope.
        # Wait, AnalysisSessionStore needs connection_id.
        # In generic_sql_agent, scope might be implied. Let's use 'default' or a placeholder if missing.
        # Or better: derive from chosen_table schema if possible.
        connection_id = "default"

        # 2. Deterministic Extraction
        det_data = _extract_metric_dimension_from_sql(sql)

        # 3. Tipo de análise — determinístico (ver _infer_analysis_type).
        import time as _time

        _t0 = _time.perf_counter()
        llm_data = _infer_analysis_type(sql)

        # 4. Construct Context
        # Validated tables
        tables = state.get("chosen_tables") or (
            [state.get("chosen_table")] if state.get("chosen_table") else []
        )

        # Primary Entity: usually the main table or derived from dimension
        primary_entity = tables[0] if tables else "unknown"

        context = AnalysisContext(
            version=1,
            primary_entity=primary_entity,
            primary_metric=det_data["metric"]
            or "count",  # default to count if None/count(*)
            primary_dimension=det_data["dimension"],
            time_column=llm_data.get("time_column"),
            detected_analysis_type=llm_data.get("analysis_type", "other"),
            validated_tables=tables,
            validated_columns=[],  # Extracting all columns from SQL regex is complex, leave empty or improve later
        )

        # 5. Save
        AnalysisSessionStore.save(user_id, connection_id, context)

        log_event(
            "analysis_context_generated",
            {
                "user_id": user_id,
                "type": context.detected_analysis_type,
                "metric": context.primary_metric,
            },
        )
        try:
            from latency_timing import registar_tempo

            registar_tempo(
                "analysis_context_timing",
                (_time.perf_counter() - _t0) * 1000,
                detalhe="analysis_context",
                type=context.detected_analysis_type,
                llm=False,
            )
        except Exception:
            pass

    except Exception as e:
        log_event("analysis_context_generation_failed", {"error": str(e)})
