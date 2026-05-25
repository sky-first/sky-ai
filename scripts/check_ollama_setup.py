#!/usr/bin/env python3
"""Script para verificar setup do Ollama e Modelos"""

import sys
import os
import httpx
import asyncio

# Adicionar root ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings


async def check_ollama():
    print("=" * 60)
    print("VERIFICAÇÃO DO OLLAMA")
    print("=" * 60)
    print(f"URL Configurda: {settings.ollama_base_url}")

    try:
        # 1. Testar conexão
        print("\n1. Testando conexão com Ollama...")
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")

        if resp.status_code != 200:
            print(f"❌ Erro ao conectar: Status {resp.status_code}")
            return False

        data = resp.json()
        models = [m["name"] for m in data.get("models", [])]
        print("✅ Conexão estabelecida!")
        print(f"📊 Modelos encontrados: {len(models)}")

        # 2. Verificar modelos necessários
        required_models = {
            "Embedding": settings.llm_model_embedding_local,
            "Orchestrator": settings.llm_model_orchestrator_local,
            "Specialist": settings.llm_model_specialist_local,
        }

        print("\n2. Verificando modelos necessários:")
        all_ok = True

        # Normalizar nomes (remover tags :latest se não especificadas)
        available_models = set(m.split(":")[0] for m in models)
        available_models_full = set(models)

        for role, model_name in required_models.items():
            # Check exact match or base name match
            base_name = model_name.split(":")[0]

            if model_name in available_models_full or base_name in available_models:
                print(f"  ✅ {role}: {model_name} (Encontrado)")
            else:
                print(f"  ❌ {role}: {model_name} (NÃO ENCONTRADO)")
                print(f"     Sugestão: ollama pull {model_name}")
                all_ok = False

        if all_ok:
            print("\n✅ Todos os modelos estão prontos!")
            return True
        else:
            print(
                "\n⚠️  Alguns modelos estão faltando. Execute 'ollama pull <modelo>' no servidor remoto."
            )
            return False

    except httpx.ConnectError:
        print("❌ Falha na conexão: Não foi possível conectar ao Ollama.")
        print(
            "   Verifique se o túnel SSH está rodando: ssh -L 11434:localhost:11434 ..."
        )
        return False
    except Exception as e:
        print(f"❌ Erro inesperado: {repr(e)}")
        import traceback

        traceback.print_exc()
        return False

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(check_ollama())
