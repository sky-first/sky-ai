"""Per-Space seed-embeddings endpoint — called by the backend on demo signup.

The script in ``scripts/seed_knowledge_embeddings.py`` walks every Space's
metrics / glossary / relationships / connections / agents and inserts
embeddings into the ``embeddings`` table so the Universe Intelligence v2
canvas can render them. Until now it had to be run manually after every
demo signup, leaving fresh demos with a half-empty constellation.

This endpoint exposes the same logic over HTTP so the backend can fire
it as a fire-and-forget call right after a demo Space is provisioned.
Same idempotency guarantees as the script: re-seeding a Space whose
embeddings already exist is a no-op.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Re-use the helpers + main() from the shared script. Importing rather
# than copy-pasting keeps the canonical text builders + DB queries in
# one place — if a future PR adds a new entity kind to the script, the
# endpoint automatically picks it up.
from scripts.seed_knowledge_embeddings import main as run_seed

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/spaces", tags=["spaces"])


class SeedEmbeddingsResponse(BaseModel):
    space_id: str
    status: str  # "ok" | "skipped"


@router.post("/{space_id}/seed-embeddings", response_model=SeedEmbeddingsResponse)
async def seed_space_embeddings(space_id: str) -> SeedEmbeddingsResponse:
    """Walks every embeddable entity owned by ``space_id`` and inserts
    the missing embedding rows. Idempotent — already-embedded rows are
    skipped at the SQL layer (``UNIQUE(document_id, entity_type, space_id)``
    in the seed script), so re-running is free.

    Fire-and-forget from the backend's demo signup is OK — failures are
    logged and the response itself is best-effort. A failed seed leaves
    the Space recoverable via the manual CLI script.
    """
    try:
        space_uuid: Optional[UUID] = UUID(space_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="space_id is not a UUID") from e

    try:
        await run_seed(space_uuid)
    except Exception as e:
        # Don't 500 the caller — fire-and-forget shouldn't propagate
        # transient OpenAI / DB errors back to the user's signup flow.
        # The script logs its own progress; surface the kind of failure
        # in the response so admins can diagnose without log access.
        logger.exception("seed_space_embeddings failed for %s", space_id)
        raise HTTPException(status_code=500, detail=str(e)) from e

    return SeedEmbeddingsResponse(space_id=space_id, status="ok")
