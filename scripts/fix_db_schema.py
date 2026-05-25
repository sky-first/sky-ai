import asyncio
import os
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fix_db_schema")


async def fix_schema():
    pg_user = os.getenv("POSTGRES_USER", "postgres")
    pg_pass = os.getenv("POSTGRES_PASSWORD", "postgres")
    pg_host = os.getenv("POSTGRES_HOST", "localhost")
    pg_port = os.getenv("POSTGRES_PORT", "5432")
    pg_db = os.getenv("POSTGRES_DB", "ai_saas_db")

    url = f"postgresql+asyncpg://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"
    logger.info(f"Connecting to {url}...")

    engine = create_async_engine(url)

    async with engine.begin() as conn:
        # 1. Enable pgvector if not enabled
        logger.info("Ensuring pgvector extension...")
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))

        # 2. Fix semantic_cache embedding type
        try:
            # Check current type
            result = await conn.execute(text("""
                SELECT format_type(atttypid, atttypmod) AS type
                FROM pg_attribute
                WHERE attrelid = 'semantic_cache'::regclass
                AND attname = 'embedding';
            """))
            row = result.fetchone()
            if row and "vector" not in row[0].lower():
                logger.info(
                    f"Converting semantic_cache.embedding from {row[0]} to vector(768)..."
                )
                # Drop index if exists (important for type change)
                await conn.execute(
                    text("DROP INDEX IF EXISTS idx_semantic_cache_embedding;")
                )
                # Alter column type
                await conn.execute(
                    text(
                        "ALTER TABLE semantic_cache ALTER COLUMN embedding TYPE vector(768) USING embedding::text::vector;"
                    )
                )
                logger.info("Conversion successful.")
            else:
                logger.info(
                    "semantic_cache.embedding is already vector or table does not exist."
                )
        except Exception as e:
            logger.warning(
                f"Could not fix semantic_cache type (it might not exist yet): {e}"
            )

        # (Audit table creation moved below — it used to happen AFTER the
        # ALTER TABLE statements, which failed with UndefinedTable on a
        # fresh db that never had query_audit_log created.)

    # 3. Create missing tables BEFORE altering them. _ensure_audit_table_async
    # opens its own session and runs CREATE TABLE IF NOT EXISTS, so the
    # outer engine needs to be closed first.
    await engine.dispose()
    from core.security.audit import _ensure_audit_table_async

    logger.info("Ensuring security audit tables exist...")
    await _ensure_audit_table_async()

    # 4. Now that the table is (probably) guaranteed to exist, add columns
    # introduced in later migrations. Reopen the engine for the ALTERs.
    # If `_ensure_audit_table_async` silently no-ops (e.g. SQLAlchemy
    # cycle) the ALTER hits "relation does not exist" — guard that case
    # so the noisy startup warning the user has seen for weeks finally
    # goes away. The columns will be added the next time the table
    # actually exists.
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        exists = (
            await conn.execute(
                text("SELECT to_regclass('public.query_audit_log') IS NOT NULL")
            )
        ).scalar()
        if exists:
            await conn.execute(
                text(
                    "ALTER TABLE query_audit_log ADD COLUMN IF NOT EXISTS platform_role VARCHAR(50);"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE query_audit_log ADD COLUMN IF NOT EXISTS crew_role VARCHAR(50);"
                )
            )
            logger.info("Audit log columns ensured (platform_role, crew_role).")
        else:
            logger.info(
                "query_audit_log not present yet — skipping ALTERs. They'll run "
                "the next boot once _ensure_audit_table_async creates the table."
            )
    await engine.dispose()
    logger.info("Fix completed.")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    asyncio.run(fix_schema())
