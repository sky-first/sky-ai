# core/security/rate_limiter.py
"""
Rate limiting simples em memória (sem backend do produto).
Para produção, considerar Redis depois.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional


class SimpleRateLimiter:
    """
    Rate limiter em memória.
    Limita queries por usuário/connection.
    """

    def __init__(
        self,
        max_queries_per_minute: int = 30,
        max_queries_per_hour: int = 200,
        max_validate_per_minute: int = 50,
    ):
        self.max_queries_per_minute = max_queries_per_minute
        self.max_queries_per_hour = max_queries_per_hour
        self.max_validate_per_minute = max_validate_per_minute

        # Estrutura: {user_id: [(timestamp, type), ...]}
        self.requests: Dict[str, list] = defaultdict(list)

    def check_rate_limit(
        self, user_id: str, request_type: str = "query"
    ) -> Tuple[bool, Optional[str]]:
        """
        Verifica rate limit.
        Retorna (allowed, error_message)
        """
        now = datetime.now()
        key = user_id or "anonymous"

        # Limpar requests antigos (> 1 hora)
        cutoff = now - timedelta(hours=1)
        self.requests[key] = [(ts, t) for ts, t in self.requests[key] if ts > cutoff]

        # Contar requests recentes
        minute_ago = now - timedelta(minutes=1)
        hour_ago = now - timedelta(hours=1)

        recent_minute = [
            (ts, t)
            for ts, t in self.requests[key]
            if ts > minute_ago and t == request_type
        ]
        recent_hour = [
            (ts, t)
            for ts, t in self.requests[key]
            if ts > hour_ago and t == request_type
        ]

        # Verificar limites
        max_per_minute = (
            self.max_validate_per_minute
            if request_type == "validate"
            else self.max_queries_per_minute
        )

        if len(recent_minute) >= max_per_minute:
            return False, f"Rate limit exceeded: {max_per_minute} requests per minute"

        if len(recent_hour) >= self.max_queries_per_hour:
            return (
                False,
                f"Rate limit exceeded: {self.max_queries_per_hour} requests per hour",
            )

        # Registrar request
        self.requests[key].append((now, request_type))

        return True, None


# Instância global
# AUMENTO DE LIMITES PARA VALIDAÇÃO
_rate_limiter = SimpleRateLimiter(
    max_queries_per_minute=1000, max_queries_per_hour=5000, max_validate_per_minute=1000
)
