# core/security/__init__.py
"""
Módulo de segurança para proteção contra ataques maliciosos.
"""
from core.security.prompt_injection import (
    detect_prompt_injection,
    sanitize_question,
)
from core.security.rate_limiter import (
    SimpleRateLimiter,
    _rate_limiter,
)

__all__ = [
    "detect_prompt_injection",
    "sanitize_question",
    "SimpleRateLimiter",
    "_rate_limiter",
]

