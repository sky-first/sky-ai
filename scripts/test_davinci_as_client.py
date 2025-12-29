#!/usr/bin/env python3
"""
Testa o sistema Davinci como cliente real.

Testa:
1. Geração de planos de dashboard
2. Validação de widgets
3. Cache de planos
4. Performance e qualidade
"""

import os
import sys
import time
import asyncio
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

# Adicionar raiz do projeto ao path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy.orm import Session
from db.session import SessionLocal
from api.routes.connection_query import dashboards_plan
from api.schemas import DashboardPlanRequest

# Configurações de teste
TEST_CONNECTION_ID = os.getenv("TEST_CONNECTION_ID") or "1fd6fee8-bf03-4e82-9c85-419a228ef726"
TEST_SPACE_ID = os.getenv("TEST_SPACE_ID") or "e409079b-5bbf-4249-a769-2010609c30f2"
TEST_USER_ID = os.getenv("TEST_USER_ID") or "00000000-0000-0000-0000-000000000000"


def analyze_widget_quality(widgets: list) -> dict:
    """Analisa qualidade dos widgets gerados"""
    analysis = {
        "total": len(widgets),
        "by_type": {},
        "with_joins": 0,
        "with_restrictive_filters": 0,
        "valid_structure": 0,
        "issues": [],
    }
    
    restrictive_patterns = ["this month", "last month", "recent", "upcoming", "pending", "este mês", "último mês"]
    
    for widget in widgets:
        # Contar por tipo
        widget_type = widget.get("type") or "unknown"
        analysis["by_type"][widget_type] = analysis["by_type"].get(widget_type, 0) + 1
        
        # Verificar estrutura
        has_key = bool(widget.get("widget_key"))
        has_type = bool(widget.get("type"))
        has_title = bool(widget.get("title"))
        has_question = bool(widget.get("question")) or widget_type == "text"
        has_viz = bool(widget.get("viz")) or widget_type == "text"
        
        if has_key and has_type and has_title and has_question and has_viz:
            analysis["valid_structure"] += 1
        else:
            analysis["issues"].append({
                "widget": widget.get("widget_key", "unknown"),
                "missing": [k for k, v in [
                    ("widget_key", has_key),
                    ("type", has_type),
                    ("title", has_title),
                    ("question", has_question),
                    ("viz", has_viz),
                ] if not v]
            })
        
        # Verificar JOINs (menciona 2+ tabelas ou tem palavra "JOIN")
        question = (widget.get("question") or "").lower()
        # Detectar JOINs: palavra "join" ou múltiplas tabelas mencionadas
        if "join" in question or question.count("`") >= 4:  # 2 tabelas = 4 backticks
            analysis["with_joins"] += 1
        
        # Verificar filtros temporais restritivos
        for pattern in restrictive_patterns:
            if pattern in question:
                analysis["with_restrictive_filters"] += 1
                break
    
    return analysis


async def test_dashboard_plan_generation():
    """Testa geração de plano de dashboard"""
    print("=" * 70)
    print("TESTE DE GERAÇÃO DE PLANO DE DASHBOARD (DAVINCI)")
    print("=" * 70)
    print()
    
    db: Session = SessionLocal()
    
    try:
        # Teste 1: Primeira chamada (deve gerar e cachear)
        print("📞 TESTE 1: Primeira chamada (gera plano)")
        print("-" * 70)
        
        request1 = DashboardPlanRequest(
            user_id=TEST_USER_ID,
            space_id=TEST_SPACE_ID,
            is_personal=True,
            language="en",
            goal="Billing overview",
            max_widgets=8,
        )
        
        start_time = time.time()
        response1 = await dashboards_plan(
            connection_id=TEST_CONNECTION_ID,
            body=request1,
            db=db,
        )
        time1 = time.time() - start_time
        
        print(f"   ⏱️  Tempo: {time1:.2f}s")
        print(f"   📊 Dashboard: {response1.dashboard_name}")
        print(f"   📝 Descrição: {response1.description or 'N/A'}")
        print(f"   📦 Widgets: {len(response1.widgets)}")
        
        # Análise de qualidade
        widgets_dict = [w.model_dump() if hasattr(w, 'model_dump') else (w.dict() if hasattr(w, 'dict') else w) for w in response1.widgets]
        analysis1 = analyze_widget_quality(widgets_dict)
        
        print(f"\n   📈 Análise de Qualidade:")
        print(f"      - Estrutura válida: {analysis1['valid_structure']}/{analysis1['total']}")
        print(f"      - Por tipo: {analysis1['by_type']}")
        print(f"      - Com JOINs: {analysis1['with_joins']}")
        print(f"      - Com filtros restritivos: {analysis1['with_restrictive_filters']}")
        
        if analysis1['issues']:
            print(f"      ⚠️  Problemas encontrados: {len(analysis1['issues'])}")
            for issue in analysis1['issues'][:3]:  # Mostrar apenas primeiros 3
                print(f"         - Widget {issue['widget']}: faltando {', '.join(issue['missing'])}")
        
        # Verificar meta
        if response1.meta:
            cached = response1.meta.get("cached", True)
            print(f"   💾 Cache: {'SIM (veio do cache)' if cached else 'NÃO (gerado agora)'}")
        
        print()
        
        # Teste 2: Segunda chamada (mesmos parâmetros - deve vir do cache)
        print("📞 TESTE 2: Segunda chamada (mesmos parâmetros - deve vir do cache)")
        print("-" * 70)
        
        request2 = DashboardPlanRequest(
            user_id=TEST_USER_ID,
            space_id=TEST_SPACE_ID,
            is_personal=True,
            language="en",
            goal="Billing overview",  # Mesmo goal
            max_widgets=8,
        )
        
        start_time = time.time()
        response2 = await dashboards_plan(
            connection_id=TEST_CONNECTION_ID,
            body=request2,
            db=db,
        )
        time2 = time.time() - start_time
        
        print(f"   ⏱️  Tempo: {time2:.2f}s")
        print(f"   📊 Dashboard: {response2.dashboard_name}")
        print(f"   📦 Widgets: {len(response2.widgets)}")
        
        # Verificar se é a mesma resposta (cache)
        if response1.dashboard_name == response2.dashboard_name:
            print("   ✅ Resposta idêntica (veio do cache)")
        else:
            print("   ⚠️  Resposta diferente (pode não ter usado cache)")
        
        # Verificar performance do cache
        if time2 < time1 * 0.5:
            print(f"   ✅ Cache mais rápido ({time2/time1:.1%} do tempo original)")
        else:
            print(f"   ⚠️  Cache não foi significativamente mais rápido ({time2/time1:.1%} do tempo original)")
        
        if response2.meta:
            cached = response2.meta.get("cached", True)
            print(f"   💾 Cache: {'SIM (veio do cache)' if cached else 'NÃO (gerado agora)'}")
        
        print()
        
        # Teste 3: Terceira chamada (goal diferente - deve gerar novo)
        print("📞 TESTE 3: Terceira chamada (goal diferente - deve gerar novo plano)")
        print("-" * 70)
        
        request3 = DashboardPlanRequest(
            user_id=TEST_USER_ID,
            space_id=TEST_SPACE_ID,
            is_personal=True,
            language="en",
            goal="Revenue analysis",  # Goal diferente
            max_widgets=8,
        )
        
        start_time = time.time()
        response3 = await dashboards_plan(
            connection_id=TEST_CONNECTION_ID,
            body=request3,
            db=db,
        )
        time3 = time.time() - start_time
        
        print(f"   ⏱️  Tempo: {time3:.2f}s")
        print(f"   📊 Dashboard: {response3.dashboard_name}")
        print(f"   📦 Widgets: {len(response3.widgets)}")
        
        # Verificar se é diferente
        if response3.dashboard_name != response1.dashboard_name:
            print("   ✅ Novo plano gerado (goal diferente)")
        else:
            print("   ⚠️  Mesmo nome (pode ser coincidência)")
        
        if response3.meta:
            cached = response3.meta.get("cached", True)
            print(f"   💾 Cache: {'SIM (veio do cache)' if cached else 'NÃO (gerado agora)'}")
        
        print()
        
        # Resumo final
        print("=" * 70)
        print("RESUMO DOS TESTES")
        print("=" * 70)
        print(f"✅ Teste 1 (Primeira chamada): {time1:.2f}s - {len(response1.widgets)} widgets")
        print(f"✅ Teste 2 (Cache): {time2:.2f}s - {len(response2.widgets)} widgets ({time2/time1:.1%} do tempo)")
        print(f"✅ Teste 3 (Goal diferente): {time3:.2f}s - {len(response3.widgets)} widgets")
        print()
        print("📊 Qualidade dos Widgets (Teste 1):")
        print(f"   - Estrutura válida: {analysis1['valid_structure']}/{analysis1['total']}")
        print(f"   - Distribuição: {analysis1['by_type']}")
        print(f"   - JOINs: {analysis1['with_joins']} widgets")
        print(f"   - Filtros restritivos: {analysis1['with_restrictive_filters']} widgets")
        print()
        
        if time2 < time1 * 0.5:
            print("✅ CACHE FUNCIONANDO: Segunda chamada foi significativamente mais rápida")
        else:
            print("⚠️  CACHE PODE NÃO ESTAR FUNCIONANDO: Segunda chamada não foi muito mais rápida")
        
        if analysis1['valid_structure'] == analysis1['total']:
            print("✅ VALIDAÇÃO FUNCIONANDO: Todos os widgets têm estrutura válida")
        else:
            print(f"⚠️  VALIDAÇÃO: {analysis1['total'] - analysis1['valid_structure']} widgets com problemas de estrutura")
        
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ ERRO durante teste: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


async def main():
    """Executa todos os testes"""
    try:
        await test_dashboard_plan_generation()
    except KeyboardInterrupt:
        print("\n\n⚠️  Teste interrompido pelo usuário")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ ERRO INESPERADO: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

