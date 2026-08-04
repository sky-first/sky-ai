"""
periodo_decision.py — LangGraph node between orchestrator and specialist.

Detects temporal questions, resolves the requested period against the actual
data boundary (MIN/MAX query), and classifies the result:

  nao_temporal  — question has no recognized relative period → pass through
  normal        — requested period is within the data range → proceed as-is
  fallback      — period is just beyond the data boundary, within tolerance
                  → use the most recent available period, warn the user
  lacuna        — period is far beyond the boundary, beyond tolerance
                  → return the gap message directly, skip specialist
  sem_dados     — table is empty or period predates all data → pass through

Principle (from spec): proteja a fonte, não o derivado.
  - 'periodo_pedido' and 'periodo_usado' are always kept as separate fields.
  - The warning ALWAYS comes before the number; it is never silent.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Tolerância sobrescrevível por cliente — não constante espalhada no código
# ---------------------------------------------------------------------------
FALLBACK_TOLERANCE: dict[str, int] = {
    "day": 7,
    "week": 28,
    "month": 90,
    "quarter": 180,
    # NOTE: medir gap anual em dias é frágil na fronteira (anos bissextos,
    # fuso horário). O conserto durável é comparar distância na unidade da
    # pergunta: abs(ano_pedido - ano_max) para "year", abs(mes_pedido - mes_max)
    # para "month", etc. 365 cobre 1 ano-calendário sem mascarar dados com
    # mais de 1 ano de atraso (gap 366d → lacuna, gap 365d → fallback).
    "year": 365,
}

# ---------------------------------------------------------------------------
# Estrutura de período resolvido
# ---------------------------------------------------------------------------
@dataclass
class Periodo:
    inicio: date
    fim: date
    unidade: str       # "day" | "week" | "month" | "quarter" | "year"
    descricao: str     # legível PT, ex: "mai/2026"
    descricao_en: str  # legível EN, ex: "May/2026"


# ---------------------------------------------------------------------------
# Detecção de pergunta temporal — keyword-based, sem LLM
# ---------------------------------------------------------------------------
_TEMPORAL_RE = re.compile(
    r"\b("
    # mês: "este mês", "deste mês" (de+este), "neste mês" (em+este)
    r"(?:d?este|neste)\s+m[êe]s|m[êe]s\s+passado|[uú]ltimo\s+m[êe]s|mes\s+anterior"
    r"|this\s+month|last\s+month"
    # trimestre
    r"|(?:d?este|neste)\s+trimestre|trimestre\s+passado|[uú]ltimo\s+trimestre"
    r"|this\s+quarter|last\s+quarter"
    # ano
    r"|(?:d?este|neste)\s+ano|ano\s+passado|[uú]ltimo\s+ano"
    r"|this\s+year|last\s+year"
    # semana
    r"|(?:d?esta|nesta)\s+semana|semana\s+passada|[uú]ltima\s+semana"
    r"|this\s+week|last\s+week"
    r")\b",
    re.IGNORECASE,
)


def detect_temporal_question(question: str) -> bool:
    return bool(_TEMPORAL_RE.search(question))


# ---------------------------------------------------------------------------
# Helpers de calendário
# ---------------------------------------------------------------------------
def _quarter_bounds(d: date) -> Tuple[date, date]:
    q = (d.month - 1) // 3
    start_month = q * 3 + 1
    end_month = start_month + 2
    start = date(d.year, start_month, 1)
    end = date(d.year, end_month, calendar.monthrange(d.year, end_month)[1])
    return start, end


def _month_name_pt(d: date) -> str:
    names = ["jan", "fev", "mar", "abr", "mai", "jun",
             "jul", "ago", "set", "out", "nov", "dez"]
    return f"{names[d.month - 1]}/{d.year}"


def _month_name_en(d: date) -> str:
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{names[d.month - 1]}/{d.year}"


# ---------------------------------------------------------------------------
# Parsing do período relativo a partir da pergunta
# ---------------------------------------------------------------------------
def parse_periodo(question: str, today: date) -> Optional[Periodo]:
    """Extrai o período relativo da pergunta. Retorna None se padrão não reconhecido."""
    q = question.lower()

    if re.search(r"este\s+m[êe]s|this\s+month", q):
        s = date(today.year, today.month, 1)
        e = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        return Periodo(s, e, "month", _month_name_pt(s), _month_name_en(s))

    if re.search(r"m[êe]s\s+passado|[uú]ltimo\s+m[êe]s|mes\s+anterior|last\s+month", q):
        first = date(today.year, today.month, 1)
        e = first - timedelta(days=1)
        s = date(e.year, e.month, 1)
        return Periodo(s, e, "month", _month_name_pt(s), _month_name_en(s))

    if re.search(r"este\s+trimestre|this\s+quarter", q):
        s, e = _quarter_bounds(today)
        n = (today.month - 1) // 3 + 1
        return Periodo(s, e, "quarter", f"T{n}/{today.year}", f"Q{n}/{today.year}")

    if re.search(r"trimestre\s+passado|[uú]ltimo\s+trimestre|last\s+quarter", q):
        s_curr, _ = _quarter_bounds(today)
        e = s_curr - timedelta(days=1)
        s, _ = _quarter_bounds(e)
        n = (e.month - 1) // 3 + 1
        return Periodo(s, e, "quarter", f"T{n}/{e.year}", f"Q{n}/{e.year}")

    if re.search(r"este\s+ano|this\s+year", q):
        s = date(today.year, 1, 1)
        e = date(today.year, 12, 31)
        return Periodo(s, e, "year", str(today.year), str(today.year))

    if re.search(r"ano\s+passado|[uú]ltimo\s+ano|last\s+year", q):
        y = today.year - 1
        return Periodo(date(y, 1, 1), date(y, 12, 31), "year", str(y), str(y))

    if re.search(r"esta\s+semana|this\s+week", q):
        s = today - timedelta(days=today.weekday())
        e = s + timedelta(days=6)
        return Periodo(s, e, "week",
                       f"semana {s.strftime('%d/%m')}–{e.strftime('%d/%m')}",
                       f"week {s.strftime('%b %d')}–{e.strftime('%b %d')}")

    if re.search(r"semana\s+passada|[uú]ltima\s+semana|last\s+week", q):
        s_curr = today - timedelta(days=today.weekday())
        e = s_curr - timedelta(days=1)
        s = e - timedelta(days=6)
        return Periodo(s, e, "week",
                       f"semana {s.strftime('%d/%m')}–{e.strftime('%d/%m')}",
                       f"week {s.strftime('%b %d')}–{e.strftime('%b %d')}")

    return None


# ---------------------------------------------------------------------------
# Detecção de ano absoluto ("de 2019", "em 2027") — eixo absoluto da Spec A
# ---------------------------------------------------------------------------
# Requer preposição temporal antes do ano para evitar capturar quantidades
# ("top 2019 clientes") e identificadores ("fatura nº 2019", "produto 2020").
# A preposição é o discriminador chave: "fatura 2019" não tem prep → não captura;
# "fatura de 2019" tem "de" → captura (e é correto: pergunta temporal).
_ABSOLUTE_YEAR_RE = re.compile(
    r"\b(?:em|de|do\s+ano|no\s+ano|in(?:\s+the\s+year)?|of|for|from)\s+((?:19|20)\d{2})\b",
    re.IGNORECASE,
)


def _extract_absolute_year(question: str) -> Optional[int]:
    """
    Returns an absolute year (int) if the question references it in clear temporal
    context. Returns None for non-temporal uses.

    Passes: "faturamento de 2019", "faturas em 2027", "revenue in 2019"
    Blocks: "top 2019 clientes", "fatura nº 2019", "produto 2020"
    """
    m = _ABSOLUTE_YEAR_RE.search(question)
    return int(m.group(1)) if m else None


def _periodo_from_year(year: int) -> Periodo:
    return Periodo(
        inicio=date(year, 1, 1),
        fim=date(year, 12, 31),
        unidade="year",
        descricao=str(year),
        descricao_en=str(year),
    )


# ---------------------------------------------------------------------------
# Detectar coluna de data principal na tabela
# ---------------------------------------------------------------------------
_DATE_TYPE_KEYWORDS = {"date", "datetime", "timestamp"}
_DATE_NAME_RE = re.compile(
    r"(^date$|_date$|_at$|invoice_date|payment_date|refund_date|"
    r"credit_date|order_date|transaction_date|created_at|updated_at)",
    re.IGNORECASE,
)


def find_date_column(table) -> Optional[str]:
    """Returns the name of the primary date column in the table, or None."""
    candidates = []
    for col in (table.columns or []):
        col_type = (col.get("type") or "").lower()
        col_name = col.get("name") or ""
        is_date_type = any(kw in col_type for kw in _DATE_TYPE_KEYWORDS)
        is_date_name = bool(_DATE_NAME_RE.search(col_name))
        if not (is_date_type or is_date_name):
            continue
        score = (2 if is_date_type else 0) + (1 if "date" in col_type else 0) + (2 if is_date_name else 0)
        candidates.append((score, col_name))
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: -x[0])[0][1]


# ---------------------------------------------------------------------------
# Query MIN/MAX no data source (síncrono)
# ---------------------------------------------------------------------------
def query_data_range(
    data_source,
    physical_name: str,
    date_col: str,
    dialect,
) -> Tuple[Optional[date], Optional[date]]:
    """Returns (min_date, max_date) for the date column. Returns (None, None) on failure."""
    try:
        from core.dialects import Dialect

        if dialect == Dialect.BIGQUERY:
            sql = (
                f"SELECT MIN(CAST(`{date_col}` AS DATE)) AS min_date, "
                f"MAX(CAST(`{date_col}` AS DATE)) AS max_date "
                f"FROM `{physical_name}`"
            )
        else:
            sql = (
                f'SELECT MIN(CAST("{date_col}" AS DATE)) AS min_date, '
                f'MAX(CAST("{date_col}" AS DATE)) AS max_date '
                f'FROM "{physical_name}"'
            )

        rows = data_source.run_query(sql)
        if not rows:
            return None, None

        row = rows[0]
        min_d = row.get("min_date") if hasattr(row, "get") else getattr(row, "min_date", None)
        max_d = row.get("max_date") if hasattr(row, "get") else getattr(row, "max_date", None)

        # Normalize to date (BigQuery may return datetime.date already)
        if hasattr(min_d, "date"):
            min_d = min_d.date()
        if hasattr(max_d, "date"):
            max_d = max_d.date()

        return min_d, max_d
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Lógica de decisão — segue o spec exato
# ---------------------------------------------------------------------------
def _periodo_dentro(p: Periodo, min_date: date, max_date: date) -> bool:
    """True se o período pedido tem qualquer sobreposição com [min_date, max_date]."""
    return p.inicio <= max_date and p.fim >= min_date


def _periodo_de(d: date, unidade: str) -> Periodo:
    """Retorna o Periodo que contém d para a unidade dada."""
    if unidade == "month":
        s = date(d.year, d.month, 1)
        e = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
        return Periodo(s, e, "month", _month_name_pt(s), _month_name_en(s))
    if unidade == "quarter":
        s, e = _quarter_bounds(d)
        n = (d.month - 1) // 3 + 1
        return Periodo(s, e, "quarter", f"T{n}/{d.year}", f"Q{n}/{d.year}")
    if unidade == "year":
        return Periodo(date(d.year, 1, 1), date(d.year, 12, 31), "year", str(d.year), str(d.year))
    if unidade == "week":
        s = d - timedelta(days=d.weekday())
        e = s + timedelta(days=6)
        return Periodo(s, e, "week",
                       f"semana {s.strftime('%d/%m')}–{e.strftime('%d/%m')}",
                       f"week {s.strftime('%b %d')}–{e.strftime('%b %d')}")
    return Periodo(d, d, "day", d.strftime("%d/%m/%Y"), d.strftime("%b %d, %Y"))


def decidir_periodo(
    periodo_pedido: Periodo,
    min_date: Optional[date],
    max_date: Optional[date],
) -> dict:
    """Decision function per spec. Returns dict with 'modo' and related fields."""
    if min_date is None:
        return {"modo": "sem_dados", "min_date": None, "max_date": None}

    if _periodo_dentro(periodo_pedido, min_date, max_date):
        return {"modo": "normal", "periodo_usado": periodo_pedido}

    if periodo_pedido.inicio > max_date:
        gap = (periodo_pedido.inicio - max_date).days
        tol = FALLBACK_TOLERANCE.get(periodo_pedido.unidade, 90)
        if gap <= tol:
            return {"modo": "fallback", "periodo_usado": _periodo_de(max_date, periodo_pedido.unidade)}
        return {"modo": "lacuna", "max_date": max_date, "gap_dias": gap}

    # periodo_pedido.fim < min_date — pediu antes do início dos dados
    return {"modo": "sem_dados", "min_date": min_date, "max_date": max_date}


def _decidir_periodo_absoluto(
    periodo_pedido: Periodo,
    min_date: Optional[date],
    max_date: Optional[date],
) -> dict:
    """For absolute years: no fallback or lacuna — outside range always → sem_dados."""
    if min_date is None:
        return {"modo": "sem_dados", "min_date": None, "max_date": None}
    if _periodo_dentro(periodo_pedido, min_date, max_date):
        return {"modo": "normal", "periodo_usado": periodo_pedido}
    return {"modo": "sem_dados", "min_date": min_date, "max_date": max_date}


# ---------------------------------------------------------------------------
# Mensagens de aviso localizadas
# ---------------------------------------------------------------------------
def _build_aviso(modo: str, periodo_pedido: Periodo, decisao: dict, lang: str) -> str:
    if modo == "fallback":
        usado = decisao["periodo_usado"]
        if lang == "pt":
            return (
                f"Não há dados de **{periodo_pedido.descricao}**. "
                f"O período mais recente com dados é **{usado.descricao}** — resultados a seguir:"
            )
        return (
            f"No data found for **{periodo_pedido.descricao_en}**. "
            f"Showing the most recent available period: **{usado.descricao_en}**."
        )

    if modo == "lacuna":
        max_d = decisao["max_date"]
        gap_meses = round(decisao.get("gap_dias", 0) / 30)
        if lang == "pt":
            return (
                f"Seus dados vão até **{max_d.strftime('%d/%m/%Y')}** "
                f"(lacuna de ~{gap_meses} meses). "
                f"Não há dados recentes disponíveis. "
                f"Quer ver o período até {max_d.strftime('%d/%m/%Y')}?"
            )
        return (
            f"Your data goes up to **{max_d.strftime('%Y-%m-%d')}** "
            f"(~{gap_meses}-month gap). "
            f"No recent data available. "
            f"Would you like to see data up to {max_d.strftime('%Y-%m-%d')}?"
        )

    if modo == "sem_dados":
        min_d = decisao.get("min_date")
        max_d = decisao.get("max_date")
        if min_d is None or max_d is None:
            if lang == "pt":
                return "Não há dados disponíveis nessa fonte."
            return "No data available in this data source."
        if lang == "pt":
            return (
                f"Não há dados nesse intervalo. "
                f"O período disponível é de **{min_d.strftime('%d/%m/%Y')}** "
                f"a **{max_d.strftime('%d/%m/%Y')}**."
            )
        return (
            f"No data available for that period. "
            f"Available range: **{min_d.strftime('%Y-%m-%d')}** "
            f"to **{max_d.strftime('%Y-%m-%d')}**."
        )

    return ""


# ---------------------------------------------------------------------------
# Função principal do nó
# ---------------------------------------------------------------------------
def run_periodo_decision(state, agent_config, data_source) -> dict:
    """
    LangGraph node: decide the period for temporal queries.
    Runs between orchestrator and specialist.
    """
    from datetime import date as date_cls

    question = state.get("question") or ""
    lang = state.get("detected_language") or state.get("locale") or "en"
    today = date_cls.today()

    # 1a. Try relative temporal detection
    periodo_pedido = None
    is_absolute_year = False
    if detect_temporal_question(question):
        periodo_pedido = parse_periodo(question, today)

    # 1b. If no relative period found, try absolute year ("de 2019", "em 2027")
    if periodo_pedido is None:
        yr = _extract_absolute_year(question)
        if yr is not None:
            periodo_pedido = _periodo_from_year(yr)
            is_absolute_year = True

    if periodo_pedido is None:
        return {**state, "periodo_modo": "nao_temporal"}

    # 2. Find the primary table and its date column
    chosen_physical = state.get("chosen_tables_physical") or []
    chosen_logical = state.get("chosen_tables") or []

    if not chosen_physical:
        return {**state, "periodo_modo": "nao_temporal"}

    physical_name = chosen_physical[0]
    logical_name = chosen_logical[0] if chosen_logical else None

    table_schema = None
    for t in agent_config.tables:
        if t.physical_name == physical_name or t.logical_name == logical_name:
            table_schema = t
            break

    if table_schema is None:
        return {**state, "periodo_modo": "nao_temporal"}

    date_col = find_date_column(table_schema)
    if date_col is None:
        return {**state, "periodo_modo": "nao_temporal"}

    # 3. Query MIN/MAX from the data source
    dialect = getattr(agent_config, "dialect", None)
    min_date, max_date = query_data_range(data_source, physical_name, date_col, dialect)

    # 4. Classify — absolute years never get fallback/lacuna, only sem_dados
    if is_absolute_year:
        decisao = _decidir_periodo_absoluto(periodo_pedido, min_date, max_date)
    else:
        decisao = decidir_periodo(periodo_pedido, min_date, max_date)

    modo = decisao["modo"]

    from core.logging_utils import log_event
    log_event("periodo_decision", {
        "modo": modo,
        "unidade": periodo_pedido.unidade,
        "periodo_pedido": periodo_pedido.descricao,
        "is_absolute_year": is_absolute_year,
        "min_date": str(min_date),
        "max_date": str(max_date),
        "gap_dias": (periodo_pedido.inicio - max_date).days if max_date and periodo_pedido.inicio > max_date else 0,
        "tol": FALLBACK_TOLERANCE.get(periodo_pedido.unidade, 90),
        "table": physical_name,
        "date_col": date_col,
    })

    base = {
        **state,
        "periodo_modo": modo,
        "periodo_coluna": date_col,
        "periodo_pedido": periodo_pedido.descricao if lang == "pt" else periodo_pedido.descricao_en,
    }

    if modo == "normal":
        return {
            **base,
            "periodo_usado": periodo_pedido.descricao if lang == "pt" else periodo_pedido.descricao_en,
            "periodo_from": periodo_pedido.inicio.isoformat(),
            "periodo_to": periodo_pedido.fim.isoformat(),
        }

    if modo == "fallback":
        usado = decisao["periodo_usado"]
        aviso = _build_aviso(modo, periodo_pedido, decisao, lang)
        return {
            **base,
            "periodo_usado": usado.descricao if lang == "pt" else usado.descricao_en,
            "periodo_from": usado.inicio.isoformat(),
            "periodo_to": usado.fim.isoformat(),
            "periodo_aviso": aviso,
        }

    if modo == "lacuna":
        aviso = _build_aviso(modo, periodo_pedido, decisao, lang)
        return {**base, "periodo_aviso": aviso, "answer": aviso}

    if modo == "sem_dados":
        # Short-circuit: specialist does NOT run — prevents spurious queries
        aviso = _build_aviso(modo, periodo_pedido, decisao, lang)
        return {**base, "periodo_aviso": aviso, "answer": aviso}

    # nao_temporal — pass through unchanged
    return base
