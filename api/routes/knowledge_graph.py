# api/routes/knowledge_graph.py
import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from db.session import get_db
from core.llm.factory import create_embedding_provider
from db.models import EmbeddingRecord
from core.rag.embeddings import build_strategy_text, build_signal_text

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
    # owner_user_id is populated when the entity was created in Personal
    # mode. It maps to EmbeddingRecord.user_id and lets the retrieval
    # filter (see core/rag/vector_store.py) return only the caller's own
    # Personal items. When NULL, the embedding is treated as Space/Crew
    # scoped.
    owner_user_id: Optional[str] = None


def _format_semantic_text(payload: KnowledgeGraphIngestPayload) -> str:
    """Transform the structured entity/relationship into plain English for the LLM."""
    
    # CASE 1: Enterprise Graph Relationship
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

    # CASE 2: Strategic Strategy & Signals (Rich Logic from Strategy Branch)
    if payload.entity_type == "signal_event":
        return build_signal_text(payload)
    elif payload.entity_type.startswith("strategy_") or payload.entity_type.startswith("strategic_"):
        return build_strategy_text(payload)

    # CASE 3: Generic Business Context
    text = f"BUSINESS CONTEXT NODE ({payload.entity_type.upper()}): '{payload.name}'. "
    if payload.description:
        text += f"Description: {payload.description}. "
    
    if payload.entity_details:
        details = payload.entity_details
        if payload.entity_type == "strategy_okr":
            text += f"This OKR has a baseline of {details.get('baseline')} and a target of {details.get('target')}. "
        elif payload.entity_type == "strategic_objective":
            text += f"Status: {details.get('status')}. Priority: {details.get('priority')}. "
            
    return text


async def _process_ingestion(payload: KnowledgeGraphIngestPayload, db: AsyncSession):
    try:
        semantic_text = _format_semantic_text(payload)
        provider = create_embedding_provider()
        
        # Gera embeddings do lote (async)
        vectors = await provider.embed_async([semantic_text])
        if not vectors or not vectors[0]:
            raise ValueError("Falha ao gerar embedding para o texto fornecido.")
        vector = vectors[0]

        # Tratar GUIDs nulos ou strings vazias
        space_uuid = UUID(payload.space_id) if payload.space_id else None
        crew_uuid = UUID(payload.crew_id) if payload.crew_id else None
        owner_uuid = UUID(payload.owner_user_id) if payload.owner_user_id else None

        # 1. Limpar versões anteriores da mesma entidade (usando document_id para persistência do ID externo)
        # DevOps used f"graph_node_{payload.id}", but my branch used payload.id directly.
        # We'll stick to a consistent document_id format.
        doc_id = payload.id
        stmt = delete(EmbeddingRecord).where(EmbeddingRecord.document_id == doc_id)
        await db.execute(stmt)

        # 2. Salvar novo registro
        metadata = {
            "kind": "knowledge_graph",
            "type": "enterprise_graph_node" if payload.entity_type == "enterprise_graph_node" else "business_context",
            "entity_id": payload.id,
            "entity_type": payload.entity_type,
            "name": payload.name,
            "target_type": payload.target_type,
            "target_id": payload.target_id,
            **(payload.entity_details or {})
        }

        record = EmbeddingRecord(
            space_id=space_uuid,
            crew_id=crew_uuid,
            user_id=owner_uuid,  # Personal ownership — see KnowledgeGraphIngestPayload.owner_user_id
            document_id=doc_id,
            text=semantic_text,
            embedding=vector,
            extra_metadata=metadata
        )
        db.add(record)

        await db.commit()
        logger.info(f"Knowledge Graph Node {payload.id} safely ingested and vectorized.")

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
    Ingest a new Enterprise Graph node, Strategy element or Signal into the Vector DB.
    """
    # BackgroundTasks is better for ingestion load
    background_tasks.add_task(_process_ingestion, payload, db)
    return {
        "success": True, 
        "entity_id": payload.id,
        "message": "Graph node ingestion scheduled in background."
    }
