"""Backfill embeddings script."""
from sqlalchemy.orm import Session
from db.session import SessionLocal
from db.models import TableMetadata, Embedding
from core.rag.vector_store import insert_embedding
from uuid import uuid4


def backfill_embeddings():
    """Reprocess embeddings for all table metadata."""
    db = SessionLocal()
    try:
        # Get all table metadata
        tables = db.query(TableMetadata).all()
        
        print(f"Processing {len(tables)} tables...")
        
        for table in tables:
            # Build description text
            description_parts = [f"Table: {table.table_name}"]
            
            if table.logical_name:
                description_parts.append(f"Logical name: {table.logical_name}")
            
            if table.description:
                description_parts.append(f"Description: {table.description}")
            
            if table.columns:
                column_names = [col.get("name", "") for col in table.columns]
                description_parts.append(f"Columns: {', '.join(column_names)}")
            
            description_text = "\n".join(description_parts)
            
            # Check if embedding already exists
            existing = db.query(Embedding).filter(
                Embedding.content_type == "table",
                Embedding.content_id == table.id
            ).first()
            
            if existing:
                print(f"Skipping {table.table_name} (embedding exists)")
                continue
            
            # Create embedding
            insert_embedding(
                db=db,
                space_id=None,  # Can be set based on connection's space
                crew_id=None,
                content_type="table",
                content_id=str(table.id),
                content_text=description_text,
                metadata={
                    "table_name": table.table_name,
                    "logical_name": table.logical_name,
                    "schema_name": table.schema_name
                }
            )
            
            print(f"Created embedding for {table.table_name}")
        
        db.commit()
        print("Embeddings backfilled successfully!")
    except Exception as e:
        db.rollback()
        print(f"Error backfilling embeddings: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    backfill_embeddings()

