#!/usr/bin/env python3
"""
Script de teste para o sistema de validação genérico.

Testa QuestionValidator e SuggestionValidator com casos reais.
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
load_dotenv()

# Adicionar o diretório raiz do projeto ao PYTHONPATH
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.validation.question_validator import QuestionValidator, ValidationSeverity
from core.validation.suggestion_validator import SuggestionValidator


def test_question_validator():
    """Testa QuestionValidator com casos diversos"""
    print("="*80)
    print("🧪 TESTE DO QUESTION VALIDATOR")
    print("="*80)
    
    # Simular metadados de tabelas (genérico, não específico de billing)
    available_tables = [
        {"name": "invoices", "logical_name": "invoices"},
        {"name": "customers", "logical_name": "customers"},
        {"name": "items", "logical_name": "items"},
        {"name": "payments", "logical_name": "payments"},
    ]
    
    available_columns = {
        "invoices": ["invoice_id", "customer_id", "invoice_date", "total_amount"],
        "customers": ["customer_id", "customer_name", "country"],
        "items": ["item_id", "invoice_id", "item_name", "quantity"],
        "payments": ["payment_id", "invoice_id", "payment_amount", "payment_date"],
    }
    
    validator = QuestionValidator(available_tables, available_columns)
    
    # Casos de teste
    test_cases = [
        {
            "question": "Quais são os valores de créditos por cliente?",
            "expected_issues": 0,
            "description": "Pergunta válida e clara",
        },
        {
            "question": "Quais itens foram vendidos em uma fatura específica?",
            "expected_issues": 1,  # Deve detectar ambiguidade
            "description": "Pergunta ambígua (requer fatura específica)",
        },
        {
            "question": "Primeiro mostre as faturas e depois os pagamentos",
            "expected_issues": 1,  # Deve detectar múltiplas queries
            "description": "Pergunta que pode gerar múltiplas queries",
        },
        {
            "question": "Quais faturas estão próximas do vencimento hoje?",
            "expected_issues": 1,  # Pode detectar possível resultado vazio
            "description": "Pergunta com filtro temporal restritivo",
        },
        {
            "question": "Quais colunas tem na tabela 'orders'?",
            "expected_issues": 1,  # Deve detectar referência a tabela inexistente
            "description": "Pergunta referenciando tabela que não existe",
        },
        {
            "question": "Qual é o total de pagamentos por mês?",
            "expected_issues": 0,
            "description": "Pergunta válida e clara",
        },
        {
            "question": "Esta é uma pergunta extremamente longa que contém muitas palavras e informações detalhadas sobre múltiplos aspectos diferentes do sistema de faturamento incluindo clientes pagamentos faturas créditos reembolsos e muitos outros elementos que tornam a pergunta muito complexa e difícil de processar de uma só vez porque ela tenta cobrir muitos tópicos diferentes simultaneamente",
            "expected_issues": 1,  # Deve detectar complexidade
            "description": "Pergunta muito longa e complexa",
        },
        {
            "question": "Mostre os dados de faturas e pagamentos e clientes e itens e créditos e reembolsos todos juntos com todas as informações detalhadas",
            "expected_issues": 1,  # Deve detectar complexidade (muitas condições)
            "description": "Pergunta com muitas condições (múltiplos 'e')",
        },
    ]
    
    print("\n📝 Executando testes...\n")
    
    passed = 0
    failed = 0
    
    for i, test_case in enumerate(test_cases, 1):
        question = test_case["question"]
        expected_issues = test_case["expected_issues"]
        description = test_case["description"]
        
        print(f"Teste {i}: {description}")
        print(f"  Pergunta: {question}")
        
        results = validator.validate_question(question)
        
        # Contar issues por severidade
        errors = [r for r in results if r.severity == ValidationSeverity.ERROR]
        warnings = [r for r in results if r.severity == ValidationSeverity.WARNING]
        infos = [r for r in results if r.severity == ValidationSeverity.INFO]
        
        print(f"  Resultados: {len(errors)} erros, {len(warnings)} warnings, {len(infos)} infos")
        
        if results:
            for result in results:
                print(f"    [{result.severity.value.upper()}] {result.code}: {result.message}")
                if result.suggestion:
                    print(f"      💡 {result.suggestion}")
        
        # Validar se encontrou issues quando esperado
        total_issues = len(results)
        if total_issues == expected_issues:
            print(f"  ✅ PASSOU (esperado {expected_issues} issues, encontrado {total_issues})")
            passed += 1
        else:
            print(f"  ❌ FALHOU (esperado {expected_issues} issues, encontrado {total_issues})")
            failed += 1
        
        print()
    
    print("="*80)
    print(f"📊 RESUMO: {passed} passou, {failed} falhou")
    print("="*80)
    
    return failed == 0


def test_suggestion_validator():
    """Testa SuggestionValidator"""
    print("\n" + "="*80)
    print("🧪 TESTE DO SUGGESTION VALIDATOR")
    print("="*80)
    
    # Mesmos metadados
    available_tables = [
        {"name": "invoices", "logical_name": "invoices"},
        {"name": "customers", "logical_name": "customers"},
    ]
    
    available_columns = {
        "invoices": ["invoice_id", "customer_id", "total_amount"],
        "customers": ["customer_id", "customer_name"],
    }
    
    question_validator = QuestionValidator(available_tables, available_columns)
    suggestion_validator = SuggestionValidator(question_validator)
    
    suggestions = [
        "Qual é o total de faturas?",  # Válida
        "Quais itens foram vendidos em uma fatura específica?",  # Ambígua
        "Primeiro mostre faturas e depois pagamentos",  # Múltiplas queries
        "Quantos clientes temos?",  # Válida
    ]
    
    print("\n📝 Testando sugestões...\n")
    
    for i, suggestion in enumerate(suggestions, 1):
        print(f"{i}. {suggestion}")
        
        is_valid, issues = suggestion_validator.validate_suggestion(suggestion)
        should_filter = suggestion_validator.should_filter_suggestion(suggestion)
        score = suggestion_validator.get_suggestion_score(suggestion)
        
        print(f"   ✅ Válida: {is_valid}")
        print(f"   🚫 Filtrar: {should_filter}")
        print(f"   📊 Score: {score:.2f}")
        
        if issues:
            print(f"   ⚠️  Issues: {len(issues)}")
            for issue in issues:
                print(f"      - [{issue.severity.value}] {issue.code}")
        
        print()
    
    print("="*80)


def main():
    """Função principal"""
    print("🧪 TESTES DO SISTEMA DE VALIDAÇÃO")
    print()
    
    # Teste 1: QuestionValidator
    test1_passed = test_question_validator()
    
    # Teste 2: SuggestionValidator
    test_suggestion_validator()
    
    if test1_passed:
        print("\n✅ Todos os testes básicos passaram!")
        return 0
    else:
        print("\n❌ Alguns testes falharam. Revise os resultados acima.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

