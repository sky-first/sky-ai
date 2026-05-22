import os
import sys
import uuid
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

# Setup path
sys.path.append(os.getcwd())

from core.agents.generic_sql_agent import (
    run_agent_once,
    AgentConfig,
    TableSchema,
    UserContext,
)
from core.data_sources.base import SQLAlchemyDataSource
from core.llm.factory import (
    create_llm_orchestrator,
    create_llm_specialist,
    create_llm_formatter,
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from core.dialects import Dialect
from config.settings import settings


@dataclass
class MockUserContext:
    user_id: Optional[str] = None
    space_id: Optional[str] = None
    crew_ids: List[str] = field(default_factory=list)
    platform_role: str = "user"
    crew_role: str = "guest"
    locale: str = "en"
    permissions: List[str] = field(default_factory=list)


def test_conversational_memory():
    print("--- TEST CONVERSATIONAL MEMORY ---")
    # Setup
    user_ctx = MockUserContext(user_id="test_user", space_id="test_space")
    thread_id = f"test-thread-{uuid.uuid4()}"

    agent_config = AgentConfig(
        id="test_agent",
        name="Test Agent",
        tables=[
            TableSchema(
                logical_name="invoices",
                physical_name="public.invoices",
                columns=[
                    {"name": "id", "type": "INTEGER"},
                    {"name": "customer_id", "type": "INTEGER"},
                    {"name": "total_amount", "type": "DECIMAL"},
                    {"name": "status", "type": "VARCHAR"},
                    {"name": "invoice_date", "type": "DATE"},
                ],
            )
        ],
    )

    sync_db_url = settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql://"
    ).replace("postgresql+psycopg2://", "postgresql://")
    engine = create_engine(sync_db_url)
    SyncSessionLocal = sessionmaker(bind=engine)
    data_source = SQLAlchemyDataSource(
        engine=engine, dialect=Dialect.POSTGRES, label="test_conn"
    )

    ll_orch = create_llm_orchestrator()
    ll_spec = create_llm_specialist()
    ll_form = create_llm_formatter()

    # Turn 1
    print("\n--- TURN 1 ---")
    question1 = "Show me the top 3 invoices"
    print(f"User: {question1}")

    state1 = run_agent_once(
        question=question1,
        user_ctx=user_ctx,
        agent_config=agent_config,
        data_source=data_source,
        db_session_factory=SyncSessionLocal,
        embedding_provider=None,
        llm_orchestrator=ll_orch,
        llm_specialist=ll_spec,
        llm_formatter=ll_form,
        thread_id=thread_id,
        chat_history=[],
    )

    print(f"AI Answer: {state1.get('answer')}")
    print(f"SQL 1: {state1.get('sql')}")

    # Turn 2: Follow-up
    print("\n--- TURN 2 (Follow-up) ---")
    question2 = "Only for customer 5"
    print(f"User: {question2}")

    # Simulate chat history being passed from API (important!)
    history = [
        {"role": "user", "content": question1},
        {"role": "assistant", "content": state1.get("answer") or "Some answer"},
    ]

    state2 = run_agent_once(
        question=question2,
        user_ctx=user_ctx,
        agent_config=agent_config,
        data_source=data_source,
        db_session_factory=SyncSessionLocal,
        embedding_provider=None,
        llm_orchestrator=ll_orch,
        llm_specialist=ll_spec,
        llm_formatter=ll_form,
        thread_id=thread_id,
        chat_history=history,
    )

    print(f"AI Answer: {state2.get('answer')}")
    print(f"SQL 2: {state2.get('sql')}")

    # Verify
    sql2 = (state2.get("sql") or "").lower()
    if ("customer_id" in sql2 or "customer 5" in sql2 or "= 5" in sql2) and (
        "invoices" in sql2
    ):
        print("\n✅ MEMORY SUCCESS: Agent maintained context.")
    else:
        print("\n❌ MEMORY FAILURE: Context lost.")


if __name__ == "__main__":
    test_conversational_memory()
