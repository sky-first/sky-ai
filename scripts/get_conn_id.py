#!/usr/bin/env python3
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from config.settings import settings


def get_conn_id():
    db_url = settings.database_url
    if db_url.startswith("postgresql+asyncpg://"):
        sync_db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    else:
        sync_db_url = db_url

    engine = create_engine(sync_db_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT id FROM data_connections LIMIT 1"))
            row = result.fetchone()
            if row:
                print(row[0])
            else:
                print("None")
    finally:
        engine.dispose()


if __name__ == "__main__":
    get_conn_id()
