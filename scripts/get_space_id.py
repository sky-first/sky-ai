#!/usr/bin/env python3
"""
Quick helper to get space_id from database for RAG setup
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from config.settings import settings


def get_spaces():
    db_url = settings.database_url
    if db_url.startswith("postgresql+asyncpg://"):
        sync_db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    else:
        sync_db_url = db_url

    engine = create_engine(sync_db_url)

    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT id, name FROM spaces LIMIT 5"))
            spaces = result.fetchall()

            if not spaces:
                print("⚠️  No spaces found in database")
                print("\nCreate a space first or check database connection")
                return

            print(f"\n📋 Available Spaces:\n")
            for space_id, name in spaces:
                print(f"  ID: {space_id}")
                print(f"  Name: {name}")
                print(
                    f"  Command: python3 scripts/setup_rag_phase1.py --space-id {space_id}\n"
                )

            # Show first space command ready to copy
            first_id = spaces[0][0]
            print(f"🚀 Quick start (first space):")
            print(f"   python3 scripts/setup_rag_phase1.py --space-id {first_id}")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    get_spaces()
