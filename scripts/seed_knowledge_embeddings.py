"""Seed embeddings for Metrics + Glossary terms + Enterprise relationships.

These three entity types live in BE-owned tables (``metrics``,
``glossary_terms``, ``user_enterprise_relationships``) but were never
embedded into the AI service's ``embeddings`` table. The Universe
Intelligence v2 canvas therefore can't show them next to the column
embeddings from connected data sources — defeating the whole point of
"see how a metric clusters near the tables it derives from".

This script:
  1. Walks every row in those three tables.
  2. Builds a short semantic-text representation per row.
  3. Calls the active embedding provider (Ollama Nomic by default).
  4. Inserts an ``EmbeddingRecord`` with ``document_id`` set to the
     source row id and ``metadata`` carrying the entity type, name,
     and source row pointer.
  5. Skips rows already embedded (idempotent on re-runs — keyed off
     ``(document_id, entity_type)`` inside ``metadata``).

Run with:
  ./venv/bin/python scripts/seed_knowledge_embeddings.py
Pass ``--space <uuid>`` to scope to a single workspace; default seeds
every space that has at least one metric / glossary / relationship.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

# Re-use the AI service's own DB session + model registry + provider.
sys.path.insert(0, "/Users/paulo.bomfim.ext/Documents/sfl/repositories/sky-poc-ai")
from db.base import SessionLocal  # noqa: E402
from db.models import EmbeddingRecord  # noqa: E402
from core.llm.factory import create_embedding_provider  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed_knowledge_embeddings")


# ─── Text builders ────────────────────────────────────────────────────


def _metric_text(row: Dict[str, Any]) -> str:
    """Build the semantic text for a metric. Includes the name, slug,
    formula description, and unit — everything that's meaningful for
    cosine similarity against a table column or a glossary term."""
    parts = [f"METRIC: {row['name']}"]
    if row.get("slug") and row["slug"] != row["name"]:
        parts.append(f"slug: {row['slug']}")
    if row.get("description"):
        parts.append(f"description: {row['description']}")
    if row.get("formula_description"):
        parts.append(f"formula: {row['formula_description']}")
    if row.get("unit"):
        parts.append(f"unit: {row['unit']}")
    if row.get("tags"):
        parts.append(f"tags: {', '.join(row['tags'])}")
    return " | ".join(parts)


def _glossary_text(row: Dict[str, Any]) -> str:
    parts = [f"GLOSSARY: {row['term']}"]
    if row.get("definition"):
        parts.append(row["definition"])
    if row.get("notes"):
        parts.append(f"notes: {row['notes']}")
    if row.get("aliases"):
        parts.append(f"aliases: {', '.join(row['aliases'])}")
    return " | ".join(parts)


def _relationship_text(row: Dict[str, Any]) -> str:
    parts = [f"RELATIONSHIP: {row['name']}"]
    if row.get("description"):
        parts.append(row["description"])
    return " | ".join(parts)


def _connection_text(row: Dict[str, Any]) -> str:
    """Semantic-text for a data connection — name + connector kind
    (postgres / mysql / sheets / …) + description. Surfacing the
    connector kind helps cosine pick up "the marketing CRM
    connection" vs. "the warehouse columns" even when names alone
    are ambiguous."""
    parts = [f"CONNECTION: {row['name']}"]
    if row.get("connector_id"):
        parts.append(f"connector: {row['connector_id']}")
    if row.get("description"):
        parts.append(row["description"])
    if row.get("table_count"):
        parts.append(f"tables: {row['table_count']}")
    return " | ".join(parts)


def _agent_text(row: Dict[str, Any]) -> str:
    """Semantic-text for an autonomous agent — name + archetype +
    depth tier + focus. Surfaces the agent on the Universe canvas
    next to the data domain it watches (e.g. Revenue Pulse clusters
    near revenue tables / metrics)."""
    parts = [f"AGENT: {row['name']}"]
    if row.get("archetype"):
        parts.append(f"archetype: {row['archetype']}")
    if row.get("depth"):
        # Map depth → tier label so the embedding text reads
        # naturally instead of "depth: quick".
        tier_label = {
            "quick": "L1 delta",
            "standard": "L2 triage",
            "deep": "L3 deep",
        }.get(row["depth"], row["depth"])
        parts.append(f"tier: {tier_label}")
    if row.get("focus"):
        parts.append(f"focus: {row['focus']}")
    return " | ".join(parts)


# ─── DB helpers ──────────────────────────────────────────────────────


async def _list_metrics(
    db: AsyncSession, space_id: Optional[UUID]
) -> List[Tuple[Dict[str, Any], Optional[UUID]]]:
    """Returns [(row_dict, space_id), ...] for the metrics to seed."""
    where = "WHERE scope_id IS NOT NULL"
    params: Dict[str, Any] = {}
    if space_id is not None:
        where += " AND scope_id = :sid"
        params["sid"] = space_id
    rows = await db.execute(
        sql_text(
            f"""
            SELECT id, name, slug, description, formula_description, unit, tags, scope_id
            FROM metrics
            {where}
            """
        ),
        params,
    )
    out: List[Tuple[Dict[str, Any], Optional[UUID]]] = []
    for r in rows.mappings().all():
        d = dict(r)
        out.append((d, d["scope_id"]))
    return out


async def _list_glossary(
    db: AsyncSession, space_id: Optional[UUID]
) -> List[Tuple[Dict[str, Any], Optional[UUID]]]:
    where = "WHERE COALESCE(scope_id, space_id) IS NOT NULL"
    params: Dict[str, Any] = {}
    if space_id is not None:
        where += " AND COALESCE(scope_id, space_id) = :sid"
        params["sid"] = space_id
    rows = await db.execute(
        sql_text(
            f"""
            SELECT id, term, definition, notes, aliases,
                   COALESCE(scope_id, space_id) AS effective_space_id
            FROM glossary_terms
            {where}
            """
        ),
        params,
    )
    out: List[Tuple[Dict[str, Any], Optional[UUID]]] = []
    for r in rows.mappings().all():
        d = dict(r)
        out.append((d, d["effective_space_id"]))
    return out


async def _list_relationships(
    db: AsyncSession, space_id: Optional[UUID]
) -> List[Tuple[Dict[str, Any], Optional[UUID]]]:
    where = "WHERE scope_id IS NOT NULL"
    params: Dict[str, Any] = {}
    if space_id is not None:
        where += " AND scope_id = :sid"
        params["sid"] = space_id
    rows = await db.execute(
        sql_text(
            f"""
            SELECT id, name, description, scope_id
            FROM user_enterprise_relationships
            {where}
            """
        ),
        params,
    )
    out: List[Tuple[Dict[str, Any], Optional[UUID]]] = []
    for r in rows.mappings().all():
        d = dict(r)
        out.append((d, d["scope_id"]))
    return out


async def _list_agents(
    db: AsyncSession, space_id: Optional[UUID]
) -> List[Tuple[Dict[str, Any], Optional[UUID]]]:
    """Returns [(row_dict, space_id), ...] for every Space-scoped
    agent. Personal- and crew-scoped agents are skipped — the v2
    canvas filters by Space, so embedding a personal agent into a
    different scope leaks it across the ACL boundary."""
    where = "WHERE scope = 'space'"
    params: Dict[str, Any] = {}
    if space_id is not None:
        where += " AND scope_id = :sid"
        params["sid"] = str(space_id)
    rows = await db.execute(
        sql_text(
            f"""
            SELECT id, name, archetype, depth, focus, scope_id
            FROM agents
            {where}
            """
        ),
        params,
    )
    out: List[Tuple[Dict[str, Any], Optional[UUID]]] = []
    for r in rows.mappings().all():
        d = dict(r)
        # agents.scope_id is stored as varchar — cast to UUID before
        # the embeddings row picks it up via the FK.
        sid_raw = d["scope_id"]
        try:
            sid = UUID(sid_raw) if sid_raw else None
        except (ValueError, TypeError):
            sid = None
        out.append((d, sid))
    return out


async def _list_connections(
    db: AsyncSession, space_id: Optional[UUID]
) -> List[Tuple[Dict[str, Any], Optional[UUID]]]:
    """Walk every (connection, space) pair via ``space_connections``.

    A connection can be shared into more than one Space, so the same
    connection produces one embedding row per Space — each row gets
    the right ``space_id`` so ACL scoping later works correctly.
    """
    # ``table_metadata.column_name`` is NOT NULL in the AI schema —
    # every row is a column. To count distinct tables we group on
    # ``table_name`` instead. ``data_connection_id`` (not
    # ``connection_id``) is the actual FK.
    base = """
        SELECT
            dc.id AS id,
            dc.name AS name,
            dc.connector_id AS connector_id,
            dc.description AS description,
            sc.space_id AS effective_space_id,
            (
                SELECT COUNT(DISTINCT tm.table_name)
                FROM table_metadata tm
                WHERE tm.data_connection_id = dc.id
            ) AS table_count
        FROM data_connections dc
        JOIN space_connections sc ON sc.connection_id = dc.id
        WHERE dc.deleted_at IS NULL
    """
    params: Dict[str, Any] = {}
    if space_id is not None:
        base += " AND sc.space_id = :sid"
        params["sid"] = space_id
    rows = await db.execute(sql_text(base), params)
    out: List[Tuple[Dict[str, Any], Optional[UUID]]] = []
    for r in rows.mappings().all():
        d = dict(r)
        out.append((d, d["effective_space_id"]))
    return out


async def _already_embedded(
    db: AsyncSession,
    source_id: str,
    entity_type: str,
    space_id: Optional[UUID] = None,
) -> bool:
    """Idempotency: keyed off (document_id, metadata->>entity_type).
    Re-running the script never duplicates rows.

    When ``space_id`` is passed (used for connections — same connection
    can ride into multiple Spaces) it's additionally matched on the
    row's ``space_id`` column so a per-Space seed is allowed.
    """
    sql = """
        SELECT 1 FROM embeddings
        WHERE document_id = :did
          AND COALESCE(metadata->>'entity_type', '') = :et
    """
    params: Dict[str, Any] = {"did": str(source_id), "et": entity_type}
    if space_id is not None:
        sql += " AND space_id = :sid"
        params["sid"] = space_id
    sql += " LIMIT 1"
    res = await db.execute(sql_text(sql), params)
    return res.first() is not None


# ─── Main seeding loop ───────────────────────────────────────────────


async def _seed_batch(
    db: AsyncSession,
    rows: List[Tuple[Dict[str, Any], Optional[UUID]]],
    entity_type: str,
    text_builder,
    *,
    per_space_unique: bool = False,
) -> Tuple[int, int]:
    """Seed a batch of rows.

    ``per_space_unique=True`` means a single source row can produce one
    embedding per Space (used for connections, which can be shared into
    multiple Spaces). When False the dedup key is just
    (document_id, entity_type) — same row across spaces collapses.
    """
    provider = create_embedding_provider()
    to_embed: List[str] = []
    pending: List[Tuple[Dict[str, Any], Optional[UUID]]] = []
    skipped = 0
    for row, space_id in rows:
        dedup_space = space_id if per_space_unique else None
        if await _already_embedded(
            db, str(row["id"]), entity_type, space_id=dedup_space
        ):
            skipped += 1
            continue
        to_embed.append(text_builder(row))
        pending.append((row, space_id))
    if not pending:
        return 0, skipped
    log.info("Embedding %d %s rows…", len(pending), entity_type)
    vectors = await provider.embed_async(to_embed)
    inserted = 0
    for (row, space_id), vec, txt in zip(pending, vectors, to_embed):
        emb = EmbeddingRecord(
            id=uuid4(),
            space_id=space_id,
            crew_id=None,
            user_id=None,
            table_metadata_id=None,
            document_id=str(row["id"]),
            embedding=vec,
            text=txt,
            extra_metadata={
                "kind": "knowledge",
                "entity_type": entity_type,
                "entity_id": str(row["id"]),
                "name": row.get("name") or row.get("term"),
                "source": "seed_knowledge_embeddings",
            },
        )
        db.add(emb)
        inserted += 1
    await db.commit()
    return inserted, skipped


async def main(space_id: Optional[UUID]) -> None:
    async with SessionLocal() as db:
        # Metrics
        metrics_rows = await _list_metrics(db, space_id)
        m_in, m_skip = await _seed_batch(db, metrics_rows, "metric", _metric_text)
        log.info("metric — inserted=%d skipped=%d", m_in, m_skip)

        # Glossary
        gloss_rows = await _list_glossary(db, space_id)
        g_in, g_skip = await _seed_batch(db, gloss_rows, "glossary", _glossary_text)
        log.info("glossary — inserted=%d skipped=%d", g_in, g_skip)

        # Relationships
        rel_rows = await _list_relationships(db, space_id)
        r_in, r_skip = await _seed_batch(
            db, rel_rows, "relationship", _relationship_text
        )
        log.info("relationship — inserted=%d skipped=%d", r_in, r_skip)

        # Connections (per-Space unique).
        conn_rows = await _list_connections(db, space_id)
        c_in, c_skip = await _seed_batch(
            db,
            conn_rows,
            "connection",
            _connection_text,
            per_space_unique=True,
        )
        log.info("connection — inserted=%d skipped=%d", c_in, c_skip)

        # Agents — Space-scoped only. Lets the v2 canvas surface
        # autonomous agents as their own family of dots, clustered
        # by archetype next to the data they watch.
        agent_rows = await _list_agents(db, space_id)
        a_in, a_skip = await _seed_batch(db, agent_rows, "agent", _agent_text)
        log.info("agent — inserted=%d skipped=%d", a_in, a_skip)

        total = m_in + g_in + r_in + c_in + a_in
        log.info(
            "DONE — %d new embeddings (skipped %d already-embedded)",
            total,
            m_skip + g_skip + r_skip + c_skip + a_skip,
        )


def _cli() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--space",
        type=str,
        default=None,
        help="Only seed for this space_id (default: every space with rows).",
    )
    args = p.parse_args()
    space_uuid = UUID(args.space) if args.space else None
    asyncio.run(main(space_uuid))


if __name__ == "__main__":
    _cli()
