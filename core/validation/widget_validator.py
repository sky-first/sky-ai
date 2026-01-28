# core/validation/widget_validator.py
"""
Validador específico para widgets do Davinci.

Valida estrutura, perguntas e configurações de visualização dos widgets.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from core.validation.question_validator import QuestionValidator, ValidationResult, ValidationSeverity
from core.logging_utils import log_event


@dataclass
class WidgetValidationResult:
    """Resultado da validação de um widget"""
    is_valid: bool
    should_filter: bool  # Se deve ser filtrado (removido do plano)
    issues: List[ValidationResult]
    widget: Dict[str, Any]  # Widget original (pode ser modificado)


class WidgetValidator:
    """
    Validador de widgets do Davinci.
    
    Valida:
    - Estrutura do widget (campos obrigatórios)
    - Pergunta do widget (usando QuestionValidator)
    - Tipo de widget e configuração de visualização
    """
    
    # Tipos de widgets permitidos
    ALLOWED_TYPES = {"chart", "kpi", "table", "text"}
    
    # Tipos de visualização permitidos por tipo de widget
    ALLOWED_VIZ_TYPES = {
        "chart": {"bar", "line", "pie", "area", "scatter", "column"},
        "kpi": {"kpi"},
        "table": {"table"},
        "text": {"text"},
    }
    
    def __init__(
        self,
        question_validator: QuestionValidator,
        strict_mode: bool = True,
    ):
        """
        Args:
            question_validator: Instância de QuestionValidator para validar perguntas
            strict_mode: Se True, filtra widgets com warnings também. Se False, apenas errors.
        """
        self.question_validator = question_validator
        self.strict_mode = strict_mode
    
    def validate_widget(self, widget: Dict[str, Any], widget_index: int = 0) -> WidgetValidationResult:
        """
        Valida um widget completo.
        
        Args:
            widget: Dict com estrutura do widget (widget_key, type, title, question, viz)
            widget_index: Índice do widget (para logging)
            
        Returns:
            WidgetValidationResult com resultado da validação
        """
        issues: List[ValidationResult] = []
        
        # 1. Validar estrutura básica
        structure_issues = self._validate_structure(widget)
        issues.extend(structure_issues)
        
        # 2. Validar pergunta (se houver)
        question = widget.get("question") or ""
        if question:
            question_issues = self.question_validator.validate_question(question)
            issues.extend(question_issues)
        else:
            # Pergunta vazia só é aceitável para widgets do tipo "text"
            if widget.get("type") != "text":
                issues.append(ValidationResult(
                    severity=ValidationSeverity.ERROR,
                    code="MISSING_QUESTION",
                    message="Widget deve ter uma pergunta (exceto tipo 'text').",
                ))
        
        # 3. Validar tipo de widget
        type_issues = self._validate_widget_type(widget)
        issues.extend(type_issues)
        
        # 4. Validar configuração de visualização
        viz_issues = self._validate_visualization(widget)
        issues.extend(viz_issues)
        
        # Determinar se deve filtrar
        # ✅ AJUSTE: strict_mode agora realmente faz diferença
        # Em strict_mode=True: filtra se houver qualquer ERROR ou WARNING
        # Em strict_mode=False: filtra APENAS se houver ERROR (ignora warnings)
        has_error = any(issue.severity == ValidationSeverity.ERROR for issue in issues)
        has_warning = any(issue.severity == ValidationSeverity.WARNING for issue in issues)
        
        # ✅ MUDANÇA: strict_mode=False agora é verdadeiramente leniente
        if self.strict_mode:
            # Modo estrito: filtrar errors E warnings
            should_filter = has_error or has_warning
        else:
            # Modo leniente: filtrar APENAS errors críticos
            should_filter = has_error
        
        # ✅ NOVO: Log detalhado se necessário
        if should_filter:
            log_event(
                "davinci_widget_filtered",
                {
                    "widget_index": widget_index,
                    "widget_key": widget.get("widget_key", "unknown"),
                    "widget_type": widget.get("type", "unknown"),
                    "widget_title": widget.get("title", "unknown")[:100],
                    "question": widget.get("question", "")[:200],
                    "issues_count": len(issues),
                    "has_error": has_error,
                    "has_warning": has_warning,
                    "strict_mode": self.strict_mode,
                    "error_codes": [i.code for i in issues if i.severity == ValidationSeverity.ERROR],
                    "warning_codes": [i.code for i in issues if i.severity == ValidationSeverity.WARNING],
                },
            )
        
        return WidgetValidationResult(
            is_valid=not should_filter,
            should_filter=should_filter,
            issues=issues,
            widget=widget,
        )
    
    def _validate_structure(self, widget: Dict[str, Any]) -> List[ValidationResult]:
        """Valida estrutura básica do widget"""
        issues: List[ValidationResult] = []
        
        # Campos obrigatórios
        required_fields = ["widget_key", "type", "title"]
        for field in required_fields:
            if field not in widget or not widget[field]:
                issues.append(ValidationResult(
                    severity=ValidationSeverity.ERROR,
                    code=f"MISSING_{field.upper()}",
                    message=f"Campo obrigatório '{field}' está ausente ou vazio.",
                ))
        
        # Validar tipos de campos
        if "widget_key" in widget and not isinstance(widget["widget_key"], str):
            issues.append(ValidationResult(
                severity=ValidationSeverity.ERROR,
                code="INVALID_WIDGET_KEY_TYPE",
                message="Campo 'widget_key' deve ser uma string.",
            ))
        
        if "type" in widget and not isinstance(widget["type"], str):
            issues.append(ValidationResult(
                severity=ValidationSeverity.ERROR,
                code="INVALID_TYPE_FIELD",
                message="Campo 'type' deve ser uma string.",
            ))
        
        if "title" in widget and not isinstance(widget.get("title"), str):
            issues.append(ValidationResult(
                severity=ValidationSeverity.WARNING,
                code="INVALID_TITLE_TYPE",
                message="Campo 'title' deve ser uma string.",
            ))
        
        return issues
    
    def _validate_widget_type(self, widget: Dict[str, Any]) -> List[ValidationResult]:
        """Valida tipo de widget"""
        issues: List[ValidationResult] = []
        
        widget_type = widget.get("type", "").strip().lower()
        
        if not widget_type:
            return issues  # Já foi validado em _validate_structure
        
        if widget_type not in self.ALLOWED_TYPES:
            issues.append(ValidationResult(
                severity=ValidationSeverity.ERROR,
                code="INVALID_WIDGET_TYPE",
                message=f"Tipo de widget '{widget_type}' não é permitido. Tipos permitidos: {', '.join(self.ALLOWED_TYPES)}",
                suggestion=f"Use um dos tipos permitidos: {', '.join(self.ALLOWED_TYPES)}",
            ))
        
        return issues
    
    def _validate_visualization(self, widget: Dict[str, Any]) -> List[ValidationResult]:
        """Valida configuração de visualização"""
        issues: List[ValidationResult] = []
        
        widget_type = widget.get("type", "").strip().lower()
        viz = widget.get("viz")
        
        # Widgets do tipo "text" podem não ter viz ou ter viz simples
        if widget_type == "text":
            if viz is None:
                return issues  # OK, text widgets podem não ter viz
            if isinstance(viz, dict) and viz.get("type") == "text":
                return issues  # OK
        
        # Outros tipos devem ter viz
        if viz is None:
            issues.append(ValidationResult(
                severity=ValidationSeverity.ERROR,
                code="MISSING_VIZ",
                message=f"Widget do tipo '{widget_type}' deve ter configuração de visualização ('viz').",
            ))
            return issues
        
        if not isinstance(viz, dict):
            issues.append(ValidationResult(
                severity=ValidationSeverity.ERROR,
                code="INVALID_VIZ_TYPE",
                message="Campo 'viz' deve ser um objeto/dict.",
            ))
            return issues
        
        viz_type = viz.get("type", "").strip().lower()
        
        if not viz_type:
            issues.append(ValidationResult(
                severity=ValidationSeverity.ERROR,
                code="MISSING_VIZ_TYPE",
                message="Campo 'viz.type' é obrigatório.",
            ))
            return issues
        
        # Validar se viz_type é permitido para este widget_type
        allowed_viz = self.ALLOWED_VIZ_TYPES.get(widget_type, set())
        if viz_type not in allowed_viz:
            issues.append(ValidationResult(
                severity=ValidationSeverity.ERROR,
                code="INVALID_VIZ_TYPE_FOR_WIDGET",
                message=f"Tipo de visualização '{viz_type}' não é permitido para widget do tipo '{widget_type}'. Tipos permitidos: {', '.join(allowed_viz)}",
                suggestion=f"Use um dos tipos permitidos: {', '.join(allowed_viz)}",
            ))
        
        # Validar mapping para charts
        if widget_type == "chart" and viz_type in {"bar", "line", "pie", "area", "scatter", "column"}:
            mapping = viz.get("mapping")
            if not isinstance(mapping, dict):
                issues.append(ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    code="MISSING_VIZ_MAPPING",
                    message=f"Widget do tipo 'chart' com viz '{viz_type}' deve ter 'mapping' definido.",
                    suggestion="Adicione 'mapping' com campos 'x' e 'y' (ou 'category' e 'value').",
                ))
        
        return issues
    
    def filter_widgets(
        self,
        widgets: List[Dict[str, Any]],
        min_widgets: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Filtra lista de widgets, removendo os inválidos.
        
        Args:
            widgets: Lista de widgets para validar
            min_widgets: Número mínimo de widgets que devem permanecer
            
        Returns:
            Lista filtrada de widgets válidos
        """
        validated = []
        filtered_count = 0
        
        for i, widget in enumerate(widgets):
            result = self.validate_widget(widget, widget_index=i)
            
            if result.should_filter:
                filtered_count += 1
                continue
            
            validated.append(result.widget)
        
        # Se filtramos muitos widgets, logar aviso
        if filtered_count > 0:
            log_event(
                "davinci_widgets_filtered_summary",
                {
                    "total_widgets": len(widgets),
                    "filtered_count": filtered_count,
                    "remaining_count": len(validated),
                    "min_widgets": min_widgets,
                },
            )
        
        # Garantir mínimo
        if len(validated) < min_widgets and len(widgets) > 0:
            # Se não temos widgets suficientes, manter alguns mesmo com problemas
            # (melhor ter widgets com problemas do que nenhum widget)
            log_event(
                "davinci_widgets_below_minimum",
                {
                    "validated_count": len(validated),
                    "min_widgets": min_widgets,
                    "action": "keeping_all_widgets",
                },
            )
            # Retornar todos os widgets originais (sem filtrar)
            return widgets
        
        return validated

