#!/usr/bin/env python3
"""
Normalize connection_metadata to table_metadata
Then generate embeddings
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
from core.rag.embeddings import OllamaEmbeddingProvider, create_embeddings_for_table_metadata
from db.models import TableMetadata
import uuid


def normalize_connection_metadata_to_table(connection_id: str, space_id: str):
    """
    Normalize JSON connection_metadata to table_metadata rows
    """
    db_url = settings.database_url
    if db_url.startswith('postgresql+asyncpg://'):
        sync_url = db_url.replace('postgresql+asyncpg://', 'postgresql://')
    else:
        sync_url = db_url
    
    engine = create_engine(sync_url)
    
    print(f"🔄 Normalizing connection {connection_id}...")
    
    with engine.connect() as conn:
        with conn.begin():
            # Get connection_metadata
            result = conn.execute(
                text("SELECT tables FROM connection_metadata WHERE connection_id = :conn_id"),
                {"conn_id": connection_id}
            )
            row = result.fetchone()
            
            if not row or not row[0]:
                print(f"❌ No metadata found for connection {connection_id}")
                return 0
            
            tables_json = row[0]  # Already parsed by SQLAlchemy
            
            print(f"  Found {len(tables_json)} tables in JSON")
            
            # Check if already normalized
            result = conn.execute(
                text("SELECT COUNT(*) FROM table_metadata WHERE data_connection_id = :conn_id"),
                {"conn_id": connection_id}
            )
            existing = result.scalar()
            
            if existing > 0:
                print(f"  ⚠️  Already normalized ({existing} rows exist)")
                return existing
            
            # Normalize
            inserted = 0
            
            # Convert list to dict if needed, or iterate directly
            if isinstance(tables_json, list):
                print("  ℹ️  tables_json is a list")
                iterator = tables_json
            else:
                iterator = tables_json.items()

            for item in iterator:
                if isinstance(tables_json, list):
                    table_name = item.get('table_name') or item.get('name')
                    table_info = item
                else:
                    table_name = item[0]
                    table_info = item[1]
                columns = table_info.get('columns', [])
                
                for col in columns:
                    col_name = col.get('name') if isinstance(col, dict) else col
                    col_type = col.get('type', 'UNKNOWN') if isinstance(col, dict) else 'UNKNOWN'
                    
                    conn.execute(
                        text("""
                            INSERT INTO table_metadata 
                            (id, data_connection_id, space_id, table_name, column_name, data_type, is_nullable)
                            VALUES (:id, :conn_id, :space_id, :table, :column, :type, :nullable)
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "conn_id": connection_id,
                            "space_id": space_id,
                            "table": table_name,
                            "column": col_name,
                            "type": col_type,
                            "nullable": True
                        }
                    )
                    inserted += 1
            
            print(f"  ✅ Inserted {inserted} metadata rows")
            return inserted


async def generate_embeddings(space_id: str):
    """Generate embeddings for table_metadata"""
    db_url = settings.database_url
    if not db_url.startswith('postgresql+asyncpg://'):
        db_url = db_url.replace('postgresql://', 'postgresql+asyncpg://')
        db_url = db_url.replace('postgresql+psycopg2://', 'postgresql+asyncpg://')
    
    engine = create_async_engine(db_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    print(f"\n🧠 Generating embeddings...")
    
    try:
        async with async_session() as db:
            provider = OllamaEmbeddingProvider()
            
            count = await create_embeddings_for_table_metadata(
                db, provider,
                space_id=space_id,
                batch_size=10,
                delay_between_batches=0.5
            )
            
            print(f"✅ Generated {count} embeddings")
            return count
    finally:
        await engine.dispose()


async def main():
    print("="*60)
    print("🚀 RAG Setup - Normalize + Embed")
    print("="*60)
    print()
    
    # Get all connections with metadata
    db_url = settings.database_url
    if db_url.startswith('postgresql+asyncpg://'):
        sync_url = db_url.replace('postgresql+asyncpg://', 'postgresql://')
    else:
        sync_url = db_url
    
    engine = create_engine(sync_url)
    
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT DISTINCT
                    dc.id as connection_id,
                    s.id as space_id,
                    s.name as space_name
                FROM connection_metadata cm
                JOIN data_connections dc ON cm.connection_id = dc.id
                JOIN space_connections sc ON dc.id = sc.connection_id
                JOIN spaces s ON sc.space_id = s.id  
                WHERE cm.tables IS NOT NULL
                LIMIT 1
            """)
        )
        
        row = result.fetchone()
        
        if not row:
            print("❌ No connections with metadata found")
            print("   Run queries in frontend first to discover schema")
            return
        
        connection_id = str(row[0])
        space_id = str(row[1])
        space_name = row[2]
        
        print(f"📍 Space: {space_name} ({space_id})")
        print(f"📍 Connection: {connection_id}")
        print()
    
    engine.dispose()
    
    # Step 1: Normalize
    print("Step 1: Normalize JSON → table_metadata")
    print("-" * 60)
    rows = normalize_connection_metadata_to_table(connection_id, space_id)
    
    if rows == 0:
        print("\n❌ Normalization failed")
        return
    
    # Step 2: Generate embeddings
    print("\nStep 2: Generate embeddings")
    print("-" * 60)
    count = await generate_embeddings(space_id)
    
    print()
    print("="*60)
    print("✅ DONE!")
    print("="*60)
    print(f"  Metadata rows: {rows}")
    print(f"  Embeddings: {count}")
    print()
    print("🎉 RAG is now active!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
