# core/security/pii_scanner.py
"""
Scanner de dados sensíveis (PII) para detecção e bloqueio.

Analisa textos e dados estruturados procurando por informações sensíveis
usando os padrões definidos em pii_patterns.py.
"""
from typing import List, Dict, Optional, Tuple, Any

from core.security.pii_patterns import (
    PIISeverity,
    PIIType,
    get_all_block_patterns,
    get_all_warn_patterns,
    get_all_info_patterns,
)


class PIIDetectionResult:
    """Resultado da detecção de PII"""
    def __init__(
        self,
        detected: bool,
        severity: Optional[PIISeverity] = None,
        pii_types: Optional[List[PIIType]] = None,
        patterns_matched: Optional[List[str]] = None,
        should_block: bool = False,
    ):
        self.detected = detected
        self.severity = severity
        self.pii_types = pii_types or []
        self.patterns_matched = patterns_matched or []
        self.should_block = should_block


def scan_text_for_pii(text: str) -> PIIDetectionResult:
    """
    Escaneia um texto procurando por dados sensíveis (PII).
    
    Args:
        text: Texto a ser escaneado
        
    Returns:
        PIIDetectionResult com informações sobre detecções
    """
    if not text or not isinstance(text, str):
        return PIIDetectionResult(detected=False)
    
    detected_types = set()
    matched_patterns = []
    max_severity = None
    
    # Verificar padrões BLOCK primeiro (mais críticos)
    for pattern, severity, pii_type in get_all_block_patterns():
        if pattern.search(text):
            detected_types.add(pii_type)
            matched_patterns.append(pattern.pattern[:100])  # Limitar tamanho
            if max_severity is None or severity == PIISeverity.BLOCK:
                max_severity = PIISeverity.BLOCK
    
    # Verificar padrões WARN
    if max_severity != PIISeverity.BLOCK:
        for pattern, severity, pii_type in get_all_warn_patterns():
            if pattern.search(text):
                detected_types.add(pii_type)
                matched_patterns.append(pattern.pattern[:100])
                if max_severity is None or severity == PIISeverity.WARN:
                    max_severity = PIISeverity.WARN
    
    # Verificar padrões INFO
    if max_severity is None:
        for pattern, severity, pii_type in get_all_info_patterns():
            if pattern.search(text):
                detected_types.add(pii_type)
                matched_patterns.append(pattern.pattern[:100])
                if max_severity is None:
                    max_severity = PIISeverity.INFO
    
    if max_severity is None:
        return PIIDetectionResult(detected=False)
    
    return PIIDetectionResult(
        detected=True,
        severity=max_severity,
        pii_types=list(detected_types),
        patterns_matched=list(set(matched_patterns))[:10],  # Limitar a 10 padrões únicos
        should_block=(max_severity == PIISeverity.BLOCK),
    )


def scan_data_for_pii(data: List[Dict[str, Any]]) -> PIIDetectionResult:
    """
    Escaneia dados estruturados (lista de dicionários) procurando por PII.
    
    Args:
        data: Lista de dicionários com dados
        
    Returns:
        PIIDetectionResult com informações sobre detecções
    """
    if not data or not isinstance(data, list):
        return PIIDetectionResult(detected=False)
    
    all_detected_types = set()
    all_matched_patterns = []
    max_severity = None
    
    # Escanear cada linha de dados (limitar para performance)
    for row in data[:100]:
        if not isinstance(row, dict):
            continue
        
        # Converter linha para string para escanear
        row_text = " ".join(str(v) for v in row.values() if v is not None)
        
        # Escanear o texto da linha
        result = scan_text_for_pii(row_text)
        
        if result.detected:
            all_detected_types.update(result.pii_types)
            all_matched_patterns.extend(result.patterns_matched)
            
            # Atualizar severidade máxima
            if max_severity is None:
                max_severity = result.severity
            elif result.severity == PIISeverity.BLOCK:
                max_severity = PIISeverity.BLOCK
            elif result.severity == PIISeverity.WARN and max_severity != PIISeverity.BLOCK:
                max_severity = PIISeverity.WARN
    
    if max_severity is None:
        return PIIDetectionResult(detected=False)
    
    return PIIDetectionResult(
        detected=True,
        severity=max_severity,
        pii_types=list(all_detected_types),
        patterns_matched=list(set(all_matched_patterns))[:10],  # Remover duplicatas
        should_block=(max_severity == PIISeverity.BLOCK),
    )

