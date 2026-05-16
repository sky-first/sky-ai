-- Migrate every pgvector column from vector(768) to vector(1024).
--
-- 1024 dims matches Bedrock Titan v2 / Cohere v3 / Ollama mxbai-embed-large,
-- so we can drop the OpenAI-only ``text-embedding-3-large`` (which needed
-- the ``dimensions=768`` truncation hack and 404'd against Bedrock-mantle).
-- See settings.embedding_dim for the runtime dimension.
--
-- Switching providers ALWAYS invalidates existing vectors (different
-- embedding spaces — a Titan vector is meaningless next to an OpenAI
-- vector). So this migration wipes the tables; the lazy seed in the
-- BE re-populates each space on first /semantic/map call.
--
-- Idempotent via per-table dim check: if the column is already
-- vector(1024), skip the destructive ops. Safe to re-run on freshly
-- provisioned databases (create_all already produces vector(1024)).

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_class WHERE relname = 'embeddings'
    ) AND (
        SELECT format_type(atttypid, atttypmod)
        FROM pg_attribute
        WHERE attrelid = 'embeddings'::regclass
          AND attname = 'embedding'
    ) != 'vector(1024)' THEN
        RAISE NOTICE 'Migrating embeddings.embedding → vector(1024)';
        TRUNCATE TABLE embeddings CASCADE;
        ALTER TABLE embeddings DROP COLUMN embedding;
        ALTER TABLE embeddings ADD COLUMN embedding vector(1024) NOT NULL;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_class WHERE relname = 'semantic_cache'
    ) AND (
        SELECT format_type(atttypid, atttypmod)
        FROM pg_attribute
        WHERE attrelid = 'semantic_cache'::regclass
          AND attname = 'embedding'
    ) != 'vector(1024)' THEN
        RAISE NOTICE 'Migrating semantic_cache.embedding → vector(1024)';
        TRUNCATE TABLE semantic_cache CASCADE;
        ALTER TABLE semantic_cache DROP COLUMN embedding;
        ALTER TABLE semantic_cache ADD COLUMN embedding vector(1024) NOT NULL;
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_class WHERE relname = 'knowledge_file_chunks'
    ) AND (
        SELECT format_type(atttypid, atttypmod)
        FROM pg_attribute
        WHERE attrelid = 'knowledge_file_chunks'::regclass
          AND attname = 'embedding'
    ) != 'vector(1024)' THEN
        RAISE NOTICE 'Migrating knowledge_file_chunks.embedding → vector(1024)';
        TRUNCATE TABLE knowledge_file_chunks CASCADE;
        ALTER TABLE knowledge_file_chunks DROP COLUMN embedding;
        ALTER TABLE knowledge_file_chunks ADD COLUMN embedding vector(1024);
    END IF;
END $$;
