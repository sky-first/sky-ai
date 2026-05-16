"""Semantic map + search endpoints — powers Universe Intelligence v2.

Two endpoints:

  * ``POST /semantic/map`` — pulls all embeddings the caller can see
    (ACL resolved upstream by the BE), runs UMAP server-side, runs
    HDBSCAN for cluster IDs, and returns the rich shape the FE
    constellation expects: per-point ``{id, source_id, kind, label,
    snippet, x, y, z, cluster_id, source}`` plus relationship edges +
    UMAP parameters at the top level.

  * ``POST /semantic/search`` — embeds an incoming query string and
    returns the top-K most similar embedding IDs via pgvector cosine
    distance. Used for the "lit path" RAG-trace overlay (Phase E):
    when a user asks a question in the chat, the FE highlights the K
    points the retriever pulled.

Both endpoints take an explicit ACL scope (``user_id`` / ``space_ids``
/ ``crew_ids``). They do **not** consult the user database directly —
the backend on port 8000 is the authority on what the caller can see
and is responsible for passing the resolved scope down here.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.llm.factory import create_embedding_provider
from core.rag.semantic_projection import (
    ClusterParams,
    ProjectionParams,
    cluster_points,
    project_to_low_dim,
)
from db.models import EmbeddingRecord
from db.session import AsyncSessionLocal

router = APIRouter(prefix="/semantic", tags=["Semantic Map"])
logger = logging.getLogger(__name__)


# ─── Request / response schemas ──────────────────────────────────────


class SemanticMapRequest(BaseModel):
    """ACL-resolved scope payload from the BE. The AI service trusts
    these IDs as authoritative — the BE is responsible for membership
    checks before forwarding the request."""

    user_id: Optional[str] = None
    space_ids: List[str] = Field(default_factory=list)
    crew_ids: List[str] = Field(default_factory=list)
    n_components: int = Field(default=3, ge=2, le=3)
    n_neighbors: int = Field(default=15, ge=2, le=200)
    min_dist: float = Field(default=0.1, ge=0.0, le=1.0)
    enable_clustering: bool = True
    min_cluster_size: int = Field(default=5, ge=2, le=200)
    limit: int = Field(default=2000, ge=1, le=10000)


class SemanticPoint(BaseModel):
    id: str
    source_id: Optional[str] = None
    kind: str
    label: str
    snippet: Optional[str] = None
    x: float
    y: float
    z: float = 0.0
    cluster_id: int = -1
    source: str = "embeddings"


class SemanticEdge(BaseModel):
    source_id: str
    target_id: str
    type: str
    label: str
    relationship_id: str


class SemanticMapResponse(BaseModel):
    points: List[SemanticPoint]
    edges: List[SemanticEdge] = Field(default_factory=list)
    model: str
    dim: int
    count: int
    n_clusters: int
    umap_params: Dict[str, Any]


class SemanticSearchRequest(BaseModel):
    user_id: Optional[str] = None
    space_ids: List[str] = Field(default_factory=list)
    crew_ids: List[str] = Field(default_factory=list)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)


class SemanticSearchHit(BaseModel):
    id: str
    score: float
    kind: str
    label: str
    snippet: Optional[str] = None


class SemanticSearchResponse(BaseModel):
    query: str
    hits: List[SemanticSearchHit]
    model: str
    dim: int


# ─── Helpers ────────────────────────────────────────────────────────


def _parse_uuid_list(values: List[str]) -> List[UUID]:
    out: List[UUID] = []
    for v in values:
        try:
            out.append(UUID(v))
        except (ValueError, TypeError):
            continue
    return out


def _infer_kind(record: EmbeddingRecord) -> str:
    """Best-effort classification of an embedding into a UI kind.

    Prefers ``extra_metadata.kind`` when the seeder set it. Falls back
    to FK-based heuristics so legacy rows still get a sensible label.
    """
    meta = record.extra_metadata or {}
    if isinstance(meta, dict):
        explicit = meta.get("kind") or meta.get("entity_kind") or meta.get("type")
        if isinstance(explicit, str) and explicit:
            return explicit
    if record.table_metadata_id is not None:
        if isinstance(meta, dict) and meta.get("column"):
            return "column"
        return "table"
    if record.document_id:
        return "document"
    return "context"


def _label_for(record: EmbeddingRecord) -> str:
    meta = record.extra_metadata or {}
    if isinstance(meta, dict):
        for key in ("label", "name", "title", "term", "metric_name"):
            v = meta.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()[:80]
    text = (record.text or "").strip()
    return text[:80] if text else "(untitled)"


def _source_id_for(record: EmbeddingRecord) -> Optional[str]:
    if record.table_metadata_id is not None:
        return str(record.table_metadata_id)
    if record.document_id:
        return record.document_id
    return None


async def _load_embeddings(
    db: AsyncSession,
    req: SemanticMapRequest,
) -> List[EmbeddingRecord]:
    """Pull every embedding visible to the resolved scope.

    Visibility = OR across user_id, space_ids, crew_ids. None of those
    are mandatory; an empty scope returns an empty list (the FE renders
    the "no embeddings" empty state).
    """
    conditions = []
    if req.user_id:
        try:
            conditions.append(EmbeddingRecord.user_id == UUID(req.user_id))
        except (ValueError, TypeError):
            pass
    space_uuids = _parse_uuid_list(req.space_ids)
    if space_uuids:
        conditions.append(EmbeddingRecord.space_id.in_(space_uuids))
    crew_uuids = _parse_uuid_list(req.crew_ids)
    if crew_uuids:
        conditions.append(EmbeddingRecord.crew_id.in_(crew_uuids))
    if not conditions:
        return []
    stmt = (
        select(EmbeddingRecord)
        .where(or_(*conditions))
        .order_by(EmbeddingRecord.created_at.desc())
        .limit(req.limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _parse_vector(raw: Any) -> Optional[np.ndarray]:
    """pgvector surfaces in three shapes depending on the read path:
    ``numpy.ndarray`` when the ORM uses ``pgvector.sqlalchemy.Vector``,
    ``list[float]`` for some raw selects, and the bracketed text fallback
    (``"[0.1,0.2,...]"``) when the column is cast to text. Missing the
    ndarray case dropped every row as "invalid vector" so /semantic/map
    returned count=0 despite embeddings existing in the DB."""
    if raw is None:
        return None
    if isinstance(raw, np.ndarray):
        return raw.astype(np.float32, copy=False)
    if isinstance(raw, (list, tuple)):
        try:
            return np.asarray(raw, dtype=np.float32)
        except (ValueError, TypeError):
            return None
    if isinstance(raw, str):
        try:
            cleaned = raw.strip().strip("[]")
            if not cleaned:
                return None
            return np.array(
                [float(v) for v in cleaned.split(",")], dtype=np.float32
            )
        except (ValueError, TypeError):
            return None
    return None


# ─── /semantic/map ──────────────────────────────────────────────────


@router.post("/map", response_model=SemanticMapResponse)
async def post_semantic_map(req: SemanticMapRequest) -> SemanticMapResponse:
    """Project every embedding visible to the resolved scope into 2-D
    or 3-D coordinates + cluster IDs.

    Returns the rich response shape the FE Universe Intelligence canvas
    expects. The BE wraps this behind ``/api/v1/context/semantic-map``
    with ACL resolution; we just trust the IDs it sends.
    """
    try:
        async with AsyncSessionLocal() as db:
            records = await _load_embeddings(db, req)
    except Exception as exc:
        logger.exception("semantic-map DB query failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not records:
        return SemanticMapResponse(
            points=[],
            edges=[],
            model="nomic-embed-text",
            dim=768,
            count=0,
            n_clusters=0,
            umap_params={
                "n_components": req.n_components,
                "n_neighbors": req.n_neighbors,
                "min_dist": req.min_dist,
                "metric": "cosine",
            },
        )

    vectors: List[np.ndarray] = []
    valid: List[EmbeddingRecord] = []
    for r in records:
        v = _parse_vector(r.embedding)
        if v is not None and v.size > 0:
            vectors.append(v)
            valid.append(r)
    if not vectors:
        return SemanticMapResponse(
            points=[],
            edges=[],
            model="nomic-embed-text",
            dim=768,
            count=0,
            n_clusters=0,
            umap_params={
                "n_components": req.n_components,
                "n_neighbors": req.n_neighbors,
                "min_dist": req.min_dist,
                "metric": "cosine",
            },
        )

    matrix = np.stack(vectors)
    coords = project_to_low_dim(
        matrix,
        ProjectionParams(
            n_components=req.n_components,
            n_neighbors=req.n_neighbors,
            min_dist=req.min_dist,
            metric="cosine",
        ),
    )

    if req.enable_clustering:
        labels, n_clusters = cluster_points(
            coords,
            ClusterParams(min_cluster_size=req.min_cluster_size),
        )
    else:
        labels = np.full(coords.shape[0], -1, dtype=np.int32)
        n_clusters = 0

    points: List[SemanticPoint] = []
    for i, r in enumerate(valid):
        c = coords[i]
        kind = _infer_kind(r)
        text = (r.text or "").strip()
        points.append(
            SemanticPoint(
                id=str(r.id),
                source_id=_source_id_for(r),
                kind=kind,
                label=_label_for(r),
                snippet=text[:200] if text else None,
                x=float(c[0]),
                y=float(c[1]),
                z=float(c[2]) if c.shape[0] > 2 else 0.0,
                cluster_id=int(labels[i]),
                source="embeddings",
            )
        )

    return SemanticMapResponse(
        points=points,
        edges=[],  # Relationship edges not yet wired into the embeddings table.
        model="nomic-embed-text",
        dim=int(matrix.shape[1]),
        count=len(points),
        n_clusters=int(n_clusters),
        umap_params={
            "n_components": req.n_components,
            "n_neighbors": req.n_neighbors,
            "min_dist": req.min_dist,
            "metric": "cosine",
        },
    )


# ─── /semantic/search ───────────────────────────────────────────────


@router.post("/search", response_model=SemanticSearchResponse)
async def post_semantic_search(req: SemanticSearchRequest) -> SemanticSearchResponse:
    """Embed ``query`` and return the top-K nearest embedding IDs in
    the caller's scope, with kind/label/snippet so the FE can highlight
    matched nodes on the constellation."""
    if not req.user_id and not req.space_ids and not req.crew_ids:
        return SemanticSearchResponse(
            query=req.query,
            hits=[],
            model="nomic-embed-text",
            dim=768,
        )

    # Embed the query — same provider the rest of the AI stack uses so
    # the comparison happens in matching vector space.
    try:
        provider = create_embedding_provider()
        vectors = await provider.embed_async([req.query])
    except Exception as exc:
        logger.exception("semantic-search embedding failed")
        raise HTTPException(
            status_code=503, detail=f"Embedding service unavailable: {exc}"
        ) from exc

    if not vectors:
        return SemanticSearchResponse(
            query=req.query,
            hits=[],
            model="nomic-embed-text",
            dim=768,
        )
    qvec = np.asarray(vectors[0], dtype=np.float32)
    qnorm = float(np.linalg.norm(qvec))
    if qnorm == 0:
        return SemanticSearchResponse(
            query=req.query,
            hits=[],
            model="nomic-embed-text",
            dim=int(qvec.size),
        )

    # Pull candidate embeddings scoped to the caller, compute cosine
    # similarity in Python. For typical scopes (≤ a few thousand rows)
    # this is fast enough; bigger scopes should switch to pgvector's
    # native ``<=>`` order-by.
    map_req = SemanticMapRequest(
        user_id=req.user_id,
        space_ids=req.space_ids,
        crew_ids=req.crew_ids,
        limit=2000,
    )
    try:
        async with AsyncSessionLocal() as db:
            records = await _load_embeddings(db, map_req)
    except Exception as exc:
        logger.exception("semantic-search DB query failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    scored: List[tuple[float, EmbeddingRecord]] = []
    for r in records:
        v = _parse_vector(r.embedding)
        if v is None or v.size != qvec.size:
            continue
        nv = float(np.linalg.norm(v))
        if nv == 0:
            continue
        score = float(np.dot(v, qvec) / (nv * qnorm))
        scored.append((score, r))

    scored.sort(key=lambda t: t[0], reverse=True)
    top = scored[: req.top_k]
    hits = [
        SemanticSearchHit(
            id=str(r.id),
            score=score,
            kind=_infer_kind(r),
            label=_label_for(r),
            snippet=((r.text or "").strip()[:200] or None),
        )
        for score, r in top
    ]
    return SemanticSearchResponse(
        query=req.query,
        hits=hits,
        model="nomic-embed-text",
        dim=int(qvec.size),
    )
