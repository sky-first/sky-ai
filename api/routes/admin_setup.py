"""
API endpoint to trigger RAG Phase 1 setup.
Add to api/routes/admin.py or create new file.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from db.session import get_db
from core.rag.embeddings import OpenAIEmbeddingProvider, create_embeddings_for_table_metadata
from core.logging_utils import log_event

router = APIRouter(prefix="/admin", tags=["admin"])


class SetupRAGRequest(BaseModel):
    space_id: str
    connection_id: str | None = None


@router.post("/setup-rag")
async def setup_rag_endpoint(
    body: SetupRAGRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Trigger RAG Phase 1 setup via API.
    This runs the embedding generation using the service's database credentials.
    """
    try:
        # Step 1: Embed table metadata
        embedding_provider = OpenAIEmbeddingProvider()
        
        num_embeddings = await create_embeddings_for_table_metadata(
            db=db,
            embedding_provider=embedding_provider,
            space_id=body.space_id,
            data_connection_id=body.connection_id,
            batch_size=20,
            delay_between_batches=1.0
        )
        
        log_event(
            "admin_setup_rag_complete",
            {"space_id": body.space_id, "num_embeddings": num_embeddings}
        )
        
        return {
            "success": True,
            "embeddings_created": num_embeddings,
            "message": f"RAG setup complete! Created {num_embeddings} embeddings."
        }
        
    except Exception as e:
        log_event(
            "admin_setup_rag_error",
            {"space_id": body.space_id, "error": str(e)[:500]}
        )
        raise HTTPException(status_code=500, detail=str(e))
