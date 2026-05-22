#!/usr/bin/env python3
"""
Run SQL migration scripts

Usage:
    python scripts/run_migration.py db/migrations/add_multi_layer_rag_tables.sql
"""
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from config.settings import settings


def run_migration(sql_file_path: str):
    """
    Execute SQL migration file.

    Args:
        sql_file_path: Path to .sql file (relative or absolute)
    """
    # Resolve path
    if not os.path.isabs(sql_file_path):
        sql_file_path = os.path.join(project_root, sql_file_path)

    if not os.path.exists(sql_file_path):
        print(f"❌ ERROR: File not found: {sql_file_path}")
        sys.exit(1)

    # Read SQL file
    print(f"📄 Reading migration: {sql_file_path}")
    with open(sql_file_path, "r") as f:
        sql_content = f.read()

    # Create engine
    print(f"🔌 Connecting to database...")
    engine = create_engine(settings.database_url)

    # Execute migration
    try:
        print(f"🚀 Executing migration...")
        with engine.connect() as conn:
            # Execute as a single transaction
            with conn.begin():
                # Split by semicolons and execute each statement
                # (excluding empty statements and comments)
                statements = [
                    stmt.strip()
                    for stmt in sql_content.split(";")
                    if stmt.strip() and not stmt.strip().startswith("--")
                ]

                for i, stmt in enumerate(statements, 1):
                    if stmt:
                        print(f"  Executing statement {i}/{len(statements)}...")
                        conn.execute(text(stmt))

        print(f"✅ Migration completed successfully!")
        print(f"📊 Tables created/updated:")
        print(f"   - metrics_catalog")
        print(f"   - query_comments")
        print(f"   - business_glossary")
        print(f"   - query_history (question_embedding column)")

    except Exception as e:
        print(f"❌ ERROR executing migration:")
        print(f"   {str(e)}")
        sys.exit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_migration.py <sql_file_path>")
        print(
            "Example: python scripts/run_migration.py db/migrations/add_multi_layer_rag_tables.sql"
        )
        sys.exit(1)

    sql_file = sys.argv[1]
    run_migration(sql_file)
