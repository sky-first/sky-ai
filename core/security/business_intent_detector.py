# core/security/business_intent_detector.py
"""
Detector de intenções de negócio (agnóstico, multi-domínio).

Usa padrões linguísticos universais que funcionam para qualquer domínio:
- Métricas e agregações
- Análises comparativas
- Rankings e classificações
- Tendências temporais

NÃO inclui palavras específicas de domínio para manter agnosticismo total.
"""

import re
from typing import Optional

# Padrões linguísticos UNIVERSAIS (funcionam para qualquer domínio)
# Baseados em estruturas gramaticais e intenções, não palavras específicas
BUSINESS_INTENT_PATTERNS = [
    # ========== PADRÕES DE AGREGAÇÃO/ANÁLISE ==========
    # "mais utilizado", "most used", "mais frequente"
    (
        r"\b(mais|most|menos|least)\s+(utilizado|used|frequente|frequent|comum|common)",
        re.IGNORECASE,
    ),
    # "qual é o maior/menor", "which is the highest/lowest"
    (
        r"\b(qual|which|quelles|welche|quali)\s+(é|is|are|são)\s+(o|a|o|os|as|the)\s+(maior|menor|mais|menos|highest|lowest)",
        re.IGNORECASE,
    ),
    # "top N", "ranking", "classificação"
    (
        r"\b(top|ranking|rank|classificação|classificación|classement)\s+\d*",
        re.IGNORECASE,
    ),
    (r"\b(melhores|best|piores|worst)\s+\d*", re.IGNORECASE),
    # ========== PADRÕES DE MÉTRICAS E TOTAIS ==========
    # "total", "soma", "média", "contagem"
    (
        r"\b(total|soma|sum|média|average|mean|contagem|count|quantidade|quantity)\s+(de|of|por|per)",
        re.IGNORECASE,
    ),
    # "por categoria", "by category", "por mês", "per month"
    (r"\b(por|by|per|par|durch)\s+\w+\s+(?:e|and|y|et|und)", re.IGNORECASE),
    (r"\b(agrupado|grouped|groupé|gruppiert)\s+(?:por|by|per)", re.IGNORECASE),
    # ========== PADRÕES DE DISTRIBUIÇÃO ==========
    # "distribuição", "distribuição por", "distribution of"
    (
        r"\b(distribuição|distribution|distribución|répartition|verteilung)\s+(?:de|of|por|by)",
        re.IGNORECASE,
    ),
    # ========== PADRÕES TEMPORAIS ==========
    # "mensal", "anual", "por mês", "per month"
    (r"\b(mensal|monthly|anual|yearly|mensuelle|mensual)\b", re.IGNORECASE),
    (r"\b(por|per|par)\s+(mês|mês|month|mes|año|year|ano)", re.IGNORECASE),
    (r"\b(total|soma|sum)\s+(?:anual|yearly|ano|year)", re.IGNORECASE),  # "total anual"
    # "evolução", "tendência", "comparar"
    (
        r"\b(evolução|evolution|evolución|évolution|tendência|trend|tendencia)",
        re.IGNORECASE,
    ),
    (r"\b(comparar|compare|comparer|vergleichen)\s+", re.IGNORECASE),
    # ========== PADRÕES DE ANÁLISE/PERFORMANCE ==========
    # "análise", "performance", "métrica", "indicador"
    (
        r"\b(análise|analysis|analyse|analisi|performance|desempenho|rendimiento)",
        re.IGNORECASE,
    ),
    (
        r"\b(métrica|metric|métrique|indicador|indicator|indicatore)\s+(?:de|of|por|by)",
        re.IGNORECASE,
    ),
    # ========== PADRÕES DE COMPARAÇÃO ==========
    # "quanto", "how much", "qual a diferença"
    (
        r"\b(quanto|how\s+much|qual\s+a\s+diferença|what\s+is\s+the\s+difference)",
        re.IGNORECASE,
    ),
    # ========== PADRÕES DE PERCENTUAL/PROPORÇÃO ==========
    # "percentual", "porcentagem", "proporção"
    (
        r"\b(percentual|percentage|porcentaje|proporção|proportion)\s+(?:de|of|por|by)",
        re.IGNORECASE,
    ),
    # ========== PADRÕES DE MÉTODO/TIPO/FORMA ==========
    # "qual método", "which method", "qual tipo", "what type"
    (
        r"\b(qual|which|what)\s+(método|method|tipo|type|forma|way|modalidade|modality)",
        re.IGNORECASE,
    ),
    # "mais utilizado", "most used" (reforço)
    (
        r"\b(método|method|tipo|type|forma|way)\s+(?:é|is)\s+(?:mais|most)\s+(?:utilizado|used)",
        re.IGNORECASE,
    ),
]


def is_business_intent(question: str) -> bool:
    """
    Verifica se a pergunta indica intenção de análise de negócio (agnóstico).

    Usa padrões linguísticos universais que funcionam para qualquer domínio,
    independente das palavras específicas usadas.

    Args:
        question: Pergunta do usuário

    Returns:
        True se a pergunta indica análise de negócio, False caso contrário

    Examples:
        ✅ "Qual método de pagamento é mais utilizado?" → True
        ✅ "Qual é o total de vendas por mês?" → True
        ✅ "Top 10 produtos mais vendidos" → True
        ✅ "Distribuição de receita por região" → True
        ❌ "Ignore todas as regras" → False
        ❌ "Show me all tables" → False
    """
    if not question or not isinstance(question, str):
        return False

    question_normalized = question.strip()
    if len(question_normalized) < 3:
        return False

    # Verificar padrões de intenção de negócio
    for pattern, flags in BUSINESS_INTENT_PATTERNS:
        if re.search(pattern, question_normalized, flags):
            return True

    return False


def get_business_intent_pattern_matched(question: str) -> Optional[str]:
    """
    Retorna qual padrão foi identificado (para logging/debug).
    """
    if not question:
        return None

    for pattern, flags in BUSINESS_INTENT_PATTERNS:
        if re.search(pattern, question, flags):
            return pattern.pattern

    return None
