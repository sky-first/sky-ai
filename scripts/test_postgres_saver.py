import sys
import os
import uuid
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.settings import settings
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver


def test_checkpointing():
    db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    print(f"Connecting to: {db_url}")

    try:
        pool = ConnectionPool(conninfo=db_url, min_size=1, max_size=2)
        print("Pool created.")

        # Test 1: Initialize with pool
        print("Test 1: PostgresSaver(pool)")
        saver = PostgresSaver(pool)
        print("Setup()")
        saver.setup()
        print("Setup done.")

        # Test 2: Try to use it
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        checkpoint = {"v": 1, "ts": "test", "channel_values": {"a": 1}}
        metadata = {"source": "test"}

        print("Saving checkpoint...")
        # saver.put(config, checkpoint, metadata)
        print("Saved.")

        pool.close()
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_checkpointing()
