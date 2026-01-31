
import pyarrow as pa
import duckdb
import pandas as pd
import sys
import os

# Add project root to sys.path
sys.path.append(os.getcwd())

from core.data_manager.duck_engine import DuckEngine

def test_arrow_duckdb_integration():
    print("🚀 Starting PyArrow + DuckDB Integration Test...")

    # 1. Create a PyArrow Table
    data = {
        'id': [1, 2, 3, 4, 5],
        'name': ['Alice', 'Bob', 'Charlie', 'David', 'Eve'],
        'amount': [100.50, 200.00, 150.75, 300.25, 50.00],
        'active': [True, False, True, True, False]
    }
    df = pd.DataFrame(data)
    arrow_table = pa.Table.from_pandas(df)
    
    print("\n✅ Step 1: Created PyArrow Table")
    print(arrow_table)

    # 2. Initialize DuckEngine
    engine = DuckEngine()
    print("\n✅ Step 2: Initialized DuckEngine")

    # 3. Register Arrow Table
    try:
        engine.register_data("users", arrow_table)
        print("\n✅ Step 3: Registered Arrow Table in DuckDB")
    except Exception as e:
        print(f"\n❌ Step 3 FAILED: {e}")
        sys.exit(1)

    # 4. Execute Query
    query = """
    SELECT 
        active, 
        COUNT(*) as count, 
        SUM(amount) as total_amount 
    FROM users 
    GROUP BY active 
    ORDER BY active DESC
    """
    
    print(f"\nExecuting Query:\n{query}")
    
    try:
        results = engine.execute(query)
        print("\n✅ Step 4: Query Execution Successful")
        print("Results:")
        for row in results:
            print(row)
            
        # Validation
        true_group = next((r for r in results if r['active'] == True), None)
        if true_group and true_group['count'] == 3 and true_group['total_amount'] == 551.5:
            print("\n🎉 SUCCESS: Data verification passed!")
        else:
            print("\n❌ FAILURE: Data verification failed!")
            print(f"Expected count=3, total=551.5. Got: {true_group}")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n❌ Step 4 FAILED: {e}")
        sys.exit(1)

    print("\nIntegration verified successfully.")

if __name__ == "__main__":
    test_arrow_duckdb_integration()
