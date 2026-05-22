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

# Security Guard (Sistema em 3 camadas)
from core.security.security_guard import (
    evaluate_security,
    SecurityAction,
    SecurityDecision,
)

from core.security.business_intent_detector import (
    is_business_intent,
    get_business_intent_pattern_matched,
)

from core.security.risk_scorer import (
    calculate_risk_score,
    RiskScore,
)

from core.security.semantic_classifier import (
    classify_intent_with_llm,
)

__all__ = [
    # Prompt injection (mantém compatibilidade)
    "detect_prompt_injection",
    "sanitize_question",
    # Rate limiter
    "SimpleRateLimiter",
    "_rate_limiter",
    # PII patterns
    "PIISeverity",
    "PIIType",
    "get_all_block_patterns",
    "get_all_warn_patterns",
    "get_all_info_patterns",
    "get_patterns_by_type",
    "get_all_patterns",
    # PII scanner
    "PIIDetectionResult",
    "scan_text_for_pii",
    "scan_data_for_pii",
    # Security Guard (novo)
    "evaluate_security",
    "SecurityAction",
    "SecurityDecision",
    # Business Intent
    "is_business_intent",
    "get_business_intent_pattern_matched",
    # Risk Scorer
    "calculate_risk_score",
    "RiskScore",
    # Semantic Classifier
    "classify_intent_with_llm",
]
