# core/validation/__init__.py
"""
Módulo de validação genérico para perguntas e sugestões.
Funciona para qualquer domínio, baseado em metadados disponíveis.
"""

from core.validation.question_validator import QuestionValidator, ValidationResult, ValidationSeverity
from core.validation.suggestion_validator import SuggestionValidator

__all__ = [
    "QuestionValidator",
    "SuggestionValidator",
    "ValidationResult",
    "ValidationSeverity",
]

