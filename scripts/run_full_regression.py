
import sys
import subprocess
import os
from pathlib import Path
from sqlalchemy import create_engine, text

# Add project root
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.settings import settings

def get_test_ids():
    db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            # Join to get a valid pair
            query = text("""
                SELECT dc.id, sc.space_id 
                FROM data_connections dc
                JOIN space_connections sc ON dc.id = sc.connection_id
                LIMIT 1
            """)
            result = conn.execute(query)
            row = result.fetchone()
            if row:
                return str(row[0]), str(row[1])
    except Exception as e:
        print(f"Error fetching IDs: {e}")
    return None, None

def run_script(script_name, args=[]):
    print(f"\nExample: Running {script_name}...")
    cmd = ["venv/bin/python", f"scripts/{script_name}"] + args
    try:
        result = subprocess.run(cmd, check=True, capture_output=False)
        print(f"✅ {script_name} PASSED")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {script_name} FAILED (Exit Code {e.returncode})")
        return False

def main():
    print("🔬 STARTING FULL REGRESSION SUITE 🔬")
    
    # 1. Fetch IDs
    conn_id, space_id = get_test_ids()
    if not conn_id:
        print("⚠️  Could not fetch Connection/Space IDs. Skipping dependent tests.")
    else:
        print(f"ℹ️  Test IDs: Connection={conn_id}, Space={space_id}")

    failures = []

    # 2. Conversational Memory (Standalone)
    if not run_script("test_conversational_memory.py"):
        failures.append("Conversational Memory")

    # 3. Security (Self-contained for IDs usually, but good to check)
    if not run_script("test_security_regression.py"):
        failures.append("Security Scanner")

    # 4. Pipeline/Dashboard (Needs IDs)
    if conn_id and space_id:
        if not run_script("test_pipeline_persistence.py", [conn_id, space_id]):
            failures.append("Dashboard/Pipeline")
    else:
        print("⏭️  Skipping Pipeline test due to missing IDs")

    print("\n" + "="*40)
    if failures:
        print(f"🚨 SUITE FAILED. Failures: {', '.join(failures)}")
        sys.exit(1)
    else:
        print("✨ ALL TESTS PASSED SUCCESSFULLY! ✨")
        sys.exit(0)

if __name__ == "__main__":
    main()
