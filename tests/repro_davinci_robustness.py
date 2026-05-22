import sys
import os
import json
from dataclasses import dataclass

# Add repository root to path
sys.path.append(os.getcwd())


# Mock necessary classes to avoid full env setup
@dataclass
class MockLLMResponse:
    content: str


class MockLLM:
    def invoke(self, messages):
        # Simulate a failure to force fallback logic,
        # OR simulate a basic JSON response to test heuristic validation.
        # For robustness testing, we often want to test the FALLBACK logic
        # or the pre-processing logic, so let's fail by default or return garbage
        # to see how the system behaves.
        return MockLLMResponse(content="invalid json")


# Import the code under test
# We need to bypass some imports in the original file that might not work locally without env vars
# But for now let's try direct import assuming PYTHONPATH is set
try:
    from core.agents.davinci_dashboard_agent import (
        _is_fact_table,
        _is_dim_table,
        _pick_join_pairs,
        _fallback_plan,
        _parse_schema_summary,
    )
except ImportError as e:
    print(f"Error importing Davinci Agent: {e}")
    sys.exit(1)


def test_heuristic_detection():
    print("--- Testing Table Heuristics ---")

    scenarios = [
        ("sales_fact", True, False),
        ("dim_customers", False, True),
        ("tabela_vendas", True, False),  # Portuguese - should fail currently
        ("cadastro_clientes", False, True),  # Portuguese - should fail currently
        ("log_access", True, False),
        ("generic_table", False, False),
    ]

    for name, expected_fact, expected_dim in scenarios:
        is_f = _is_fact_table(name)
        is_d = _is_dim_table(name)

        status_f = "✅" if is_f == expected_fact else f"❌ (Exp: {expected_fact})"
        status_d = "✅" if is_d == expected_dim else f"❌ (Exp: {expected_dim})"

        print(f"Table '{name}': Fact={is_f} {status_f} | Dim={is_d} {status_d}")


def test_fallback_generation():
    print("\n--- Testing Fallback Generation ---")

    # 1. Cryptic Schema
    cryptic_tables = ["T001", "T002"]
    cryptic_schema = """
- T001 cols: C1, C2, C3, DT_LOG keys:
- T002 cols: C1, C4, AMT_VAL keys:
"""

    # 2. Portuguese Schema
    pt_tables = ["vendas_br", "clientes_sp"]
    pt_schema = """
- vendas_br cols: id_venda, id_cliente, valor_total, dt_venda keys: id_cliente
- clientes_sp cols: id_cliente, nome_completo, categoria keys: id_cliente
"""

    scenarios = [
        ("Cryptic", cryptic_tables, cryptic_schema),
        ("Portuguese", pt_tables, pt_schema),
    ]

    for label, tables, schema in scenarios:
        print(f"\nScenario: {label}")
        plan = _fallback_plan(
            goal="Analyze data",
            logical_tables=tables,
            max_widgets=4,
            schema_summary=schema,
        )

        print(f"Plan Title: {plan.dashboard_name}")
        for w in plan.widgets:
            print(f"  - [{w['type']}] {w['title']}: {w['question']}")


if __name__ == "__main__":
    test_heuristic_detection()
    test_fallback_generation()
