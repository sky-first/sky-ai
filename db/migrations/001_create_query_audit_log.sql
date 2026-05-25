-- Migration: Create query_audit_log table for security auditing
-- Created: 2026-01-07
--
-- NOTE:
-- - We generate UUID ids in application code to avoid requiring pgcrypto/uuid-ossp extensions.
-- - Apply with: psql -d ai_saas_db -f db/migrations/001_create_query_audit_log.sql

CREATE TABLE IF NOT EXISTS query_audit_log (
    id UUID PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Context
    connection_id UUID NOT NULL,
    user_id VARCHAR(255),
    space_id UUID,
    crew_ids TEXT[], -- Array de crew IDs
    thread_id VARCHAR(255),
    
    -- Query info
    question TEXT NOT NULL,
    sql_generated TEXT,
    sql_executed TEXT,
    sql_validated BOOLEAN,
    validation_error TEXT,
    
    -- Result info
    num_rows INTEGER,
    execution_time_ms INTEGER,
    has_error BOOLEAN,
    error_message TEXT,
    
    -- Security info
    was_rate_limited BOOLEAN DEFAULT FALSE,
    prompt_injection_detected BOOLEAN DEFAULT FALSE,
    prompt_injection_pattern TEXT,
    progressive_escalation_score INTEGER DEFAULT 0,
    progressive_escalation_detected BOOLEAN DEFAULT FALSE,
    
    -- Metadata
    detected_language VARCHAR(10),
    chosen_tables TEXT[],
    answer_preview TEXT -- Primeiros 500 chars
);

-- Indexes para performance
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON query_audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_user ON query_audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_connection ON query_audit_log(connection_id);
CREATE INDEX IF NOT EXISTS idx_audit_space ON query_audit_log(space_id);
CREATE INDEX IF NOT EXISTS idx_audit_thread ON query_audit_log(thread_id);
CREATE INDEX IF NOT EXISTS idx_audit_prompt_injection ON query_audit_log(prompt_injection_detected) WHERE prompt_injection_detected = TRUE;
CREATE INDEX IF NOT EXISTS idx_audit_escalation ON query_audit_log(progressive_escalation_detected) WHERE progressive_escalation_detected = TRUE;

-- Comentários
COMMENT ON TABLE query_audit_log IS 'Auditoria completa de todas as queries executadas pela IA';
COMMENT ON COLUMN query_audit_log.progressive_escalation_score IS 'Score de 0-100 indicando suspeita de progressive escalation';

