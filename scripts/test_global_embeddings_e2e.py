import asyncio
import os
import sys
import uuid

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, delete, text
from db.session import AsyncSessionLocal as async_session
from db.models import DataConnection, Space, TableMetadata, EmbeddingRecord
from core.ingestion.service import run_metadata_ingestion, run_metadata_embeddings
from core.rag.vector_store import search_embeddings_async
from core.rag.embeddings import OllamaEmbeddingProvider

async def test_end_to_end_global_embeddings():
    print("🚀 Starting End-to-End Global Embeddings Test...")
    
    conn_id = str(uuid.uuid4())
    space_id_A = str(uuid.uuid4()) # Space authorized to use this connection
    
    # Dummy Connection Name
    conn_name = f"Test_Conn_Global_{conn_id[:8]}"
    
    async with async_session() as db:
        # =========================================================================
        # 1. SETUP: Create Connection (Global - no Space link implied here for creation) and Space
        # =========================================================================
        print(f"1. Creating Test Connection {conn_id} and Space {space_id_A}...")
        
        try:
             await db.execute(
                text("""
                    INSERT INTO data_connections (id, name, config, created_at)
                    VALUES (:id, :name, '{}', NOW())
                """),
                {"id": conn_id, "name": conn_name}
            )
             
             await db.execute(
                text("INSERT INTO spaces (id, name, created_at) VALUES (:id, 'Test Space A', NOW())"),
                {"id": space_id_A}
            )
             
             # Mock Backend Metadata Cache (Source of Truth)
             await db.execute(
                text("""
                    INSERT INTO connection_metadata (connection_id, tables, last_metadata_update)
                    VALUES (:cid, :tables, NOW())
                """),
                {
                    "cid": conn_id,
                    "tables": "[{\"name\": \"users\", \"schema\": \"public\", \"columns\": [{\"name\": \"id\", \"type\": \"int\"}, {\"name\": \"email\", \"type\": \"text\"}]}]"
                }
            )
             await db.commit()
        except Exception as e:
            print(f"❌ Setup Failed: {e}")
            return

        # =========================================================================
        # 2. INGESTION (Global Mode)
        # =========================================================================
        print("2. Running Global Ingestion (space_id=None)...")
        try:
            # Metadata
            inserted = await run_metadata_ingestion(
                db=db,
                connection_id=conn_id,
                space_id=None # GLOBAL
            )
            print(f"   Metadata Inserted: {inserted}")
            
            # Embeddings
            # Triggering embeddings generation
            created = await run_metadata_embeddings(
                db=db,
                connection_id=conn_id,
                space_id=None, # GLOBAL
                embedding_provider=OllamaEmbeddingProvider() # Use real or mock? Let's try real if Ollama is up.
            )
            print(f"   Embeddings Created: {created}")
            
        except Exception as e:
            print(f"❌ Ingestion Failed: {e}")
            await cleanup(db, conn_id, space_id_A)
            return

        # =========================================================================
        # 3. VERIFICATION (Global Storage)
        # =========================================================================
        print("3. Verifying Global Storage...")
        
        # Check TableMetadata
        res = await db.execute(select(TableMetadata).where(TableMetadata.data_connection_id == conn_id))
        meta = res.scalars().first()
        if not meta:
            print("❌ No Metadata found!")
        elif meta.space_id is not None:
             print(f"❌ Metadata is NOT Global! space_id={meta.space_id}")
        else:
             print("✅ Metadata is Global (space_id=None).")

        # Check Embeddings
        res = await db.execute(select(EmbeddingRecord).where(EmbeddingRecord.table_metadata_id == meta.id))
        emb = res.scalars().first()
        if not emb:
             print("❌ No Embedding found!")
        elif emb.space_id is not None:
             print(f"❌ Embedding is NOT Global! space_id={emb.space_id}")
        else:
             print("✅ Embedding is Global (space_id=None).")

        # =========================================================================
        # 4. QUERY / RETRIEVAL (Local Vision)
        # =========================================================================
        print("4. Testing Local Vision Retrieval...")
        
        provider = OllamaEmbeddingProvider()
        
        # A. Correct Context: User in Space A querying Connection Global
        # We simulate the chat query behavior
        print("   A. Querying from Space A with correct Connection ID...")
        results_valid = await search_embeddings_async(
            db=db,
            embedding_provider=provider,
            space_id=space_id_A, # User's Space
            crew_ids=None,
            query_text="email users", # Should match the table
            connection_id=conn_id # THE KEY: This enables seeing the global embedding
        )
        
        if len(results_valid) > 0:
            print(f"✅ FOUND {len(results_valid)} records (Correct).")
            # Verify it's the right one
            if results_valid[0].id == emb.id:
                 print("   Matches expected embedding ID.")
        else:
            print("❌ FAILED to find global embedding with valid connection_id!")

        # B. Incorrect Context: User in Space A querying DIFFERENT Connection context
        # (Should NOT leak the global embedding logic merely by space_id)
        # Wait, if I query connection_id=DIFFERENT, the join condition 
        # (TableMetadata.data_connection_id == connection_id) will fail.
        # This proves separation.
        print("   B. Querying with WRONG Connection ID...")
        wrong_conn_id = str(uuid.uuid4())
        results_invalid = await search_embeddings_async(
            db=db,
            embedding_provider=provider,
            space_id=space_id_A,
            crew_ids=None,
            query_text="email users",
            connection_id=wrong_conn_id
        )
        
        if len(results_invalid) == 0:
             print("✅ correctly found 0 records (Isolation works).")
        else:
             print(f"❌ FAILED! Leaked {len(results_invalid)} records from wrong connection!")

        # C. Legacy/Local Context: No connection_id passed
        # Should NOT find global embeddings (because logic `if connection_id:` block handles global).
        # Should return only Local Space embeddings (which we don't have here).
        print("   C. Querying with NO Connection ID (Legacy mode)...")
        results_legacy = await search_embeddings_async(
            db=db,
            embedding_provider=provider,
            space_id=space_id_A,
            crew_ids=None,
            query_text="email users",
            connection_id=None
        )
        if len(results_legacy) == 0:
             print("✅ correctly found 0 records (Legacy mode hides global).")
        else:
             print(f"❌ FAILED! Leaked {len(results_legacy)} records in legacy mode!")

        # =========================================================================
        # CLEANUP
        # =========================================================================
        await cleanup(db, conn_id, space_id_A)
        print("🏁 Test Complete.")

async def cleanup(db, conn_id, space_id):
    print("🧹 Cleaning up...")
    try:
        # Delete embeddings
        # Since they are global, cascade might not work if we delete Space.
        # But deleting Connection should cascade table_metadata.
        # And table_metadata deletion might not cascade embeddings if not configured in DB.
        # So we delete embeddings manually via metadata join.
        await db.execute(text("DELETE FROM connection_metadata WHERE connection_id = :id"), {"id": conn_id})
        
        # Fetch metadata IDs first
        res = await db.execute(select(TableMetadata.id).where(TableMetadata.data_connection_id == conn_id))
        meta_ids = res.scalars().all()
        
        if meta_ids:
            await db.execute(delete(EmbeddingRecord).where(EmbeddingRecord.table_metadata_id.in_(meta_ids)))
            await db.execute(delete(TableMetadata).where(TableMetadata.id.in_(meta_ids)))
        
        await db.execute(delete(DataConnection).where(DataConnection.id == conn_id))
        await db.execute(delete(Space).where(Space.id == space_id))
        await db.commit()
    except Exception as e:
        print(f"Cleanup warning: {e}")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(test_end_to_end_global_embeddings())
