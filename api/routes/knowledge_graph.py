import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from uuid import UUID

from db.session import get_db
from core.llm.factory import create_embedding_provider
from db.models import EmbeddingRecord
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

router = APIRouter(prefix="/knowledge-graph", tags=["Knowledge Graph"])
logger = logging.getLogger(__name__)


class SourceEntity(BaseModel):
    id: str
    type: str
    details: Optional[Dict[str, str]] = None


class KnowledgeGraphIngestPayload(BaseModel):
    id: str  # Entity or Relationship ID
    name: Optional[str] = None
    description: Optional[str] = None
    entity_type: str = "enterprise_graph_node"
    # Fields for relationships
    sources: Optional[List[SourceEntity]] = None
    target_id: Optional[str] = None
    target_type: Optional[str] = None
    target_details: Optional[Dict[str, str]] = None
    relationship_type: Optional[str] = None
    # Fields for generic entities
    entity_details: Optional[Dict[str, Any]] = None
    space_id: Optional[str] = None
    crew_id: Optional[str] = None


def _format_semantic_text(payload: KnowledgeGraphIngestPayload) -> str:
    """Transform the structured entity/relationship into plain English for the LLM."""
    if payload.entity_type == "enterprise_graph_node" and payload.sources:
        sources_text = ", ".join([f"{f'{s.type} ' if s.type else ''}'{s.id}'" for s in payload.sources])
        text = (
            f"ENTERPRISE GRAPH RELATIONSHIP: '{payload.name}'. "
            f"This node represents a '{payload.relationship_type}' connection. "
        )
        if payload.description:
            text += f"Description: {payload.description}. "
        text += f"The source entities ({sources_text}) are semantically linked to the target {payload.target_type} '{payload.target_id}'. "
        return text

    # Generic Entity Formatting
    text = f"BUSINESS CONTEXT NODE ({payload.entity_type.upper()}): '{payload.name}'. "
    if payload.description:
        text += f"Description: {payload.description}. "
    
    if payload.entity_details:
        details = payload.entity_details
        if payload.entity_type == "strategy_okr":
            text += f"This OKR has a baseline of {details.get('baseline')} and a target of {details.get('target')}. "
        elif payload.entity_type == "strategic_objective":
            text += f"Status: {details.get('status')}. Priority: {details.get('priority')}. "
        elif payload.entity_type == "signal_event":
            text += f"Nature: {payload.entity_details.get('nature')}. Category: {payload.entity_details.get('category')}. "
            
    return text


async def _process_ingestion(payload: KnowledgeGraphIngestPayload, db: AsyncSession):
    try:
        semantic_text = _format_semantic_text(payload)
        provider = create_embedding_provider()
        # Use embed_async or ensure it's called correctly if it's sync
        embedding_vectors = await provider.embed_async([semantic_text])
        embedding_vector = embedding_vectors[0] if embedding_vectors else []

        # Tratar GUIDs nulos ou strings vazias
        space_uuid = UUID(payload.space_id) if payload.space_id else None
        crew_uuid = UUID(payload.crew_id) if payload.crew_id else None

        # Verificar se já existe (atualização) ou criar novo
        result = await db.execute(
            select(EmbeddingRecord).filter(
                EmbeddingRecord.document_id == f"graph_node_{payload.id}"
            )
        )
        existing = result.scalar_one_or_none()

        metadata = {
            "type": "enterprise_graph_node" if payload.entity_type == "enterprise_graph_node" else "business_context",
            "entity_id": payload.id,
            "entity_type": payload.entity_type,
            "name": payload.name,
            "target_type": payload.target_type,
            "target_id": payload.target_id
        }

        if existing:
            existing.text = semantic_text
            existing.embedding = embedding_vector
            existing.space_id = space_uuid
            existing.crew_id = crew_uuid
            existing.extra_metadata = metadata
        else:
            record = EmbeddingRecord(
                space_id=space_uuid,
                crew_id=crew_uuid,
                document_id=f"graph_node_{payload.id}",
                text=semantic_text,
                embedding=embedding_vector,
                extra_metadata=metadata
            )
            db.add(record)

        await db.commit()
        logger.info(f"Knowledge Graph Node {payload.id} safely ingested.")

    except Exception as e:
        await db.rollback()
        logger.error(f"Error ingesting Knowledge Graph Node: {e}")


@router.post("/ingest")
async def ingest_knowledge_graph_node(
    payload: KnowledgeGraphIngestPayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Ingest a new Enterprise Graph node (Relationship) into the Vector DB.
    """
    background_tasks.add_task(_process_ingestion, payload, db)
    return {"status": "accepted", "message": "Graph node ingestion scheduled in background."}
