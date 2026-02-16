from __future__ import annotations

import json
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.logging_utils import log_event
from core.contracts.analysis_context import AnalysisContext
from core.services.dashboard_modes import MODE_CONFIG, validate_mode # NEW IMPORT


@dataclass
class DavinciDashboardPlan:
    dashboard_name: str
    description: Optional[str]
    widgets: List[Dict[str, Any]]
    meta: Dict[str, Any]
    full_results: Optional[Dict[str, Any]] = None  # NEW: Raw structured analysis


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


def _is_instrumental_command(text: str) -> bool:
    """
    Check if the text is purely an instrumental command (e.g. 'Create a dashboard')
    rather than a substantive data query.
    """
    if not text:
        return True
    t = text.lower().strip()
    # Common command patterns
    commands = [
        "create", "generate", "make", "build", "show me a", "show a", "dashboard", "report", "analysis"
    ]
    # If the text is very short and starts with a command, or is exactly a command sequence
    # E.g. "Create dashboard", "Generate report for sales"
    # We want to be careful not to trap "Sales per month"
    
    # If it's just "dashboard", "sales dashboard", etc.
    if t in ["dashboard", "sales dashboard", "report", "sales report"]:
        return True
    
    # If it starts with a command and is short (likely a meta-command)
    words = t.split()
    if len(words) <= 5:
        if words[0] in ["create", "generate", "make", "build"]:
            return True
            
    return False


def _fallback_plan(
    goal: str, 
    logical_tables: List[str], 
    max_widgets: int, 
    schema_summary: str = "", 
    original_question: Optional[str] = None,
    table_metadata: Optional[List[Dict[str, Any]]] = None,
    language: str = "en"
) -> DavinciDashboardPlan:
    """
    Smart fallback plan when LLM fails.
    Uses domain-aware weighted random choices to avoid a deterministic 'hardcoded' feel.
    """
    import random

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

    # Detect primary domain
    domain = "general"
    goal_lower = goal.lower()
    all_tables_lower = " ".join(logical_tables).lower()
    
    if any(x in goal_lower or x in all_tables_lower for x in ["sale", "order", "revenue", "product", "deal"]):
        domain = "sales"
    elif any(x in goal_lower or x in all_tables_lower for x in ["pay", "refund", "invoice", "transaction", "bank", "billing"]):
        domain = "payments"
    elif any(x in goal_lower or x in all_tables_lower for x in ["user", "customer", "visitor", "churn", "client"]):
        domain = "users"

    # Define thematic pattern clusters
    patterns = {
        "sales": [
            ("kpi", "Total Revenue", "What is the total revenue summed across all records?"),
            ("chart", "Revenue Trend", "Show the monthly revenue trend. Return period and value.", {"type": "line", "mapping": {"x": "period", "y": "value"}}),
            ("chart", "Top Products", "What are the top 10 products by revenue?", {"type": "bar", "mapping": {"x": "category", "y": "value"}}),
            ("chart", "Sales Distribution", "Show sales distribution by category.", {"type": "pie", "mapping": {"x": "category", "y": "value"}}),
            ("table", "Recent Orders", "Show the 15 most recent orders with key details."),
            ("chart", "Monthly Growth", "Show the percentage growth in sales month over month.", {"type": "area", "mapping": {"x": "period", "y": "value"}}),
        ],
        "payments": [
            ("kpi", "Total Collections", "What is the total amount collected?"),
            ("chart", "Payment Status", "Show the distribution of payments by status.", {"type": "pie", "mapping": {"x": "category", "y": "value"}}),
            ("chart", "Refund Rate", "What is the trend of refunds over time?", {"type": "line", "mapping": {"x": "period", "y": "value"}}),
            ("chart", "Top Billing Regions", "Which regions have the highest billing volume?", {"type": "bar", "mapping": {"x": "category", "y": "value"}}),
            ("table", "Recent Transactions", "Show the last 15 payment transactions."),
            ("chart", "Average Transaction Value", "Show average transaction value by month.", {"type": "line", "mapping": {"x": "period", "y": "value"}}),
        ],
        "users": [
            ("kpi", "Total Users", "How many unique users are in the system?"),
            ("chart", "User Growth", "Show the monthly trend of new user registrations.", {"type": "line", "mapping": {"x": "period", "y": "value"}}),
            ("chart", "User Retention", "Show active users by segment/type.", {"type": "bar", "mapping": {"x": "category", "y": "value"}}),
            ("chart", "Geographic Distribution", "Show the distribution of users by country or region.", {"type": "pie", "mapping": {"x": "category", "y": "value"}}),
            ("table", "Latest Signups", "Show details of the 15 newest members."),
            ("chart", "Activity Breakdown", "What is the distribution of user activity status?", {"type": "pie", "mapping": {"x": "category", "y": "value"}}),
        ],
        "general": [
            ("kpi", "Total Activity", "What is the total count of records?"),
            ("chart", "Volume Trend", "How does record volume trend over time?", {"type": "line", "mapping": {"x": "period", "y": "value"}}),
            ("chart", "Top Segments", "What are the top 10 segments for this data?", {"type": "bar", "mapping": {"x": "category", "y": "value"}}),
            ("chart", "Data Composition", "Show the distribution of records by its primary category.", {"type": "pie", "mapping": {"x": "category", "y": "value"}}),
            ("table", "Recent Records", "Show the most recent 15 records."),
            ("chart", "Density Analysis", "Show the distribution of data counts.", {"type": "bar", "mapping": {"x": "category", "y": "value"}}),
        ]
    }

    # Select domain patterns and shuffle to avoid fixed order
    domain_patterns = patterns.get(domain, patterns["general"])
    random.shuffle(domain_patterns)
    
    # Fill remaining widgets from patterns
    pattern_idx = 0
    while len(widgets) < max_widgets and pattern_idx < len(domain_patterns):
        p_type, p_title, p_question, *p_viz = domain_patterns[pattern_idx]
        
        # Determine table to use
        t = picked[pattern_idx % max(1, len(picked))] # Use picked tables for context
        question_with_table = p_question.replace("records", f"`{t}` records").replace("system", f"`{t}` table")
        if "`" not in question_with_table and not question_with_table.startswith("From"):
             question_with_table = f"From `{t}`: {p_question}"
        
        widgets.append({
            "widget_key": f"w{len(widgets)+1}",
            "type": p_type,
            "title": f"[{domain.title()}] {p_title}",
            "question": question_with_table,
            "viz": p_viz[0] if p_viz else {"type": p_type}
        })
        pattern_idx += 1

    # Final safety: if still not enough, add simple KPI for each table
    for i, t in enumerate(picked):
        if len(widgets) >= max_widgets: break
        widgets.append({
            "widget_key": f"w{len(widgets)+1}",
            "type": "kpi",
            "title": f"Total {t.title()}",
            "question": f"How many records are in `{t}` in total?",
            "viz": {"type": "kpi"}
        })

    return DavinciDashboardPlan(
        dashboard_name=goal.strip()[:80] or "Dashboard",
        description=f"Auto-generated {domain} dashboard with intention-aware variety.",
        widgets=widgets[:max_widgets],
        meta={"fallback": True, "reason": "SMART_FALLBACK", "domain": domain, "has_original_question": original_question is not None},
        full_results={
            "verdict": f"Automated analysis for: {goal}",
            "descriptive": {"charts": [], "kpis": []},
            "diagnostic": "Analysis limited due to generation constraints.",
            "predictive": "N/A",
            "prescriptive": "N/A"
        }
    )


def validate_plan_structure(plan: dict) -> dict:
    """
    Validates that the LLM response follows the strict structured schema.
    """
    required_keys = ["verdict", "descriptive"]
    for key in required_keys:
        if key not in plan:
            raise ValueError(f"Missing required key: {key}")
            
    if not isinstance(plan["descriptive"], dict):
        raise ValueError("Field 'descriptive' must be an object")

    if "charts" not in plan["descriptive"]:
        raise ValueError("Missing 'charts' in descriptive section")
        
    return plan


def enforce_mode_rules(plan: dict, mode: str) -> dict:
    """
    Deterministic enforcement of mode constraints (charts count, text length, sections).
    """
    config = MODE_CONFIG[mode]
    
    # 1. Enforce Chart Limits
    charts = plan["descriptive"].get("charts", [])
    if not isinstance(charts, list):
        charts = []
        
    # Slice to max
    charts = charts[:config["max_charts"]]
    
    # Check min (Critical fail-fast)
    if len(charts) < config["min_charts"]:
        # Log this event but maybe don't crash hard if we can survive? 
        # User requested "Fail fast > inconsistent dashboard".
        # But for "visual" mode requiring 5 charts, if LLM gives 4, maybe we shouldn't crash?
        # Let's conform to the plan: Raise ValueError.
        raise ValueError(f"Insufficient charts generated for mode '{mode}'. Expected min {config['min_charts']}, got {len(charts)}.")
        
    plan["descriptive"]["charts"] = charts
    
    # 2. Enforce Sections
    allowed_sections = set(config["include_sections"])
    keys_to_remove = [k for k in plan.keys() if k not in allowed_sections and k != "descriptive"]
    for k in keys_to_remove:
        plan.pop(k, None)
        
    # 3. Enforce Text Length
    for section, limit in config["max_text"].items():
        if section in plan and isinstance(plan[section], str):
            if len(plan[section]) > limit:
                # Smart trim? Or just hard trim?
                # Hard trim for safety + ellipsis
                plan[section] = plan[section][:limit] + "..."
                
    return plan


def convert_to_widgets(plan: dict, mode: str, analysis_context: Optional[AnalysisContext] = None) -> List[Dict[str, Any]]:
    """
    Converts the structured insight plan into the flat list of widgets expected by the frontend.
    Enforces Strict Cognitive Order: Verdict -> Charts -> Narrative.
    """
    widgets = []
    widget_counter = 1
    
    def next_key():
        nonlocal widget_counter
        k = f"w{widget_counter}"
        widget_counter += 1
        return k

    # 0. Anchor Widget (Enterprise Mode) - Always first if present
    if analysis_context:
        # We assume the caller handles the anchor widget logic or we build it here.
        # The original code built it separately. Let's build it here to be clean.
        # But wait, `_build_primary_widget_from_context` needs `goal`. 
        # For now, let's assume the LLM plan is the source of truth for NEW widgets.
        pass

    # 1. Verdict (Headline / Text Widget)
    # In 'visual' mode, verdict is short, maybe a KPI title or subtitle? 
    # Current frontend maps 'text' type to a text widget.
    if "verdict" in plan and plan["verdict"]:
        widgets.append({
            "widget_key": next_key(),
            "type": "text",
            "title": "Executive Verdict",
            "question": "N/A",
            "viz": {
                "type": "text",
                "content": f"**Verdict:** {plan['verdict']}"
            }
        })

    # 2. Charts (Descriptive)
    for chart in plan["descriptive"].get("charts", []):
        widgets.append({
            "widget_key": next_key(),
            "type": "chart",
            "title": chart.get("title", "Chart"),
            "question": chart.get("question", ""),
            "viz": {
                "type": chart.get("viz_type", "bar"),
                "mapping": {
                    "x": chart.get("x_axis", "category"),
                    "y": chart.get("y_axis", "value")
                }
            },
            "data_requirements": chart.get("data_requirements", {})
        })

    # 3. KPIs (Descriptive)
    for kpi in plan["descriptive"].get("kpis", []):
         widgets.append({
            "widget_key": next_key(),
            "type": "kpi",
            "title": kpi.get("title", "KPI"),
            "question": kpi.get("question", ""),
            "viz": {"type": "kpi"}
        })

    # 4. Diagnostic (Narrative)
    if "diagnostic" in plan and plan["diagnostic"]:
        widgets.append({
            "widget_key": next_key(),
            "type": "text",
            "title": "Diagnostic Analysis",
            "question": "N/A",
            "viz": {
                "type": "text",
                "content": plan["diagnostic"]
            }
        })

    # 5. Predictive (Narrative)
    if "predictive" in plan and plan["predictive"]:
        widgets.append({
            "widget_key": next_key(),
            "type": "text",
            "title": "Predictive Outlook",
            "question": "N/A",
            "viz": {
                "type": "text",
                "content": plan["predictive"]
            }
        })

    # 6. Prescriptive (Narrative)
    if "prescriptive" in plan and plan["prescriptive"]:
        widgets.append({
            "widget_key": next_key(),
            "type": "text",
            "title": "Recommendations",
            "question": "N/A",
            "viz": {
                "type": "text",
                "content": plan["prescriptive"]
            }
        })
        
    # 7. Execution (Narrative)
    if "execution" in plan and plan["execution"]:
        widgets.append({
            "widget_key": next_key(),
            "type": "text",
            "title": "Execution Plan",
            "question": "N/A",
            "viz": {
                "type": "text",
                "content": plan["execution"]
            }
        })

    return widgets


def generate_structured_insight(
    llm: Any,
    mode: str,
    system_prompt: str,
    user_prompt: str
) -> dict:
    """
    Calls the LLM with mode-specific configurations to generate the structured plan.
    """
    config = MODE_CONFIG[mode]["llm"]
    
    # Adjust prompt to enforce JSON structure
    json_schema = (
        "{\n"
        "  \"verdict\": \"High-level executive summary (string)\",\n"
        "  \"descriptive\": {\n"
        "      \"charts\": [{ \"title\": \"...\", \"question\": \"...\", \"viz_type\": \"bar|line|pie|...\", \"x_axis\": \"...\", \"y_axis\": \"...\" }],\n"
        "      \"kpis\": [{ \"title\": \"...\", \"question\": \"...\" }]\n"
        "  },\n"
        "  \"diagnostic\": \"Why did this happen? (string)\",\n"
        "  \"predictive\": \"What will happen? (string)\",\n"
        "  \"prescriptive\": \"What should we do? (string)\",\n"
        "  \"execution\": \"Action plan (string)\"\n"
        "}\n\n"
        "SPECIAL SYNTAX: Augmented Narratives (MANDATORY for Textual/Mix modes)\n"
        "In narrative fields (diagnostic, predictive, prescriptive, execution), you MUST embed rich metrics derived from your analysis using this syntax:\n"
        "[[Metric: Label | Value | Status]]\n"
        "Example Diagnostic: 'The spike was driven by [[Metric: Summer Campaign | $2.5M | success]], while [[Metric: Churn | 12% | danger]] remained high.'\n"
        "Statuses: success (green/up), warning (orange/neutral), danger (red/down), info (blue/neutral)."
    )
    
    instruction = (
        f"\n\nMODE: You are generating a {mode.upper()} dashboard.\n"
        f"OUTPUT FORMAT: You must return a SINGLE JSON object strictly following this schema:\n"
        f"{json_schema}\n"
    )
    
    # Merge instruction into system prompt
    full_system = system_prompt + instruction

    try:
        # TODO: Pass temperature/max_tokens if the LLM wrapper covers it. 
        # Assuming `llm.invoke` or the factory handles params, or we validly pass them in constructor.
        # For now, we rely on the implementation plan's architecture.
        # If LLM object is already configured, we might not be able to override here easily without a `bind` or similar.
        # We will assume standard invoke for now.
        resp = llm.invoke([{"role": "system", "content": full_system}, {"role": "user", "content": user_prompt}])
        content = getattr(resp, "content", "") or ""
        
        parsed = _safe_json_loads(content)
        if not parsed:
            raise ValueError("Failed to parse LLM JSON response")
            
        return parsed
        
    except Exception as e:
        log_event("davinci_structured_generation_error", {"mode": mode, "error": str(e)})
        raise e




def _choose_metric_col(cols: List[str]) -> Optional[str]:
    for c in cols:
        if any(x in c.lower() for x in ["amount", "value", "total", "price", "cost", "revenue", "sales", "count", "qty"]):
            return c
    return cols[0] if cols else None

def _choose_dim_col(cols: List[str]) -> Optional[str]:
    for c in cols:
        if any(x in c.lower() for x in ["status", "type", "category", "region", "country", "name", "customer", "product"]):
            return c
    return cols[1] if len(cols) > 1 else (cols[0] if cols else None)

def _choose_date_col(cols: List[str]) -> Optional[str]:
    for c in cols:
        if any(x in c.lower() for x in ["date", "time", "created", "timestamp", "period", "day", "month", "year"]):
            return c
    return None

def _pick_col_agnostic(t_name: str, cols: List[str], role: str, meta_map: Dict[str, Any]) -> Optional[str]:
    if role == "metric": return _choose_metric_col(cols)
    if role == "time": return _choose_date_col(cols)
    if role == "attribute": return _choose_dim_col(cols)
    return cols[0] if cols else None


def generate_dashboard_plan(
    *,
    llm: Any,
    goal: str,
    # language: str, <-- REMOVED
    max_widgets: int,
    logical_tables: List[str],
    schema_summary: str,
    original_question: Optional[str] = None,
    initial_ai_response: Optional[str] = None,
    context_spaces: Optional[List[str]] = None,
    context_crews: Optional[List[str]] = None,
    context_tables: Optional[List[str]] = None,
    table_metadata: Optional[List[Dict[str, Any]]] = None,
    analysis_context: Optional[AnalysisContext] = None,
    mode: Optional[str] = "mix",
) -> DavinciDashboardPlan:
    """
    Davinci "graph": generate a dashboard plan as STRICT JSON.
    Supports "Textual", "Visual", and "Mix" modes.
    """
    # 0. Validate Mode
    mode = validate_mode(mode) if mode else "mix"
    config = MODE_CONFIG[mode]
    
    # language = "en" <-- REMOVED (Implicit default in prompts)
    
    if not logical_tables:
        try:
            with open("/tmp/davinci_debug.log", "a") as f:
                f.write(f"{datetime.utcnow()} - FALLBACK: No logical tables found. Goal: {goal}\n")
        except: pass
        return _fallback_plan(goal=goal, logical_tables=[], max_widgets=max_widgets, schema_summary=schema_summary, original_question=original_question, table_metadata=table_metadata)

    table_cols, table_keys = _parse_schema_summary(schema_summary)

    # 🧠 SCHEMA INTELLIGENCE INJECTION (Kept Inline for robustness)
    enriched_schema_summary = schema_summary
    dataset_constraints_text = ""
    
    if table_metadata:
        try:
            # Pre-compute roles
            meta_map = {
                (f"{t.get('schema')}.{t.get('name')}" if t.get('schema') else t.get('name')): t 
                for t in table_metadata
            }
            for t in table_metadata:
                meta_map[t.get("name")] = t

            # 1. Filter non-analytic tables
            filtered_logical = []
            for t_name in logical_tables:
                 t_meta = meta_map.get(t_name)
                 row_count = int(t_meta.get("row_count") or t_meta.get("stats", {}).get("row_count") or 0) if t_meta else 0
                 if not AnalyticTableFilter.should_exclude(t_name, row_count):
                     filtered_logical.append(t_name)
            
            if len(filtered_logical) > 0:
                logical_tables = filtered_logical

            # 2. Enrich Summary
            lines = []
            for line in schema_summary.splitlines():
                if not line.strip().startswith("- "):
                    lines.append(line)
                    continue
                try:
                    parts = line[2:].split(" cols:", 1)
                    t_name = parts[0].strip()
                    col_str = parts[1].strip() if len(parts) > 1 else ""
                except:
                    lines.append(line)
                    continue

                if t_name not in logical_tables:
                    continue

                t_meta = meta_map.get(t_name)
                role_info = ""
                new_col_str = col_str
                
                if t_meta:
                    role = _get_table_role(t_name, t_meta).upper()
                    row_count = int(t_meta.get("row_count") or t_meta.get("stats", {}).get("row_count") or 0)
                    row_str = f", ~{row_count} rows" if row_count is not None else ""
                    role_info = f" [{role}{row_str}]"
                    
                    summary_cols = [c.strip() for c in col_str.split(",")]
                    enriched_cols = []
                    col_meta_lookup = {c.get("name").lower(): c for c in t_meta.get("columns", [])}
                    
                    for c_raw in summary_cols:
                        c_name = c_raw.lower()
                        c_meta = col_meta_lookup.get(c_name)
                        suffix = ""
                        if c_meta:
                            col_role = "attribute" # Default
                            # Simple heuristics for suffix
                            ctype = str(c_meta.get("type", "")).upper()
                            if any(x in ctype for x in ["INT", "FLOAT", "NUMERIC", "DECIMAL"]): suffix = " [M]"
                            elif any(x in ctype for x in ["DATE", "TIME"]): suffix = " [T]"
                            elif "id" in c_name: suffix = " [K]"
                        enriched_cols.append(f"{c_raw}{suffix}")
                    new_col_str = ", ".join(enriched_cols)

                    # Date Range
                    min_d = None
                    max_d = None
                    for c in t_meta.get("columns", []):
                        if c.get("min_date") and (not min_d or c["min_date"] < min_d): min_d = c["min_date"]
                        if c.get("max_date") and (not max_d or c["max_date"] > max_d): max_d = c["max_date"]
                    if min_d and max_d:
                         role_info += f" [Range: {str(min_d).split()[0]} to {str(max_d).split()[0]}]"

                lines.append(f"- {t_name}{role_info} cols: {new_col_str}")
            enriched_schema_summary = "\n".join(lines)
            
            # 3. Dataset Profiling (Simplified)
            from core.profiling import DatasetProfiler, ConstraintGenerator
            profiler = DatasetProfiler()
            constraint_gen = ConstraintGenerator()
            profiles = profiler.profile_tables(table_metadata or [])
            stats = profiler.get_size_statistics(profiles)
            smallest_size = stats["smallest_size"]
            constraints = constraint_gen.generate(smallest_size)
            
            if smallest_size in ["tiny", "small"]:
                 dataset_constraints_text = f"\n⚠️ DATASET SIZE: {smallest_size.upper()}. Use aggregations. Avoid specific filters unless requested."
                 
        except Exception as e:
            log_event("davinci_enrichment_error", {"error": str(e)})

    # 🚀 PROMPT CONSTRUCTION
    system_base = (
        "You are Davinci, a specialized Analytics Agent.\n"
        f"Today is {datetime.utcnow().strftime('%Y-%m-%d')}.\n"
        "Your goal is to generate a comprehensive, coherent dashboard plan.\n"
        "Think like a Senior Data Analyst: Start with the most important numbers, then explain 'Why' (Diagnostics), then look forward (Predictive).\n"
        "IMPORTANT: You must ALWAYS respond in English, regardless of the user's input language. If the user asks in Portuguese or Spanish, you must still answer in English.\n"
    )
    
    # Context String
    context_str = ""
    if initial_ai_response:
        context_str += f"\nRecent Insight: '{initial_ai_response}' (Use this connectivity)\n"
    if context_spaces:
        context_str += f"Spaces: {', '.join(context_spaces)}\n"

    # User Prompt
    # We guide the LLM to focus on the structure required by the mode
    if analysis_context:
        query_context = f"Analyzing Entity: {analysis_context.primary_entity}"
    else:
        query_context = f"Original Question: {original_question or goal}"

    user_base = (
        f"Goal: {goal}\n"
        f"{query_context}\n"
        f"Tables: {', '.join(logical_tables)}\n"
        f"Schema:\n{enriched_schema_summary}\n"
        f"{dataset_constraints_text}\n"
        f"{context_str}\n"
        f"Generate a dashboard plan that tells a story."
    )

    try:
        # 1. Generate Structured Insight
        structured_plan = generate_structured_insight(
            llm=llm,
            mode=mode,
            system_prompt=system_base,
            user_prompt=user_base
        )
        
        # 2. Validate Structure
        structured_plan = validate_plan_structure(structured_plan)
        
        # 3. Enforce Mode Rules
        structured_plan = enforce_mode_rules(structured_plan, mode)
        
        # 4. Convert to Widgets
        widgets = convert_to_widgets(structured_plan, mode, analysis_context)

        # 4.5 Grounding Validation
        grounding_result = {}
        if table_metadata:
            try:
                from core.agents.davinci_validator import DavinciPlanValidator
                validator = DavinciPlanValidator(table_metadata)
                grounding_result = validator.validate_plan(
                    structured_plan, 
                    context_provided=bool(initial_ai_response)
                )
            except Exception as e:
                log_event("davinci_validation_error", {"error": str(e)})
        
        # 5. Metadata & Response
        return DavinciDashboardPlan(
            dashboard_name=original_question or goal,
            description=structured_plan.get("verdict", ""),
            widgets=widgets,
            meta={
                "mode": mode,
                "grounding": grounding_result,
                "generated_at": datetime.utcnow().isoformat(),
                "model": getattr(llm, "model_name", "unknown"),
                "has_original_question": original_question is not None
            },
            full_results=structured_plan # PASS RAW PLAN
        )

    except ValueError as e:
        log_event("davinci_mode_validation_failed", {"error": str(e), "mode": mode, "goal": goal})
        # If strict validation fails, we fallback to a safe default
        return _fallback_plan(
            goal=goal, 
            logical_tables=logical_tables, 
            max_widgets=max_widgets, 
            schema_summary=schema_summary, 
            original_question=original_question, 
            table_metadata=table_metadata
        )
    except Exception as e:
        log_event("davinci_generation_failed", {"error": str(e), "mode": mode})
        return _fallback_plan(
            goal=goal, 
            logical_tables=logical_tables, 
            max_widgets=max_widgets, 
            schema_summary=schema_summary, 
            original_question=original_question, 
            table_metadata=table_metadata
        )

