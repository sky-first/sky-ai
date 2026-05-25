import sys
import os
from dataclasses import dataclass

# Add project root to path
sys.path.append(os.getcwd())

from core.data_sources.factory import DataSourceFactory, DataSourceConfig
from core.dialects import Dialect

# from db.models import DataConnection # Avoid importing strict SQLAlchemy model


@dataclass
class MockConnection:
    id: str
    type: str
    config: dict


def test_dialect_assignment():
    print("Testing DataSourceFactory dialect assignment...")

    # 1. BigQuery
    bq_conn = MockConnection(
        id="bq-123", type="bigquery", config={"project_id": "test", "dataset": "ds"}
    )
    bq_source = DataSourceFactory.build_from_dataconnection(bq_conn)
    print(f"BigQuery Source Dialect: {bq_source.dialect}")
    assert bq_source.dialect == Dialect.BIGQUERY, "BigQuery dialect mismatch!"

    # 2. API
    api_conn = MockConnection(
        id="api-123", type="api", config={"base_url": "http://api.com"}
    )
    api_source = DataSourceFactory.build_from_dataconnection(api_conn)
    print(f"API Source Dialect: {api_source.dialect}")
    assert api_source.dialect == Dialect.NOSQL, "API dialect mismatch!"

    # 3. Postgres
    pg_conn = MockConnection(
        id="pg-123",
        type="postgres",
        config={"dsn": "postgresql://user:pass@localhost/db"},
    )
    pg_source = DataSourceFactory.build_from_dataconnection(pg_conn)
    print(f"Postgres Source Dialect: {pg_source.dialect}")
    assert pg_source.dialect == Dialect.POSTGRES, "Postgres dialect mismatch!"

    print("\n✅ All dialect assignments correct!")


if __name__ == "__main__":
    try:
        test_dialect_assignment()
    except Exception as e:
        print(f"\n❌ Test Failed: {e}")
        sys.exit(1)
