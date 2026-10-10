-- Migration: trilhos de auditoria completos na base de CADA cliente
-- Created: 2026-10-10
--
-- O sky-ai passou a gravar query_audit_log, prompt_security_audit e
-- security_alerts na base do cliente (Modelo B) em vez da base da plataforma.
-- Medido em produção a 10/10/2026: as bases de cliente tinham query_audit_log
-- com 0 linhas e sem as colunas de papel/PII (o 001 é anterior a elas), e não
-- tinham prompt_security_audit de todo.
--
-- Corre em todas as bases pelo scripts/sync_tenants.py (hook de deploy) e na
-- da plataforma. Idempotente: tudo IF NOT EXISTS. Manter em linha com o DDL de
-- core/security/audit.py::_ensure_audit_table_async, que faz o mesmo em tempo
-- de execução.

ALTER TABLE IF EXISTS query_audit_log
    ADD COLUMN IF NOT EXISTS platform_role VARCHAR(50),
    ADD COLUMN IF NOT EXISTS crew_role VARCHAR(50),
    ADD COLUMN IF NOT EXISTS pii_detected_in_prompt BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS pii_detected_in_response BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS pii_types TEXT[],
    ADD COLUMN IF NOT EXISTS pii_severity VARCHAR(10),
    ADD COLUMN IF NOT EXISTS pii_patterns_matched TEXT[],
    ADD COLUMN IF NOT EXISTS pii_blocked BOOLEAN DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS security_alerts (
    id UUID PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    user_id VARCHAR(255),
    connection_id UUID,
    alert_type VARCHAR(50),
    severity VARCHAR(20),
    details JSONB
);
CREATE INDEX IF NOT EXISTS idx_alerts_user ON security_alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_alerts_type ON security_alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON security_alerts(severity);

CREATE TABLE IF NOT EXISTS prompt_security_audit (
    id UUID PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    connection_id UUID,
    user_id VARCHAR(255),
    prompt_text_redacted TEXT,
    security_status VARCHAR(20),
    blocked_by VARCHAR(50),
    risk_score FLOAT,
    scan_details JSONB
);
CREATE INDEX IF NOT EXISTS idx_prompt_audit_timestamp ON prompt_security_audit(timestamp);
CREATE INDEX IF NOT EXISTS idx_prompt_audit_user ON prompt_security_audit(user_id);
CREATE INDEX IF NOT EXISTS idx_prompt_audit_connection ON prompt_security_audit(connection_id);
CREATE INDEX IF NOT EXISTS idx_prompt_audit_status ON prompt_security_audit(security_status);
