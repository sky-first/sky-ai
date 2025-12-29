# core/validation/suggestion_validator.py
"""
Validador genérico para sugestões de bootstrap.
Valida se sugestões são executáveis baseado em metadados.
"""

from __future__ import annotations

from typing import List, Tuple
from core.validation.question_validator import QuestionValidator, ValidationResult, ValidationSeverity


class SuggestionValidator:
    """
    Valida sugestões geradas pelo bootstrap para garantir que são executáveis.
    """
    
    def __init__(self, question_validator: QuestionValidator):
        """
        Args:
            question_validator: Instância de QuestionValidator configurada
        """
        self.question_validator = question_validator
    
    def validate_suggestion(self, suggestion: str) -> Tuple[bool, List[ValidationResult]]:
        """
        Valida uma sugestão e retorna (is_valid, issues).
        
        Args:
            suggestion: Texto da sugestão/pergunta
            
        Returns:
            Tuple (is_valid, issues) onde:
            - is_valid: True se não há erros críticos
            - issues: Lista de todos os problemas encontrados
        """
        issues = self.question_validator.validate_question(suggestion)
        
        # Filtrar apenas erros críticos
        critical_issues = [i for i in issues if i.severity == ValidationSeverity.ERROR]
        is_valid = len(critical_issues) == 0
        
        return is_valid, issues
    
    def should_filter_suggestion(self, suggestion: str) -> bool:
        """
        Retorna True se a sugestão deve ser filtrada (não mostrada).
        
        Args:
            suggestion: Texto da sugestão/pergunta
            
        Returns:
            True se deve filtrar, False caso contrário
        """
        is_valid, issues = self.validate_suggestion(suggestion)
        
        # Filtrar se tiver erros críticos OU múltiplos warnings
        critical_errors = [i for i in issues if i.severity == ValidationSeverity.ERROR]
        warnings = [i for i in issues if i.severity == ValidationSeverity.WARNING]
        
        # Filtrar se:
        # 1. Tem erros críticos
        # 2. Tem 2 ou mais warnings (muitos problemas)
        # 3. Tem warning de filtro temporal restritivo (RESTRICTIVE_TIME_FILTER) - esses frequentemente retornam vazio
        has_restrictive_time_filter = any(
            i.code == "RESTRICTIVE_TIME_FILTER" for i in warnings
        )
        
        should_filter = (
            len(critical_errors) > 0 
            or len(warnings) >= 2
            or has_restrictive_time_filter  # Filtrar sugestões com filtros temporais restritivos
        )
        
        return should_filter
    
    def get_suggestion_score(self, suggestion: str) -> float:
        """
        Retorna um score de qualidade da sugestão (0.0 a 1.0).
        Quanto maior, melhor a sugestão.
        
        Args:
            suggestion: Texto da sugestão/pergunta
            
        Returns:
            Score entre 0.0 (ruim) e 1.0 (excelente)
        """
        is_valid, issues = self.validate_suggestion(suggestion)
        
        if not is_valid:
            return 0.0
        
        # Score base: 1.0
        score = 1.0
        
        # Penalizar por warnings (-0.2 cada)
        warnings = [i for i in issues if i.severity == ValidationSeverity.WARNING]
        score -= len(warnings) * 0.2
        
        # Penalizar por info (-0.1 cada)
        infos = [i for i in issues if i.severity == ValidationSeverity.INFO]
        score -= len(infos) * 0.1
        
        # Garantir que não fique negativo
        return max(0.0, score)

