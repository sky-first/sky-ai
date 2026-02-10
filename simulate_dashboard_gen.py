import asyncio
import sys
import os

# Adjust path to find core modules
sys.path.append(os.getcwd())

from core.agents.davinci_dashboard_agent import _fallback_plan
from core.sql.validator_advanced import AdvancedSQLValidator
from core.llm.specialist import _build_secure_system_prompt
from core.security.security_config import SecurityConfig
from core.dialects import Dialect

async def simulate_dashboard():
    print("--- Simulating Dashboard Generation ---")
    
    # Mock data resembling the 'refunds' scenario from logs
    logical_tables = ["refunds", "credit_memos"]
    table_metadata = [
        {"name": "refunds", "columns": [{"name": "refund_id", "type": "STRING"}, {"name": "refund_amount", "type": "FLOAT"}, {"name": "refund_year_month", "type": "STRING"}]},
        {"name": "credit_memos", "columns": [{"name": "credit_memo_id", "type": "STRING"}, {"name": "amount", "type": "FLOAT"}]}
    ]
    
    # 1. Generate Plan (Fallback)
    print("\n1. Generating Plan...")
    plan = _fallback_plan(
        goal="Create dashboard for refunds",
        logical_tables=logical_tables,
        max_widgets=4,
        table_metadata=table_metadata,
        original_question="Show me refunds dashboard"
    )
    
    print(f"Plan generated with {len(plan.widgets)} widgets.")
    
    # 2. Inspect prompts
    print("\n2. Inspecting Generated Questions and Simulating Prompt...")
    # Initialize validator with our mock tables
    allowed = {"refunds", "credit_memos", "data-mesh-gcp.billing_silver.silver_refunds_enriquecido"} 
    
    # Mock analysis context
    mock_schema = """
    Table: refunds
    Columns: refund_id (STRING), refund_amount (FLOAT), refund_year_month (STRING)
    Description: Refund records
    
    Table: credit_memos
    Columns: credit_memo_id (STRING), amount (FLOAT)
    Description: Credit memos issued
    """
    
    for i, w in enumerate(plan.widgets):
        print(f"\n[Widget {i+1}] Type: {w['type']}, Title: {w['title']}")
        print(f"Question: {w['question']}")
        
        # Simulate full context construction
        # System Prompt
        system_msg = _build_secure_system_prompt(
            physical_names=["data-mesh-gcp.billing_silver.silver_refunds_enriquecido"], # mocking physical name
            max_limit=150,
            max_columns=50,
            use_multiple_tables=False, # simplification for now
            security_rules="", # Use default
            dialect=Dialect.BIGQUERY
        )
        
        # User Message (simulating run_specialist logic)
        user_content = (
            f"User question:\n{w['question']}\n\n"
            f"Table schema:\n{mock_schema}\n"
            "Generate only the SQL query (or IMPOSSIBLE: <reason>)."
        )
        
        full_context = system_msg['content'] + "\n\n" + user_content
        
        # Check for key instructions
        if "without returning any rows" in full_context.lower():
            print("   -> WARNING: Instruction to return no rows found in full context?")
        if "LIMIT" in full_context:
            print("   -> 'LIMIT' instruction present.")
        
        print(f"   Context Length: {len(full_context)} chars")
        
        if "Using `refunds` JOIN `credit_memos`" in w['question']:
            print("   -> JOIN detected.")

if __name__ == "__main__":
    asyncio.run(simulate_dashboard())
