#!/usr/bin/env python3
"""
RAG Setup - Versão Simplificada
Descobre space_id automaticamente e roda embeddings
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from config.settings import settings
from core.rag.embeddings import (
    OpenAIEmbeddingProvider,
    create_embeddings_for_table_metadata,
)


def get_first_space_id():
    """Auto-discover space_id from database"""
    db_url = settings.database_url
    if db_url.startswith("postgresql+asyncpg://"):
        sync_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    else:
        sync_url = db_url

    engine = create_engine(sync_url)

    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT id, name FROM spaces LIMIT 1"))
            row = result.fetchone()
            if row:
                print(f"📍 Auto-discovered Space: {row[1]}")
                print(f"📍 Space ID: {row[0]}\n")
                return str(row[0])
            else:
                print("❌ No spaces found in database!")
                return None
    except Exception as e:
        print(f"❌ Database error: {e}")
        return None
    finally:
        engine.dispose()


async def run_embeddings(space_id: str):
    """Run embedding generation"""
    # Convert to async URL
    db_url = settings.database_url
    if not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
        db_url = db_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")

    engine = create_async_engine(db_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with async_session() as db:
            provider = OpenAIEmbeddingProvider()
            print("🧠 Generating embeddings (OpenAI text-embedding-3-large)...\n")

            count = await create_embeddings_for_table_metadata(
                db,
                provider,
                space_id=space_id,
                batch_size=10,
                delay_between_batches=0.5,
            )

            print(f"\n🎉 SUCCESS! Created {count} embeddings")
            print(f"\n✅ RAG is now ready for Ollama!")
            print(f"\nNext steps:")
            print(f"  1. Test query in frontend")
            print(f"  2. Check logs: grep multi_layer_rag logs/ai.log")
            print(f"  3. Get Ollama API from DevOps")

            return count

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return 0
    finally:
        await engine.dispose()


async def main():
    print("=" * 60)
    print("🚀 RAG Phase 1 - Auto Setup")
    print("=" * 60 + "\n")

    # Step 1: Find space_id
    space_id = get_first_space_id()
    if not space_id:
        print("\n❌ Cannot proceed without a valid space_id")
        print("   Create a space in the frontend first.")
        sys.exit(1)

    # Step 2: Run embeddings
    count = await run_embeddings(space_id)

    if count > 0:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)
