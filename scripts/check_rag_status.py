#!/usr/bin/env python3
"""
Verify RAG System Status
1. Check row counts in tables
2. Test vector search
"""

import sys
import asyncio
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from config.settings import settings
from core.rag.embeddings import OllamaEmbeddingProvider
import socket


async def main():
    print("=" * 60)
    print("🔍 RAG System Verification")
    print("=" * 60)

    # 1. Check Tables
    print("\n1. Table Counts:")
    db_url = settings.database_url
    if not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = create_async_engine(db_url)

    async with engine.connect() as conn:
        tables = [
            "table_metadata",
            "embeddings",
            "connection_metadata",
            "metrics_catalog",
            "business_glossary",
            "query_comments",
        ]

        for table in tables:
            try:
                result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                count = result.scalar()
                status = "✅" if count > 0 else "❌"
                if table in ["metrics_catalog", "business_glossary", "query_comments"]:
                    # These might be empty initially, which is fine
                    status = "ℹ️" if count == 0 else "✅"

                print(f"{status} {table:25} : {count}")
            except Exception as e:
                print(f"❌ {table:25} : ERROR - {e}")

        # 2. Test Vector Search
        print("\n2. Testing Vector Search:")

        try:
            # Create embedding for a test query
            query = "sales revenue"
            print(f"   Embedding query: '{query}'...")

            provider = OllamaEmbeddingProvider()
            query_embedding_list = provider.embed([query])[0]
            query_embedding = str(query_embedding_list)

            print(f"   Generated embedding: {len(query_embedding_list)} dimensions")

            # Simple cosine similarity search
            sql = """
                SELECT 
                    tm.table_name,
                    tm.column_name,
                    tm.data_type,
                    1 - (e.embedding <=> :embedding) as similarity
                FROM embeddings e
                JOIN table_metadata tm ON e.table_metadata_id = tm.id
                ORDER BY e.embedding <=> :embedding
                LIMIT 3
            """

            result = await conn.execute(text(sql), {"embedding": query_embedding})
            rows = result.fetchall()

            if rows:
                print(f"   ✅ Search successful! Top 3 matches:")
                for row in rows:
                    print(f"      - {row[0]}.{row[1]} ({row[2]}) | Sim: {row[3]:.4f}")
            else:
                print("   ⚠️  Search returned no results (tables might be empty?)")

        except Exception as e:
            print(f"   ❌ Search failed: {e}")

    await engine.dispose()
    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
