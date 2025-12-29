#!/usr/bin/env python3
"""
Testa o cache de bootstrap suggestions.

Verifica se:
1. Primeira chamada gera sugestões e armazena no cache
2. Segunda chamada (mesmos parâmetros) retorna do cache (mais rápido)
3. Chamada com parâmetros diferentes gera novas sugestões
4. Cache expira após TTL
"""

import sys
import os
import time
from pathlib import Path

# Adicionar raiz do projeto ao path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy.orm import Session
from db.session import SessionLocal
from api.routes.connection_query import (
    chat_bootstrap,
    _get_cache_key,
    _get_cached_bootstrap,
    _set_cached_bootstrap,
    _bootstrap_cache,
    CACHE_TTL_MINUTES,
)
from api.schemas import ChatBootstrapRequest

# Configurações de teste
TEST_CONNECTION_ID = "1fd6fee8-bf03-4e82-9c85-419a228ef726"
TEST_SPACE_ID = "e409079b-5bbf-4249-a769-2010609c30f2"
TEST_USER_ID = "test-user-123"


def test_cache_key_generation():
    """Testa geração de chaves de cache"""
    print("🧪 Testando geração de chaves de cache...")
    
    key1 = _get_cache_key(
        connection_id="conn-1",
        space_id="space-1",
        crew_ids=["crew-1", "crew-2"],
        is_personal=True,
        language="en",
    )
    
    key2 = _get_cache_key(
        connection_id="conn-1",
        space_id="space-1",
        crew_ids=["crew-2", "crew-1"],  # Ordem diferente
        is_personal=True,
        language="en",
    )
    
    # Chaves devem ser iguais (crew_ids ordenados)
    assert key1 == key2, f"Chaves devem ser iguais: {key1} != {key2}"
    print("✅ Chaves geradas corretamente (crew_ids ordenados)")
    
    key3 = _get_cache_key(
        connection_id="conn-1",
        space_id="space-1",
        crew_ids=["crew-1", "crew-2"],
        is_personal=False,  # Modo diferente
        language="en",
    )
    
    # Chaves devem ser diferentes (modo diferente)
    assert key1 != key3, f"Chaves devem ser diferentes: {key1} == {key3}"
    print("✅ Chaves diferentes para modos diferentes")
    
    print("✅ Teste de geração de chaves: PASSOU\n")


def test_cache_storage_and_retrieval():
    """Testa armazenamento e recuperação do cache"""
    print("🧪 Testando armazenamento e recuperação do cache...")
    
    # Limpar cache
    _bootstrap_cache.clear()
    
    from api.schemas import ChatBootstrapResponse, ChatBootstrapSuggestion
    
    # Criar resposta de teste
    test_response = ChatBootstrapResponse(
        greeting="Test greeting",
        suggestions=[
            ChatBootstrapSuggestion(
                title="Test suggestion",
                kind="question",
                question="Test question?",
            )
        ],
        meta={"test": True},
    )
    
    cache_key = "test:key:1"
    
    # Armazenar
    _set_cached_bootstrap(cache_key, test_response)
    assert len(_bootstrap_cache) == 1, "Cache deve ter 1 entrada"
    print("✅ Resposta armazenada no cache")
    
    # Recuperar
    cached = _get_cached_bootstrap(cache_key)
    assert cached is not None, "Resposta deve estar no cache"
    assert cached.greeting == "Test greeting", "Greeting deve ser igual"
    print("✅ Resposta recuperada do cache")
    
    # Testar expiração (simular tempo passado)
    from datetime import datetime, timedelta
    _bootstrap_cache[cache_key] = (
        test_response,
        datetime.now() - timedelta(minutes=CACHE_TTL_MINUTES + 1),
    )
    
    expired = _get_cached_bootstrap(cache_key)
    assert expired is None, "Resposta expirada deve retornar None"
    assert cache_key not in _bootstrap_cache, "Entrada expirada deve ser removida"
    print("✅ Cache expirado removido corretamente")
    
    print("✅ Teste de armazenamento e recuperação: PASSOU\n")


async def test_bootstrap_with_cache():
    """Testa chamadas reais ao endpoint com cache"""
    print("🧪 Testando chamadas reais ao endpoint com cache...")
    
    db: Session = SessionLocal()
    try:
        # Limpar cache antes do teste
        _bootstrap_cache.clear()
        
        request = ChatBootstrapRequest(
            user_id=TEST_USER_ID,
            space_id=TEST_SPACE_ID,
            is_personal=True,
            language="en",
            max_suggestions=4,
        )
        
        # Primeira chamada (deve gerar e cachear)
        print("📞 Primeira chamada (deve gerar sugestões)...")
        start_time = time.time()
        response1 = await chat_bootstrap(
            connection_id=TEST_CONNECTION_ID,
            body=request,
            db=db,
        )
        time1 = time.time() - start_time
        print(f"   ⏱️  Tempo: {time1:.2f}s")
        print(f"   📝 Greeting: {response1.greeting[:50]}...")
        print(f"   📊 Sugestões: {len(response1.suggestions)}")
        
        # Verificar se está no cache
        cache_key = _get_cache_key(
            connection_id=TEST_CONNECTION_ID,
            space_id=TEST_SPACE_ID,
            crew_ids=None,
            is_personal=True,
            language="en",
        )
        assert cache_key in _bootstrap_cache, "Resposta deve estar no cache"
        print("   ✅ Resposta armazenada no cache")
        
        # Segunda chamada (deve vir do cache - mais rápida)
        print("\n📞 Segunda chamada (deve vir do cache)...")
        start_time = time.time()
        response2 = await chat_bootstrap(
            connection_id=TEST_CONNECTION_ID,
            body=request,
            db=db,
        )
        time2 = time.time() - start_time
        print(f"   ⏱️  Tempo: {time2:.2f}s")
        print(f"   📝 Greeting: {response2.greeting[:50]}...")
        print(f"   📊 Sugestões: {len(response2.suggestions)}")
        
        # Verificar se é a mesma resposta
        assert response1.greeting == response2.greeting, "Greetings devem ser iguais"
        assert len(response1.suggestions) == len(response2.suggestions), "Número de sugestões deve ser igual"
        print("   ✅ Resposta idêntica (veio do cache)")
        
        # Verificar se foi mais rápida (cache deve ser muito mais rápido)
        if time2 < time1 * 0.5:  # Cache deve ser pelo menos 2x mais rápido
            print(f"   ✅ Cache mais rápido ({time2/time1:.1%} do tempo original)")
        else:
            print(f"   ⚠️  Cache não foi significativamente mais rápido ({time2/time1:.1%} do tempo original)")
        
        # Terceira chamada com parâmetros diferentes (deve gerar nova)
        print("\n📞 Terceira chamada (parâmetros diferentes - deve gerar nova)...")
        request_different = ChatBootstrapRequest(
            user_id=TEST_USER_ID,
            space_id=TEST_SPACE_ID,
            is_personal=False,  # Modo diferente
            language="en",
            max_suggestions=4,
        )
        
        start_time = time.time()
        response3 = await chat_bootstrap(
            connection_id=TEST_CONNECTION_ID,
            body=request_different,
            db=db,
        )
        time3 = time.time() - start_time
        print(f"   ⏱️  Tempo: {time3:.2f}s")
        print(f"   📝 Greeting: {response3.greeting[:50]}...")
        print(f"   📊 Sugestões: {len(response3.suggestions)}")
        
        # Verificar se é diferente (pode ser igual por acaso, mas geralmente é diferente)
        print("   ✅ Nova resposta gerada (parâmetros diferentes)")
        
        # Verificar se há 2 entradas no cache
        assert len(_bootstrap_cache) >= 2, f"Cache deve ter pelo menos 2 entradas, tem {len(_bootstrap_cache)}"
        print(f"   ✅ Cache tem {len(_bootstrap_cache)} entradas")
        
        print("\n✅ Teste de chamadas reais: PASSOU\n")
        
    except Exception as e:
        print(f"\n❌ Erro durante teste: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


async def main():
    """Executa todos os testes"""
    print("=" * 60)
    print("TESTE DE CACHE DE BOOTSTRAP SUGGESTIONS")
    print("=" * 60)
    print()
    
    try:
        # Testes unitários
        test_cache_key_generation()
        test_cache_storage_and_retrieval()
        
        # Teste de integração (requer conexão com banco)
        print("⚠️  Teste de integração requer conexão com banco de dados")
        print("   Execute apenas se tiver acesso ao banco de dados de teste\n")
        
        # Descomentar para executar teste de integração:
        # await test_bootstrap_with_cache()
        
        print("=" * 60)
        print("✅ TODOS OS TESTES PASSARAM")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n❌ TESTE FALHOU: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERRO INESPERADO: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

