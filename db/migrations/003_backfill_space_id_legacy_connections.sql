-- Migration: backfill space_id for legacy connections and their metadata.
--
-- Context
-- -------
-- Incident 2026-04-15: users Paulo + Laís hit 404 on the AI chat because
-- data_connections created BEFORE migration 002 have space_id = NULL.
-- Migration 002 only ALTER-added the column, it never populated it for
-- existing rows. The new query path filters by (space_id, connection_id)
-- and returns 0 rows for legacy users, which surfaces as a 404.
--
-- Strategy
-- --------
-- Resolve space_id for each orphan data_connections row in priority
-- order:
--
--   1. Primary signal: space_connections join table. If the connection
--      is already linked to one or more spaces, pick the earliest one.
--
--   2. Fallback: the creator's personal/default space. We pick any
--      space_members row for created_by; if there are multiple, we
--      prefer the one created first (typically the user's own space).
--
--   3. Give up silently: if neither yields a row, the column stays
--      NULL and the code-side defensive fallback (space_id IS NULL
--      match) keeps the connection usable until an admin re-scopes it.
--
-- Once data_connections is settled, cascade the same space_id down to
-- table_metadata rows that belong to those connections AND are still
-- NULL. This is what the app's chat queries actually read.
--
-- Idempotency: every UPDATE has `WHERE space_id IS NULL`, so re-running
-- is safe and only touches rows that still need it.

BEGIN;

-- ── Step 1: backfill data_connections from space_connections ────────────
UPDATE data_connections dc
SET space_id = sc.space_id
FROM (
    SELECT DISTINCT ON (connection_id)
           connection_id, space_id
    FROM space_connections
    ORDER BY connection_id
) sc
WHERE dc.id = sc.connection_id
  AND dc.space_id IS NULL;

-- ── Step 2: backfill remaining data_connections from creator's space ────
UPDATE data_connections dc
SET space_id = sm.space_id
FROM (
    SELECT DISTINCT ON (user_id)
           user_id, space_id
    FROM space_members
    ORDER BY user_id, created_at ASC
) sm
WHERE dc.created_by = sm.user_id
  AND dc.space_id IS NULL;

-- ── Step 3: cascade space_id down to table_metadata ─────────────────────
-- Only touch rows whose connection has a resolved space_id — rows
-- orphaned at step 2 stay NULL and rely on the code-side fallback.
UPDATE table_metadata tm
SET space_id = dc.space_id
FROM data_connections dc
WHERE tm.data_connection_id = dc.id
  AND tm.space_id IS NULL
  AND dc.space_id IS NOT NULL;

COMMIT;

-- Verify, for ops visibility. After running, the number of NULL rows
-- should be the count of truly orphan connections (no space_connections
-- link AND creator with no space membership). Ideally 0.
--
--   SELECT COUNT(*) FROM data_connections WHERE space_id IS NULL;
--   SELECT COUNT(*) FROM table_metadata WHERE space_id IS NULL;
