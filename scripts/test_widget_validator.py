#!/usr/bin/env python3
"""
Testa o WidgetValidator para widgets do Davinci.
"""

import sys
import os
from pathlib import Path

# Adicionar raiz do projeto ao path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.validation.widget_validator import WidgetValidator, WidgetValidationResult
from core.validation.question_validator import QuestionValidator, ValidationSeverity


def create_test_question_validator():
    """Cria um QuestionValidator de teste"""
    available_tables = [
        {"name": "invoices", "logical_name": "invoices"},
        {"name": "customers", "logical_name": "customers"},
        {"name": "payments", "logical_name": "payments"},
    ]
    available_columns = {
        "invoices": ["id", "customer_id", "amount", "status", "created_at"],
        "customers": ["id", "name", "email", "country"],
        "payments": ["id", "invoice_id", "amount", "method", "date"],
    }
    return QuestionValidator(available_tables, available_columns)


def test_valid_widget():
    """Testa widget válido"""
    print("🧪 Testando widget válido...")
    
    validator = WidgetValidator(create_test_question_validator())
    
    widget = {
        "widget_key": "w1",
        "type": "chart",
        "title": "Total Revenue",
        "question": "What is the total amount from invoices?",
        "viz": {"type": "bar", "mapping": {"x": "category", "y": "value"}},
    }
    
    result = validator.validate_widget(widget)
    
    assert result.is_valid, f"Widget válido foi rejeitado: {result.issues}"
    assert not result.should_filter, "Widget válido não deve ser filtrado"
    assert len(result.issues) == 0, f"Widget válido não deve ter issues: {result.issues}"
    
    print("✅ Widget válido: PASSOU\n")


def test_missing_fields():
    """Testa widget com campos faltando"""
    print("🧪 Testando widget com campos faltando...")
    
    validator = WidgetValidator(create_test_question_validator())
    
    # Sem widget_key
    widget1 = {
        "type": "chart",
        "title": "Test",
        "question": "Test question?",
        "viz": {"type": "bar"},
    }
    result1 = validator.validate_widget(widget1)
    assert not result1.is_valid, "Widget sem widget_key deve ser inválido"
    assert result1.should_filter, "Widget sem widget_key deve ser filtrado"
    assert any(issue.code == "MISSING_WIDGET_KEY" for issue in result1.issues)
    
    # Sem type
    widget2 = {
        "widget_key": "w1",
        "title": "Test",
        "question": "Test question?",
        "viz": {"type": "bar"},
    }
    result2 = validator.validate_widget(widget2)
    assert not result2.is_valid, "Widget sem type deve ser inválido"
    
    # Sem question (exceto text)
    widget3 = {
        "widget_key": "w1",
        "type": "chart",
        "title": "Test",
        "viz": {"type": "bar"},
    }
    result3 = validator.validate_widget(widget3)
    assert not result3.is_valid, "Widget sem question deve ser inválido (exceto text)"
    assert any(issue.code == "MISSING_QUESTION" for issue in result3.issues)
    
    # Text widget sem question (OK)
    widget4 = {
        "widget_key": "w1",
        "type": "text",
        "title": "Info",
        "viz": {"type": "text", "content": "Some info"},
    }
    result4 = validator.validate_widget(widget4)
    assert result4.is_valid, "Widget text sem question deve ser válido"
    
    print("✅ Campos faltando: PASSOU\n")


def test_invalid_widget_type():
    """Testa widget com tipo inválido"""
    print("🧪 Testando widget com tipo inválido...")
    
    validator = WidgetValidator(create_test_question_validator())
    
    widget = {
        "widget_key": "w1",
        "type": "invalid_type",
        "title": "Test",
        "question": "Test question?",
        "viz": {"type": "bar"},
    }
    
    result = validator.validate_widget(widget)
    assert not result.is_valid, "Widget com tipo inválido deve ser inválido"
    assert result.should_filter, "Widget com tipo inválido deve ser filtrado"
    assert any(issue.code == "INVALID_WIDGET_TYPE" for issue in result.issues)
    
    print("✅ Tipo inválido: PASSOU\n")


def test_invalid_viz_type():
    """Testa widget com tipo de visualização inválido"""
    print("🧪 Testando widget com viz type inválido...")
    
    validator = WidgetValidator(create_test_question_validator())
    
    # Chart com viz type inválido
    widget1 = {
        "widget_key": "w1",
        "type": "chart",
        "title": "Test",
        "question": "Test question?",
        "viz": {"type": "kpi"},  # kpi não é válido para chart
    }
    result1 = validator.validate_widget(widget1)
    assert not result1.is_valid, "Chart com viz type inválido deve ser inválido"
    assert any(issue.code == "INVALID_VIZ_TYPE_FOR_WIDGET" for issue in result1.issues)
    
    # KPI sem viz
    widget2 = {
        "widget_key": "w1",
        "type": "kpi",
        "title": "Test",
        "question": "What is the total?",
    }
    result2 = validator.validate_widget(widget2)
    assert not result2.is_valid, "KPI sem viz deve ser inválido"
    assert any(issue.code == "MISSING_VIZ" for issue in result2.issues)
    
    print("✅ Viz type inválido: PASSOU\n")


def test_question_validation():
    """Testa validação de perguntas"""
    print("🧪 Testando validação de perguntas...")
    
    validator_non_strict = WidgetValidator(create_test_question_validator(), strict_mode=False)
    validator_strict = WidgetValidator(create_test_question_validator(), strict_mode=True)
    
    # Pergunta válida
    widget1 = {
        "widget_key": "w1",
        "type": "chart",
        "title": "Test",
        "question": "What is the total amount from invoices?",
        "viz": {"type": "bar", "mapping": {"x": "category", "y": "value"}},
    }
    result1 = validator_non_strict.validate_widget(widget1)
    assert result1.is_valid, "Pergunta válida deve passar"
    
    # Pergunta com filtro temporal restritivo (pode ou não ser detectado)
    widget2 = {
        "widget_key": "w1",
        "type": "chart",
        "title": "Test",
        "question": "What are the invoices from this month?",
        "viz": {"type": "bar", "mapping": {"x": "x", "y": "y"}},
    }
    result2_non_strict = validator_non_strict.validate_widget(widget2)
    result2_strict = validator_strict.validate_widget(widget2)
    
    # Em modo não-strict, warnings não devem filtrar
    # Em modo strict, se tiver warning, deve filtrar
    has_warning = any(issue.severity == ValidationSeverity.WARNING for issue in result2_strict.issues)
    if has_warning:
        assert not result2_non_strict.should_filter, "Em modo não-strict, warnings não devem filtrar"
        assert result2_strict.should_filter, "Em modo strict, warnings devem filtrar"
    
    print("✅ Validação de perguntas: PASSOU\n")


def test_filter_widgets():
    """Testa filtro de lista de widgets"""
    print("🧪 Testando filtro de widgets...")
    
    validator = WidgetValidator(create_test_question_validator(), strict_mode=True)
    
    widgets = [
        {
            "widget_key": "w1",
            "type": "chart",
            "title": "Valid Widget",
            "question": "What is the total amount from invoices?",
            "viz": {"type": "bar", "mapping": {"x": "category", "y": "value"}},
        },
        {
            "widget_key": "w2",
            "type": "invalid_type",  # Inválido
            "title": "Invalid Widget",
            "question": "Test?",
            "viz": {"type": "bar"},
        },
        {
            "widget_key": "w3",
            "type": "kpi",
            "title": "Valid KPI",
            "question": "What is the total amount?",
            "viz": {"type": "kpi"},
        },
    ]
    
    filtered = validator.filter_widgets(widgets, min_widgets=1)
    
    assert len(filtered) == 2, f"Deve filtrar 1 widget inválido, restam {len(filtered)}"
    assert all(w.get("widget_key") in ["w1", "w3"] for w in filtered), "Widgets filtrados incorretamente"
    
    print("✅ Filtro de widgets: PASSOU\n")


def main():
    """Executa todos os testes"""
    print("=" * 60)
    print("TESTE DO WIDGET VALIDATOR")
    print("=" * 60)
    print()
    
    try:
        test_valid_widget()
        test_missing_fields()
        test_invalid_widget_type()
        test_invalid_viz_type()
        test_question_validation()
        test_filter_widgets()
        
        print("=" * 60)
        print("✅ TODOS OS TESTES PASSARAM")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n❌ TESTE FALHOU: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERRO INESPERADO: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

