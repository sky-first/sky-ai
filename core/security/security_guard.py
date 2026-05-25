# core/security/security_guard.py
"""
Security Guard: orquestra as 3 camadas de segurança.

Layer 1: Risk Scorer (heurística leve)
Layer 2: Semantic Classifier (LLM, condicional)
Layer 3: Domain Context (allowlist de intenções)

Decisão final baseada em todas as camadas.
"""

from typing import Optional, Dict, List
from dataclasses import dataclass
from enum import Enum

from core.security.business_intent_detector import is_business_intent
from core.security.risk_scorer import calculate_risk_score, RiskScore
from core.security.semantic_classifier import classify_intent_with_llm, IntentCategory
from core.llm.providers import LLMProvider


class SecurityAction(Enum):
    """Ação de segurança a ser tomada"""

    ALLOW = "allow"
    BLOCK = "block"
    SANITIZE = "sanitize"


@dataclass
class SecurityDecision:
    """Decisão de segurança"""

    action: SecurityAction
    reason: str
    risk_score: int
    llm_category: Optional[str] = None
    confidence: float = 0.0

    def is_blocked(self) -> bool:
        """Retorna True se a ação é bloquear"""
        return self.action == SecurityAction.BLOCK

    def is_allowed(self) -> bool:
        """Retorna True se a ação é permitir"""
        return self.action == SecurityAction.ALLOW


async def evaluate_security(
    question: str,
    llm_provider: Optional[LLMProvider] = None,
    allowed_tables: Optional[List[str]] = None,
    security_config: Optional[Dict] = None,
) -> SecurityDecision:
    """
    Avalia segurança usando 3 camadas (agnóstico).

    Fluxo:
    1. Layer 3 (Fast): Allowlist de intenções de negócio
    2. Layer 1: Risk scorer (heurística leve)
    3. Layer 2 (Condicional): LLM classifier (só se necessário)
    4. Decisão final

    Args:
        question: Pergunta do usuário
        llm_provider: Provider LLM para classificação semântica (opcional)
        allowed_tables: Tabelas permitidas (para contexto futuro)
        security_config: Configuração de segurança (para contexto futuro)

    Returns:
        SecurityDecision com ação e razão
    """
    if not question:
        return SecurityDecision(
            action=SecurityAction.ALLOW, reason="EMPTY_QUESTION", risk_score=0
        )

    # ========== LAYER 3: Allowlist rápida (bypass para negócio) ==========
    # Verificar se é intenção de negócio legítima (agnóstico)
    if is_business_intent(question):
        return SecurityDecision(
            action=SecurityAction.ALLOW,
            reason="BUSINESS_INTENT_WHITELIST",
            risk_score=0,
        )

    # ========== LAYER 1: Risk scorer (heurística leve) ==========
    risk_score_obj = calculate_risk_score(question)
    risk_score = risk_score_obj.score

    # Se risco muito baixo, permitir sem LLM
    if risk_score == 0:
        return SecurityDecision(
            action=SecurityAction.ALLOW, reason="ZERO_RISK_SCORE", risk_score=0
        )

    # ========== LAYER 2: LLM Classifier (condicional) ==========
    # Chamar LLM apenas se:
    # - Risk score >= 2 (houve algum sinal de risco)
    # - Não passou pela allowlist (não é intenção óbvia de negócio)

    llm_category: Optional[IntentCategory] = None
    llm_confidence: float = 0.0

    should_call_llm = risk_score >= 2

    if should_call_llm and llm_provider:
        try:
            llm_category, llm_confidence = await classify_intent_with_llm(
                question, llm_provider
            )

            # Se LLM classifica como SAFE_BUSINESS, permitir
            if llm_category == "SAFE_BUSINESS":
                return SecurityDecision(
                    action=SecurityAction.ALLOW,
                    reason=f"LLM_SAFE_BUSINESS_{llm_confidence:.2f}",
                    risk_score=risk_score,
                    llm_category=llm_category,
                    confidence=llm_confidence,
                )

            # Se LLM classifica como malicioso, bloquear
            if llm_category in [
                "MALICIOUS_INJECTION",
                "DATA_EXFILTRATION",
                "PRIVILEGE_ESCALATION",
                "SYSTEM_MANIPULATION",
            ]:
                return SecurityDecision(
                    action=SecurityAction.BLOCK,
                    reason=f"LLM_{llm_category}_{llm_confidence:.2f}",
                    risk_score=risk_score + 5,  # Adicionar peso extra
                    llm_category=llm_category,
                    confidence=llm_confidence,
                )
        except Exception as e:
            # Se LLM falhar, continuar com heurística
            pass

    # ========== DECISÃO FINAL: Baseada em pontuação ==========
    # Sem LLM ou LLM retornou UNKNOWN, usar heurística

    # Se risk score >= 5 (comandos DDL/DML críticos), bloquear sempre
    if risk_score >= 5:
        return SecurityDecision(
            action=SecurityAction.BLOCK,
            reason=f"HIGH_RISK_SCORE_{risk_score}",
            risk_score=risk_score,
            llm_category=llm_category,
            confidence=llm_confidence,
        )
    elif risk_score >= 4:
        # Risk score >= 4: bloquear (não apenas sanitizar)
        return SecurityDecision(
            action=SecurityAction.BLOCK,
            reason=f"MEDIUM_HIGH_RISK_SCORE_{risk_score}",
            risk_score=risk_score,
            llm_category=llm_category,
            confidence=llm_confidence,
        )
    elif risk_score >= 2:
        # Risk score 2-3: pode ser perigoso, mas permitir com log
        return SecurityDecision(
            action=SecurityAction.ALLOW,
            reason=f"LOW_MEDIUM_RISK_SCORE_{risk_score}",
            risk_score=risk_score,
            llm_category=llm_category,
            confidence=llm_confidence,
        )
    else:
        # Risk score baixo (0-1), permitir
        return SecurityDecision(
            action=SecurityAction.ALLOW,
            reason=f"LOW_RISK_SCORE_{risk_score}",
            risk_score=risk_score,
            llm_category=llm_category,
            confidence=llm_confidence,
        )
