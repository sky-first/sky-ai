import os

TARGET_FILE = "/Users/thedatafirst/skyfirst/repositories/sky-poc-ai/core/agents/davinci_dashboard_agent.py"

IMPORTS_TO_ADD = "from core.agents.schema_intelligence import AnalyticTableFilter, ColumnFeatures, ColumnScorer, SchemaScorer, JoinScorer\n"

# Helper function
HELPER_FUNC = """
def _get_table_role(table_name: str, meta: Dict[str, Any]) -> str:
    from core.agents.schema_intelligence import SchemaScorer
    try:
        row_count = int(meta.get("row_count") or meta.get("stats", {}).get("row_count") or 0)
        cols = meta.get("columns", [])
        features = SchemaScorer.extract_features(table_name, cols, row_count)
        score = SchemaScorer.score_table(features)
        return score.get("role", "unknown")
    except:
        return "unknown"

"""

MISSING_HELPERS = """
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
"""

NEW_FUNCTION_CODE = r'''def generate_dashboard_plan(
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
    
    # Force English only
    language = "en"

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
        
        # 5. Metadata & Response
        return DavinciDashboardPlan(
            dashboard_name=original_question or goal,
            description=structured_plan.get("verdict", ""),
            widgets=widgets,
            meta={
                "mode": mode,
                "generated_at": datetime.utcnow().isoformat(),
                "model": getattr(llm, "model_name", "unknown"),
                "has_original_question": original_question is not None
            }
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
'''


def apply_replacement():
    with open(TARGET_FILE, "r") as f:
        content = f.read()

    # 1. Add Helper if missing (and MISSING HELPERS)
    if "def _choose_metric_col" not in content:
        # Insert before generate_dashboard_plan
        start_marker = "def generate_dashboard_plan("
        idx = content.find(start_marker)
        if idx != -1:
            content = content[:idx] + MISSING_HELPERS + "\n" + content[idx:]
        else:
            print(
                "Could not find start of generate_dashboard_plan -- skipping helper injection"
            )

    # 2. Add imports if needed (handled in previous run, but good to ensure)
    if "core.agents.schema_intelligence" not in content:
        import_marker = "from core.services.dashboard_modes import"
        idx = content.find(import_marker)
        if idx != -1:
            end_line = content.find("\n", idx)
            content = content[: end_line + 1] + IMPORTS_TO_ADD + content[end_line + 1 :]

    # 3. Replace Function
    start_marker = "def generate_dashboard_plan("
    start_idx = content.find(start_marker)

    if start_idx == -1:
        print("Could not find start of generate_dashboard_plan")
        return

    # Replace to end of file
    new_content = content[:start_idx] + NEW_FUNCTION_CODE + "\n"

    with open(TARGET_FILE, "w") as f:
        f.write(new_content)

    print("Successfully replaced generate_dashboard_plan logic.")


if __name__ == "__main__":
    apply_replacement()
