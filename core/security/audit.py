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
import logging
import json
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
_ensure_cooldown_seconds: float = 30.0
_failure_backoff_seconds: float = 60.0

#: Destination key for rows that belong to the platform DB (default
#: context / single-tenant mode / tenants without a dedicated DB).
_PLATFORM_TARGET = "__platform__"

# Per-destination state. Used to be two globals, which meant one tenant
# whose DB was down stopped the audit trail of every other tenant (and of
# the platform) for 60 s at a time.
_last_ensure_attempt: Dict[str, float] = {}
_backoff_until: Dict[str, float] = {}

logger = logging.getLogger("dataassistant")


# ── Tenant routing ────────────────────────────────────────────────────
#
# The audit rows carry the customer's question, the SQL we generated and
# ran against their data and the prompt text. In Model B those belong in
# the tenant's own database — measured in production on 10/10/2026 they
# were all landing in the shared platform DB (``skyaisaas``): ~1.900
# ``query_audit_log`` and ~8.300 ``prompt_security_audit`` rows in 7 days,
# while every tenant DB had 0.
#
# The flush runs in a background task created at startup (or a thread),
# whose contextvars are the startup ones — ``current_tenant()`` there is
# always the default context. So the tenant has to be captured when the
# row is *enqueued*, inside the request, and travel with the entry.


def _capture_tenant():
    """The request's tenant context, or None if it cannot be read.

    Never raises: auditing must not break a query.
    """
    try:
        from core.tenant_context import current_tenant

        return current_tenant()
    except Exception:  # noqa: BLE001
        return None


def _routes_to_tenant(ctx) -> bool:
    """True when ``ctx`` has a dedicated DB the rows must go to.

    Same rule as ``TenantConnectionManager._maybe_pool``: the default
    context, or a tenant without ``db_host``/``db_name``, uses the
    platform DB.
    """
    return bool(
        ctx is not None
        and not getattr(ctx, "is_default", True)
        and getattr(ctx, "db_name", "")
        and getattr(ctx, "db_host", "")
    )


def _target_key(ctx) -> str:
    return ctx.slug if _routes_to_tenant(ctx) else _PLATFORM_TARGET


def _open_session(ctx):
    """Async session for the destination of ``ctx``, or None.

    For a tenant this is **strict**: if the tenant engine cannot be built
    we get None and the rows wait — they are never written to the
    platform DB instead, which would be the very leak this fixes.
    """
    if _routes_to_tenant(ctx):
        from core.tenant_db import tenant_connection_manager

        return tenant_connection_manager.async_session_or_none(ctx)
    from db.base import SessionLocal

    return SessionLocal()


def _enqueue(entry: Dict[str, Any]) -> None:
    entry["_tenant"] = _capture_tenant()
    _audit_buffer.append(entry)


def log_query_audit(
    connection_id: str,
    user_id: Optional[str],
    space_id: Optional[str],
    crew_ids: Optional[List[str]],
    thread_id: Optional[str],
    question: str,
    platform_role: Optional[str] = None,
    crew_role: Optional[str] = None,
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
        "platform_role": platform_role,
        "crew_role": crew_role,
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

    _enqueue(log_entry)


def log_security_alert(
    connection_id: str,
    user_id: Optional[str],
    alert_type: str,  # 'PII_PROMPT', 'PROMPT_INJECTION', etc
    severity: str,  # 'BLOCK', 'CRITICAL', 'HIGH'
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
        "details": details,
    }
    _enqueue(log_entry)


def log_prompt_security_audit(
    connection_id: str,
    user_id: Optional[str],
    prompt_text_redacted: str,
    security_status: str,  # 'ALLOWED', 'BLOCKED', 'FLAGGED'
    blocked_by: Optional[str],
    risk_score: float,
    scan_details: Dict[str, Any],
):
    """
    Registra uma auditoria detalhada de segurança de prompt.
    """
    log_entry = {
        "_type": "prompt_audit",
        "id": str(uuid4()),
        "timestamp": datetime.now().isoformat(),
        "connection_id": connection_id,
        "user_id": user_id,
        "prompt_text_redacted": prompt_text_redacted,
        "security_status": security_status,
        "blocked_by": blocked_by,
        "risk_score": risk_score,
        "scan_details": scan_details,
    }
    _enqueue(log_entry)


async def _ensure_audit_table_async(db, target: str = _PLATFORM_TARGET) -> None:
    """
    Best-effort: cria a tabela/indexes se ainda não existirem.
    Evita falhas em ambientes onde a migration ainda não foi aplicada.

    Corre na sessão do destino (``db``) — a base da plataforma ou a base
    do cliente. Nas bases de cliente o ``001_create_query_audit_log.sql``
    cria a tabela sem as colunas de papel/PII e ``prompt_security_audit``
    nem existia; é este passo (e o ``007_audit_na_base_do_cliente.sql``)
    que as põe lá. Cooldown por destino.
    """
    now = time.time()
    if now - _last_ensure_attempt.get(target, 0.0) < _ensure_cooldown_seconds:
        return
    _last_ensure_attempt[target] = now

    try:
        await db.execute(text("""
                CREATE TABLE IF NOT EXISTS query_audit_log (
                    id UUID PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    connection_id UUID NOT NULL,
                    user_id VARCHAR(255),
                    space_id UUID,
                    crew_ids TEXT[],
                    thread_id VARCHAR(255),
                    platform_role VARCHAR(50),
                    crew_role VARCHAR(50),
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
                """))
        # ── Columns added after the table first shipped ──────────
        # ``CREATE TABLE IF NOT EXISTS`` is a no-op once the table
        # exists, so every column appended to the DDL above never
        # reached an environment created before it. Production hit
        # exactly that: the table predates ``platform_role``,
        # ``crew_role`` and the whole PII block, so each flush died
        # with
        #     column "platform_role" of relation "query_audit_log"
        #     does not exist
        # and the audit rows were silently dropped — including the
        # PII-detection evidence, which is the part we actually need
        # for compliance.
        #
        # ``ADD COLUMN IF NOT EXISTS`` is idempotent and cheap (a
        # catalogue lookup when the column is already there), so it
        # is safe to run on the same cooldown as the CREATE and
        # self-heals whatever an environment happens to be missing.
        # Keep this list in lockstep with the DDL above.
        await db.execute(text("""
                ALTER TABLE query_audit_log
                    ADD COLUMN IF NOT EXISTS platform_role VARCHAR(50),
                    ADD COLUMN IF NOT EXISTS crew_role VARCHAR(50),
                    ADD COLUMN IF NOT EXISTS pii_detected_in_prompt BOOLEAN DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS pii_detected_in_response BOOLEAN DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS pii_types TEXT[],
                    ADD COLUMN IF NOT EXISTS pii_severity VARCHAR(10),
                    ADD COLUMN IF NOT EXISTS pii_patterns_matched TEXT[],
                    ADD COLUMN IF NOT EXISTS pii_blocked BOOLEAN DEFAULT FALSE;
                """))
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON query_audit_log(timestamp);"
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_audit_user ON query_audit_log(user_id);"
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_audit_connection ON query_audit_log(connection_id);"
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_audit_space ON query_audit_log(space_id);"
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_audit_thread ON query_audit_log(thread_id);"
            )
        )
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
        # PII indexes and role/PII columns are managed by Alembic migration 004.
        await db.commit()

        # --- Tabela security_alerts ---
        await db.execute(text("""
                CREATE TABLE IF NOT EXISTS security_alerts (
                    id UUID PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    user_id VARCHAR(255),
                    connection_id UUID,
                    alert_type VARCHAR(50),
                    severity VARCHAR(20),
                    details JSONB
                );
                """))
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_alerts_user ON security_alerts(user_id);"
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_alerts_type ON security_alerts(alert_type);"
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_alerts_severity ON security_alerts(severity);"
            )
        )

        # --- Tabela prompt_security_audit ---
        await db.execute(text("""
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
                """))
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_prompt_audit_timestamp ON prompt_security_audit(timestamp);"
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_prompt_audit_user ON prompt_security_audit(user_id);"
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_prompt_audit_connection ON prompt_security_audit(connection_id);"
            )
        )
        await db.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_prompt_audit_status ON prompt_security_audit(security_status);"
            )
        )

        await db.commit()
    except Exception:
        await db.rollback()


async def _insert_entries(db, batch: List[Dict[str, Any]]) -> None:
    """INSERT de um lote já agrupado por destino, na sessão ``db``."""
    # Separa logs por tipo
    audit_batch = [e for e in batch if e.get("_type") not in ("alert", "prompt_audit")]
    alert_batch = [e for e in batch if e.get("_type") == "alert"]
    prompt_audit_batch = [e for e in batch if e.get("_type") == "prompt_audit"]

    if not audit_batch and not alert_batch and not prompt_audit_batch:
        return

    # 1. Inserir AUDIT LOGS
    if audit_batch:
        insert_sql = text("""
        INSERT INTO query_audit_log (
            id, connection_id, user_id, space_id, crew_ids, thread_id,
            platform_role, crew_role,
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
            :platform_role,
            :crew_role,
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
        """)

    if audit_batch:
        for entry in audit_batch:
            params = {
                "id": entry.get("id"),
                "connection_id": entry.get("connection_id"),
                "user_id": entry.get("user_id"),
                "space_id": entry.get("space_id"),
                "crew_ids": entry.get("crew_ids") or [],
                "thread_id": entry.get("thread_id"),
                "platform_role": entry.get("platform_role"),
                "crew_role": entry.get("crew_role"),
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
                "prompt_injection_detected": bool(
                    entry.get("prompt_injection_detected", False)
                ),
                "prompt_injection_pattern": entry.get("prompt_injection_pattern"),
                "progressive_escalation_score": int(
                    entry.get("progressive_escalation_score", 0) or 0
                ),
                "progressive_escalation_detected": bool(
                    entry.get("progressive_escalation_detected", False)
                ),
                "detected_language": entry.get("detected_language"),
                "chosen_tables": entry.get("chosen_tables") or [],
                "answer_preview": entry.get("answer_preview"),
                # Campos PII
                "pii_detected_in_prompt": bool(
                    entry.get("pii_detected_in_prompt", False)
                ),
                "pii_detected_in_response": bool(
                    entry.get("pii_detected_in_response", False)
                ),
                "pii_types": entry.get("pii_types") or [],
                "pii_severity": entry.get("pii_severity"),
                "pii_patterns_matched": entry.get("pii_patterns_matched") or [],
                "pii_blocked": bool(entry.get("pii_blocked", False)),
            }
            await db.execute(insert_sql, params)

    # 2. Inserir SECURITY ALERTS
    if alert_batch:
        insert_alert_sql = text("""
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
            """)

        for entry in alert_batch:
            params = {
                "id": entry.get("id"),
                "user_id": entry.get("user_id"),
                "connection_id": entry.get("connection_id"),
                "alert_type": entry.get("alert_type"),
                "severity": entry.get("severity"),
                "details": (
                    json.dumps(entry.get("details")) if entry.get("details") else None
                ),
            }
            await db.execute(insert_alert_sql, params)

    # 3. Inserir PROMPT AUDITS
    if prompt_audit_batch:
        insert_prompt_sql = text("""
            INSERT INTO prompt_security_audit (
                id, user_id, connection_id, 
                prompt_text_redacted, security_status, blocked_by, 
                risk_score, scan_details
            ) VALUES (
                CAST(:id AS uuid),
                :user_id,
                CAST(:connection_id AS uuid),
                :prompt_text_redacted,
                :security_status,
                :blocked_by,
                :risk_score,
                :scan_details
            )
            """)

        for entry in prompt_audit_batch:
            params = {
                "id": entry.get("id"),
                "user_id": entry.get("user_id"),
                "connection_id": entry.get("connection_id"),
                "prompt_text_redacted": entry.get("prompt_text_redacted"),
                "security_status": entry.get("security_status"),
                "blocked_by": entry.get("blocked_by"),
                "risk_score": entry.get("risk_score"),
                "scan_details": (
                    json.dumps(entry.get("scan_details"))
                    if entry.get("scan_details")
                    else None
                ),
            }
            await db.execute(insert_prompt_sql, params)


async def _flush_target(target: str, ctx, entries: List[Dict[str, Any]]) -> None:
    """Grava ``entries`` na base de ``target`` (plataforma ou cliente).

    Levanta em caso de falha; quem chama isola a falha a este destino.
    """
    session = _open_session(ctx)
    if session is None:
        # Base do cliente indisponível (segredo, rede…). As linhas voltam
        # à fila — NUNCA vão para a base da plataforma em vez disso.
        for entry in entries:
            _audit_buffer.append(entry)
        raise RuntimeError(f"tenant DB unavailable for audit target {target!r}")

    async with session as db:
        try:
            # Garantir tabelas/colunas no destino (best-effort, com cooldown).
            await _ensure_audit_table_async(db, target)
            await _insert_entries(db, entries)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def _flush_audit_buffer_async():
    """Flush do buffer para PostgreSQL (async).

    Cada entrada vai para a base do cliente capturado no momento em que foi
    registada (``_tenant``); sem cliente, para a base da plataforma. Uma
    falha num destino não trava os outros, e nunca chega a quem pergunta.
    """
    try:
        if not _audit_buffer:
            return

        batch = []
        for _ in range(min(_flush_batch_size, len(_audit_buffer))):
            if _audit_buffer:
                batch.append(_audit_buffer.popleft())
        if not batch:
            return

        now = time.time()
        groups: Dict[str, Any] = {}
        deferred: List[Dict[str, Any]] = []
        for entry in batch:
            ctx = entry.get("_tenant")
            target = _target_key(ctx)
            # Backoff por destino: um cliente em baixo não pára os outros.
            if _backoff_until.get(target, 0.0) > now:
                deferred.append(entry)
                continue
            groups.setdefault(target, (ctx, []))[1].append(entry)

        # Voltam ao fim da fila, para não taparem os destinos saudáveis.
        for entry in deferred:
            _audit_buffer.append(entry)

        for target, (ctx, entries) in groups.items():
            try:
                await _flush_target(target, ctx, entries)
            except Exception as e:  # noqa: BLE001 — auditoria nunca parte nada
                logger.error(
                    "Error flushing audit log",
                    extra={
                        "audit_target": target,
                        "rows": len(entries),
                        "error": str(e)[:300],
                    },
                )
                # Evitar spam: backoff por 60s, só para este destino.
                _backoff_until[target] = time.time() + _failure_backoff_seconds
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error in audit flush: {e}")


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
        logger.warning(
            "No running event loop for audit flusher, using threading fallback"
        )

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
    global _flusher_running
    _flusher_running = False

    # Cancelar task se existir
    if _flusher_task and not _flusher_task.done():
        _flusher_task.cancel()

    # Flush final (síncrono)
    try:
        asyncio.run(_flush_audit_buffer_async())
    except Exception:
        pass
