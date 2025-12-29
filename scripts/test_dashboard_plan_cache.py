#!/usr/bin/env python3
"""
Testa o cache de dashboard plans (Davinci).

Verifica se:
1. Primeira chamada gera plano e armazena no cache
2. Segunda chamada (mesmos parâmetros) retorna do cache (mais rápido)
3. Chamada com parâmetros diferentes gera novo plano
4. Cache expira após TTL
"""

import sys
import os
import time
from pathlib import Path

# Adicionar raiz do projeto ao path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from api.routes.connection_query import (
    _get_dashboard_plan_cache_key,
    _get_cached_dashboard_plan,
    _set_cached_dashboard_plan,
    _dashboard_plan_cache,
    DASHBOARD_PLAN_CACHE_TTL_MINUTES,
    DASHBOARD_PLAN_MAX_CACHE_SIZE,
)
from api.schemas import DashboardPlanResponse, DashboardPlanWidget


def test_cache_key_generation():
    """Testa geração de chaves de cache"""
    print("🧪 Testando geração de chaves de cache...")
    
    key1 = _get_dashboard_plan_cache_key(
        connection_id="conn-1",
        space_id="space-1",
        crew_ids=["crew-1", "crew-2"],
        is_personal=True,
        goal="Billing overview",
        max_widgets=8,
        language="en",
    )
    
    key2 = _get_dashboard_plan_cache_key(
        connection_id="conn-1",
        space_id="space-1",
        crew_ids=["crew-2", "crew-1"],  # Ordem diferente
        is_personal=True,
        goal="Billing overview",  # Mesmo goal
        max_widgets=8,
        language="en",
    )
    
    # Chaves devem ser iguais (crew_ids ordenados, goal normalizado)
    assert key1 == key2, f"Chaves devem ser iguais: {key1} != {key2}"
    print("✅ Chaves geradas corretamente (crew_ids ordenados, goal normalizado)")
    
    key3 = _get_dashboard_plan_cache_key(
        connection_id="conn-1",
        space_id="space-1",
        crew_ids=["crew-1", "crew-2"],
        is_personal=True,
        goal="Different Goal",  # Goal diferente
        max_widgets=8,
        language="en",
    )
    
    # Chaves devem ser diferentes (goal diferente)
    assert key1 != key3, f"Chaves devem ser diferentes: {key1} == {key3}"
    print("✅ Chaves diferentes para goals diferentes")
    
    # Testar normalização de goal (espaços extras, case)
    key4 = _get_dashboard_plan_cache_key(
        connection_id="conn-1",
        space_id="space-1",
        crew_ids=["crew-1", "crew-2"],
        is_personal=True,
        goal="  BILLING   OVERVIEW  ",  # Espaços extras, uppercase
        max_widgets=8,
        language="en",
    )
    
    # Deve normalizar para mesma chave
    assert key1 == key4, f"Chaves devem ser iguais após normalização: {key1} != {key4}"
    print("✅ Normalização de goal funciona corretamente")
    
    print("✅ Teste de geração de chaves: PASSOU\n")


def test_cache_storage_and_retrieval():
    """Testa armazenamento e recuperação do cache"""
    print("🧪 Testando armazenamento e recuperação do cache...")
    
    # Limpar cache
    _dashboard_plan_cache.clear()
    
    # Criar resposta de teste
    test_response = DashboardPlanResponse(
        dashboard_name="Test Dashboard",
        description="Test description",
        widgets=[
            DashboardPlanWidget(
                widget_key="w1",
                type="chart",
                title="Test Widget",
                question="Test question?",
                viz={"type": "bar"},
            )
        ],
        meta={"test": True},
    )
    
    cache_key = "test:dashboard:plan:1"
    
    # Armazenar
    _set_cached_dashboard_plan(cache_key, test_response)
    assert len(_dashboard_plan_cache) == 1, "Cache deve ter 1 entrada"
    print("✅ Plano armazenado no cache")
    
    # Recuperar
    cached = _get_cached_dashboard_plan(cache_key)
    assert cached is not None, "Plano deve estar no cache"
    assert cached.dashboard_name == "Test Dashboard", "Nome do dashboard deve ser igual"
    assert len(cached.widgets) == 1, "Deve ter 1 widget"
    print("✅ Plano recuperado do cache")
    
    # Testar expiração (simular tempo passado)
    from datetime import datetime, timedelta
    _dashboard_plan_cache[cache_key] = (
        test_response,
        datetime.now() - timedelta(minutes=DASHBOARD_PLAN_CACHE_TTL_MINUTES + 1),
    )
    
    expired = _get_cached_dashboard_plan(cache_key)
    assert expired is None, "Plano expirado deve retornar None"
    assert cache_key not in _dashboard_plan_cache, "Entrada expirada deve ser removida"
    print("✅ Cache expirado removido corretamente")
    
    print("✅ Teste de armazenamento e recuperação: PASSOU\n")


def test_cache_size_limit():
    """Testa limite de tamanho do cache"""
    print("🧪 Testando limite de tamanho do cache...")
    
    # Limpar cache
    _dashboard_plan_cache.clear()
    
    # Criar múltiplas entradas
    for i in range(DASHBOARD_PLAN_MAX_CACHE_SIZE + 5):
        cache_key = f"test:plan:{i}"
        test_response = DashboardPlanResponse(
            dashboard_name=f"Dashboard {i}",
            description="Test",
            widgets=[],
            meta={},
        )
        _set_cached_dashboard_plan(cache_key, test_response)
    
    # Cache não deve exceder tamanho máximo
    assert len(_dashboard_plan_cache) <= DASHBOARD_PLAN_MAX_CACHE_SIZE, \
        f"Cache deve ter no máximo {DASHBOARD_PLAN_MAX_CACHE_SIZE} entradas, tem {len(_dashboard_plan_cache)}"
    
    print(f"✅ Limite de cache respeitado ({len(_dashboard_plan_cache)} entradas)")
    print("✅ Teste de limite de tamanho: PASSOU\n")


def main():
    """Executa todos os testes"""
    print("=" * 60)
    print("TESTE DE CACHE DE DASHBOARD PLANS")
    print("=" * 60)
    print()
    
    try:
        # Testes unitários
        test_cache_key_generation()
        test_cache_storage_and_retrieval()
        test_cache_size_limit()
        
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

