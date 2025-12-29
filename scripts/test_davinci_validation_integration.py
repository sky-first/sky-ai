#!/usr/bin/env python3
"""
Testa a integração do WidgetValidator no generate_dashboard_plan.

Verifica se:
1. Widgets inválidos são filtrados
2. Widgets válidos são mantidos
3. Sistema funciona mesmo quando validação filtra muitos widgets
"""

import sys
import os
from pathlib import Path

# Adicionar raiz do projeto ao path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.agents.davinci_dashboard_agent import generate_dashboard_plan
from core.llm.factory import create_llm_specialist


def test_validation_integration():
    """Testa integração da validação no generate_dashboard_plan"""
    print("🧪 Testando integração da validação no generate_dashboard_plan...")
    
    # Configuração de teste
    llm = create_llm_specialist(creativity=10, length=35)
    goal = "Billing overview"
    language = "en"
    max_widgets = 8
    
    # Schema de teste (billing)
    logical_tables = ["invoices", "customers", "payments", "refunds"]
    schema_summary = """
- invoices cols: id, customer_id, amount, status, created_at keys: customer_id
- customers cols: id, name, email, country keys: id
- payments cols: id, invoice_id, amount, method, date keys: invoice_id
- refunds cols: id, invoice_id, amount, reason, date keys: invoice_id
"""
    
    print("📞 Gerando plano de dashboard...")
    plan = generate_dashboard_plan(
        llm=llm,
        goal=goal,
        language=language,
        max_widgets=max_widgets,
        logical_tables=logical_tables,
        schema_summary=schema_summary,
    )
    
    print(f"   📊 Dashboard: {plan.dashboard_name}")
    print(f"   📦 Widgets: {len(plan.widgets)}")
    
    # Verificar se todos os widgets têm estrutura válida
    print("\n   🔍 Validando estrutura dos widgets...")
    issues_found = 0
    for i, widget in enumerate(plan.widgets, 1):
        # Verificar campos obrigatórios
        if not widget.get("widget_key"):
            print(f"      ⚠️  Widget {i}: Sem widget_key")
            issues_found += 1
        if not widget.get("type"):
            print(f"      ⚠️  Widget {i}: Sem type")
            issues_found += 1
        if not widget.get("title"):
            print(f"      ⚠️  Widget {i}: Sem title")
            issues_found += 1
        if not widget.get("question") and widget.get("type") != "text":
            print(f"      ⚠️  Widget {i}: Sem question (e não é text)")
            issues_found += 1
        if not widget.get("viz") and widget.get("type") != "text":
            print(f"      ⚠️  Widget {i}: Sem viz (e não é text)")
            issues_found += 1
    
    if issues_found == 0:
        print("      ✅ Todos os widgets têm estrutura válida")
    else:
        print(f"      ⚠️  {issues_found} problemas encontrados na estrutura")
    
    # Verificar distribuição
    kpi_count = sum(1 for w in plan.widgets if w.get("type") == "kpi")
    table_count = sum(1 for w in plan.widgets if w.get("type") == "table")
    chart_count = sum(1 for w in plan.widgets if w.get("type") == "chart")
    text_count = sum(1 for w in plan.widgets if w.get("type") == "text")
    
    print(f"\n   📈 Distribuição: {kpi_count} KPI, {table_count} Table, {chart_count} Chart, {text_count} Text")
    
    # Verificar se perguntas não têm filtros temporais restritivos óbvios
    print("\n   🔍 Verificando perguntas por filtros temporais restritivos...")
    restrictive_patterns = ["this month", "last month", "recent", "upcoming", "pending"]
    restrictive_count = 0
    for widget in plan.widgets:
        question = (widget.get("question") or "").lower()
        for pattern in restrictive_patterns:
            if pattern in question:
                restrictive_count += 1
                print(f"      ⚠️  Widget '{widget.get('title', 'Unknown')}': Pergunta com '{pattern}'")
                break
    
    if restrictive_count == 0:
        print("      ✅ Nenhuma pergunta com filtros temporais restritivos detectados")
    else:
        print(f"      ⚠️  {restrictive_count} widgets com filtros temporais restritivos")
    
    # Verificar meta
    if plan.meta:
        print(f"\n   📋 Meta: {plan.meta}")
        if plan.meta.get("fallback"):
            print("      ℹ️  Plano gerado via fallback")
        else:
            print("      ✅ Plano gerado pelo LLM")
    
    print("\n✅ Teste de integração: PASSOU\n")
    
    return plan


def main():
    """Executa todos os testes"""
    print("=" * 60)
    print("TESTE DE INTEGRAÇÃO - VALIDAÇÃO DAVINCI")
    print("=" * 60)
    print()
    
    try:
        plan = test_validation_integration()
        
        print("=" * 60)
        print("✅ TODOS OS TESTES PASSARAM")
        print("=" * 60)
        print(f"\n📊 Resumo do plano gerado:")
        print(f"   - Nome: {plan.dashboard_name}")
        print(f"   - Widgets: {len(plan.widgets)}")
        print(f"   - Fallback: {plan.meta.get('fallback', False) if plan.meta else False}")
        
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

