from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.logging_utils import log_event


@dataclass
class DavinciDashboardPlan:
    dashboard_name: str
    description: Optional[str]
    widgets: List[Dict[str, Any]]
    meta: Dict[str, Any]


def _parse_schema_summary(schema_summary: str) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """
    Parse the schema summary produced by `connection_query.dashboards_plan`.

    Expected line format:
      - <logical_table> cols: a, b, c keys: k1, k2
    """
    table_cols: dict[str, list[str]] = {}
    table_keys: dict[str, list[str]] = {}
    for raw in (schema_summary or "").splitlines():
        line = raw.strip()
        if not line.startswith("- "):
            continue
        # "- table cols: ... keys: ..."
        try:
            line = line[2:]
            table = line.split(" cols:", 1)[0].strip()
            rest = line.split(" cols:", 1)[1] if " cols:" in line else ""
            cols_part = rest
            keys_part = ""
            if " keys:" in rest:
                cols_part, keys_part = rest.split(" keys:", 1)
            cols = [c.strip() for c in (cols_part or "").split(",") if c.strip()]
            keys = [k.strip() for k in (keys_part or "").split(",") if k.strip()]
            if table:
                table_cols[table] = cols
                table_keys[table] = keys
        except Exception:
            continue
    return table_cols, table_keys


def _count_tables_mentioned(question: str, logical_tables: list[str]) -> int:
    q = (question or "").lower()
    mentioned: set[str] = set()
    for t in logical_tables:
        tl = (t or "").lower()
        if not tl:
            continue
        # Prefer explicit backtick mentions, but allow plain fallback.
        if f"`{tl}`" in q or tl in q:
            mentioned.add(tl)
    return len(mentioned)


def _pick_join_pairs(table_keys: dict[str, list[str]], logical_tables: list[str]) -> list[tuple[str, str, str]]:
    """
    Pick join pairs based on overlapping key-like columns.
    Returns list of (A, B, key).
    """
    pairs: list[tuple[str, str, str]] = []
    keys_norm: dict[str, set[str]] = {
        t: {k.lower() for k in (table_keys.get(t) or []) if k} for t in logical_tables
    }

    # Prefer overlaps that look like foreign keys.
    def score_key(k: str) -> int:
        if k.endswith("_id") and k != "id":
            return 3
        if "id" in k and k != "id":
            return 2
        return 1

    for i, a in enumerate(logical_tables):
        for b in logical_tables[i + 1 :]:
            overlap = keys_norm.get(a, set()) & keys_norm.get(b, set())
            if not overlap:
                continue
            # Choose best key from overlap.
            best = sorted(overlap, key=lambda k: (-score_key(k), k))[0]
            pairs.append((a, b, best))

    # Deterministic ordering: prefer stronger keys then stable names
    pairs = sorted(pairs, key=lambda p: (-score_key(p[2]), p[0].lower(), p[1].lower(), p[2]))
    return pairs


def _is_fact_table(name: str) -> bool:
    """
    Identifica se uma tabela parece ser uma fact table (tabela de fatos/eventos).
    Agnóstico de domínio: usa padrões genéricos que funcionam para qualquer tipo de negócio.
    """
    n = (name or "").lower()
    # Padrões genéricos que indicam tabelas de fatos/eventos (agnóstico)
    pats = (
        "transaction",
        "event",
        "session",
        "activity",
        "log",
        "record",
        "entry",
        "item",
        "line_",
        "fact_",
        "measure",
        "metric",
    )
    return any(p in n for p in pats)


def _is_dim_table(name: str) -> bool:
    """
    Identifica se uma tabela parece ser uma dimension table (tabela de dimensões).
    Agnóstico de domínio: usa padrões genéricos que funcionam para qualquer tipo de negócio.
    """
    n = (name or "").lower()
    # Padrões genéricos que indicam tabelas de dimensões (agnóstico)
    pats = (
        "entity",
        "master",
        "reference",
        "lookup",
        "dim_",
        "dimension",
        "catalog",
        "directory",
        "registry",
        "product",
        "vendor",
        "merchant",
        "category",
        "country",
        "region",
        "dim_",
    )
    return any(p in n for p in pats)


def _pick_fact_dim_pairs(
    table_keys: dict[str, list[str]], logical_tables: list[str]
) -> list[tuple[str, str, str]]:
    """
    Choose join pairs where one table is likely a fact and the other a dimension.
    Returns list of (fact, dim, key).
    """
    pairs = _pick_join_pairs(table_keys, logical_tables)
    out: list[tuple[str, str, str]] = []
    for a, b, k in pairs:
        if _is_fact_table(a) and _is_dim_table(b):
            out.append((a, b, k))
        elif _is_fact_table(b) and _is_dim_table(a):
            out.append((b, a, k))
    return out


def _choose_metric_col(cols: list[str]) -> str | None:
    pats = ("amount", "total", "value", "revenue", "price", "cost", "qty", "quantity", "balance", "paid")
    for p in pats:
        hit = next((c for c in cols if p in c.lower()), None)
        if hit:
            return hit
    return None


def _choose_dim_col(cols: list[str]) -> str | None:
    pats = ("name", "category", "type", "status", "method", "segment", "reason", "country", "region")
    for p in pats:
        hit = next((c for c in cols if p in c.lower()), None)
        if hit:
            return hit
    return None


def _choose_date_col(cols: list[str]) -> str | None:
    pats = ("date", "time", "created", "updated", "month", "day")
    for p in pats:
        hit = next((c for c in cols if p in c.lower()), None)
        if hit:
            return hit
    return None


def _enforce_join_mix(
    widgets: list[dict[str, Any]],
    *,
    logical_tables: list[str],
    table_cols: dict[str, list[str]],
    table_keys: dict[str, list[str]],
    max_widgets: int,
) -> list[dict[str, Any]]:
    """
    Ensure at least a minimum number of widgets are explicitly cross-table (JOIN) questions.
    We detect cross-table by number of logical tables mentioned in the question text.
    If insufficient, we rewrite some chart widgets into join-based questions.
    """
    if not widgets or not logical_tables:
        return widgets

    # For N=8, we want a strong cross-table dashboard.
    min_join = min(5, max_widgets)

    join_pairs = _pick_join_pairs(table_keys, logical_tables)
    if not join_pairs:
        return widgets

    def is_join_widget(w: dict[str, Any]) -> bool:
        q = str(w.get("question") or "")
        return _count_tables_mentioned(q, logical_tables) >= 2

    current_join = sum(1 for w in widgets if is_join_widget(w))
    if current_join >= min_join:
        return widgets

    # Prefer rewriting chart widgets first.
    rewrite_idxs = [i for i, w in enumerate(widgets) if str(w.get("type") or "") == "chart"]
    # If still not enough, allow rewriting KPI widgets too.
    if len(rewrite_idxs) < (min_join - current_join):
        rewrite_idxs += [i for i, w in enumerate(widgets) if str(w.get("type") or "") == "kpi"]

    needed = min_join - current_join
    rewrite_idxs = rewrite_idxs[:needed]

    # Create deterministic join templates.
    for n, idx in enumerate(rewrite_idxs):
        a, b, key = join_pairs[n % len(join_pairs)]
        a_cols = table_cols.get(a, [])
        b_cols = table_cols.get(b, [])
        metric = _choose_metric_col(a_cols) or _choose_metric_col(b_cols)
        dim = _choose_dim_col(b_cols) or _choose_dim_col(a_cols)
        dt = _choose_date_col(a_cols) or _choose_date_col(b_cols)

        # Pick a viz type to diversify.
        viz_type = ["bar", "line", "pie", "area", "scatter"][n % 5]

        if viz_type in {"line", "area"} and dt:
            question = (
                f"Using `{a}` JOIN `{b}` on `{key}`, show a monthly trend of "
                f"{('total ' + metric) if metric else 'count of records'} by `{dt}`. "
                "Return a table with two columns: period and value."
            )
            viz = {"type": viz_type, "mapping": {"x": "period", "y": "value"}}
        elif viz_type == "pie" and dim:
            question = (
                f"Using `{a}` JOIN `{b}` on `{key}`, show the distribution of `{dim}` "
                f"by {('total ' + metric) if metric else 'count of records'} (top 8 + other). "
                "Return columns: category and value."
            )
            viz = {"type": "pie", "mapping": {"x": "category", "y": "value"}}
        elif viz_type == "scatter" and metric and dim:
            question = (
                f"Using `{a}` JOIN `{b}` on `{key}`, build a scatter plot of `{metric}` versus `{dim}` "
                "(use numeric dimension if applicable; otherwise pick a suitable numeric column). "
                "Return columns: x, y, and category."
            )
            viz = {"type": "scatter", "mapping": {"x": "x", "y": "y"}}
        else:
            # Default: bar/column style.
            question = (
                f"Using `{a}` JOIN `{b}` on `{key}`, show the top 10 `{dim or b}` by "
                f"{('total ' + metric) if metric else 'count of records'}. "
                "Return columns: category and value."
            )
            viz = {"type": "bar", "mapping": {"x": "category", "y": "value"}}

        widgets[idx] = {
            **widgets[idx],
            "type": "chart",
            "title": widgets[idx].get("title") or f"Cross-table insight {idx+1}",
            "question": question,
            "viz": viz,
        }

    return widgets


def _enforce_distribution_and_fact_dim(
    widgets: list[dict[str, Any]],
    *,
    logical_tables: list[str],
    table_cols: dict[str, list[str]],
    table_keys: dict[str, list[str]],
    max_widgets: int,
) -> list[dict[str, Any]]:
    """
    For the auto "super dashboard" (N=8), enforce:
      - 2 KPI
      - 1 Table
      - 5 Chart
      - >= 3 fact+dimension JOIN widgets (questions explicitly mention 2+ tables)
    """
    if not widgets or not logical_tables:
        return widgets

    # Only enforce strongly for larger dashboards.
    if max_widgets < 6:
        return widgets

    target_kpi = 2 if max_widgets >= 8 else 1
    target_table = 1
    target_chart = max_widgets - target_kpi - target_table

    def wtype(w: dict[str, Any]) -> str:
        return str(w.get("type") or "chart")

    join_pairs = _pick_join_pairs(table_keys, logical_tables)
    fact_dim_pairs = _pick_fact_dim_pairs(table_keys, logical_tables)

    def _rewrite_as_table(i: int, pair: tuple[str, str, str] | None) -> None:
        if pair:
            fact, dim, key = pair
            dim_cols = table_cols.get(dim, [])
            label = _choose_dim_col(dim_cols) or "name"
            question = (
                f"Using `{fact}` JOIN `{dim}` on `{key}`, show the latest 15 records with key fields and `{label}`. "
                "Return a table with <= 15 rows."
            )
            widgets[i] = {
                **widgets[i],
                "type": "table",
                "title": widgets[i].get("title") or "Joined detail view",
                "question": question,
                "viz": {"type": "table"},
            }
        else:
            t = logical_tables[0]
            widgets[i] = {
                **widgets[i],
                "type": "table",
                "title": widgets[i].get("title") or f"Latest rows from {t}",
                "question": f"Show the latest 15 rows from `{t}`. Return a table with <= 15 rows.",
                "viz": {"type": "table"},
            }

    def _rewrite_as_kpi(i: int, pair: tuple[str, str, str] | None) -> None:
        if pair:
            fact, dim, key = pair
            metric = _choose_metric_col(table_cols.get(fact, [])) or _choose_metric_col(table_cols.get(dim, []))
            if metric:
                question = f"Using `{fact}` JOIN `{dim}` on `{key}`, what is the total `{metric}`? Return a single number."
                title = f"Total {metric}"
            else:
                question = f"Using `{fact}` JOIN `{dim}` on `{key}`, how many records are there? Return a single number."
                title = "Total records"
            widgets[i] = {**widgets[i], "type": "kpi", "title": widgets[i].get("title") or title, "question": question, "viz": {"type": "kpi"}}
        else:
            # ✅ FIX: Usar terminologia de negócio em vez de técnica
            t = logical_tables[0]
            # Mapear nomes técnicos para termos de negócio
            business_name = t.replace("_", " ").replace("silver", "").replace("enriquecido", "").strip()
            if "credit" in t.lower() and "memo" in t.lower():
                business_name = "credit notes"
            elif "invoice" in t.lower():
                business_name = "invoices"
            elif "payment" in t.lower():
                business_name = "payments"
            elif "customer" in t.lower():
                business_name = "customers"
            elif "refund" in t.lower():
                business_name = "refunds"
            
            widgets[i] = {
                **widgets[i],
                "type": "kpi",
                "title": widgets[i].get("title") or f"Total {business_name.title()}",
                "question": f"How many {business_name} are there in total? Return a single number.",
                "viz": {"type": "kpi"},
            }

    # Ensure at least one table widget.
    table_idxs = [i for i, w in enumerate(widgets) if wtype(w) == "table"]
    if len(table_idxs) < target_table:
        candidates = [i for i, w in enumerate(widgets) if wtype(w) == "chart"] or list(range(len(widgets)))
        idx = candidates[-1]
        pair = fact_dim_pairs[0] if fact_dim_pairs else (join_pairs[0] if join_pairs else None)
        _rewrite_as_table(idx, pair)

    # Ensure KPI count.
    kpi_idxs = [i for i, w in enumerate(widgets) if wtype(w) == "kpi"]
    while len(kpi_idxs) < target_kpi:
        candidates = [i for i, w in enumerate(widgets) if wtype(w) == "chart"]
        if not candidates:
            candidates = [i for i, w in enumerate(widgets) if wtype(w) != "table"] or [0]
        idx = candidates[0]
        pair = fact_dim_pairs[len(kpi_idxs) % len(fact_dim_pairs)] if fact_dim_pairs else (join_pairs[0] if join_pairs else None)
        _rewrite_as_kpi(idx, pair)
        kpi_idxs = [i for i, w in enumerate(widgets) if wtype(w) == "kpi"]

    # Reduce extras (convert extra tables/kpis back to charts).
    table_idxs = [i for i, w in enumerate(widgets) if wtype(w) == "table"]
    if len(table_idxs) > target_table:
        for idx in table_idxs[target_table:]:
            widgets[idx] = {**widgets[idx], "type": "chart", "viz": {"type": "bar"}}

    kpi_idxs = [i for i, w in enumerate(widgets) if wtype(w) == "kpi"]
    if len(kpi_idxs) > target_kpi:
        for idx in kpi_idxs[target_kpi:]:
            widgets[idx] = {**widgets[idx], "type": "chart", "viz": {"type": "bar"}}

    # Ensure chart count.
    chart_idxs = [i for i, w in enumerate(widgets) if wtype(w) == "chart"]
    if len(chart_idxs) < target_chart:
        for i, w in enumerate(widgets):
            if wtype(w) not in {"chart"} and len(chart_idxs) < target_chart:
                # Keep at least one table.
                if wtype(w) == "table" and sum(1 for ww in widgets if wtype(ww) == "table") <= 1:
                    continue
                widgets[i] = {**widgets[i], "type": "chart", "viz": {"type": "bar"}}
                chart_idxs = [j for j, ww in enumerate(widgets) if wtype(ww) == "chart"]

    # Ensure >=3 fact+dim join widgets by rewriting some charts deterministically.
    if fact_dim_pairs:
        min_fact_dim = min(3, max_widgets)
        for n in range(min_fact_dim):
            fact, dim, key = fact_dim_pairs[n % len(fact_dim_pairs)]
            idx_candidates = [i for i, w in enumerate(widgets) if wtype(w) == "chart"]
            if not idx_candidates:
                break
            idx = idx_candidates[n % len(idx_candidates)]
            metric = _choose_metric_col(table_cols.get(fact, [])) or _choose_metric_col(table_cols.get(dim, []))
            dt = _choose_date_col(table_cols.get(fact, [])) or _choose_date_col(table_cols.get(dim, []))
            if dt:
                question = (
                    f"Using `{fact}` JOIN `{dim}` on `{key}`, show a monthly trend of "
                    f"{('total ' + metric) if metric else 'count of records'} by `{dt}`. Return columns: period, value."
                )
                viz = {"type": "line", "mapping": {"x": "period", "y": "value"}}
                title = f"Trend ({fact} ↔ {dim})"
            else:
                question = (
                    f"Using `{fact}` JOIN `{dim}` on `{key}`, show top 10 `{dim}` by "
                    f"{('total ' + metric) if metric else 'count of records'}. Return columns: category, value."
                )
                viz = {"type": "bar", "mapping": {"x": "category", "y": "value"}}
                title = f"Top {dim} ({fact} ↔ {dim})"
            widgets[idx] = {**widgets[idx], "type": "chart", "title": title, "question": question, "viz": viz}

    return widgets


def _safe_json_loads(text: str) -> Optional[dict]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        # try extracting first {...} block
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


def _fallback_plan(goal: str, logical_tables: List[str], max_widgets: int, schema_summary: str = "", original_question: Optional[str] = None) -> DavinciDashboardPlan:
    """
    Deterministic fallback plan when LLM fails.
    Produces widgets that are safe to execute with small result sets.
    """
    picked = logical_tables[:12]
    widgets: List[Dict[str, Any]] = []

    # ✅ Se temos pergunta original, ela deve ser a primeira widget
    if original_question:
        widgets.append(
            {
                "widget_key": "w1",
                "type": "chart",
                "title": "Main Insight",
                "question": original_question.strip(),
                "viz": {"type": "bar", "mapping": {"x": "category", "y": "value"}},
            }
        )
        # Ajustar max_widgets restantes
        remaining_widgets = max_widgets - 1
    else:
        remaining_widgets = max_widgets

    # Try to build a strong fallback using join/key hints when available.
    table_cols, table_keys = _parse_schema_summary(schema_summary)
    join_pairs = _pick_join_pairs(table_keys, logical_tables) if logical_tables else []
    fact_dim_pairs = _pick_fact_dim_pairs(table_keys, logical_tables) if logical_tables else []

    # If we have no catalog metadata, return a text-only plan explaining the next step.
    if not picked:
        widgets.append(
            {
                "widget_key": "w1",
                "type": "text",
                "title": "Connect data to generate dashboards",
                "question": "N/A",
                "viz": {
                    "type": "text",
                    "content": (
                        "I couldn't find any tables in your data catalog for this connection yet.\n\n"
                        "Next steps:\n"
                        "- Open your connection settings and run **Refresh catalog**\n"
                        "- Ensure your credentials are configured correctly\n\n"
                        "After the catalog is ready, try creating the dashboard again."
                    ),
                },
            }
        )
        # Duplicate to match max_widgets if needed
        while len(widgets) < max_widgets:
            widgets.append({**widgets[-1], "widget_key": f"w{len(widgets)+1}"})
        return DavinciDashboardPlan(
            dashboard_name=goal.strip()[:80] or "Dashboard",
            description="Auto-generated dashboard plan (catalog not ready yet).",
            widgets=widgets[:max_widgets],
            meta={"fallback": True, "reason": "NO_CATALOG_METADATA", "has_original_question": original_question is not None},
        )

    # Strong fallback layout for N=8:
    # 2 KPI, 1 Table, 5 Charts with required viz types (bar, line, pie, area, scatter).
    # Prefer fact↔dim join pairs; otherwise any join pairs; otherwise single-table safe widgets.

    def _pick_pair(i: int) -> tuple[str, str, str] | None:
        if fact_dim_pairs:
            return fact_dim_pairs[i % len(fact_dim_pairs)]
        if join_pairs:
            return join_pairs[i % len(join_pairs)]
        return None

    # KPI #1 (prefer join + metric)
    pair0 = _pick_pair(0)
    if pair0:
        fact, dim, key = pair0
        metric = _choose_metric_col(table_cols.get(fact, [])) or _choose_metric_col(table_cols.get(dim, []))
        title = f"Total {metric}" if metric else "Total records"
        question = (
            f"Using `{fact}` JOIN `{dim}` on `{key}`, what is the total `{metric}`? Return a single number."
            if metric
            else f"Using `{fact}` JOIN `{dim}` on `{key}`, how many records are there? Return a single number."
        )
        widgets.append({"widget_key": "w1", "type": "kpi", "title": title, "question": question, "viz": {"type": "kpi"}})
    else:
        # ✅ FIX: Usar terminologia de negócio
        t = picked[0]
        business_name = t.replace("_", " ").replace("silver", "").replace("enriquecido", "").strip()
        if "credit" in t.lower() and "memo" in t.lower():
            business_name = "credit notes"
        elif "invoice" in t.lower():
            business_name = "invoices"
        elif "payment" in t.lower():
            business_name = "payments"
        elif "customer" in t.lower():
            business_name = "customers"
        elif "refund" in t.lower():
            business_name = "refunds"
        
        widgets.append(
            {
                "widget_key": "w1",
                "type": "kpi",
                "title": f"Total {business_name.title()}",
                "question": f"How many {business_name} are there in total? Return a single number.",
                "viz": {"type": "kpi"},
            }
        )

    # KPI #2
    pair1 = _pick_pair(1)
    if pair1:
        fact, dim, key = pair1
        metric = _choose_metric_col(table_cols.get(fact, [])) or _choose_metric_col(table_cols.get(dim, []))
        title = f"Total {metric}" if metric else "Total records"
        question = (
            f"Using `{fact}` JOIN `{dim}` on `{key}`, what is the total `{metric}`? Return a single number."
            if metric
            else f"Using `{fact}` JOIN `{dim}` on `{key}`, how many records are there? Return a single number."
        )
        widgets.append({"widget_key": "w2", "type": "kpi", "title": title, "question": question, "viz": {"type": "kpi"}})
    else:
        # ✅ FIX: Usar terminologia de negócio
        t = picked[1] if len(picked) > 1 else picked[0]
        business_name = t.replace("_", " ").replace("silver", "").replace("enriquecido", "").strip()
        if "credit" in t.lower() and "memo" in t.lower():
            business_name = "credit notes"
        elif "invoice" in t.lower():
            business_name = "invoices"
        elif "payment" in t.lower():
            business_name = "payments"
        elif "customer" in t.lower():
            business_name = "customers"
        elif "refund" in t.lower():
            business_name = "refunds"
        
        widgets.append(
            {
                "widget_key": "w2",
                "type": "kpi",
                "title": f"Total {business_name.title()}",
                "question": f"How many {business_name} are there in total? Return a single number.",
                "viz": {"type": "kpi"},
            }
        )

    # Table (prefer join detail)
    pair2 = _pick_pair(2)
    if pair2:
        fact, dim, key = pair2
        dim_cols = table_cols.get(dim, [])
        label = _choose_dim_col(dim_cols) or "name"
        widgets.append(
            {
                "widget_key": "w3",
                "type": "table",
                "title": "Joined detail view",
                "question": (
                    f"Using `{fact}` JOIN `{dim}` on `{key}`, show the latest 15 records with key fields and `{label}`. "
                    "Return a table with <= 15 rows."
                ),
                "viz": {"type": "table"},
            }
        )
    else:
        # ✅ FIX: Melhorar pergunta de tabela para especificar ordem
        # Problema: "Show the latest 15 rows" é ambíguo - não especifica como ordenar
        # Resultado: IA não sabe qual coluna usar para "latest", retorna vazio
        t = picked[0]
        t_cols = table_cols.get(t, [])
        dt = _choose_date_col(t_cols)
        
        if dt:
            # Se temos coluna de data, usar ela para ordenar
            widgets.append({
                "widget_key": "w3",
                "type": "table",
                "title": f"Recent Records from {t}",
                "question": f"Show the 15 most recent records from `{t}` ordered by `{dt}` descending.",
                "viz": {"type": "table"},
            })
        else:
            # Sem coluna de data, pedir amostra representativa
            widgets.append({
                "widget_key": "w3",
                "type": "table",
                "title": f"Sample Records from {t}",
                "question": f"Show a sample of 15 records from `{t}` with key information.",
                "viz": {"type": "table"},
            })

    # Charts: force required viz set for a "super dashboard"
    # Ajustar índice inicial se já temos pergunta original
    start_idx = 4 if not original_question else 5
    required_viz = ["bar", "line", "pie", "area", "scatter"]
    # Calcular quantos charts precisamos: total desejado - widgets já criados
    num_charts_needed = max_widgets - len(widgets)
    charts_to_generate = min(max(0, num_charts_needed), len(required_viz))
    
    for i, viz_type in enumerate(required_viz[:charts_to_generate], start=start_idx):
        pair = _pick_pair(i)
        if pair:
            a, b, key = pair
            a_cols = table_cols.get(a, [])
            b_cols = table_cols.get(b, [])
            metric = _choose_metric_col(a_cols) or _choose_metric_col(b_cols)
            dim = _choose_dim_col(b_cols) or _choose_dim_col(a_cols)
            dt = _choose_date_col(a_cols) or _choose_date_col(b_cols)

            if viz_type in {"line", "area"} and dt:
                question = (
                    f"Using `{a}` JOIN `{b}` on `{key}`, show a monthly trend of "
                    f"{('total ' + metric) if metric else 'count of records'} by `{dt}`. "
                    "Return columns: period and value."
                )
                viz = {"type": viz_type, "mapping": {"x": "period", "y": "value"}}
                title = f"Trend ({a} ↔ {b})"
            elif viz_type == "pie" and dim:
                question = (
                    f"Using `{a}` JOIN `{b}` on `{key}`, show the distribution of `{dim}` "
                    f"by {('total ' + metric) if metric else 'count of records'} (top 8 + other). "
                    "Return columns: category and value."
                )
                viz = {"type": "pie", "mapping": {"x": "category", "y": "value"}}
                title = f"Distribution by {dim}"
            elif viz_type == "scatter" and metric:
                question = (
                    f"Using `{a}` JOIN `{b}` on `{key}`, build a scatter plot for `{metric}` against another numeric measure. "
                    "Return columns: x, y, and category."
                )
                viz = {"type": "scatter", "mapping": {"x": "x", "y": "y"}}
                title = f"Scatter ({metric})"
            else:
                question = (
                    f"Using `{a}` JOIN `{b}` on `{key}`, show the top 10 `{dim or b}` by "
                    f"{('total ' + metric) if metric else 'count of records'}. "
                    "Return columns: category and value."
                )
                viz = {"type": "bar", "mapping": {"x": "category", "y": "value"}}
                title = f"Top {dim or 'categories'}"

            widgets.append({"widget_key": f"w{i}", "type": "chart", "title": title, "question": question, "viz": viz})
        else:
            # ✅ MELHORIA: Single-table fallback com perguntas específicas
            t = picked[(i - 1) % max(1, len(picked))]
            t_cols = table_cols.get(t, [])
            metric = _choose_metric_col(t_cols)
            dim = _choose_dim_col(t_cols)
            dt = _choose_date_col(t_cols)
            
            # Gerar pergunta específica baseada no tipo de viz e colunas disponíveis
            if viz_type in {"line", "area"} and dt and metric:
                question = f"What is the trend of {metric} over time using `{dt}` from `{t}`? Show monthly aggregation."
                viz = {"type": viz_type, "mapping": {"x": "period", "y": "value"}}
                title = f"{metric.replace('_', ' ').title()} Trend"
            elif viz_type == "pie" and dim and metric:
                question = f"What is the distribution of {metric} by {dim} in `{t}`? Show top 8 categories."
                viz = {"type": "pie", "mapping": {"x": "category", "y": "value"}}
                title = f"{metric.replace('_', ' ').title()} by {dim.replace('_', ' ').title()}"
            elif viz_type == "scatter" and metric:
                # Scatter precisa de duas métricas numéricas
                question = f"Show the relationship between {metric} and record count in `{t}`. Return x, y, and category columns."
                viz = {"type": "scatter", "mapping": {"x": "x", "y": "y"}}
                title = f"{metric.replace('_', ' ').title()} Analysis"
            elif metric and dim:
                # Bar/column padrão
                question = f"What are the top 10 {dim} by total {metric} in `{t}`?"
                viz = {"type": "bar", "mapping": {"x": "category", "y": "value"}}
                title = f"Top {dim.replace('_', ' ').title()}"
            else:
                # Último recurso: pergunta genérica mas ainda melhor que antes
                question = f"What is the distribution of records in `{t}` by main dimension? Show top 10."
                viz = {"type": viz_type, "mapping": {"x": "category", "y": "value"}}
                title = f"Distribution in {t}"
            
            widgets.append({
                "widget_key": f"w{i}",
                "type": "chart",
                "title": title,
                "question": question,
                "viz": viz,
            })

    # Trim / pad deterministically
    widgets = widgets[:max_widgets]
    while len(widgets) < max_widgets:
        widgets.append({**widgets[-1], "widget_key": f"w{len(widgets)+1}"})

    return DavinciDashboardPlan(
        dashboard_name=goal.strip()[:80] or "Dashboard",
        description="Auto-generated super dashboard based on your accessible data.",
        widgets=widgets[:max_widgets],
        meta={"fallback": True, "reason": "LLM_FALLBACK", "has_original_question": original_question is not None},
    )


def generate_dashboard_plan(
    *,
    llm: Any,
    goal: str,
    language: str,
    max_widgets: int,
    logical_tables: List[str],
    schema_summary: str,
    original_question: Optional[str] = None,
    initial_ai_response: Optional[str] = None,
    context_spaces: Optional[List[str]] = None,
    context_crews: Optional[List[str]] = None,
    context_tables: Optional[List[str]] = None,
) -> DavinciDashboardPlan:
    """
    Davinci "graph": generate a dashboard plan as STRICT JSON.

    Inputs are already permission-filtered (logical_tables/schema_summary).
    
    If original_question is provided:
    - The first widget MUST be the original question (70-80% weight)
    - The remaining 7 widgets will be strongly related to the original question
    """
    # Keep the request bounded and deterministic-ish.
    # Temporary product decision: cap at 8 widgets for auto dashboard creation.
    max_widgets = max(1, min(8, int(max_widgets)))
    # Force English only
    language = "en"

    if not logical_tables:
        return _fallback_plan(goal=goal, logical_tables=[], max_widgets=max_widgets, schema_summary=schema_summary, original_question=original_question)

    table_cols, table_keys = _parse_schema_summary(schema_summary)

    # NOTE: when using `.format(...)`, any `{}` in the prompt becomes a formatting placeholder.
    # We intentionally avoid `.format` here because the JSON schema includes `{}`.
    min_join = min(5, max_widgets)
    
    # Modificar prompt baseado em se temos pergunta original ou não
    if original_question:
        system = (
            "You are Davinci, a dashboard planner.\n"
            "\n"
            "🎯 PRIMARY GOAL: The user asked a SPECIFIC question. Your dashboard MUST focus on answering THAT question.\n"
            "⚠️ DO NOT generate a generic 'overview' dashboard that happens to include the question.\n"
            "⚠️ DO NOT try to use all available tables if they're not relevant to the question.\n"
            "\n"
            "CRITICAL REQUIREMENT: The user has provided an ORIGINAL QUESTION that MUST be the FIRST widget.\n"
            "\n"
            "Rules:\n"
            "- Output STRICT JSON only.\n"
            "- The FIRST widget MUST be exactly the user's original question (provided below).\n"
            "- The remaining 7 widgets MUST be DIRECTLY RELATED to the original question (80-90% relevance).\n"
            "- Think: 'What specific insights would help answer or expand on this exact question?'\n"
            "- AVOID: Generic widgets that could apply to any dashboard (e.g., 'customer distribution' when question is about refunds).\n"
            "- Use ONLY the provided logical table names.\n"
            "- ALWAYS wrap referenced table names in backticks (e.g., `table1`).\n"
            "- Each widget must have: widget_key, type, title, question, viz.\n"
            "- Widget types allowed: chart, kpi, table, text.\n"
            "- CRITICAL: Questions MUST be BUSINESS-ORIENTED, not technical:\n"
            "  * AVOID: 'How many rows are in the table?', 'Total rows in silver_credit_memos', 'Count of records'\n"
            "  * PREFER: 'How many credit notes were issued?', 'Total number of invoices', 'Count of active customers'\n"
            "  * Think: 'What business metric does this represent?' not 'What's in the database?'\n"
            "  * Use business terminology: 'credit notes' not 'credit_memos table rows', 'customers' not 'customer records'\n"
            "  * Focus on INSIGHTS, not data structure: 'revenue trends' not 'sum of amount column'\n"
            "- Questions MUST be answerable from the provided tables.\n"
            "- Prefer aggregated queries that return <= 15 rows for charts.\n"
            "- Visualization (viz) RULES:\n"
            "  * The 'viz' object MUST contain 'type' (bar, line, area, pie, donut, scatter, kpi, table).\n"
            "  * For charts, it MUST contain 'mapping' with 'x' (X-axis column) and 'y' (Y-axis metric).\n"
            "  * For multi-series charts, also include 'series' (the column that defines different lines/bars).\n"
            "  * Example single-series: {\"type\": \"bar\", \"mapping\": {\"x\": \"month\", \"y\": \"total_sales\"}}.\n"
            "  * Example multi-series: {\"type\": \"line\", \"mapping\": {\"x\": \"date\", \"y\": \"amount\", \"series\": \"status\"}}.\n"
            "  * CRITICAL: Use 'scatter' ONLY when X and Y are BOTH numeric. For categorical X (like 'reason', 'status', 'category'), use 'bar' or 'pie'.\n"
            "  * CRITICAL: For questions about 'distribution by X', use 'bar' or 'pie', NOT 'scatter'.\n"
            "  * CRITICAL: Match viz type to data - categorical data needs bar/pie, time series needs line/area, numeric correlation needs scatter.\n"
            "- Make the dashboard engaging: mix widget types (KPIs + charts + at least one table when possible).\n"
            "- Prefer a mix of chart viz types (bar/column, line/area, pie/donut, scatter) when applicable.\n"
            "- IMPORTANT: Prefer cross-table insights. When useful, ask questions that require JOINs.\n"
            "- For N=8: at least 3 of the JOIN widgets MUST be fact+dimension joins.\n"
            "- CRITICAL: AVOID EMPTY WIDGETS - Every widget MUST return data:\n"
            "  * DO NOT use restrictive time filters like 'last 30 days' or 'last week' - data might not exist in that range.\n"
            "  * Instead, use 'recent' or 'latest' without specific date ranges, or use broader ranges like 'last 12 months'.\n"
            "  * For 'recent transactions', ask for 'latest 15 records ordered by date' instead of 'records from last 30 days'.\n"
            "  * Prefer aggregated queries (COUNT, SUM, AVG) over filtered queries.\n"
            "  * Avoid questions about specific statuses/conditions that might not exist.\n"
            "  * Example GOOD: 'Show the 15 most recent refund transactions ordered by date descending'.\n"
            "  * Example BAD: 'Show refund transactions from the last 30 days' (might be empty).\n"
            f"- Language for titles/questions: English (STRICT REQUIREMENT - ALWAYS ENGLISH)\n"
            "- EXACTLY N widgets.\n"
            "- DASHBOARD TITLE (dashboard_name) RULES:\n"
            "  * The title must be SPECIFIC and DESCRIPTIVE (max 60 chars).\n"
            "  * AVOID generic titles like 'Sales Dashboard' or 'Analytical Dashboard'.\n"
            "  * USE CONTEXT: If the user's question or previous answer mentions a specific region, product, or timeframe, INCLUDE IT in the title.\n"
            "  * Examples: 'Sales Trend 2024 (SP)', 'Top Customers & Churn', 'High Value Orders Analysis'.\n"
            "  * Since original_question is present, the title MUST be directly related to it.\n"
            'JSON schema: {{"dashboard_name": string, "description": string, "widgets": ['
            '{{"widget_key": string, "type": string, "title": string, "question": string, "viz": object}}'
            "]}}.\n"
        )
        
        # ✅ NOVO: Adicionar contexto de subspaces e crews se disponível
        context_str = ""
        if initial_ai_response:
            context_str += (
                f"\nCONTEXT: The user just received this answer from the AI: '{initial_ai_response}'. "
                "Use this to suggest widgets potentially related to this insight (e.g. if the answer mentions 'Sales in SP', suggest 'Sales by Region').\n"
            )
        if context_spaces:
            context_str += f"Context Spaces (available departments/areas): {', '.join(context_spaces)}\n"
        if context_crews:
            context_str += f"Context Crews (available teams/groups): {', '.join(context_crews)}\n"
        if context_tables:
            context_str += f"Context Tables (full accessible list): {', '.join(context_tables[:50])}...\n"
        
        user = (
            f"N={max_widgets}\n"
            f"\n"
            f"🎯 ORIGINAL QUESTION (MUST be first widget, word-for-word): {original_question}\n"
            f"\n"
            f"📋 INSTRUCTIONS:\n"
            f"Generate 7 additional widgets that are DIRECTLY RELATED to the question above.\n"
            f"\n"
            f"✅ GOOD EXAMPLE (if question is about 'monthly refund performance'):\n"
            f"- Widget 1: {original_question} (exact question)\n"
            f"- Widget 2: What is the total refund amount over time? (business metric)\n"
            f"- Widget 3: What are the top reasons for refunds? (business insight)\n"
            f"- Widget 4: What is the refund rate by customer segment? (business analysis)\n"
            f"- Widget 5: What is the average refund processing time? (operational metric)\n"
            f"- Widget 6: How are refund amounts distributed? (business distribution)\n"
            f"- Widget 7: Which products have the most refunds? (business insight)\n"
            f"- Widget 8: What are the recent refund transactions? (business data)\n"
            f"\n"
            f"❌ BAD EXAMPLE (technical/literal questions - AVOID):\n"
            f"- Widget 1: {original_question}\n"
            f"- Widget 2: How many rows are in the refunds table? (technical, not useful)\n"
            f"- Widget 3: Show all columns from credit_memos (technical, not insightful)\n"
            f"- Widget 4: Count of records in payments table (technical, not business-oriented)\n"
            f"- Widget 5: Sum of amount column (technical, lacks context)\n"
            f"\n"
            f"❌ BAD EXAMPLE (generic overview - AVOID):\n"
            f"- Widget 1: {original_question}\n"
            f"- Widget 2: Payment methods (NOT about refunds)\n"
            f"- Widget 3: Customer distribution (NOT about refunds)\n"
            f"- Widget 4: Credit memos (NOT about refunds)\n"
            f"- Widget 5: Revenue trends (NOT about refunds)\n"
            f"\n"
            f"❌ BAD EXAMPLE (filters that return empty results):\n"
            f"- Widget: 'What are the recent high-value invoices?' (implies WHERE category='High' -> EMPTY)\n"
            f"- Widget: 'Show refunds from last week' (temporal filter -> EMPTY)\n"
            f"- INSTEAD USE SORTING: 'Show the recent invoices with highest amounts' (ORDER BY amount DESC -> DATA)\n"
            f"- INSTEAD USE SORTING: 'Show the 15 most recent refund transactions' (ORDER BY date DESC -> DATA)\n"
            f"\n"
            f"{context_str}"
            f"Goal: {goal}\n"
            f"Accessible tables for JOINs: {', '.join(logical_tables[:20])}\n"
            f"Schema sample:\n{schema_summary}\n"
            f"\n"
            f"🎯 CRITICAL: Focus on '{original_question}'. Extract the key metric/dimension and build ALL widgets around it.\n"
            f"Generate a dashboard that comprehensively answers: '{original_question}'\n"
        )
    else:
        # Prompt original (sem pergunta original)
        system = (
            "You are Davinci, a dashboard planner.\n"
            "You propose a dashboard (name + widgets) based on accessible tables.\n"
            "Rules:\n"
            "- Output STRICT JSON only.\n"
            "- Use ONLY the provided logical table names.\n"
            "- ALWAYS wrap referenced table names in backticks (e.g., `table1`).\n"
            "- Each widget must have: widget_key, type, title, question, viz.\n"
            "- Widget types allowed: chart, kpi, table, text.\n"
            "- Questions MUST be answerable from the provided tables.\n"
            "- Prefer aggregated queries that return <= 15 rows for charts.\n"
            "- Visualization (viz) RULES:\n"
            "  * The 'viz' object MUST contain 'type' (bar, line, area, pie, donut, scatter, kpi, table).\n"
            "  * For charts, it MUST contain 'mapping' with 'x' (X-axis column) and 'y' (Y-axis metric).\n"
            "  * For multi-series charts, also include 'series' (the column that defines different lines/bars).\n"
            "  * Example single-series: {\"type\": \"bar\", \"mapping\": {\"x\": \"month\", \"y\": \"total_sales\"}}.\n"
            "  * Example multi-series: {\"type\": \"line\", \"mapping\": {\"x\": \"date\", \"y\": \"amount\", \"series\": \"status\"}}.\n"
            "  * CRITICAL: Use 'scatter' ONLY when X and Y are BOTH numeric. For categorical X, use 'bar' or 'column'.\n"
            "- Make the dashboard engaging: mix widget types (KPIs + charts + at least one table when possible).\n"
            "- Prefer a mix of chart viz types (bar/column, line/area, pie/donut, scatter) when applicable.\n"
            "- IMPORTANT: Prefer cross-table insights. When useful, ask questions that require JOINs (e.g., fact_table + dimension_table, transaction + entity) to produce better business metrics.\n"
            "- If keys are provided in the schema sample, use them to suggest joined questions (e.g., *_id and date fields).\n"
            f"- Hard requirement: at least {min_join} of N widgets MUST require JOINs across 2+ tables.\n"
            "- For N=8: enforce a fixed distribution: exactly 2 KPI widgets, exactly 1 Table widget, and exactly 5 Chart widgets.\n"
            "- For N=8: at least 3 of the JOIN widgets MUST be fact+dimension joins (e.g., transactions↔entities, events↔references).\n"
            "- Language for titles/questions: English (STRICT REQUIREMENT - ALWAYS ENGLISH) - EVEN IF USER SPEAKS ANOTHER LANGUAGE.\n"
            "- DATA SAFETY: Do not invent columns. Only use columns present in 'Schema sample'.\n"
            "- CRITICAL: AVOID EMPTY WIDGETS - Every widget MUST return data:\n"
            "  * Prefer aggregated queries (COUNT, SUM, AVG) over filtered queries\n"
            "  * Avoid questions about specific statuses/conditions that might not exist (e.g., 'overdue', 'pending')\n"
            "  * Use broad questions that work with any data (e.g., 'total revenue' instead of 'overdue invoices')\n"
            "  * For tables/charts, ask for 'top N' or 'distribution by' instead of specific filters\n"
            "  * Example GOOD: 'What is the total revenue by customer?' (always returns data)\n"
            "  * Example BAD: 'Which customers are overdue?' (might return empty if no overdue customers)\n"
            "- EXACTLY N widgets.\n"
            "- DASHBOARD TITLE (dashboard_name) RULES:\n"
            "  * The title must be SPECIFIC and DESCRIPTIVE (max 60 chars).\n"
            "  * AVOID generic titles like 'Sales Dashboard' or 'Analytical Dashboard'.\n"
            "  * USE CONTEXT: If a specific goal, region, or timeframe is inferred, INCLUDE IT in the title.\n"
            "  * Examples: 'Sales Trend 2024 (SP)', 'Top Customers & Churn', 'High Value Orders Analysis'.\n"
            'JSON schema: {{"dashboard_name": string, "description": string, "widgets": ['
            '{{"widget_key": string, "type": string, "title": string, "question": string, "viz": object}}'
            "]}}.\n"
        )
        
        # ✅ NOVO: Adicionar contexto de subspaces e crews se disponível
        context_str = ""
        if initial_ai_response:
            context_str += (
                f"\nCONTEXT: The user just received this answer from the AI: '{initial_ai_response}'. "
                "Use this to suggest widgets potentially related to this insight (e.g. if the answer mentions 'Sales in SP', suggest 'Sales by Region').\n"
            )
        if context_spaces:
            context_str += f"Context Spaces (available departments/areas): {', '.join(context_spaces)}\n"
        if context_crews:
            context_str += f"Context Crews (available teams/groups): {', '.join(context_crews)}\n"
        if context_tables:
            context_str += f"Context Tables (full accessible list): {', '.join(context_tables[:50])}...\n"
        
        user = (
            f"N={max_widgets}\n"
            f"{context_str}"
            f"Goal: {goal}\n"
            f"Accessible tables for JOINs: {', '.join(logical_tables[:20])}\n"
            f"Schema sample:\n{schema_summary}\n"
        )

    try:
        resp = llm.invoke([{"role": "system", "content": system}, {"role": "user", "content": user}])
        parsed = _safe_json_loads(getattr(resp, "content", "") or "")
        if not isinstance(parsed, dict):
            raise ValueError("LLM did not return valid JSON object")

        dashboard_name = str(parsed.get("dashboard_name") or "").strip() or (goal.strip()[:80] or "Dashboard")
        description = str(parsed.get("description") or "").strip() or None
        widgets_raw = parsed.get("widgets") or []
        if not isinstance(widgets_raw, list) or not widgets_raw:
            raise ValueError("LLM returned no widgets")

        widgets: List[Dict[str, Any]] = []
        for i, w in enumerate(widgets_raw[:max_widgets], start=1):
            if not isinstance(w, dict):
                continue
            widget_key = str(w.get("widget_key") or f"w{i}").strip() or f"w{i}"
            wtype = str(w.get("type") or "chart").strip()
            title = str(w.get("title") or "").strip() or f"Widget {i}"
            question = str(w.get("question") or "").strip()
            viz = w.get("viz") if isinstance(w.get("viz"), dict) else {"type": "bar"}
            if not question:
                continue
            widgets.append(
                {
                    "widget_key": widget_key,
                    "type": wtype,
                    "title": title,
                    "question": question,
                    "viz": viz,
                }
            )

        if not widgets:
            raise ValueError("LLM widgets invalid")

        # ✅ CRÍTICO: Se temos pergunta original, garantir que seja a primeira widget
        if original_question:
            original_question_clean = original_question.strip()
            first_widget_question = widgets[0].get("question", "").strip() if widgets else ""
            
            # Verificar se a primeira widget já é a pergunta original (comparação flexível)
            is_same_question = (
                original_question_clean.lower() == first_widget_question.lower() or
                original_question_clean.lower() in first_widget_question.lower() or
                first_widget_question.lower() in original_question_clean.lower()
            )
            
            if not is_same_question:
                # Criar widget com a pergunta original como primeiro
                # Tentar preservar tipo e viz da primeira widget gerada, ou usar defaults
                original_widget = {
                    "widget_key": "w1",
                    "type": widgets[0].get("type", "chart") if widgets else "chart",
                    "title": widgets[0].get("title", "Original Question") if widgets else "Original Question",
                    "question": original_question_clean,
                    "viz": widgets[0].get("viz", {"type": "bar"}) if widgets else {"type": "bar"},
                }
                # Inserir no início e manter apenas max_widgets
                widgets = [original_widget] + widgets[1:max_widgets]
            else:
                # Já está correto, mas garantir que a pergunta está exatamente como o usuário forneceu
                widgets[0]["question"] = original_question_clean

        # Normalize count
        widgets = widgets[:max_widgets]
        while len(widgets) < max_widgets:
            widgets.append(widgets[-1])

        # Enforce cross-table join mix if the LLM didn't satisfy it.
        widgets = _enforce_join_mix(
            widgets,
            logical_tables=logical_tables,
            table_cols=table_cols,
            table_keys=table_keys,
            max_widgets=max_widgets,
        )

        widgets = _enforce_distribution_and_fact_dim(
            widgets,
            logical_tables=logical_tables,
            table_cols=table_cols,
            table_keys=table_keys,
            max_widgets=max_widgets,
        )

        # ✅ NOVA: Validar widgets usando WidgetValidator
        try:
            from core.validation.widget_validator import WidgetValidator
            from core.validation.question_validator import QuestionValidator
            
            # Preparar metadados para QuestionValidator
            available_tables_meta = [
                {
                    "name": t,
                    "logical_name": t,
                    "columns": table_cols.get(t, []),
                }
                for t in logical_tables
            ]
            available_columns = {
                t: table_cols.get(t, [])
                for t in logical_tables
            }
            
            question_validator = QuestionValidator(available_tables_meta, available_columns)
            # ✅ FIX: strict_mode=False para não filtrar widgets com warnings
            # A IA gera os widgets, então eles devem funcionar mesmo com warnings leves
            widget_validator = WidgetValidator(question_validator, strict_mode=False)
            
            # Filtrar widgets problemáticos (mas preservar a primeira se for original_question)
            widgets_before_validation = len(widgets)
            original_widget_preserved = None
            if original_question and widgets:
                original_widget_preserved = widgets[0]
                widgets_to_validate = widgets[1:]
            else:
                widgets_to_validate = widgets
            
            widgets_validated = widget_validator.filter_widgets(
                widgets_to_validate, 
                min_widgets=max(1, (max_widgets - 1) // 2) if original_question else max(1, max_widgets // 2)
            )
            
            # Reconstruir lista com original preservado
            if original_widget_preserved:
                widgets = [original_widget_preserved] + widgets_validated
            else:
                widgets = widgets_validated
            
            widgets_after_validation = len(widgets)
            
            # Se filtramos muitos widgets, logar aviso
            if widgets_before_validation > widgets_after_validation:
                log_event(
                    "davinci_widgets_validated",
                    {
                        "goal": goal[:200],
                        "original_question": original_question[:200] if original_question else None,
                        "widgets_before": widgets_before_validation,
                        "widgets_after": widgets_after_validation,
                        "filtered": widgets_before_validation - widgets_after_validation,
                    },
                )
            
            # Se não temos widgets suficientes após validação, usar fallback
            min_required = max(1, max_widgets // 2)
            if len(widgets) < min_required:
                log_event(
                    "davinci_validation_too_many_filtered",
                    {
                        "goal": goal[:200],
                        "original_question": original_question[:200] if original_question else None,
                        "remaining_widgets": len(widgets),
                        "min_required": min_required,
                        "action": "using_fallback",
                    },
                )
                # Retornar fallback se validação filtrou muitos widgets
                return _fallback_plan(
                    goal=goal, 
                    logical_tables=logical_tables, 
                    max_widgets=max_widgets, 
                    schema_summary=schema_summary,
                    original_question=original_question,
                )
            
        except Exception as e:
            # Se validação falhar, continuar sem filtrar (fail-safe)
            log_event(
                "davinci_validation_error",
                {
                    "goal": goal[:200],
                    "original_question": original_question[:200] if original_question else None,
                    "error": str(e)[:500],
                    "action": "continuing_without_validation",
                },
            )

        log_event(
            "davinci_plan_generated",
            {
                "goal": goal[:200],
                "original_question": original_question[:200] if original_question else None,
                "language": language,
                "num_widgets": len(widgets),
                "join_widgets": sum(1 for w in widgets if _count_tables_mentioned(str(w.get("question") or ""), logical_tables) >= 2),
                "type_counts": {
                    "kpi": sum(1 for w in widgets if str(w.get("type") or "") == "kpi"),
                    "table": sum(1 for w in widgets if str(w.get("type") or "") == "table"),
                    "chart": sum(1 for w in widgets if str(w.get("type") or "") == "chart"),
                    "text": sum(1 for w in widgets if str(w.get("type") or "") == "text"),
                },
                "fallback": False,
                "has_original_question": original_question is not None,
            },
        )
        return DavinciDashboardPlan(
            dashboard_name=dashboard_name,
            description=description,
            widgets=widgets,
            meta={
                "fallback": False, 
                "model": getattr(getattr(llm, "_chat", None), "model_name", None),
                "has_original_question": original_question is not None,
            },
        )
    except Exception as e:
        log_event(
            "davinci_plan_error",
            {
                "goal": goal[:200], 
                "original_question": original_question[:200] if original_question else None,
                "error": str(e)[:500]
            },
        )
        return _fallback_plan(goal=goal, logical_tables=logical_tables, max_widgets=max_widgets, schema_summary=schema_summary, original_question=original_question)

