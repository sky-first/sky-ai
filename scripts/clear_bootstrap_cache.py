#!/usr/bin/env python3
"""
Script para limpar o cache de bootstrap (útil quando há problemas com cache antigo).
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Adicionar raiz do projeto ao path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from api.routes.connection_query import _bootstrap_cache, _dashboard_plan_cache


def clear_caches():
    """Limpa todos os caches"""
    print("=" * 70)
    print("LIMPEZA DE CACHE")
    print("=" * 70)
    print()

    bootstrap_size = len(_bootstrap_cache)
    dashboard_size = len(_dashboard_plan_cache)

    print(f"📊 Cache Bootstrap: {bootstrap_size} entradas")
    print(f"📊 Cache Dashboard Plan: {dashboard_size} entradas")
    print()

    if bootstrap_size > 0:
        _bootstrap_cache.clear()
        print("✅ Cache Bootstrap limpo!")

    if dashboard_size > 0:
        _dashboard_plan_cache.clear()
        print("✅ Cache Dashboard Plan limpo!")

    if bootstrap_size == 0 and dashboard_size == 0:
        print("ℹ️  Caches já estavam vazios")

    print()
    print("=" * 70)
    print("✅ LIMPEZA CONCLUÍDA")
    print("=" * 70)
    print()
    print("💡 Agora as próximas chamadas vão gerar novas respostas sem cache")
    print("💡 O card 'Create dashboard' deve aparecer nas novas respostas")


if __name__ == "__main__":
    clear_caches()
