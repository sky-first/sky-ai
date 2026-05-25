import os
import sys
import unittest
from unittest.mock import MagicMock

import pyarrow as pa

from core.agents.generic_sql_agent import AgentConfig, TableSchema
from core.data_sources.base import BaseDataSource
from core.dialects import Dialect
from core.llm.formatter import run_formatter

# Add root to path
sys.path.append(os.getcwd())

# Import Core Components


class MockDataSource(BaseDataSource):
    """Mock Data Source returning Arrow Table"""

    def __init__(self, table_name="users"):
        self.table_name = table_name
        self.config = MagicMock()
        self.config.id = "mock_ds"
        self.dialect = Dialect.POSTGRES

    def run_query_arrow(self, sql: str):
        # Return a simple Arrow Table
        data = [pa.array(["User A", "User B"]), pa.array([100, 200])]
        return pa.Table.from_arrays(data, names=["name", "amount"])

    def run_query(self, sql: str):
        raise RuntimeError("run_query called instead of run_query_arrow!")


class TestFullRegression(unittest.TestCase):

    def setUp(self):
        self.table = TableSchema(
            logical_name="users", physical_name="project.dataset.users_v1", columns=[]
        )
        self.agent_config = AgentConfig(
            id="reg_agent", name="Regression Agent", tables=[self.table]
        )
        self.data_source = MockDataSource()
        self.db_factory = MagicMock()
        self.llm_orch = MagicMock()
        self.llm_spec = MagicMock()
        self.llm_fmt = MagicMock()

        # Mocks
        self.llm_orch.invoke.return_value = "users"
        self.llm_spec.invoke.return_value = "-- TITLE: User Analysis\nSELECT name, amount FROM project.dataset.users_v1 LIMIT 10"
        self.llm_fmt.invoke.return_value = "The analysis shows User A and User B."

    def test_formatter_state_update(self):
        print("--- Test: Formatter Arrow -> List State Update ---")

        # Create a state simulating what comes out of Specialist (Arrow Table)
        arrow_table = self.data_source.run_query_arrow("SELECT...")

        state = {
            "question": "analyze users",
            "data": arrow_table,  # Arrow Table here
            "sql": "SELECT...",
            "answer": None,
        }

        # Run Formatter directly to check state update
        new_state = run_formatter(state, self.agent_config, self.llm_fmt)

        # Verify
        data_in_state = new_state.get("data")
        print(f"Data type in state: {type(data_in_state)}")

        self.assertIsInstance(
            data_in_state, list, "Formatter should convert Arrow to List in state"
        )
        self.assertEqual(len(data_in_state), 2)
        print("[Pass] Formatter correctly updated state with List.")


if __name__ == "__main__":
    unittest.main()
