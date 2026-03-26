
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
            if row and 'vector' not in row[0].lower():
                logger.info(f"Converting semantic_cache.embedding from {row[0]} to vector(768)...")
                # Drop index if exists (important for type change)
                await conn.execute(text("DROP INDEX IF EXISTS idx_semantic_cache_embedding;"))
                # Alter column type
                await conn.execute(text("ALTER TABLE semantic_cache ALTER COLUMN embedding TYPE vector(768) USING embedding::text::vector;"))
                logger.info("Conversion successful.")
            else:
                logger.info("semantic_cache.embedding is already vector or table does not exist.")
        except Exception as e:
            logger.warning(f"Could not fix semantic_cache type (it might not exist yet): {e}")

        # 3. Create missing tables (best-effort using core.security.audit logic)
        logger.info("Ensuring security audit tables exist...")
        from core.security.audit import _ensure_audit_table_async
        # We need a hack here because _ensure_audit_table_async creates its own session
        # But for this script, we can just call it (it handles CREATE TABLE IF NOT EXISTS)
        
    await engine.dispose()
    
    # Call the original ensure function to create tables
    logger.info("Calling core.security.audit._ensure_audit_table_async()...")
    await _ensure_audit_table_async()
    logger.info("Fix completed.")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    asyncio.run(fix_schema())
