# core/rag/embedding_cache.py
"""
Cache Redis para embeddings de texto.

Estratégia:
  - Chave: emb_cache:{sha256(texto_normalizado)}
  - TTL: 24h (embeddings são determinísticos, não expiram rapidamente)
  - Serialização: JSON (lista de floats)
  - Fallback: se Redis indisponível, opera sem cache (sem quebrar o sistema)

Padrão seguido: core/security/rate_limiter_redis.py
"""

from __future__ import annotations

import hashlib
import json
from typing import List, Optional

from config.settings import settings
from core.logging_utils import log_event

# TTL padrão: 24 horas (embeddings são determinísticos)
EMBEDDING_CACHE_TTL_SECONDS = 86_400

# Prefixo das chaves no Redis
CACHE_KEY_PREFIX = "emb_cache"

# ── Inicialização do cliente Redis ────────────────────────────────────────────

try:
    from core.redis_utils import make_redis_client

    _redis_client = make_redis_client(
        settings.celery_broker_url,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    REDIS_AVAILABLE = True
    log_event(
        "embedding_cache_redis_connected", {"url": settings.celery_broker_url[:30]}
    )
except Exception as _e:
    REDIS_AVAILABLE = False
    _redis_client = None
    log_event("embedding_cache_redis_unavailable", {"reason": str(_e)[:200]})


# ── Estatísticas em memória ───────────────────────────────────────────────────

_stats = {"hits": 0, "misses": 0, "errors": 0}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_key(text: str) -> str:
    """Gera chave Redis a partir do texto normalizado."""
    normalized = text.strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{CACHE_KEY_PREFIX}:{digest}"


def _serialize(vector: List[float]) -> str:
    return json.dumps(vector)


def _deserialize(raw: str) -> List[float]:
    return json.loads(raw)


# ── API pública ───────────────────────────────────────────────────────────────


def get_cached_embedding(text: str) -> Optional[List[float]]:
    """
    Busca embedding no cache Redis.

    Returns:
        Lista de floats se encontrado, None caso contrário.
    """
    if not REDIS_AVAILABLE or not _redis_client:
        return None

    key = _make_key(text)
    try:
        raw = _redis_client.get(key)
        if raw is None:
            _stats["misses"] += 1
            return None

        vector = _deserialize(raw)
        _stats["hits"] += 1
        log_event(
            "embedding_cache_hit",
            {
                "key_prefix": key[:20],
                "hit_rate_pct": _hit_rate(),
            },
        )
        return vector

    except Exception as e:
        _stats["errors"] += 1
        log_event("embedding_cache_get_error", {"error": str(e)[:200]})
        return None


def set_cached_embedding(
    text: str,
    vector: List[float],
    ttl: int = EMBEDDING_CACHE_TTL_SECONDS,
) -> bool:
    """
    Armazena embedding no cache Redis.

    Returns:
        True se armazenado com sucesso, False caso contrário.
    """
    if not REDIS_AVAILABLE or not _redis_client:
        return False

    key = _make_key(text)
    try:
        _redis_client.setex(key, ttl, _serialize(vector))
        log_event(
            "embedding_cache_set",
            {
                "key_prefix": key[:20],
                "ttl_seconds": ttl,
                "dims": len(vector),
            },
        )
        return True

    except Exception as e:
        _stats["errors"] += 1
        log_event("embedding_cache_set_error", {"error": str(e)[:200]})
        return False


def get_cache_stats() -> dict:
    """Retorna estatísticas do cache de embeddings."""
    total = _stats["hits"] + _stats["misses"]
    return {
        "redis_available": REDIS_AVAILABLE,
        "hits": _stats["hits"],
        "misses": _stats["misses"],
        "errors": _stats["errors"],
        "hit_rate_pct": round(_hit_rate(), 2),
        "total_requests": total,
    }


def _hit_rate() -> float:
    total = _stats["hits"] + _stats["misses"]
    if total == 0:
        return 0.0
    return (_stats["hits"] / total) * 100
