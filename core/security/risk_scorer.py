# core/security/risk_scorer.py
"""
Risk scorer: heurística leve que apenas pontua, nunca bloqueia diretamente.
A decisão final é tomada pelo security_guard considerando todas as camadas.
"""
import re
from typing import List
from dataclasses import dataclass
from core.security.prompt_injection import _normalize


@dataclass
class RiskScore:
    """Representa uma pontuação de risco"""
    score: int
    reasons: List[str]
    
    def __repr__(self):
        return f"RiskScore(score={self.score}, reasons={self.reasons[:3]})"


# Padrões suspeitos com pontuação (não bloqueiam diretamente)
SUSPICIOUS_PATTERNS = [
    # Tentativas de manipulação do sistema
    (re.compile(r'\bignore\s+(?:all|todas|toutes)\s+(?:rules?|regras|règles)\b', re.IGNORECASE), 4),
    (re.compile(r'\bignore\s+(?:all|todas|toutes|previous)\b', re.IGNORECASE), 4),
    (re.compile(r'\bignore\s+previous\s+(?:instructions?|instruções)\b', re.IGNORECASE), 4),
    (re.compile(r'\bsystem\s+prompt\b', re.IGNORECASE), 4),
    (re.compile(r'\byou\s+are\s+now\b', re.IGNORECASE), 3),
    (re.compile(r'\bforget\s+all\b', re.IGNORECASE), 3),
    
    # Tentativas de bypass
    (re.compile(r'\bbypass\b', re.IGNORECASE), 2),
    (re.compile(r'\boverride\b', re.IGNORECASE), 2),
    (re.compile(r'\bhack\b', re.IGNORECASE), 2),
    
    # Tentativas de execução direta de SQL/DML
    (re.compile(r'\b(drop|delete|truncate|alter)\s+(?:table|database|schema)\b', re.IGNORECASE), 5),
    (re.compile(r'\bselect\s+\*\b', re.IGNORECASE), 2),
    (re.compile(r'\binformation_schema\b', re.IGNORECASE), 4),
    (re.compile(r'\bpg_catalog\b', re.IGNORECASE), 4),
    
    # Tentativas de exfiltração de schema
    (re.compile(r'\b(show|list|quais|which)\s+(?:all\s+)?tables?\b', re.IGNORECASE), 2),
    (re.compile(r'\b(show|list|quais|which)\s+(?:all\s+)?columns?\b', re.IGNORECASE), 2),
    (re.compile(r'\bshow\s+me\s+all\s+tables?\b', re.IGNORECASE), 2),  # Específico para "show me all tables"
    (re.compile(r'\bschema\b', re.IGNORECASE), 2),
    (re.compile(r'\bmetadata\b', re.IGNORECASE), 2),
    
    # Encoding/obfuscation
    (re.compile(r'\b[A-Za-z0-9+/=]{120,}\b'), 3),  # Base64 payload grande
    
    # Role-play/jailbreak
    (re.compile(r'\bdan\s+mode\b', re.IGNORECASE), 3),
    (re.compile(r'\bdo\s+anything\s+now\b', re.IGNORECASE), 3),
    (re.compile(r'\bdeveloper\s+message\b', re.IGNORECASE), 2),
    
    # Code fences (pode ser tentativa de injeção)
    (re.compile(r'```'), 1),
    (re.compile(r'<system>|</system>'), 2),
    (re.compile(r'<developer>|</developer>'), 2),
    
    # Execute exactly SQL
    (re.compile(r'\bexecute\s+(?:exactly|exatamente)\b', re.IGNORECASE), 4),
    (re.compile(r'\brode\s+(?:exatamente|exactly)\s+sql\b', re.IGNORECASE), 4),
]


def calculate_risk_score(question: str) -> RiskScore:
    """
    Calcula pontuação de risco usando heurística leve.
    
    NUNCA bloqueia diretamente - apenas pontua. A decisão final é do security_guard.
    
    Args:
        question: Pergunta do usuário
        
    Returns:
        RiskScore com pontuação e razões
    """
    if not question:
        return RiskScore(score=0, reasons=[])
    
    question_normalized = _normalize(question)
    risk_score = 0
    reasons = []
    
    for pattern, points in SUSPICIOUS_PATTERNS:
        if pattern.search(question_normalized):
            risk_score += points
            reasons.append(f"{pattern.pattern[:50]}: +{points}")
    
    return RiskScore(score=risk_score, reasons=reasons)

