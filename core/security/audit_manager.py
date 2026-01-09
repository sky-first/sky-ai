# core/security/audit_manager.py
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
import logging

from core.security.audit import log_prompt_security_audit
from core.security.pii_scanner import scan_text_for_pii, PIIDetectionResult
from core.security.security_guard import evaluate_security, SecurityDecision, SecurityAction
from core.security.progressive_escalation import detect_progressive_escalation

logger = logging.getLogger("dataassistant.security")

@dataclass
class SecurityAuditReport:
    is_blocked: bool = False
    security_status: str = "ALLOWED"  # ALLOWED, BLOCKED, FLAGGED
    blocked_by: Optional[str] = None
    reason: Optional[str] = None
    risk_score: float = 0.0
    redacted_prompt: str = ""
    scan_details: Dict[str, Any] = field(default_factory=dict)

class AuditManager:
    """
    Manager centralizado para avaliação de segurança de prompts e auditoria.
    Unifica PII, Prompt Injection e Progressive Escalation.
    """

    @staticmethod
    async def evaluate_prompt(
        question: str,
        user_id: Optional[str],
        connection_id: str,
        thread_id: Optional[str] = None,
        llm_client: Any = None
    ) -> SecurityAuditReport:
        report = SecurityAuditReport(redacted_prompt=question)
        
        # 1. PII Scan (Input)
        pii_result = scan_text_for_pii(question)
        if pii_result.should_block:
            report.is_blocked = True
            report.security_status = "BLOCKED"
            report.blocked_by = "PII_SCANNER"
            report.reason = "Sensitive data (PII) detected in prompt"
            report.risk_score = 1.0
            report.redacted_prompt = "[REDACTED_PII]"
            report.scan_details["pii"] = {
                "detected_types": [t.value for t in pii_result.pii_types],
                "severity": str(pii_result.severity)
            }
            # Se for PII Block, já podemos parar aqui para não enviar PII para o LLM do Security Guard
            await AuditManager._log_audit(user_id, connection_id, report)
            return report

        # 2. Security Guard (Prompt Injection / Jailbreak)
        # Nota: llm_client deve ser o cliente OpenAI configurado
        security_decision = await evaluate_security(
            question=question,
            llm_client=llm_client
        )
        
        report.scan_details["security_guard"] = {
            "reason": security_decision.reason,
            "risk_score": float(security_decision.risk_score),
            "category": security_decision.llm_category
        }
        
        if security_decision.is_blocked():
            report.is_blocked = True
            report.security_status = "BLOCKED"
            report.blocked_by = "SECURITY_GUARD"
            report.reason = security_decision.reason
            report.risk_score = max(report.risk_score, float(security_decision.risk_score))
            await AuditManager._log_audit(user_id, connection_id, report)
            return report

        # 3. Progressive Escalation
        t_id = thread_id or f"{user_id or 'anon'}-{connection_id}"
        escalation_detected, escalation_score, escalation_reason = detect_progressive_escalation(
            user_id=user_id or "anonymous",
            thread_id=t_id,
            question=question
        )
        
        if escalation_detected:
            # Escalation geralmente gera um FLAGGED ou BLOCK dependendo da política
            # Por enquanto, se detectado, vamos considerar como risco alto
            report.scan_details["escalation"] = {
                "score": escalation_score,
                "reason": escalation_reason
            }
            report.risk_score = max(report.risk_score, escalation_score / 100.0)
            
            if escalation_score >= 80: # Threshold arbitrário para block automático
                report.is_blocked = True
                report.security_status = "BLOCKED"
                report.blocked_by = "PROGRESSIVE_ESCALATION"
                report.reason = escalation_reason
                await AuditManager._log_audit(user_id, connection_id, report)
                return report
            else:
                report.security_status = "FLAGGED"

        # Se chegou aqui sem ser bloqueado, está permitido
        await AuditManager._log_audit(user_id, connection_id, report)
        return report

    @staticmethod
    async def _log_audit(user_id: Optional[str], connection_id: str, report: SecurityAuditReport):
        """Persiste o log de auditoria especializado via core.security.audit"""
        try:
            log_prompt_security_audit(
                connection_id=connection_id,
                user_id=user_id,
                prompt_text_redacted=report.redacted_prompt[:2000],  # Truncar se necessário
                security_status=report.security_status,
                blocked_by=report.blocked_by,
                risk_score=report.risk_score,
                scan_details=report.scan_details
            )
        except Exception as e:
            logger.error(f"Failed to log prompt security audit: {e}")
