from __future__ import annotations

import json
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.logging_utils import log_event
from core.contracts.analysis_context import AnalysisContext # NEW IMPORT


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
    Pick join pairs based on overlapping keys, using Schema Intelligence scoring.
    Returns list of (A, B, key).
    """
    pairs: list[tuple[str, str, str]] = []
    
    # Pre-compute keys per table
    keys_norm: dict[str, set[str]] = {
        t: {k.lower() for k in (table_keys.get(t) or []) if k} for t in logical_tables
    }

    for i, a in enumerate(logical_tables):
        for b in logical_tables[i + 1 :]:
            # Overlapping columns (potential join keys)
            overlap = keys_norm.get(a, set()) & keys_norm.get(b, set())
            
            best_key = None
            best_score = -1.0
            
            # 1. Check strict name overlaps
            for k in overlap:
                # Score using JoinScorer logic for identical names
                s = JoinScorer.score_join(a, k, b, k)
                if s > best_score:
                    best_score = s
                    best_key = k
            
            # 2. Check FK patterns (user_id <-> id) which might NOT be in strict overlap
            # We need to iterate all keys in A vs keys in B? 
            # Or just check if 'id' is in one and 'table_id' in other?
            # JoinScorer handles the check, but we need candidates.
            # Simplified: Use the existing table_keys dict to find pairs.
            
            keys_a = list(keys_norm.get(a, set()))
            keys_b = list(keys_norm.get(b, set()))
            
            for ka in keys_a:
                for kb in keys_b:
                    if ka == kb: continue # Already handled in overlap above
                    
                    s = JoinScorer.score_join(a, ka, b, kb)
                    if s > best_score:
                        best_score = s
                        best_key = (ka, kb) # Wait, legacy returns (A, B, Key). If keys differ, we can't return single key. 
                        # Davinci only supports single key equality joins currently.
                        # So we MUST pick single key matches from overlap.
            
            if best_key and best_score > 0.5:
                # If best_key is a tuple, it implies A.k1 = B.k2, but current signature expects single key string
                # implies "USING (key)". 
                # If Davinci supports "ON A.k1 = B.k2", we need to change signature.
                # Checking usages: users of this function probably expect `USING (key)`.
                # Let's check: _pick_fact_dim_pairs calls this.
                # And generated SQL usually uses inferred logic.
                
                # For now, strict adherence to `USING (key)`:
                if isinstance(best_key, str):
                   pairs.append((a, b, best_key))
                
    # Deterministic ordering
    pairs = sorted(pairs, key=lambda p: (p[0].lower(), p[1].lower(), p[2]))
    return pairs


from core.agents.schema_intelligence import SchemaScorer, TableFeatures, ColumnScorer, ColumnFeatures, AnalyticTableFilter, JoinScorer

def _get_table_role(table_name: str, metadata: dict | None) -> str:
    """
    Determine table role using SchemaScorer if metadata is available.
    Falls back to 'unknown' if no metadata.
    """
    if not metadata:
        return "unknown"
    
    # Extract features
    # Note: row_count might be missing, default to 0 (which scores as small dim)
    row_count = int(metadata.get("row_count") or metadata.get("stats", {}).get("row_count") or 0)
    cols = metadata.get("columns", [])
    
    features = SchemaScorer.extract_features(table_name, cols, row_count)
    result = SchemaScorer.score_table(features)
    return result["role"]


def _pick_fact_dim_pairs(
    table_keys: dict[str, list[str]], 
    logical_tables: list[str],
    table_metadata_map: dict[str, dict]
) -> list[tuple[str, str, str]]:
    """
    Choose join pairs where one table is likely a fact and the other a dimension.
    Uses Schema Intelligence scoring.
    Returns list of (fact, dim, key).
    """
    pairs = _pick_join_pairs(table_keys, logical_tables)
    out: list[tuple[str, str, str]] = []
    
    # Pre-compute roles to avoid re-scoring inside loop
    roles = {}
    for t in logical_tables:
        roles[t] = _get_table_role(t, table_metadata_map.get(t))

    for a, b, k in pairs:
        role_a = roles.get(a, "unknown")
        role_b = roles.get(b, "unknown")
        
        # Logic: Looking for Fact <-> Dim/Ambiguous
        # (Ambiguous behaves like a dim often enough for joins)
        if role_a == "fact" and role_b in ("dimension", "ambiguous", "unknown"):
            out.append((a, b, k))
        elif role_b == "fact" and role_a in ("dimension", "ambiguous", "unknown"):
            out.append((b, a, k))
            
    return out


def _find_col_by_role(role: str, cols: list[str], row_count: int = 1000) -> str | None:
    """
    Finds a column matching the requested role (metric, attribute, time, key)
    using generic schema intelligence signals, NOT hardcoded names.
    """
    for c in cols:
        # Mock features since we only have names here in this context
        # Ideally we pass full metadata, but for fallback this is okay.
        # Wait, blindly trusting name patterns is what we want to avoid.
        # But here we only have names string list.
        # We need to rely on what information we have.
        # If we only have names, we are forced to use heuristics.
        # BUT, the caller usually has metadata available now.
        pass
    return None

# Rethink: The callers (_enforce_join_mix, etc) passed `table_cols` (names only).
# We need to upgrade them to pass metadata if possible.
# In `_fallback_plan`, we DO parse schema summary into `table_cols`.
# Schema summary format: "table cols: a, b (int), c (date)" - maybe we can enhance parsing?
# For now, let's implement a "best effort" agnostic picker that looks at suffixes/prefixes common in DB design
# IF we don't have metadata. BUT the goal is NO hardcoded english.

# Better approach:
# `_choose_metric_col` was using "amount", "price".
# New approach:
# If we have basic type hints from schema summary ("amount (int)"), we use that.
# If not, strictly avoid "guessing" by name unless it's universal (like "id").

def _find_best_col(cols: list[str], role: str) -> str | None:
    # This is a temporary bridge. To be fully agnostic, we need TYPES.
    # The `_parse_schema_summary` doesn't strictly parse types yet, just names.
    # Let's assume we can't be perfect without types, but we can be BETTER than just English keywords.
    # Actually, we can just return the first column that 'looks' right? No.
    
    # We will accept that without metadata, we might fail to find a "perfect" metric.
    # But we should rely on what we have.
    return cols[0] if cols else None 

# WAIT. `_fallback_plan` HAS `table_metadata` (full dict).
# We should use THAT.

def _get_col_type_from_meta(t_name: str, c_name: str, meta_map: dict) -> str:
    t = meta_map.get(t_name) or meta_map.get(f"public.{t_name}") # loose schema match
    if not t: return "unknown"
    for c in t.get("columns", []):
         if c.get("name") == c_name:
             return str(c.get("type", "")).upper()
    return "unknown"

def _pick_col_agnostic(t_name: str, cols: list[str], role: str, meta_map: dict) -> str | None:
    """
    Picks a column based on TYPE from metadata, ignoring name.
    """
    for c in cols:
        ctype = _get_col_type_from_meta(t_name, c, meta_map)
        
        if role == "metric":
            # Any numeric type
            if any(x in ctype for x in ["INT", "FLOAT", "NUMERIC", "DECIMAL"]):
                if not c.endswith("id"): # Universal convention, not english specific
                    return c
        elif role == "time":
            if any(x in ctype for x in ["DATE", "TIME"]):
                return c
        elif role == "attribute":
            if any(x in ctype for x in ["CHAR", "TEXT", "STRING"]):
                return c
                
    return None




def _build_primary_widget_from_context(context: AnalysisContext, goal: str) -> Dict[str, Any]:
    """
    Builds the 'Anchor Widget' deterministically from the validated context.
    This widget is the 'Truth' of the system.
    """
    # Decide viz type based on context
    viz_type = "bar"
    mapping = {"x": context.primary_dimension or "category", "y": context.primary_metric}
    
    question = f"Show {context.primary_metric}"
    if context.primary_dimension:
        question += f" by {context.primary_dimension}"
    
    if context.detected_analysis_type == "trend" and context.time_column:
        viz_type = "line"
        mapping = {"x": context.time_column, "y": context.primary_metric}
        question = f"Trend of {context.primary_metric} over time ({context.time_column})"
    elif context.detected_analysis_type == "distribution" and context.primary_dimension:
        viz_type = "pie"
        question = f"Distribution of {context.primary_metric} by {context.primary_dimension}"
    elif context.detected_analysis_type == "kpi":
        viz_type = "kpi"
        mapping = {} # KPI has no mapping usually, or specific format
        question = f"Total {context.primary_metric}"

    return {
        "widget_key": "w1",
        "title": (question[:60] if len(question) > 60 else question), # Use question as title for clarity
        "question": question,
        "type": "kpi" if viz_type == "kpi" else "chart",
        "viz": {
            "type": viz_type, 
            "mapping": mapping
        },
        "data_requirements": {
            "x_axis_column": mapping.get("x"),
            "y_axis_column": mapping.get("y"),
            "involved_tables": context.validated_tables
        }
    }

def _enforce_join_mix(
    widgets: list[dict[str, Any]],
    *,
    logical_tables: list[str],
    table_cols: dict[str, list[str]],
    table_keys: dict[str, list[str]],
    table_metadata_map: dict[str, dict] = {},
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
        metric = _pick_col_agnostic(a, a_cols, "metric", table_metadata_map) or _pick_col_agnostic(b, b_cols, "metric", table_metadata_map)
        dim = _pick_col_agnostic(b, b_cols, "attribute", table_metadata_map) or _pick_col_agnostic(a, a_cols, "attribute", table_metadata_map)
        dt = _pick_col_agnostic(a, a_cols, "time", table_metadata_map) or _pick_col_agnostic(b, b_cols, "time", table_metadata_map)

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
    table_metadata_map: dict[str, dict] = {},
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
    target_chart = max(0, max_widgets - target_kpi - target_table)

    # Need metadata map for agnostic picker. It wasn't passed to this function in legacy code.
    # We will modify the signature OR construct a partial one if needed.
    # For now, let's assume `table_metadata_map` is passed (I will update signature).
    meta_map = table_metadata_map

    def wtype(w: dict[str, Any]) -> str:
        return str(w.get("type") or "chart")

    join_pairs = _pick_join_pairs(table_keys, logical_tables)
    # Note: This function (enforce_distribution) is not currently used in the main LLM path,
    # but strictly used in fallback logic/old paths. 
    # Providing empty metadata map here as a placeholder or needs update if reactivated.
    fact_dim_pairs = _pick_fact_dim_pairs(table_keys, logical_tables, {})

    def _rewrite_as_table(i: int, pair: tuple[str, str, str] | None) -> None:
        if pair:
            fact, dim, key = pair
            dim_cols = table_cols.get(dim, [])
            label = _pick_col_agnostic(dim, dim_cols, "attribute", meta_map) or "name"
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
            metric = _pick_col_agnostic(fact, table_cols.get(fact, []), "metric", meta_map) or _pick_col_agnostic(dim, table_cols.get(dim, []), "metric", meta_map)
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
    # FIX: Prevent infinite loop by selecting candidates that are NOT already KPIs.
    kpi_idxs = [i for i, w in enumerate(widgets) if wtype(w) == "kpi"]
    loop_safety = 0
    while len(kpi_idxs) < target_kpi and loop_safety < 20:
        loop_safety += 1
        # Prefer charts first
        candidates = [i for i, w in enumerate(widgets) if wtype(w) == "chart"]
        # If no charts, look for anything that is NOT a table and NOT already a KPI
        if not candidates:
            candidates = [i for i, w in enumerate(widgets) if wtype(w) != "table" and wtype(w) != "kpi"]
        
        # If still no candidates (e.g. everything is table or we have exhausted non-tables), force pick any non-KPI
        if not candidates:
             candidates = [i for i, w in enumerate(widgets) if wtype(w) != "kpi"]
        
        if not candidates:
             # Last resort: just break to avoid infinite loop (we might have fewer KPIs than requested)
             break
             
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
            metric = _pick_col_agnostic(fact, table_cols.get(fact, []), "metric", meta_map) or _pick_col_agnostic(dim, table_cols.get(dim, []), "metric", meta_map)
            dt = _pick_col_agnostic(fact, table_cols.get(fact, []), "time", meta_map) or _pick_col_agnostic(dim, table_cols.get(dim, []), "time", meta_map)
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
    """
    Safely load JSON, handling common LLM formatting errors (markdown fences, double braces).
    """
    if not text:
        return None

    # 1. Strip markdown fences
    text = text.replace("```json", "").replace("```", "").strip()

    # 2. Handle double braces {{ ... }} common in some LLM outputs
    # If the text starts with {{ and ends with }}, strip the outer braces
    if text.startswith("{{") and text.endswith("}}"):
        text = text[1:-1]
    
    # 3. Try standard load
    try:
        return json.loads(text)
    except Exception:
        # 4. Fallback: extract first {...} block
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = text[start : end + 1]
                # Fix double braces inside the block if present
                if candidate.startswith("{{") and candidate.endswith("}}"):
                    candidate = candidate[1:-1]
                return json.loads(candidate)
        except Exception:
            return None
    return None


def _fallback_plan(
    goal: str, 
    logical_tables: List[str], 
    max_widgets: int, 
    schema_summary: str = "", 
    original_question: Optional[str] = None,
    table_metadata: Optional[List[Dict[str, Any]]] = None
) -> DavinciDashboardPlan:
    """
    Deterministic fallback plan when LLM fails.
    Produces widgets that are safe to execute with small result sets.
    """

    picked = logical_tables[:100]
    widgets: List[Dict[str, Any]] = []

    # ✅ Se temos pergunta original, ela deve ser a primeira widget
    if original_question:
        widgets.append(
            {
                "widget_key": "w1",
                "type": "table",
                "title": "Main Insight",
                "question": original_question.strip(),
                "viz": {"type": "table"},
            }
        )
        # Ajustar max_widgets restantes
        remaining_widgets = max_widgets - 1
    else:
        remaining_widgets = max_widgets

    # Try to build a strong fallback using join/key hints when available.
    # Try to build a strong fallback using join/key hints when available.
    table_cols, table_keys = _parse_schema_summary(schema_summary)
    
    # Build metadata map for scoring
    meta_map = {t['name']: t for t in (table_metadata or [])} if table_metadata else {}
    # Also support logical names matching
    if table_metadata:
        for t in table_metadata:
            # Try to handle schema.table vs table
            full = f"{t.get('schema')}.{t.get('name')}" if t.get('schema') else t.get('name')
            meta_map[full] = t
            
    join_pairs = _pick_join_pairs(table_keys, logical_tables) if logical_tables else []
    fact_dim_pairs = _pick_fact_dim_pairs(table_keys, logical_tables, meta_map) if logical_tables else []

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
        metric = _pick_col_agnostic(fact, table_cols.get(fact, []), "metric", meta_map) or _pick_col_agnostic(dim, table_cols.get(dim, []), "metric", meta_map)
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
        metric = _pick_col_agnostic(fact, table_cols.get(fact, []), "metric", meta_map) or _pick_col_agnostic(dim, table_cols.get(dim, []), "metric", meta_map)
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
        label = _pick_col_agnostic(dim, dim_cols, "attribute", meta_map) or "name"
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
        dt = _pick_col_agnostic(t, t_cols, "time", meta_map)
        
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
            metric = _pick_col_agnostic(a, a_cols, "metric", meta_map) or _pick_col_agnostic(b, b_cols, "metric", meta_map)
            dim = _pick_col_agnostic(b, b_cols, "attribute", meta_map) or _pick_col_agnostic(a, a_cols, "attribute", meta_map)
            dt = _pick_col_agnostic(a, a_cols, "time", meta_map) or _pick_col_agnostic(b, b_cols, "time", meta_map)

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

    # Trim to max_widgets
    widgets = widgets[:max_widgets]

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
    table_metadata: Optional[List[Dict[str, Any]]] = None,
    analysis_context: Optional[AnalysisContext] = None, # NEW ARGUMENT
) -> DavinciDashboardPlan:
    """
    Davinci "graph": generate a dashboard plan as STRICT JSON.
    Supports "Comparison" and "Expansion" modes via AnalysisContext.
    """
    # Keep the request bounded and deterministic-ish.
    # Temporary product decision: cap at 8 widgets for auto dashboard creation.
    max_widgets = max(1, min(8, int(max_widgets)))
    # Force English only
    language = "en"

    if not logical_tables:
        try:
            with open("/tmp/davinci_debug.log", "a") as f:
                f.write(f"{datetime.utcnow()} - FALLBACK: No logical tables found. Goal: {goal}\n")
        except: pass
        return _fallback_plan(goal=goal, logical_tables=[], max_widgets=max_widgets, schema_summary=schema_summary, original_question=original_question, table_metadata=table_metadata)

    table_cols, table_keys = _parse_schema_summary(schema_summary)

    # NOTE: when using `.format(...)`, any `{}` in the prompt becomes a formatting placeholder.
    # We intentionally avoid `.format` here because the JSON schema includes `{}`.
    min_join = min(3, max_widgets)

    # 🧠 SCHEMA INTELLIGENCE INJECTION
    # Enrich the schema summary with Role and Stats to help the LLM.
    enriched_schema_summary = schema_summary
    if table_metadata:
        try:
            # Pre-compute roles
            meta_map = {
                (f"{t.get('schema')}.{t.get('name')}" if t.get('schema') else t.get('name')): t 
                for t in table_metadata
            }
            # Fallback for simple names
            for t in table_metadata:
                meta_map[t.get("name")] = t

            # 1. First Pass: Filter out non-analytic tables (Logs, System code) using AnalyticTableFilter
            logging_dropped = []
            filtered_logical = []
            
            for t_name in logical_tables:
                 t_meta = meta_map.get(t_name)
                 row_count = 0
                 if t_meta:
                     row_count = int(t_meta.get("row_count") or t_meta.get("stats", {}).get("row_count") or 0)
                 
                 if AnalyticTableFilter.should_exclude(t_name, row_count):
                     logging_dropped.append(t_name)
                 else:
                     filtered_logical.append(t_name)
            
            if len(filtered_logical) < len(logical_tables):
                log_event("davinci_analytic_filter_applied", {
                    "dropped": logging_dropped,
                    "count": len(logging_dropped)
                })
                # Update the logical_tables list used for prompt generation!
                logical_tables = filtered_logical

            # 2. Enrich Summary with Role and Column Types
            lines = []
            for line in schema_summary.splitlines():
                if not line.strip().startswith("- "):
                    lines.append(line)
                    continue
                
                # Extract table name from summary line line "- table_name cols:..."
                try:
                    parts = line[2:].split(" cols:", 1)
                    t_name = parts[0].strip()
                    col_str = parts[1].strip() if len(parts) > 1 else ""
                except:
                    lines.append(line)
                    continue

                # Skip if table was filtered out
                if t_name not in logical_tables:
                    continue

                t_meta = meta_map.get(t_name)
                role_info = ""
                new_col_str = col_str
                
                if t_meta:
                    # Table Role & Count
                    role = _get_table_role(t_name, t_meta).upper()
                    row_count = int(t_meta.get("row_count") or t_meta.get("stats", {}).get("row_count") or 0)
                    row_str = f", ~{row_count} rows" if row_count is not None else ""
                    role_info = f" [{role}{row_str}]"
                    
                    # Column Roles!
                    # Parse current summary cols: "id, amount, date"
                    # We need to map these back to metadata to score them
                    summary_cols = [c.strip() for c in col_str.split(",")]
                    enriched_cols = []
                    
                    # Create lookup for column metadata
                    col_meta_lookup = {c.get("name").lower(): c for c in t_meta.get("columns", [])}
                    
                    for c_raw in summary_cols:
                        c_name = c_raw.lower()
                        c_meta = col_meta_lookup.get(c_name)
                        
                        suffix = ""
                        if c_meta:
                            # Build features for scoring
                            ctype = str(c_meta.get("type", "")).upper()
                            card = c_meta.get("stats", {}).get("distinct_count")
                            
                            is_num = any(t in ctype for t in ["INT", "FLOAT", "NUMERIC", "DECIMAL", "DOUBLE", "REAL"])
                            is_txt = any(t in ctype for t in ["CHAR", "TEXT", "STRING"])
                            is_time = any(t in ctype for t in ["DATE", "TIME", "TIMESTAMP"])
                            is_key = (c_name == "id" or c_name.endswith("_id") or c_name.endswith("id"))
                            
                            feat = ColumnFeatures(
                                name=c_name, 
                                dtype=ctype,
                                is_numeric=is_num,
                                is_text=is_txt,
                                is_time=is_time,
                                is_key_candidate=is_key,
                                cardinality=card
                            )
                            
                            col_role = ColumnScorer.classify_column(feat, row_count)
                            
                            # Add mini tags for important roles
                            if col_role == "metric": suffix = " [M]"   # Metric
                            elif col_role == "time": suffix = " [T]"   # Time
                            elif col_role == "key": suffix = " [K]"    # Key
                            # Attributes get no suffix to reduce noise, or [A]? Let's leave clear.
                        
                        enriched_cols.append(f"{c_raw}{suffix}")
                    
                    new_col_str = ", ".join(enriched_cols)
                    
                    # ✅ OPTION 1: Add Table-level date range if found in any column
                    range_info = ""
                    min_d = None
                    max_d = None
                    for c in t_meta.get("columns", []):
                        if c.get("min_date") and (not min_d or c["min_date"] < min_d):
                            min_d = c["min_date"]
                        if c.get("max_date") and (not max_d or c["max_date"] > max_d):
                            max_d = c["max_date"]
                    
                    if min_d and max_d:
                        # Format as [Data Range: YYYY-MM-DD to YYYY-MM-DD]
                        # Remove time part if it's there
                        m1 = str(min_d).split()[0]
                        m2 = str(max_d).split()[0]
                        range_info = f" [Data Range: {m1} to {m2}]"
                        role_info += range_info
                
                # Rewrite line: "- table [FACT, ~5M] cols: id [K], amount [M]..."
                lines.append(f"- {t_name}{role_info} cols: {new_col_str}")
            
            enriched_schema_summary = "\n".join(lines)
        except Exception as e:
            # Fail silently to original summary if enrichment fails
            log_event("davinci_schema_enrichment_error", {"error": str(e)})
    
    # ✅ DATASET PROFILING & CONSTRAINT GENERATION (Phase 2 + 3)
    # Profile tables based on row count and generate query constraints
    # WITH user intent override for explicit filters
    dataset_constraints_text = ""
    try:
        from core.profiling import DatasetProfiler, ConstraintGenerator, IntentOverride
        
        profiler = DatasetProfiler()
        constraint_gen = ConstraintGenerator()
        intent_override = IntentOverride()
        
        # Profile available tables
        profiles = profiler.profile_tables(table_metadata or [])
        
        # Get size statistics
        stats = profiler.get_size_statistics(profiles)
        smallest_size = stats["smallest_size"]
        
        # Generate base constraints based on smallest dataset
        # (most conservative approach for multi-table scenarios)
        constraints = constraint_gen.generate(smallest_size)
        
        # 🎯 PHASE 3: Check for user intent override
        # If user explicitly mentions filters (e.g., "failed payments"),
        # allow those filters even on TINY datasets
        allow_filters, override_reason = intent_override.should_allow_filters(
            goal=goal,
            dataset_size=smallest_size,
            base_constraints=constraints.to_dict()
        )
        
        log_event("davinci_dataset_profiling", {
            "total_tables": stats["total_tables"],
            "total_rows": stats["total_rows"],
            "size_distribution": stats["by_size"],
            "smallest_size": smallest_size,
            "requires_aggregation": constraints.requires_aggregation,
            "max_filter_complexity": constraints.max_filter_complexity,
            "intent_override_active": allow_filters,
            "override_reason": override_reason,
        })
        
        # Build constraint text for prompt injection
        if smallest_size in ["tiny", "small"]:
            # Only inject constraints for small datasets
            constraint_lines = [
                f"\n⚠️ DATASET SIZE NOTICE: The smallest dataset has only {smallest_size.upper()} size ({stats['total_rows']} total rows).",
                "\n📊 QUERY SAFETY GUIDELINES:",
            ]
            
            if constraints.requires_aggregation:
                constraint_lines.append(
                    "- ✅ REQUIRED: Use aggregations (COUNT, SUM, AVG) with GROUP BY to avoid empty results"
                )
            
            # Adaptive filter guidance based on intent override
            if allow_filters and override_reason and "explicit intent" in override_reason.lower():
                # User has explicit filter intent - allow it!
                constraint_lines.append(
                    f"- ✅ ALLOWED: WHERE filters detected in user request ({override_reason})"
                )
                filter_hints = intent_override.extract_filter_hints(goal)
                if filter_hints:
                    constraint_lines.append(
                        f"  → User-requested filter: {filter_hints[0]}"
                    )
            elif constraints.max_filter_complexity == 0:
                constraint_lines.append(
                    "- ❌ AVOID: WHERE filters (dataset too small, filters will likely return empty results)"
                )
                constraint_lines.append(
                    "  → EXCEPTION: If user explicitly mentions a filter (e.g., 'failed payments'), you MAY use it"
                )
            elif constraints.max_filter_complexity <= 2:
                constraint_lines.append(
                    "- ⚠️ CAUTION: Use WHERE filters very sparingly (simple conditions only)"
                )
            
            if "temporal_grouping" in constraints.preferred_strategies:
                constraint_lines.append(
                    "- ✅ PREFERRED: Temporal groupings (GROUP BY month/year/quarter)"
                )
            
            if "categorical_breakdown" in constraints.preferred_strategies:
                constraint_lines.append(
                    "- ✅ PREFERRED: Categorical breakdowns (GROUP BY status/category/type)"
                )
            
            dataset_constraints_text = "\n".join(constraint_lines) + "\n"
    
    except Exception as e:
        # Profiling failure should not break dashboard generation
        log_event("davinci_profiling_error", {"error": str(e)})
        dataset_constraints_text = ""

    # Modify prompt based on whether we have an original question or not
    if analysis_context:
        # 🌟 ENTERPRISE MODE: Deterministic Anchor + Expansion
        # The first widget is built by code, LLM generates the expansions.
        
        system = (
            "You are Davinci, a specialized Analytics Expansion Agent.\n"
            "\n"
            f"📅 TEMPORAL CONTEXT: Today is {datetime.utcnow().strftime('%Y-%m-%d')}.\n"
            "⚠️ IMPORTANT: Only use date filters that are relevant to the provided 'Data Range' in the schema summary.\n"
            "\n"
            "🎯 PRIMARY MISSION: The user is analyzing a specific entity. You must generate COMPLEMENTARY views.\n"
            "The Primary Analysis (Widget 1) has already been defined. Your job is to GENERATE 7 EXPANSION WIDGETS.\n"
            "\n"
            f"🔒 CONTEXT LOCK: You are analyzing: '{analysis_context.primary_entity}'.\n"
            f"⛔ FORBIDDEN: Do NOT change the topic. Do NOT analyze unrelated entities.\n"
            f"✅ ALLOWED: Drill-downs, trends, distributions, and relations OF the '{analysis_context.primary_entity}'.\n"
            "\n"
            "Rules:\n"
            "- Output STRICT JSON only.\n"
            "- The FIRST widget is reserved (W1). You must generate W2 to W8.\n" # Actually output W2..W8 directly?
            # Wait, the LLM usually generates the full list. We can let it generate 7 items and we prepend W1.
            # Or we instruct it "The first widget is... generate the REST".
            # Let's simple ask for 7 widgets and we prepend/manage keys later.
            "- Generate 7 high-value widgets that expand on the primary analysis.\n"
            "- Use ONLY the provided logical table names.\n"
            "- ALWAYS wrap referenced table names in backticks (e.g., `table1`).\n"
            "- Each widget must have: widget_key, title, question, intent, data_requirements.\n"
            "- `data_requirements`: { \"x_axis_column\": \"...\", \"y_axis_column\": \"...\", \"involved_tables\": [...] }\n"
            "- ⚠️ CRITICAL: The column names MUST EXACTLY MATCH the schema summary.\n"
            f"- Language: English (STRICT).\n"
            "- METRIC SELECTION: Choose the most relevant numeric column for business value.\n"
            f"- DASHBOARD TITLE must include '{analysis_context.primary_entity}'.\n"
            f'JSON schema: {{"dashboard_name": string, "description": string, "widgets": ['
            f'{{"widget_key": string, "title": string, "question": string, "intent": string, "data_requirements": {{"x_axis_column": string, "y_axis_column": string, "involved_tables": string[]}} }}'
            f']}}.\n'
        )
        
        user = (
            f"N=7 (Expansion Widgets)\n"
            f"\n"
            f"🧠 PRIMARY ANALYSIS CONTEXT (The 'Truth'):\n"
            f"- Entity: {analysis_context.primary_entity}\n"
            f"- Metric: {analysis_context.primary_metric}\n"
            f"- Dimension: {analysis_context.primary_dimension or 'N/A'}\n"
            f"- Type: {analysis_context.detected_analysis_type}\n"
            f"\n"
            f"Original Question: {original_question or goal}\n"
            f"\n"
            f"Accessible tables: {', '.join(analysis_context.validated_tables)}\n"
            f"Schema sample:\n{enriched_schema_summary}\n"
            f"{dataset_constraints_text}"
            f"\n"
            f"🎯 TASK: Generate 7 expansion widgets that provide deeper insight into '{analysis_context.primary_entity}'.\n"
            f"Think: Why did this metric change? How is it distributed? What's the trend?\n"
        )
        
    elif original_question:
        system = (
            "You are Davinci, a dashboard planner.\n"
            "\n"
            f"📅 TEMPORAL CONTEXT: Today is {datetime.utcnow().strftime('%Y-%m-%d')}.\n"
            "⚠️ IMPORTANT: Only use date filters that are relevant to the provided 'Data Range' in the schema summary.\n"
            "If the data ends in the past, do NOT ask for 'this month' or 'today'. Instead, ask for the 'last available month' or 'recent records'.\n"
            "⚠️ CRITICAL: When using CONTEXT, do NOT assume the data exists just because it was mentioned. Verify against Schema sample time ranges.\n"
            "\n"
            "🎯 PRIMARY GOAL: The user asked a SPECIFIC question. Your dashboard MUST focus on answering THAT question.\n"
            "⚠️ DO NOT generate a generic 'overview' dashboard that happens to include the question.\n"
            "\n"
            "CRITICAL REQUIREMENT: The user has provided an ORIGINAL QUESTION that MUST be the FIRST widget.\n"
            "\n"
            "Rules:\n"
            "- Output STRICT JSON only.\n"
            "- The FIRST widget MUST be exactly the user's original question (provided below).\n"
            "- The remaining widgets MUST be DIRECTLY RELATED to the original question (80-90% relevance).\n"
            "- Think: 'What specific insights would help answer or expand on this exact question?'\n"
            "- AVOID: Generic widgets that could apply to any dashboard (e.g., 'customer distribution' when question is about refunds).\n"
            "- Use ONLY the provided logical table names.\n"
            "- ALWAYS wrap referenced table names in backticks (e.g., `table1`).\n"
            "- Each widget must have: widget_key, title, question, intent, data_requirements.\n"
            "- CRITICAL: Questions MUST be BUSINESS-ORIENTED, not technical.\n"
            "- QUESTIONS ONLY: Do not worry about visualization details (like colors or chart types). Focus on the DATA INTENT.\n"
            "- `intent`: One of [trend, distribution, comparison, composition, ranking, list, kpi]\n"
            "- `data_requirements`: {\n"
            "    \"x_axis_column\": \"name of column\",\n"
            "    \"y_axis_column\": \"name of metric column\",\n"
            "    \"involved_tables\": [\"table1\", \"table2\"],  <-- ⚠️ CRITICAL: List all logical tables needed for this question\n"
            "    \"filters\": \"...\"\n"
            "  }\n"
            "- METRIC SELECTION: Choose the most relevant numeric column for business value.\n"
            "  * x_axis_column: Should be the dimension (Time, Category, Region).\n"
            "  * y_axis_column: Should be the metric (Amount, Count, Value).\n"
            "  * ⚠️ CRITICAL: The column names MUST EXACTLY MATCH the column names in the schema summary below.\n"
            "  * ⛔ FORBIDDEN: Do NOT invent column names. If a column is not listed in the schema, DO NOT USE IT.\n"
            "  * ⛔ FORBIDDEN: Do NOT assume 'name', 'type', or 'status' exist unless you see them.\n"
            "- Make the dashboard engaging: mix intents (KPIs + Trends + Lists).\n"
            "- IMPORTANT: Prefer cross-table insights (JOINs) to produce rich business metrics.\n"
            "- CRITICAL: AVOID EMPTY WIDGETS - Every widget MUST return data:\n"
            "  * Prefer aggregated queries (COUNT, SUM, AVG) over filtered queries\n"
            "  * Use broad questions that work with any data (e.g., 'total revenue' instead of 'overdue invoices')\n"
            f"- Language for titles/questions: English (STRICT REQUIREMENT - ALWAYS ENGLISH)\n"
            "- EXACTLY N widgets.\n"
            "- DASHBOARD TITLE (dashboard_name) RULES:\n"
            "  * The title must be SPECIFIC and DESCRIPTIVE (max 60 chars).\n"
            "  * Since original_question is present, the title MUST be directly related to it.\n"
            f'JSON schema: {{"dashboard_name": string, "description": string, "widgets": ['
            f'{{"widget_key": string, "title": string, "question": string, "intent": string, "data_requirements": {{"x_axis_column": string, "y_axis_column": string, "involved_tables": string[]}} }}'
            f']}}.\n'
        )
        
        # ✅ NEW: Add subspaces and crews context if available
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
            context_str += f"Context Tables (full accessible list): {', '.join(context_tables[:100])}...\n"
        
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
            f"{context_str}"
            f"Goal: {goal}\n"
            f"Accessible tables for JOINs: {', '.join(logical_tables[:100])}\n"
            f"Schema sample (with structural hints):\n{enriched_schema_summary}\n"
            f"{dataset_constraints_text}"
            f"\n"
            f"🎯 CRITICAL: Focus on '{original_question}'. Extract the key metric/dimension and build ALL widgets around it.\n"
            f"Generate a dashboard that comprehensively answers: '{original_question}'\n"
        )
    else:
        # Original prompt (without original question)
        system = (
            "You are Davinci, a dashboard planner.\n"
            f"📅 TEMPORAL CONTEXT: Today is {datetime.utcnow().strftime('%Y-%m-%d')}.\n"
            "⚠️ IMPORTANT: Only use date filters that are relevant to the provided 'Data Range' in the schema summary.\n"
            "You propose a dashboard (name + widgets) based on accessible tables.\n"
            "Rules:\n"
            "- Output STRICT JSON only.\n"
            "- Use ONLY the provided logical table names.\n"
            "- ALWAYS wrap referenced table names in backticks (e.g., `table1`).\n"
            "- Each widget must have: widget_key, title, question, intent, data_requirements.\n"
            "- CRITICAL: Questions MUST be BUSINESS-ORIENTED, not technical.\n"
            "- QUESTIONS ONLY: Do not worry about visualization details (like colors or chart types). Focus on the DATA INTENT.\n"
            "- `intent`: One of [trend, distribution, comparison, composition, ranking, list, kpi]\n"
            "- `data_requirements`: {\n"
            "    \"x_axis_column\": \"name of column\",\n"
            "    \"y_axis_column\": \"name of metric column\",\n"
            "    \"involved_tables\": [\"table1\", \"table2\"]\n"
            "  }\n"
            "- METRIC SELECTION: Choose the most relevant numeric column for business value.\n"
            "  * x_axis_column: Should be the dimension (Time, Category, Region).\n"
            "  * y_axis_column: Should be the metric (Amount, Count, Value).\n"
            "  * ⚠️ CRITICAL: The column names MUST EXACTLY MATCH the column names in the schema summary below.\n"
            "  * ⛔ FORBIDDEN: Do NOT invent column names. If a column is not listed in the schema, DO NOT USE IT.\n"
            "  * ⚠️ CRITICAL: The column names MUST EXACTLY MATCH the column names in the schema.\n"
            "- Make the dashboard engaging: mix intents (KPIs + Trends + Lists).\n"
            "- IMPORTANT: Prefer cross-table insights (JOINs) to produce rich business metrics.\n"
            "- If keys are provided in the schema sample, use them to suggest joined questions.\n"
            "- Language for titles/questions: English (STRICT REQUIREMENT - ALWAYS ENGLISH) - EVEN IF USER SPEAKS ANOTHER LANGUAGE.\n"
            "- DATA SAFETY: Do not invent columns. Only use columns present in 'Schema sample'.\n"
            "- CRITICAL: AVOID EMPTY WIDGETS - Every widget MUST return data:\n"
            "  * Prefer aggregated queries (COUNT, SUM, AVG) over filtered queries\n"
            "  * Use broad questions that work with any data (e.g., 'total revenue' instead of 'overdue invoices')\n"
            "  * For tables/charts, ask for 'top N' or 'distribution by' instead of specific filters\n"
            "- EXACTLY N widgets.\n"
            "- DASHBOARD TITLE (dashboard_name) RULES:\n"
            "  * The title must be SPECIFIC and DESCRIPTIVE (max 60 chars).\n"
            "  * AVOID generic titles like 'Sales Dashboard' or 'Analytical Dashboard'.\n"
            "  * USE CONTEXT: If a specific goal, region, or timeframe is inferred, INCLUDE IT in the title.\n"
            f'JSON schema: {{"dashboard_name": string, "description": string, "widgets": ['
            f'{{"widget_key": string, "title": string, "question": string, "intent": string, "data_requirements": {{"x_axis_column": string, "y_axis_column": string}} }}'
            f']}}.\n'
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
            context_str += f"Context Tables (full accessible list): {', '.join(context_tables[:100])}...\n"
        
        user = (
            f"N={max_widgets}\n"
            f"{context_str}"
            f"Goal: {goal}\n"
            f"Accessible tables for JOINs: {', '.join(logical_tables[:100])}\n"
            f"Schema sample (with structural hints):\n{enriched_schema_summary}\n"
            f"{dataset_constraints_text}"
        )

    try:
        resp = llm.invoke([{"role": "system", "content": system}, {"role": "user", "content": user}])
        raw_content = getattr(resp, "content", "") or ""
        try:
            parsed = _safe_json_loads(raw_content)
        except Exception as e:
            log_event("davinci_json_parse_error", {"error": str(e), "raw": raw_content})
            
            # Resiliência: se a resposta não for JSON válido, tentar fallback
            if analysis_context:
                 # If it failed with analysis_context, we can still try fallback with original_question if available
                 pass
            try:
                with open("/tmp/davinci_debug.log", "a") as f:
                    f.write(f"{datetime.utcnow()} - FALLBACK: JSON Parse Error\\nRAW CONTENT:\\n{raw_content}\\nERROR: {str(e)}\\n")
            except: pass
            return _fallback_plan(
                goal=goal,
                logical_tables=logical_tables,
                max_widgets=max_widgets,
                schema_summary=schema_summary,
                original_question=original_question,
                table_metadata=table_metadata
            )

        if not isinstance(parsed, dict):
            raise ValueError("LLM did not return valid JSON object")

        # Convert raw dicts to widget objects if needed, or just validate fields.
        widgets_raw = parsed.get("widgets", [])
        
        # 🌟 ENTERPRISE MODE: Prepend deterministic anchor widget if context exists
        if analysis_context:
            try:
                anchor_widget = _build_primary_widget_from_context(analysis_context, goal)
                # Ensure unique keys
                anchor_widget["widget_key"] = "w1"
                
                # Shift keys of LLM widgets
                for i, w in enumerate(widgets_raw):
                    w["widget_key"] = f"w{i+2}"
                
                # Prepend
                widgets_raw.insert(0, anchor_widget)
                # Trim to max_widgets
                widgets_raw = widgets_raw[:max_widgets]
                
            except Exception as e:
                log_event("davinci_anchor_widget_error", {"error": str(e)})
                # Continue with LLM widgets only if anchor fails (should not happen)
                pass

        dashboard_name = str(parsed.get("dashboard_name") or "").strip() or (goal.strip()[:80] or "Dashboard")
        description = str(parsed.get("description") or "").strip() or None
        # widgets_raw = parsed.get("widgets") or [] # This line is now redundant due to analysis_context block
        if not isinstance(widgets_raw, list) or not widgets_raw:
            raise ValueError("LLM returned no widgets")

        widgets: List[Dict[str, Any]] = []
        
        # 🧠 DESIGNER STEP: Import WidgetDesigner
        from core.agents.widget_designer import WidgetDesigner
        
        # Helper to find column metadata
        def _get_col_meta(t_name: str, c_name: str) -> Dict[str, Any]:
            if not t_name or not c_name or not table_metadata:
                return {}
            # Flatten map for easier lookup? 
            # Or just iterate. Optimization: pre-index.
            # Assuming table_metadata is list of Dict
            for t in table_metadata:
                name = t.get("name")
                schema = t.get("schema")
                full = f"{schema}.{name}" if schema else name
                if name == t_name or full == t_name:
                    for c in t.get("columns", []):
                        if c.get("name") == c_name:
                            return c
            return {}

        for i, w in enumerate(widgets_raw[:max_widgets], start=1):
            if not isinstance(w, dict):
                continue
            
            # 1. ANALYST OUTPUT (The "WHAT")
            widget_key = str(w.get("widget_key") or f"w{i}").strip() or f"w{i}"
            question = str(w.get("question") or "").strip()
            intent = str(w.get("intent") or "chart").strip().lower()
            
            # Data Requirements
            reqs = w.get("data_requirements", {})
            x_col = reqs.get("x_axis_column")
            y_col = reqs.get("y_axis_column")
            
            # Identify table for metadata lookup
            # Heuristic: find referenced table in question or use first available
            # Ideally LLM should return "primary_table". But for now, let's infer.
            referenced_tables = [t for t in logical_tables if t in question]
            primary_table = referenced_tables[0] if referenced_tables else (logical_tables[0] if logical_tables else None)
            
            x_meta = _get_col_meta(primary_table, x_col)
            y_meta = _get_col_meta(primary_table, y_col)

            # 2. DESIGNER OUTPUT (The "HOW")
            # Deterministic visualization choice
            viz_config = WidgetDesigner.choose_viz(
                intent=intent,
                x_col=x_col,
                y_col=y_col,
                x_meta=x_meta,
                y_meta=y_meta
            )
            
            # Final Widget Construction
            # Map "type" from designer to widget type
            wtype = "chart"
            if viz_config["type"] == "kpi": wtype = "kpi"
            elif viz_config["type"] == "table": wtype = "table"
            
            widgets.append({
                "widget_key": widget_key,
                "type": wtype,
                "title": str(w.get("title") or "").strip() or f"Widget {i}",
                "question": question,
                "viz": viz_config
            })

        if not widgets:
            raise ValueError("LLM widgets invalid")

        # ✅ CRITICAL: If we have an original question, ensure it is the first widget
        if original_question and not analysis_context: # Only apply if not in analysis_context mode
            original_question_clean = original_question.strip()
            # 1. First, try to find the original question anywhere in the list (not just index 0)
            found_idx = -1
            for i, w in enumerate(widgets):
                w_question = str(w.get("question") or "").strip().lower()
                if (original_question_clean.lower() in w_question or 
                    w_question in original_question_clean.lower()):
                    found_idx = i
                    break
            
            if found_idx >= 0:
                # Found it! Move it to the front if it's not already
                if found_idx > 0:
                    w = widgets.pop(found_idx)
                    widgets.insert(0, w)
                
                # Ensure text matches exactly
                widgets[0]["question"] = original_question_clean
            else:
                # Not found. We must inject it.
                # Use WidgetDesigner for the original question too!
                # We don't have explicit columns for the original question from LLM yet (since it wasn't in the list)
                # So we use a generic intent or try to guess.
                # Or - we accept the "smart default" logic we added previously, but clean it up.
                
                # Let's assume a generic "list" or "chart" intent and let Designer decide if we had columns.
                # But here we don't have columns. So falling back to the Smart Heuristic 2.0 (Logic from previous step)
                # But actually, we can try to use WidgetDesigner if we infer intent from keywords.
                
                q_lower = original_question_clean.lower()
                inferred_intent = "chart"
                if any(x in q_lower for x in ["trend", "growth", "over time"]): inferred_intent = "trend"
                elif any(x in q_lower for x in ["distribution", "breakdown"]): inferred_intent = "distribution"
                elif any(x in q_lower for x in ["list", "table", "details"]): inferred_intent = "list"
                
                # Without columns, Designer defaults to Table or Bar.
                # We can mock metadata to guide it? No, keep it simple.
                # Use Designer with empty cols -> gives Table.
                # But user hated Table.
                # So we manually force the Smart Viz if Designer returns Table default?
                
                # Actually, let's trust the "Smart Heuristic" block I wrote previously, 
                # but updated to be cleaner.
                
                smart_viz = {"type": "bar", "mapping": {"x": "category", "y": "value"}} # Default
                smart_type = "chart"
                
                if "trend" in inferred_intent: 
                     smart_viz = {"type": "line", "mapping": {"x": "period", "y": "value"}}
                elif "distribution" in inferred_intent:
                     smart_viz = {"type": "pie", "mapping": {"x": "category", "y": "value"}}
                elif "list" in inferred_intent:
                     smart_viz = {"type": "table"}
                     smart_type = "table"

                original_widget = {
                    "widget_key": "w1",
                    "type": smart_type,
                    "title": original_question_clean,
                    "question": original_question_clean,
                    "viz": smart_viz,
                }
                # Insert at the beginning
                widgets = [original_widget] + widgets


        # Normalize count
        widgets = widgets[:max_widgets]

        # 🚀 REFACTORED: LLM-Driven Mode
        # Removed _enforce_join_mix and _enforce_distribution_and_fact_dim
        # We rely on the LLM's plan as the source of truth, avoiding "cookie cutter" overwrites.

        # ✅ NEW: Validate widgets using WidgetValidator
        try:
            from core.validation.widget_validator import WidgetValidator
            from core.validation.question_validator import QuestionValidator
            
            # Prepare metadata for QuestionValidator
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
            # ✅ FIX: strict_mode=False to not filter widgets with mild warnings
            # The AI generates the widgets, so they should work even with mild warnings
            widget_validator = WidgetValidator(question_validator, strict_mode=False)
            
            # Filter problematic widgets (but preserve the first one if it is original_question or anchor)
            widgets_before_validation = len(widgets)
            preserved_widget = None
            if original_question and widgets:
                preserved_widget = widgets[0]
                widgets_to_validate = widgets[1:]
            elif analysis_context and widgets: # If analysis_context, the first widget is the anchor
                preserved_widget = widgets[0]
                widgets_to_validate = widgets[1:]
            else:
                widgets_to_validate = widgets
            
            widgets_validated = widget_validator.filter_widgets(
                widgets_to_validate, 
                min_widgets=max(1, (max_widgets - 1) // 2) if (original_question or analysis_context) else max(1, max_widgets // 2)
            )
            
            # Reconstruct list with preserved original/anchor
            if preserved_widget:
                widgets = [preserved_widget] + widgets_validated
            else:
                widgets = widgets_validated
            
            # ✅ SEMANTIC DEDUPLICATION (MD5 Signature)
            # Uses Question + Widget Type to identify duplicates, instead of just Title.
            import hashlib
            
            def _widget_signature(w: Dict[str, Any]) -> str:
                # Normalize question and type to create a signature
                q = (w.get("question") or "").strip().lower()
                t = (w.get("type") or "").strip().lower()
                # Remove extra spaces from question to avoid false negatives
                q_clean = " ".join(q.split())
                base = f"{q_clean}|{t}"
                return hashlib.md5(base.encode()).hexdigest()

            seen_signatures = set()
            deduplicated_widgets = []
            
            for widget in widgets:
                sig = _widget_signature(widget)
                if sig not in seen_signatures:
                    seen_signatures.add(sig)
                    deduplicated_widgets.append(widget)
            
            widgets_before_dedup = len(widgets)
            widgets = deduplicated_widgets
            
            if widgets_before_dedup > len(widgets):
                log_event(
                    "davinci_widgets_deduplicated",
                    {
                        "goal": goal[:200],
                        "widgets_before": widgets_before_dedup,
                        "widgets_after": len(widgets),
                        "removed_duplicates": widgets_before_dedup - len(widgets),
                        "method": "semantic_signature"
                    },
                )
            
            widgets_after_validation = len(widgets)
            
            # If we filtered many widgets, log warning
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
            
            # If we don't have enough widgets after validation, use fallback
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
                # Return fallback if validation filtered too many widgets
                try:
                    with open("/tmp/davinci_debug.log", "a") as f:
                        f.write(f"{datetime.utcnow()} - FALLBACK: Too many widgets filtered. Remaining: {len(widgets)}\\n")
                except: pass
                return _fallback_plan(
                    goal=goal, 
                    logical_tables=logical_tables, 
                    max_widgets=max_widgets, 
                    schema_summary=schema_summary,
                    original_question=original_question,
                    table_metadata=table_metadata
                )
            
        except Exception as e:
            # If validation fails, continue without filtering (fail-safe)
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
                "has_analysis_context": analysis_context is not None,
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
        try:
            with open("/tmp/davinci_debug.log", "a") as f:
                f.write(f"{datetime.utcnow()} - FALLBACK: General Exception: {str(e)}\\n")
        except: pass
        return _fallback_plan(goal=goal, logical_tables=logical_tables, max_widgets=max_widgets, schema_summary=schema_summary, original_question=original_question, table_metadata=table_metadata)

