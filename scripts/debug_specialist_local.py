
import asyncio
import os
import sys

# Add project root
sys.path.append(os.getcwd())

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine
from core.llm.specialist import run_specialist, AgentState, AgentConfig, TableSchema
from core.data_sources.base import SQLAlchemyDataSource
from core.dialects import Dialect

# Mock LLM to avoid API Key issues
class MockLLM:
    def invoke(self, messages):
        # Return a simulated SQL response
        class Response:
            content = "SELECT id, email FROM users LIMIT 5;"
        return Response()

def debug_local():
    print("🐛 Starting Local Debug with Mock LLM...")
    
    # 1. Setup Source (Postgres Local)
    # Using Docker connection directly since environment is messed up
    dsn = "postgresql://postgres:postgres@localhost:5432/ai_saas_db" 
    
    # from config.settings import settings
    # dsn = settings.database_url 
    
    try:
        engine = create_engine(dsn)
        data_source = SQLAlchemyDataSource(engine, Dialect.POSTGRES)
    except Exception as e:
        print(f"Failed to connect to DB: {e}")
        return
    
    # 2. Setup Agent Config
    agent_config = AgentConfig(
        id="debug-agent",
        name="Debug Agent",
        tables=[
            TableSchema(logical_name="users", physical_name="users", columns=[])
        ],
        dialect=Dialect.POSTGRES
    )
    
    # 3. Setup State
    state = AgentState(
        question="List top 5 users",
        chosen_table="users",
        chosen_table_physical="users",
        security_config=None
    )

    llm = MockLLM()
    # Mock LLM is safe to init directly

    print("Running Specialist...")
    try:
        result = run_specialist(state, agent_config, data_source, llm)
        print("✅ Result State Keys:", result.keys())
        if result.get("error"):
            print("❌ Error in State:", result["error"])
        if result.get("sql"):
            print("📜 SQL:", result["sql"])
        if result.get("data"):
            print("📊 Rows:", len(result["data"]))
            
    except Exception as e:
        print("💥 CRITICAL EXCEPTION:")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_local()
