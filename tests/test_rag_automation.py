#!/usr/bin/env python3
"""
Test RAG Automation
Simulate frontend calling /connections/{id}/discover
Expect: Encached metadata ingestion + Automatic embedding generation
"""
from typing import Any
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from config.settings import settings
import httpx

# Mock the function that normally requires a running API server
# We will invoke the service logic directly to test integration
from core.ingestion.service import run_metadata_ingestion, run_metadata_embeddings
from core.llm.factory import create_embedding_provider

async def get_test_ids():
    db_url = settings.database_url
    if not db_url.startswith('postgresql+asyncpg://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://')
        
    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT DISTINCT dc.id, s.id 
            FROM connection_metadata cm
            JOIN data_connections dc ON cm.connection_id = dc.id
            JOIN space_connections sc ON dc.id = sc.connection_id
            JOIN spaces s ON sc.space_id = s.id
            WHERE cm.tables IS NOT NULL
            LIMIT 1
        """))
        row = result.fetchone()
        await engine.dispose()
        return row

async def main():
    print("="*60)
    print("🤖 Testing RAG Automation")
    print("="*60)
    
    ids = await get_test_ids()
    if not ids:
        print("❌ No valid connection found to test")
        return
        
    connection_id, space_id = str(ids[0]), str(ids[1])
    print(f"📍 Connection: {connection_id}")
    print(f"📍 Space: {space_id}")
    
    # Simulate what the API endpoint does
    print("\n1. Simulating Metadata Ingestion (Cache -> TableMetadata)...")
    db_url = settings.database_url
    if not db_url.startswith('postgresql+asyncpg://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://')
    
    engine = create_async_engine(db_url)
    try:
        async with engine.begin() as conn:
            # We need a session, but for this quick test a connection with begin() works 
            # if we adapt the function signature or mock the DB session.
            # Actually, let's use the real sessionmaker to be safe.
            from sqlalchemy.orm import sessionmaker
            from sqlalchemy.ext.asyncio import AsyncSession
            SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            
            async with SessionLocal() as db:
                # 1. Ingest
                inserted = await run_metadata_ingestion(
                    db=db,
                    space_id=space_id,
                    connection_id=connection_id
                )
                print(f"   ✅ Ingested {inserted} rows from cache")
                
                # 2. Embed (Ollama)
                print("\n2. Simulating Automatic Embedding (Ollama)...")
                provider = create_embedding_provider()
                print(f"   Using provider: {type(provider).__name__}")
                
                created = await run_metadata_embeddings(
                    db=db,
                    space_id=space_id,
                    connection_id=connection_id,
                    embedding_provider=provider
                )
                print(f"   ✅ Created {created} embeddings")
                
    except Exception as e:
        print(f"\n❌ Automation failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await engine.dispose()

    print("\n" + "="*60)

if __name__ == "__main__":
    asyncio.run(main())
