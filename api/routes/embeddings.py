"""Batch embedding endpoint — called by the backend Celery knowledge worker.

The backend worker streams a file from Azure/local storage, parses it into
text chunks, then POSTs those chunks here to get embeddings back. This
keeps the embedding model (Ollama / OpenAI) centralised in the AI engine
instead of duplicating provider logic in the backend.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from core.llm.factory import create_embedding_provider

router = APIRouter(prefix="/embeddings", tags=["embeddings"])


class BatchEmbedRequest(BaseModel):
    texts: List[str] = Field(..., min_length=1, description="Texts to embed.")


class BatchEmbedResponse(BaseModel):
    embeddings: List[List[float]]
    model: str


@router.post("/batch", response_model=BatchEmbedResponse)
async def batch_embed(body: BatchEmbedRequest) -> BatchEmbedResponse:
    """Embed a list of texts and return the vectors.

    The dimension depends on the active provider:
    - Ollama nomic-embed-text: 768 dims
    - OpenAI text-embedding-3-large (forced to 768): 768 dims
    """
    provider = create_embedding_provider()
    embeddings = await provider.embed_async(body.texts)
    return BatchEmbedResponse(
        embeddings=embeddings,
        model=getattr(provider, "model", "unknown"),
    )
