"""Celery task that drains the ``context:ingest`` Redis stream.

Thin shim over ``core.rag.context_ingest.process_event``: the business
logic is a pure async function that takes fetch_row / embed / upsert /
soft_delete callables. This file wires those callables to production
impls (Redis consumer group, backend HTTP client, embedding provider,
Postgres writer) and hands off to the pure function per message.

Run via:
    celery -A worker.celery_app worker -Q context_ingest

In Phase 2.4 we only build the scaffold — the stream consumer loop
and backend HTTP glue. Dimensional correctness of the embedding
(vector(1536) in the backend migration vs 768 from Ollama) is
explicitly handled by skipping the embedding when dimensions disagree,
so the row still lands and retrieval falls back to full-text until the
provider side is aligned (tracked separately).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from worker.celery_app import celery_app

logger = logging.getLogger(__name__)

CONTEXT_STREAM = "context:ingest"
CONSUMER_GROUP = "context-ingest"
CONSUMER_NAME = "worker-1"

# Expected embedding dimension in the backend's context_documents table
# (see migration add_context_documents_20260415.py). The Ollama provider
# we use locally produces 768-d vectors, so in the default dev setup we
# intentionally skip the embedding write. Production uses an OpenAI
# provider that matches.
EXPECTED_EMBEDDING_DIM = 1536


async def _fetch_row_via_backend(event) -> Optional[dict[str, Any]]:
    """Fetch the full source row from the backend using the HMAC-authed
    client. Returns None if the row is gone (404).
    """
    try:
        from core.clients.backend_client import get_backend_client

        client = get_backend_client()
    except Exception:
        logger.exception("backend client not available — cannot fetch row")
        return None

    path = f"/api/v1/context/rows/{event.source_table}/{event.source_id}"
    try:
        resp = await client.get(path)
    except Exception as exc:
        # 404 → row gone; other errors propagate so Celery retries.
        msg = str(exc).lower()
        if "404" in msg or "not found" in msg:
            return None
        raise
    return resp if isinstance(resp, dict) else None


async def _embed_or_skip(text: str) -> Optional[list[float]]:
    try:
        from core.rag.embeddings import get_embedding_provider

        provider = get_embedding_provider()
        vec = await provider.embed_text(text) if hasattr(provider, "embed_text") else provider.embed([text])[0]
    except Exception:
        logger.exception("embedding provider failed — skipping vector")
        return None
    if vec is None:
        return None
    vec_list = list(vec)
    if len(vec_list) != EXPECTED_EMBEDDING_DIM:
        logger.info(
            "embedding dim mismatch: got=%d want=%d — skipping vector write",
            len(vec_list),
            EXPECTED_EMBEDDING_DIM,
        )
        return None
    return vec_list


async def _process_message(raw_payload: str) -> str:
    """Decode a stream message and run one event through the pipeline."""
    from core.rag.context_ingest import (
        ContextEvent,
        postgres_soft_delete,
        postgres_upsert,
        process_event,
    )
    from db.session import async_session

    event = ContextEvent.from_payload(raw_payload)

    async with async_session() as db:  # type: ignore[operator]
        async def _upsert(spec):
            await postgres_upsert(db, spec)
            await db.commit()

        async def _soft_delete(table, sid):
            ok = await postgres_soft_delete(db, table, sid)
            await db.commit()
            return ok

        status = await process_event(
            event,
            fetch_row=_fetch_row_via_backend,
            embed=_embed_or_skip,
            upsert=_upsert,
            soft_delete=_soft_delete,
        )
    return status


@celery_app.task(
    name="context.ingest.drain_batch",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=5,
)
def drain_batch(self, batch_size: int = 50, block_ms: int = 5000) -> dict[str, int]:
    """Pull up to ``batch_size`` events from the stream and process them.

    Scheduled by Celery beat every few seconds (wired in Phase 2.4b).
    Each event runs through the pure pipeline; the outcome is aggregated
    for observability. We use the Redis Streams consumer-group API so
    multiple workers can share the queue without double-processing.
    """
    return asyncio.run(_drain_batch_async(batch_size, block_ms))


async def _drain_batch_async(batch_size: int, block_ms: int) -> dict[str, int]:
    try:
        import redis.asyncio as aioredis

        from config.settings import settings
    except Exception:
        logger.exception("redis / settings import failed")
        return {"processed": 0, "errors": 1}

    client = aioredis.from_url(settings.redis_url or "redis://localhost:6379/0", decode_responses=True)

    # Ensure the consumer group exists. XGROUP fails with BUSYGROUP if it
    # already does — swallow that one case.
    try:
        await client.xgroup_create(CONTEXT_STREAM, CONSUMER_GROUP, id="0", mkstream=True)
    except Exception as exc:  # noqa: BLE001
        if "BUSYGROUP" not in str(exc):
            logger.warning("xgroup_create: %s", exc)

    counts: dict[str, int] = {
        "upserted": 0,
        "deleted": 0,
        "skipped_no_template": 0,
        "skipped_no_row": 0,
        "skipped_bad_event": 0,
        "errors": 0,
    }

    try:
        messages = await client.xreadgroup(
            groupname=CONSUMER_GROUP,
            consumername=CONSUMER_NAME,
            streams={CONTEXT_STREAM: ">"},
            count=batch_size,
            block=block_ms,
        )
    except Exception:
        logger.exception("xreadgroup failed")
        return {"processed": 0, "errors": 1}

    if not messages:
        return counts

    for _stream, entries in messages:
        for msg_id, fields in entries:
            payload = fields.get("payload") if isinstance(fields, dict) else None
            if not payload:
                counts["errors"] += 1
                await client.xack(CONTEXT_STREAM, CONSUMER_GROUP, msg_id)
                continue
            try:
                status = await _process_message(payload)
                counts[status] = counts.get(status, 0) + 1
                await client.xack(CONTEXT_STREAM, CONSUMER_GROUP, msg_id)
            except Exception:
                logger.exception("process_message failed for %s — leaving un-acked", msg_id)
                counts["errors"] += 1

    total = sum(v for k, v in counts.items() if k != "errors")
    logger.info("context ingest drain: processed=%d errors=%d breakdown=%s", total, counts["errors"], counts)
    return counts
