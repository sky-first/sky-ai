# core/security/audit.py
"""
Sistema de auditoria assíncrono para queries.
Não bloqueia requests - usa buffer em memória + flush periódico.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Any, Optional, List
from collections import deque
import asyncio
import threading
from uuid import uuid4
import time

from sqlalchemy import text

# Buffer em memória (thread-safe com deque)
_audit_buffer: deque = deque(maxlen=1000)  # Máximo 1000 logs em buffer
_flush_interval = 5.0  # Flush a cada 5 segundos
_flush_batch_size = 50  # Flush em lotes de 50
_flusher_running = False
_flusher_task: Optional[asyncio.Task] = None
_audit_disabled_until_ts: float = 0.0
_last_ensure_attempt_ts: float = 0.0
_ensure_cooldown_seconds: float = 30.0


def log_query_audit(
    connection_id: str,
    user_id: Optional[str],
    space_id: Optional[str],
    crew_ids: Optional[List[str]],
    thread_id: Optional[str],
    question: str,
    sql_generated: Optional[str] = None,
    sql_executed: Optional[str] = None,
    sql_validated: Optional[bool] = None,
    validation_error: Optional[str] = None,
    num_rows: Optional[int] = None,
    execution_time_ms: Optional[int] = None,
    has_error: Optional[bool] = None,
    error_message: Optional[str] = None,
    was_rate_limited: bool = False,
    prompt_injection_detected: bool = False,
    prompt_injection_pattern: Optional[str] = None,
    progressive_escalation_score: int = 0,
    progressive_escalation_detected: bool = False,
    detected_language: Optional[str] = None,
    chosen_tables: Optional[List[str]] = None,
    answer_preview: Optional[str] = None,
    # Campos PII
    pii_detected_in_prompt: bool = False,
    pii_detected_in_response: bool = False,
    pii_types: Optional[List[str]] = None,
    pii_severity: Optional[str] = None,
    pii_patterns_matched: Optional[List[str]] = None,
    pii_blocked: bool = False,
):
    """
    Adiciona log ao buffer (não bloqueia).
    Thread-safe.
    """
    log_entry = {
        "id": str(uuid4()),
        "timestamp": datetime.now().isoformat(),
        "connection_id": connection_id,
        "user_id": user_id,
        "space_id": str(space_id) if space_id else None,
        "crew_ids": crew_ids or [],
        "thread_id": thread_id,
        "question": question[:1000] if question else None,  # Limitar tamanho
        "sql_generated": sql_generated[:5000] if sql_generated else None,
        "sql_executed": sql_executed[:5000] if sql_executed else None,
        "sql_validated": sql_validated,
        "validation_error": validation_error[:500] if validation_error else None,
        "num_rows": num_rows,
        "execution_time_ms": execution_time_ms,
        "has_error": has_error,
        "error_message": error_message[:1000] if error_message else None,
        "was_rate_limited": was_rate_limited,
        "prompt_injection_detected": prompt_injection_detected,
        "prompt_injection_pattern": prompt_injection_pattern,
        "progressive_escalation_score": progressive_escalation_score,
        "progressive_escalation_detected": progressive_escalation_detected,
        "detected_language": detected_language,
        "chosen_tables": chosen_tables or [],
        "answer_preview": answer_preview[:500] if answer_preview else None,
        # Campos PII
        "pii_detected_in_prompt": pii_detected_in_prompt,
        "pii_detected_in_response": pii_detected_in_response,
        "pii_types": pii_types or [],
        "pii_severity": pii_severity,
        "pii_patterns_matched": pii_patterns_matched or [],
        "pii_blocked": pii_blocked,
    }
    
    _audit_buffer.append(log_entry)


def log_security_alert(
    connection_id: str,
    user_id: Optional[str],
    alert_type: str,  # 'PII_PROMPT', 'PROMPT_INJECTION', etc
    severity: str,    # 'BLOCK', 'CRITICAL', 'HIGH'
    details: Dict[str, Any],
):
    """
    Registra um alerta de segurança no buffer.
    """
    log_entry = {
        "_type": "alert",  # Marcador interno
        "id": str(uuid4()),
        "timestamp": datetime.now().isoformat(),
        "connection_id": connection_id,
        "user_id": user_id,
        "alert_type": alert_type,
        "severity": severity,
        "details": details
    }
    _audit_buffer.append(log_entry)



async def _ensure_audit_table_async() -> None:
    """
    Best-effort: cria a tabela/indexes se ainda não existirem.
    Evita falhas em ambientes onde a migration ainda não foi aplicada.
    """
    global _last_ensure_attempt_ts
    now = time.time()
    if now - _last_ensure_attempt_ts < _ensure_cooldown_seconds:
        return
    _last_ensure_attempt_ts = now

    from db.base import SessionLocal
    
    async with SessionLocal() as db:
        try:
            await db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS query_audit_log (
                        id UUID PRIMARY KEY,
                        timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        connection_id UUID NOT NULL,
                        user_id VARCHAR(255),
                        space_id UUID,
                        crew_ids TEXT[],
                        thread_id VARCHAR(255),
                        question TEXT NOT NULL,
                        sql_generated TEXT,
                        sql_executed TEXT,
                        sql_validated BOOLEAN,
                        validation_error TEXT,
                        num_rows INTEGER,
                        execution_time_ms INTEGER,
                        has_error BOOLEAN,
                        error_message TEXT,
                        was_rate_limited BOOLEAN DEFAULT FALSE,
                        prompt_injection_detected BOOLEAN DEFAULT FALSE,
                        prompt_injection_pattern TEXT,
                        progressive_escalation_score INTEGER DEFAULT 0,
                        progressive_escalation_detected BOOLEAN DEFAULT FALSE,
                        detected_language VARCHAR(10),
                        chosen_tables TEXT[],
                        answer_preview TEXT,
                        pii_detected_in_prompt BOOLEAN DEFAULT FALSE,
                        pii_detected_in_response BOOLEAN DEFAULT FALSE,
                        pii_types TEXT[],
                        pii_severity VARCHAR(10),
                        pii_patterns_matched TEXT[],
                        pii_blocked BOOLEAN DEFAULT FALSE
                    );
                    """
                )
            )
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON query_audit_log(timestamp);"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_user ON query_audit_log(user_id);"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_connection ON query_audit_log(connection_id);"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_space ON query_audit_log(space_id);"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_thread ON query_audit_log(thread_id);"))
            await db.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_audit_prompt_injection ON query_audit_log(prompt_injection_detected) WHERE prompt_injection_detected = TRUE;"
                )
            )
            await db.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_audit_escalation ON query_audit_log(progressive_escalation_detected) WHERE progressive_escalation_detected = TRUE;"
                )
            )
            await db.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_audit_pii_blocked ON query_audit_log(pii_blocked) WHERE pii_blocked = TRUE;"
                )
            )
            await db.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_audit_pii_detected ON query_audit_log(pii_detected_in_prompt, pii_detected_in_response) WHERE pii_detected_in_prompt = TRUE OR pii_detected_in_response = TRUE;"
                )
            )
            await db.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_audit_pii_detected ON query_audit_log(pii_detected_in_prompt, pii_detected_in_response) WHERE pii_detected_in_prompt = TRUE OR pii_detected_in_response = TRUE;"
                )
            )
            
            # --- Tabela security_alerts ---
            await db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS security_alerts (
                        id UUID PRIMARY KEY,
                        timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        user_id VARCHAR(255),
                        connection_id UUID,
                        alert_type VARCHAR(50),
                        severity VARCHAR(20),
                        details JSONB
                    );
                    """
                )
            )
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_alerts_user ON security_alerts(user_id);"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_alerts_type ON security_alerts(alert_type);"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_alerts_severity ON security_alerts(severity);"))
            
            await db.commit()
        except Exception:
            await db.rollback()


async def _flush_audit_buffer_async():
    """Flush do buffer para PostgreSQL (async)"""
    global _audit_disabled_until_ts

    # Backoff quando DB está indisponível / tabela ainda não existe.
    if time.time() < _audit_disabled_until_ts:
        return

    if not _audit_buffer:
        return
    
    # Pegar até batch_size logs
    batch = []
    for _ in range(min(_flush_batch_size, len(_audit_buffer))):
        if _audit_buffer:
            batch.append(_audit_buffer.popleft())
    
    if not batch:
        return
    
    # Inserir no banco
    try:
        from db.base import SessionLocal
        
        async with SessionLocal() as db:
            try:
                # Garantir tabela existe (best-effort). Se migration já foi aplicada, é NO-OP.
                await _ensure_audit_table_async()

                # Separa logs de auditoria normal de logs de alerta
                audit_batch = [e for e in batch if e.get("_type") != "alert"]
                alert_batch = [e for e in batch if e.get("_type") == "alert"]

                # 1. Inserir AUDIT LOGS
                if audit_batch:
                    insert_sql = text(
                    """
                    INSERT INTO query_audit_log (
                        id, connection_id, user_id, space_id, crew_ids, thread_id,
                        question, sql_generated, sql_executed, sql_validated, validation_error,
                        num_rows, execution_time_ms, has_error, error_message,
                        was_rate_limited, prompt_injection_detected, prompt_injection_pattern,
                        progressive_escalation_score, progressive_escalation_detected,
                        detected_language, chosen_tables, answer_preview,
                        pii_detected_in_prompt, pii_detected_in_response, pii_types,
                        pii_severity, pii_patterns_matched, pii_blocked
                    ) VALUES (
                        CAST(:id AS uuid),
                        CAST(:connection_id AS uuid),
                        :user_id,
                        CAST(:space_id AS uuid),
                        :crew_ids,
                        :thread_id,
                        :question,
                        :sql_generated,
                        :sql_executed,
                        :sql_validated,
                        :validation_error,
                        :num_rows,
                        :execution_time_ms,
                        :has_error,
                        :error_message,
                        :was_rate_limited,
                        :prompt_injection_detected,
                        :prompt_injection_pattern,
                        :progressive_escalation_score,
                        :progressive_escalation_detected,
                        :detected_language,
                        :chosen_tables,
                        :answer_preview,
                        :pii_detected_in_prompt,
                        :pii_detected_in_response,
                        :pii_types,
                        :pii_severity,
                        :pii_patterns_matched,
                        :pii_blocked
                    )
                    """
                )



                if audit_batch:
                    for entry in audit_batch:
                        params = {
                            "id": entry.get("id"),
                            "connection_id": entry.get("connection_id"),
                            "user_id": entry.get("user_id"),
                            "space_id": entry.get("space_id"),
                            "crew_ids": entry.get("crew_ids") or [],
                            "thread_id": entry.get("thread_id"),
                            "question": entry.get("question"),
                            "sql_generated": entry.get("sql_generated"),
                            "sql_executed": entry.get("sql_executed"),
                            "sql_validated": entry.get("sql_validated"),
                            "validation_error": entry.get("validation_error"),
                            "num_rows": entry.get("num_rows"),
                            "execution_time_ms": entry.get("execution_time_ms"),
                            "has_error": entry.get("has_error"),
                            "error_message": entry.get("error_message"),
                            "was_rate_limited": bool(entry.get("was_rate_limited", False)),
                            "prompt_injection_detected": bool(entry.get("prompt_injection_detected", False)),
                            "prompt_injection_pattern": entry.get("prompt_injection_pattern"),
                            "progressive_escalation_score": int(entry.get("progressive_escalation_score", 0) or 0),
                            "progressive_escalation_detected": bool(entry.get("progressive_escalation_detected", False)),
                            "detected_language": entry.get("detected_language"),
                            "chosen_tables": entry.get("chosen_tables") or [],
                            "answer_preview": entry.get("answer_preview"),
                            # Campos PII
                            "pii_detected_in_prompt": bool(entry.get("pii_detected_in_prompt", False)),
                            "pii_detected_in_response": bool(entry.get("pii_detected_in_response", False)),
                            "pii_types": entry.get("pii_types") or [],
                            "pii_severity": entry.get("pii_severity"),
                            "pii_patterns_matched": entry.get("pii_patterns_matched") or [],
                            "pii_blocked": bool(entry.get("pii_blocked", False)),
                        }
                        await db.execute(insert_sql, params)
                
                # 2. Inserir SECURITY ALERTS
                if alert_batch:
                    insert_alert_sql = text(
                        """
                        INSERT INTO security_alerts (
                            id, user_id, connection_id, 
                            alert_type, severity, details
                        ) VALUES (
                            CAST(:id AS uuid),
                            :user_id,
                            CAST(:connection_id AS uuid),
                            :alert_type,
                            :severity,
                            :details
                        )
                        """
                    )
                    
                    import json
                    for entry in alert_batch:
                        params = {
                            "id": entry.get("id"),
                            "user_id": entry.get("user_id"),
                            "connection_id": entry.get("connection_id"),
                            "alert_type": entry.get("alert_type"),
                            "severity": entry.get("severity"),
                            "details": json.dumps(entry.get("details")) if entry.get("details") else None
                        }
                        await db.execute(insert_alert_sql, params)
                
                await db.commit()
            except Exception as e:
                await db.rollback()
                # Log erro mas não quebrar aplicação
                import logging
                logger = logging.getLogger("dataassistant")
                logger.error(f"Error flushing audit log: {e}")
                # Evitar spam: backoff por 60s em caso de falha
                _audit_disabled_until_ts = time.time() + 60.0
    except Exception as e:
        import logging
        logger = logging.getLogger("dataassistant")
        logger.error(f"Error in audit flush: {e}")
        _audit_disabled_until_ts = time.time() + 60.0


async def _flusher_loop_async():
    """Loop de flush periódico (async)"""
    while _flusher_running:
        await asyncio.sleep(_flush_interval)
        if _flusher_running:
            await _flush_audit_buffer_async()


def start_audit_flusher():
    """Inicia loop de flush periódico (chamar no startup da aplicação)"""
    global _flusher_running, _flusher_task
    
    if _flusher_running:
        return  # Já está rodando
    
    _flusher_running = True
    
    # Criar task async no event loop atual
    try:
        loop = asyncio.get_running_loop()
        _flusher_task = loop.create_task(_flusher_loop_async())
    except RuntimeError:
        # Não há event loop rodando, usar threading como fallback
        import logging
        logger = logging.getLogger("dataassistant")
        logger.warning("No running event loop for audit flusher, using threading fallback")
        
        def _sync_flusher_loop():
            while _flusher_running:
                time.sleep(_flush_interval)
                if _flusher_running:
                    # Executar async flush em novo loop
                    try:
                        asyncio.run(_flush_audit_buffer_async())
                    except Exception as e:
                        logger.error(f"Error in sync audit flush: {e}")
        
        thread = threading.Thread(target=_sync_flusher_loop, daemon=True)
        thread.start()


def stop_audit_flusher():
    """Para o flush (chamar no shutdown)"""
    global _flusher_running, _flusher_task
    _flusher_running = False
    
    # Cancelar task se existir
    if _flusher_task and not _flusher_task.done():
        _flusher_task.cancel()
    
    # Flush final (síncrono)
    try:
        asyncio.run(_flush_audit_buffer_async())
    except Exception:
        pass
