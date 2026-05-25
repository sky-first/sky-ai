# core/security/progressive_escalation.py
"""
Detecção de progressive escalation (tentativas incrementais de descobrir schema).
Usa Redis para rastrear histórico de perguntas por sessão.
"""

from __future__ import annotations

from typing import Tuple, Optional, Dict, List
from config.settings import settings
import time

# Padrões que indicam "exploração de schema"
SCHEMA_EXPLORATION_KEYWORDS = [
    "quais tabelas",
    "what tables",
    "list tables",
    "quais colunas",
    "what columns",
    "list columns",
    "estrutura",
    "structure",
    "schema",
    "metadados",
    "metadata",
    "describe",
    "show tables",
    "show columns",
    "quais campos",
    "what fields",
    "tipos de dados",
    "data types",
    "relacionamentos",
    "relationships",
]

try:
    from core.redis_utils import make_redis_client

    redis_client = make_redis_client(
        settings.celery_broker_url,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    REDIS_AVAILABLE = True
except Exception:
    REDIS_AVAILABLE = False
    redis_client = None

# In-memory fallback (works in single-process deployments and for local testing)
_MEMORY_EVENTS: Dict[str, List[float]] = {}


def detect_progressive_escalation(
    user_id: str,
    thread_id: str,
    question: str,
    window_minutes: int = 5,
    max_schema_questions: int = 5,
) -> Tuple[bool, int, Optional[str]]:
    """
    Detecta progressive escalation.
    Retorna (is_suspicious, score, reason)

    Args:
        user_id: ID do usuário
        thread_id: ID da thread/sessão
        question: Pergunta atual
        window_minutes: Janela de tempo para análise (padrão: 5 minutos)
        max_schema_questions: Máximo de perguntas sobre schema antes de alertar

    Returns:
        (is_suspicious, score, reason)
        - is_suspicious: True se detectado progressive escalation
        - score: Score de 0-100 (quanto maior, mais suspeito)
        - reason: Motivo da detecção (ou None)
    """
    question_lower = (question or "").lower()

    # Verificar se pergunta é sobre schema
    is_schema_question = any(
        keyword in question_lower for keyword in SCHEMA_EXPLORATION_KEYWORDS
    )

    if not is_schema_question:
        # Não é sobre schema, não é suspeito
        return False, 0, None

    key = f"escalation:{user_id or 'anonymous'}:{thread_id or 'default'}"

    # Prefer Redis if available; otherwise use in-memory fallback.
    if REDIS_AVAILABLE and redis_client is not None:
        try:
            # Adicionar pergunta ao histórico (com timestamp)
            from datetime import datetime

            now = datetime.now()
            entry = f"{now.isoformat()}:{(question or '')[:200]}"
            redis_client.lpush(key, entry)
            redis_client.expire(key, window_minutes * 60)  # TTL

            # Contar perguntas sobre schema na janela
            history = redis_client.lrange(key, 0, max_schema_questions * 2)

            schema_count = 0
            for entry in history:
                entry_lower = entry.lower()
                if any(kw in entry_lower for kw in SCHEMA_EXPLORATION_KEYWORDS):
                    schema_count += 1

            score = min(100, int((schema_count / max_schema_questions) * 100))
            if schema_count >= max_schema_questions:
                return (
                    True,
                    score,
                    f"Multiple schema exploration questions ({schema_count} in {window_minutes} minutes)",
                )
            return False, score, None
        except Exception as e:
            # If Redis fails, fallback to memory (fail-safe for local tests)
            import logging

            logger = logging.getLogger("dataassistant")
            logger.warning(f"Progressive escalation detection failed (redis): {e}")

    # In-memory fallback
    now_ts = time.time()
    window_seconds = window_minutes * 60
    events = _MEMORY_EVENTS.get(key, [])
    # keep only within window
    events = [t for t in events if (now_ts - t) <= window_seconds]
    events.insert(0, now_ts)
    _MEMORY_EVENTS[key] = events[: max_schema_questions * 4]

    schema_count = len(events)
    score = min(100, int((schema_count / max_schema_questions) * 100))
    if schema_count >= max_schema_questions:
        return (
            True,
            score,
            f"Multiple schema exploration questions ({schema_count} in {window_minutes} minutes)",
        )
    return False, score, None


def get_escalation_score(user_id: str, thread_id: str, window_minutes: int = 5) -> int:
    """
    Obtém score atual de progressive escalation sem adicionar nova pergunta.
    Útil para verificar score antes de processar.
    """
    if not REDIS_AVAILABLE:
        return 0

    try:
        key = f"escalation:{user_id or 'anonymous'}:{thread_id or 'default'}"
        history = redis_client.lrange(key, 0, 20)  # Últimas 20 perguntas

        schema_count = sum(
            1
            for entry in history
            if any(kw in entry.lower() for kw in SCHEMA_EXPLORATION_KEYWORDS)
        )

        return min(100, int((schema_count / 5) * 100))
    except Exception:
        return 0
