-- Migration: Add space_id to data_connections
-- Checks if column exists before adding to prevent errors

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'data_connections'
        AND column_name = 'space_id'
    ) THEN
        ALTER TABLE data_connections ADD COLUMN space_id UUID;
        
        -- Optional: Create index for performance
        CREATE INDEX IF NOT EXISTS idx_data_connections_space_id ON data_connections(space_id);
    END IF;
END $$;
