# core/agents/universe/trigger.py
"""
Background task executor for Universe Intelligence discovery cycles.
Called by the /universe/trigger API endpoint — runs in FastAPI BackgroundTasks.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def run_discovery_background(
    space_id: str,
    output_format: str = "text",
) -> None:
    """
    Runs a Universe Intelligence discovery cycle in the background.
    Designed to be called from FastAPI BackgroundTasks.

    Args:
        space_id: UUID string of the Space to investigate.
        output_format: "text" | "mix" — controls analyst output.
    """
    import uuid
    from db.base import SyncSessionLocal
    from db.models import DataConnection, User
    from core.agents.universe.orchestrator import UniverseDiscoveryManager
    from core.auth.models import UserContext, User as UserPydantic
    from core.agents.factory import build_agent_config_for_user_space
    from core.data_sources.factory import DataSourceFactory
    from core.llm.factory import create_embedding_provider
    from core.dialects import Dialect
    from sqlalchemy import select

    logger.info(f"[Universe Trigger] Starting Global Discovery: space={space_id}, format={output_format}")

    db = SyncSessionLocal()
    try:
        manager = UniverseDiscoveryManager(db)

        # Build system user context (headless)
        user_obj = db.query(User).first()
        if user_obj:
            user_pydantic = UserPydantic(
                id=user_obj.id,
                email=user_obj.email,
                name=user_obj.name or "Universe System",
                is_active=True,
            )
        else:
            user_pydantic = UserPydantic(
                id=uuid.uuid4(),
                email="system@universe.ai",
                name="Universe System",
                is_active=True,
            )

        user_ctx = UserContext(
            user=user_pydantic,
            space_id=uuid.UUID(space_id),
            crew_ids=[],
            platform_role="admin",
            crew_role="commander",
            permissions=["read", "write"]
        )

        # Resolve data connection
        conn_obj = (
            db.query(DataConnection)
            .filter(DataConnection.space.any(id=space_id))
            .first()
        )
        if not conn_obj:
            logger.warning(f"[Universe Trigger] No data connection for space {space_id}")
            return

        data_source = DataSourceFactory.build_from_dataconnection(conn_obj)
        dialect = getattr(data_source, "dialect", Dialect.POSTGRES)
        embedding_provider = create_embedding_provider()

        agent_config = build_agent_config_for_user_space(
            db=db,
            user_ctx=user_ctx,
            space_id=space_id,
            dialect=dialect,
        )

        insight = await manager.run_general_discovery(
            user_ctx=user_ctx,
            agent_config=agent_config,
            empresa_contexto="SaaS Billing Company.",
            objetivos_estrategicos=["Increase Revenue", "Reduce Churn", "Optimize Overdue Invoices"],
            data_source=data_source,
            embedding_provider=embedding_provider,
            db_session_factory=SyncSessionLocal,
            output_format=output_format,
        )

        if insight:
            logger.info(f"[Universe Trigger] Insight approved: {insight.get('title')} [{insight.get('category')}]")
        else:
            logger.info("[Universe Trigger] No insight approved for this cycle.")

    except Exception as e:
        logger.exception(f"[Universe Trigger] Error during discovery: {e}")
    finally:
        db.close()
