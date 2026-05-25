-- Add user_id column to semantic_cache so Personal-mode cache rows are
-- isolated per user. Without this, user A's Personal question answer
-- could be served to user B when both hit the same connection_id —
-- exactly the cross-user leak the retrieval-side fixes already close.
--
-- Nullable: existing Space/Crew rows stay NULL; new Personal rows get
-- the caller's user_id. The lookup rule added in connection_query.py
-- reads this column.
--
-- Safe to run multiple times: guarded by IF NOT EXISTS.

ALTER TABLE semantic_cache
    ADD COLUMN IF NOT EXISTS user_id TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_semantic_cache_user_id
    ON semantic_cache(user_id);
