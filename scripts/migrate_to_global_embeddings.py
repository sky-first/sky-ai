import asyncio
import os
import sys

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, update, delete, text
from sqlalchemy.orm import selectinload
from db.session import AsyncSessionLocal as async_session
from db.models import TableMetadata, EmbeddingRecord, DataConnection

async def migrate_to_global_embeddings():
    print("Starting migration to Global Embeddings (deduplication mode)...")
    
    async with async_session() as db:
        async with db.begin():
            # 1. Fetch all connection IDs (to iterate and reduce memory load if needed, but doing all is fine for POC)
            result = await db.execute(select(DataConnection.id))
            conn_ids = result.scalars().all()
            
            total_merged = 0
            total_updated = 0
            
            for conn_id in conn_ids:
                print(f"Processing Connection {conn_id}...")
                
                # 2. Fetch all metadata for this connection
                stmt = select(TableMetadata).where(TableMetadata.data_connection_id == conn_id)
                result = await db.execute(stmt)
                all_meta = result.scalars().all()
                
                # 3. Group by (table_name, column_name)
                # We identify duplicates that were created for different spaces/crews
                grouped = {}
                for m in all_meta:
                    key = (m.table_name, m.column_name)
                    if key not in grouped:
                        grouped[key] = []
                    grouped[key].append(m)
                
                for key, records in grouped.items():
                    # Records list contains 1 or more metadata entries for the same column
                    
                    if not records:
                        continue
                        
                    # Pick the first one as MASTER
                    master = records[0]
                    duplicates = records[1:]
                    
                    # A. Update Master to be Global
                    # We clear space_id and crew_id to make it universally accessible
                    if master.space_id is not None or master.crew_id is not None:
                         master.space_id = None
                         master.crew_id = None
                         db.add(master)
                         total_updated += 1
                    
                    # B. Handle Duplicates
                    if duplicates:
                        dup_ids = [d.id for d in duplicates]
                        print(f"  Merging {len(duplicates)} duplicates for {key} into {master.id}")
                        
                        # 1. Reassign embeddings from duplicates to master
                        # AND ensure they are global (space_id=None)
                        await db.execute(
                            update(EmbeddingRecord)
                            .where(EmbeddingRecord.table_metadata_id.in_(dup_ids))
                            .values(table_metadata_id=master.id, space_id=None, crew_id=None)
                        )
                        
                        # 2. Delete duplicate metadata rows
                        await db.execute(
                            delete(TableMetadata)
                            .where(TableMetadata.id.in_(dup_ids))
                        )
                        total_merged += len(duplicates)
                    
                    # C. Ensure embeddings linked to Master are also global
                    # (In case master had embeddings but no duplicates, or embeddings were already on master)
                    await db.execute(
                        update(EmbeddingRecord)
                        .where(EmbeddingRecord.table_metadata_id == master.id)
                        .values(space_id=None, crew_id=None)
                    )

            print(f"Migration Complete.")
            print(f"Total entries updated to global: {total_updated}")
            print(f"Total duplicates merged/deleted: {total_merged}")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(migrate_to_global_embeddings())
