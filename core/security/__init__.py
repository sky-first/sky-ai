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
from core.security.pii_patterns import (
    PIISeverity,
    PIIType,
    get_all_block_patterns,
    get_all_warn_patterns,
    get_all_info_patterns,
    get_patterns_by_type,
    get_all_patterns,
)
from core.security.pii_scanner import (
    PIIDetectionResult,
    scan_text_for_pii,
    scan_data_for_pii,
)

__all__ = [
    "detect_prompt_injection",
    "sanitize_question",
    "SimpleRateLimiter",
    "_rate_limiter",
    "PIISeverity",
    "PIIType",
    "get_all_block_patterns",
    "get_all_warn_patterns",
    "get_all_info_patterns",
    "get_patterns_by_type",
    "get_all_patterns",
    "PIIDetectionResult",
    "scan_text_for_pii",
    "scan_data_for_pii",
]

