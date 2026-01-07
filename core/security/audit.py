# core/security/audit.py
"""
Sistema de auditoria assíncrono para queries.
Não bloqueia requests - usa buffer em memória + flush periódico.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Any, Optional, List
from collections import deque
import threading
from uuid import uuid4
import time

from sqlalchemy.orm import Session
from sqlalchemy import text
from db.base import SessionLocal

# Buffer em memória (thread-safe com deque)
_audit_buffer: deque = deque(maxlen=1000)  # Máximo 1000 logs em buffer
_flush_interval = 5.0  # Flush a cada 5 segundos
_flush_batch_size = 50  # Flush em lotes de 50
_flusher_running = False
_flusher_thread: Optional[threading.Thread] = None
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
    }
    
    _audit_buffer.append(log_entry)


def _ensure_audit_table(db: Session) -> None:
    """
    Best-effort: cria a tabela/indexes se ainda não existirem.
    Evita falhas em ambientes onde a migration ainda não foi aplicada.
    """
    global _last_ensure_attempt_ts
    now = time.time()
    if now - _last_ensure_attempt_ts < _ensure_cooldown_seconds:
        return
    _last_ensure_attempt_ts = now

    db.execute(
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
                answer_preview TEXT
            );
            """
        )
    )
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON query_audit_log(timestamp);"))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_user ON query_audit_log(user_id);"))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_connection ON query_audit_log(connection_id);"))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_space ON query_audit_log(space_id);"))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_thread ON query_audit_log(thread_id);"))
    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_audit_prompt_injection ON query_audit_log(prompt_injection_detected) WHERE prompt_injection_detected = TRUE;"
        )
    )
    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_audit_escalation ON query_audit_log(progressive_escalation_detected) WHERE progressive_escalation_detected = TRUE;"
        )
    )
    db.commit()


def _flush_audit_buffer():
    """Flush do buffer para PostgreSQL (síncrono, roda em thread separada)"""
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
        db = SessionLocal()
        try:
            # Garantir tabela existe (best-effort). Se migration já foi aplicada, é NO-OP.
            _ensure_audit_table(db)

            insert_sql = text(
                """
                INSERT INTO query_audit_log (
                    id, connection_id, user_id, space_id, crew_ids, thread_id,
                    question, sql_generated, sql_executed, sql_validated, validation_error,
                    num_rows, execution_time_ms, has_error, error_message,
                    was_rate_limited, prompt_injection_detected, prompt_injection_pattern,
                    progressive_escalation_score, progressive_escalation_detected,
                    detected_language, chosen_tables, answer_preview
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
                    :answer_preview
                )
                """
            )

            params_batch: List[Dict[str, Any]] = []
            for entry in batch:
                params_batch.append(
                    {
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
                    }
                )

            db.execute(insert_sql, params_batch)
            db.commit()
        except Exception as e:
            db.rollback()
            # Log erro mas não quebrar aplicação
            import logging
            logger = logging.getLogger("dataassistant")
            logger.error(f"Error flushing audit log: {e}")
            # Evitar spam: backoff por 60s em caso de falha
            _audit_disabled_until_ts = time.time() + 60.0
        finally:
            db.close()
    except Exception as e:
        import logging
        logger = logging.getLogger("dataassistant")
        logger.error(f"Error in audit flush: {e}")
        _audit_disabled_until_ts = time.time() + 60.0


def _flusher_loop():
    """Loop de flush periódico (roda em thread separada)"""
    while _flusher_running:
        time.sleep(_flush_interval)
        if _flusher_running:
            _flush_audit_buffer()


def start_audit_flusher():
    """Inicia loop de flush periódico (chamar no startup da aplicação)"""
    global _flusher_running, _flusher_thread
    
    if _flusher_running:
        return  # Já está rodando
    
    _flusher_running = True
    _flusher_thread = threading.Thread(target=_flusher_loop, daemon=True)
    _flusher_thread.start()


def stop_audit_flusher():
    """Para o flush (chamar no shutdown)"""
    global _flusher_running
    _flusher_running = False
    # Flush final
    _flush_audit_buffer()

