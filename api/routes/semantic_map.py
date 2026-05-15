"""Semantic map endpoint — Universe Intelligence v2.

Projects all Space-scoped embeddings to 2-D (or 3-D) coordinates so the
frontend constellation can position dots without running a heavy UMAP on
the client side. Also exposes a top-K cosine-similarity search used by the
RAG trace overlay to highlight the most relevant nodes when the user
inspects an AI answer.

Projection uses truncated SVD (numpy.linalg.svd) — no extra dependency.
The result is deterministic for a given set of embeddings and is fast enough
for the dataset sizes we handle (≤ 50 k rows per Space).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/spaces", tags=["semantic-map"])


# ── Pydantic models ────────────────────────────────────────────────────────

class EmbeddingPoint(BaseModel):
    id: str
    document_id: Optional[str] = None
    text: str
    x: float
    y: float
    z: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


class SemanticMapResponse(BaseModel):
    space_id: str
    dimensions: int
    total: int
    points: List[EmbeddingPoint]


class SearchRequest(BaseModel):
    query_vector: List[float] = Field(..., description="Query embedding vector (768 dims).")
    top_k: int = Field(default=10, ge=1, le=100)


class SearchHit(BaseModel):
    id: str
    document_id: Optional[str] = None
    text: str
    score: float
    metadata: Optional[Dict[str, Any]] = None


class SearchResponse(BaseModel):
    space_id: str
    top_k: int
    hits: List[SearchHit]


# ── Helpers ────────────────────────────────────────────────────────────────

def _truncated_svd_2d(matrix: np.ndarray) -> np.ndarray:
    """Project N×D matrix to N×2 using the top-2 right singular vectors."""
    if matrix.shape[0] < 2:
        return np.zeros((matrix.shape[0], 2))
    # Center
    centered = matrix - matrix.mean(axis=0)
    # Economy SVD — only compute as many singular vectors as needed
    n_components = min(3, centered.shape[0], centered.shape[1])
    try:
        _, _, Vt = np.linalg.svd(centered, full_matrices=False)
        return centered @ Vt[:n_components].T
    except np.linalg.LinAlgError:
        return np.zeros((matrix.shape[0], n_components))


def _cosine_similarity(matrix: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Return cosine similarity of each row in matrix against query."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    q_norm = np.linalg.norm(query)
    if q_norm == 0:
        return np.zeros(len(matrix))
    safe_norms = np.where(norms == 0, 1.0, norms)
    return (matrix / safe_norms) @ (query / q_norm)


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("/{space_id}/semantic-map", response_model=SemanticMapResponse)
async def get_semantic_map(
    space_id: str,
    dimensions: int = Query(default=2, ge=2, le=3),
    limit: int = Query(default=2000, ge=1, le=10000),
) -> SemanticMapResponse:
    """Project all embeddings visible to ``space_id`` into 2-D or 3-D
    coordinates via truncated SVD.

    The frontend Universe Intelligence canvas calls this once on load to
    position every dot. Results are not cached — each call recomputes from
    the live ``embeddings`` table so newly seeded entities appear immediately.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("""
                    SELECT id::text, document_id, text,
                           embedding::text, metadata
                    FROM embeddings
                    WHERE space_id = CAST(:space_id AS uuid)
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                {"space_id": space_id, "limit": limit},
            )
            rows = result.fetchall()
    except Exception as exc:
        logger.exception("semantic-map DB error for space %s", space_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not rows:
        return SemanticMapResponse(
            space_id=space_id, dimensions=dimensions, total=0, points=[]
        )

    # Parse pgvector text format "[0.1,0.2,...]"
    vectors = []
    valid_rows = []
    for row in rows:
        try:
            vec_str = row.embedding.strip("[]")
            vec = np.array([float(v) for v in vec_str.split(",")], dtype=np.float32)
            vectors.append(vec)
            valid_rows.append(row)
        except Exception:
            continue

    if not vectors:
        return SemanticMapResponse(
            space_id=space_id, dimensions=dimensions, total=0, points=[]
        )

    matrix = np.stack(vectors)
    projected = _truncated_svd_2d(matrix)

    points: List[EmbeddingPoint] = []
    for i, row in enumerate(valid_rows):
        coords = projected[i]
        points.append(
            EmbeddingPoint(
                id=row.id,
                document_id=row.document_id,
                text=row.text[:200],
                x=float(coords[0]),
                y=float(coords[1]),
                z=float(coords[2]) if dimensions == 3 and len(coords) > 2 else None,
                metadata=row.metadata,
            )
        )

    return SemanticMapResponse(
        space_id=space_id,
        dimensions=dimensions,
        total=len(points),
        points=points,
    )


@router.post("/{space_id}/semantic-search", response_model=SearchResponse)
async def semantic_search(
    space_id: str,
    body: SearchRequest,
) -> SearchResponse:
    """Top-K cosine similarity search over the Space's embeddings.

    Used by the RAG trace overlay: when the user inspects an AI answer the
    frontend sends the answer's embedding and highlights the K nearest nodes
    on the Universe canvas.
    """
    query_vec = np.array(body.query_vector, dtype=np.float32)

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("""
                    SELECT id::text, document_id, text,
                           embedding::text, metadata
                    FROM embeddings
                    WHERE space_id = CAST(:space_id AS uuid)
                    ORDER BY embedding <=> CAST(:qvec AS vector)
                    LIMIT :top_k
                """),
                {
                    "space_id": space_id,
                    "qvec": f"[{','.join(str(v) for v in body.query_vector)}]",
                    "top_k": body.top_k,
                },
            )
            rows = result.fetchall()
    except Exception as exc:
        logger.exception("semantic-search DB error for space %s", space_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    hits: List[SearchHit] = []
    for row in rows:
        try:
            vec_str = row.embedding.strip("[]")
            vec = np.array([float(v) for v in vec_str.split(",")], dtype=np.float32)
            score = float(_cosine_similarity(vec.reshape(1, -1), query_vec)[0])
        except Exception:
            score = 0.0
        hits.append(
            SearchHit(
                id=row.id,
                document_id=row.document_id,
                text=row.text[:200],
                score=score,
                metadata=row.metadata,
            )
        )

    return SearchResponse(space_id=space_id, top_k=body.top_k, hits=hits)
