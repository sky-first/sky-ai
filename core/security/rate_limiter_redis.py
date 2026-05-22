# core/security/rate_limiter_redis.py
"""
Rate limiter distribuído usando Redis.
Fallback para memória se Redis não disponível.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Tuple, Optional
from config.settings import settings


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


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
    # Fallback para rate limiter em memória
    from core.security.rate_limiter import SimpleRateLimiter

    _fallback_limiter = SimpleRateLimiter()


class DistributedRateLimiter:
    """Rate limiter usando Redis com fallback para memória"""

    def __init__(
        self,
        max_queries_per_minute: int = 30,
        max_queries_per_hour: int = 200,
        max_validate_per_minute: int = 50,
    ):
        self.max_queries_per_minute = max_queries_per_minute
        self.max_queries_per_hour = max_queries_per_hour
        self.max_validate_per_minute = max_validate_per_minute

    def check_rate_limit(
        self, user_id: str, request_type: str = "query"
    ) -> Tuple[bool, Optional[str]]:
        """Verifica rate limit usando Redis ou fallback"""
        if not REDIS_AVAILABLE:
            return _fallback_limiter.check_rate_limit(user_id, request_type)

        key = user_id or "anonymous"

        # Limites
        max_per_minute = (
            self.max_validate_per_minute
            if request_type == "validate"
            else self.max_queries_per_minute
        )

        # Chaves Redis
        key_minute = f"rate_limit:{key}:{request_type}:minute"
        key_hour = f"rate_limit:{key}:{request_type}:hour"

        try:
            # Pipeline para operações atômicas
            pipe = redis_client.pipeline()

            # Incrementar contadores
            pipe.incr(key_minute)
            pipe.expire(key_minute, 60)  # TTL de 60 segundos
            pipe.incr(key_hour)
            pipe.expire(key_hour, 3600)  # TTL de 1 hora

            # Obter valores atuais
            pipe.get(key_minute)
            pipe.get(key_hour)

            results = pipe.execute()

            # results[0] = incr minute, results[1] = expire minute
            # results[2] = incr hour, results[3] = expire hour
            # results[4] = get minute, results[5] = get hour
            count_minute = int(results[4] or 0)
            count_hour = int(results[5] or 0)

            # Verificar limites
            if count_minute > max_per_minute:
                return (
                    False,
                    f"Rate limit exceeded: {max_per_minute} requests per minute",
                )

            if count_hour > self.max_queries_per_hour:
                return (
                    False,
                    f"Rate limit exceeded: {self.max_queries_per_hour} requests per hour",
                )

            return True, None

        except Exception as e:
            # Se Redis falhar, usar fallback
            import logging

            logger = logging.getLogger("dataassistant")
            logger.warning(f"Redis rate limiter failed, using fallback: {e}")
            return _fallback_limiter.check_rate_limit(user_id, request_type)


# Instância global. Defaults are generous for authenticated production
# traffic; tighten via env for the public demo so a bot loop can't burn
# OpenAI / LLM budget:
#   RATE_LIMIT_QUERIES_PER_MINUTE=10
#   RATE_LIMIT_QUERIES_PER_HOUR=60
#   RATE_LIMIT_VALIDATE_PER_MINUTE=20
_rate_limiter = DistributedRateLimiter(
    max_queries_per_minute=_env_int("RATE_LIMIT_QUERIES_PER_MINUTE", 1000),
    max_queries_per_hour=_env_int("RATE_LIMIT_QUERIES_PER_HOUR", 5000),
    max_validate_per_minute=_env_int("RATE_LIMIT_VALIDATE_PER_MINUTE", 1000),
)
