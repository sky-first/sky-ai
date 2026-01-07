#!/usr/bin/env python3
"""
Script para testar as 15 perguntas de negócio e medir tempo de resposta.
"""
import asyncio
import time
import httpx
import json
from typing import List, Dict, Any

# Configuração
API_BASE_URL = "http://localhost:8001"  # AI Service roda na porta 8001
CONNECTION_ID = "afdf5872-e58e-4015-925b-a2f940df701c"
SPACE_ID = "ff9fc8ae-15c1-48f2-a12b-191a2c904a3d"
USER_ID = "test-user-15-questions"
CREW_IDS = ["5354e712-1096-4846-ab7f-62bf3d2a7aa9"]

# Headers
HEADERS = {
    "Content-Type": "application/json",
}

# 15 perguntas de negócio
QUESTIONS = [
    "Qual foi o total de vendas no último mês?",
    "Quais são os 10 produtos mais vendidos?",
    "Qual é a receita média por cliente?",
    "Quantos clientes novos tivemos este ano?",
    "Qual é o ticket médio de compra?",
    "Quais são as vendas por região?",
    "Qual é a taxa de crescimento mensal?",
    "Quais produtos têm estoque baixo?",
    "Qual é o faturamento por categoria?",
    "Quais são os clientes mais rentáveis?",
    "Qual é a margem de lucro por produto?",
    "Quantos pedidos foram cancelados?",
    "Qual é a média de itens por pedido?",
    "Quais vendedores têm melhor desempenho?",
    "Qual é a previsão de vendas para o próximo mês?",
]


async def test_question(client: httpx.AsyncClient, question: str, index: int) -> Dict[str, Any]:
    """Testa uma pergunta e retorna o resultado."""
    start_time = time.time()
    
    try:
        response = await client.post(
            f"{API_BASE_URL}/connections/{CONNECTION_ID}/query",
            json={
                "question": question,
                "user_id": USER_ID,
                "space_id": SPACE_ID,
                "crew_ids": CREW_IDS,
            },
            headers=HEADERS,
            timeout=120.0,
        )
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            data = response.json()
            return {
                "index": index + 1,
                "question": question,
                "status": "SUCCESS",
                "time_seconds": round(elapsed, 2),
                "sql": data.get("sql", "")[:100] + "..." if data.get("sql") else None,
                "row_count": len(data.get("data", [])) if data.get("data") else 0,
            }
        else:
            return {
                "index": index + 1,
                "question": question,
                "status": f"ERROR ({response.status_code})",
                "time_seconds": round(elapsed, 2),
                "error": response.text[:200],
            }
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "index": index + 1,
            "question": question,
            "status": "EXCEPTION",
            "time_seconds": round(elapsed, 2),
            "error": str(e)[:200],
        }


async def run_tests():
    """Executa todos os testes."""
    print("=" * 80)
    print("TESTE DAS 15 PERGUNTAS DE NEGÓCIO")
    print("=" * 80)
    print()
    
    # Verificar se o servidor está rodando
    async with httpx.AsyncClient() as client:
        try:
            health = await client.get(f"{API_BASE_URL}/health", timeout=5.0)
            if health.status_code != 200:
                print(f"❌ Servidor não está saudável: {health.status_code}")
                return
            print("✅ Servidor está rodando")
        except Exception as e:
            print(f"❌ Não foi possível conectar ao servidor: {e}")
            print(f"   Verifique se o servidor está rodando em {API_BASE_URL}")
            return
    
    print()
    print("Executando perguntas...")
    print("-" * 80)
    
    results: List[Dict[str, Any]] = []
    total_start = time.time()
    
    async with httpx.AsyncClient() as client:
        for i, question in enumerate(QUESTIONS):
            result = await test_question(client, question, i)
            results.append(result)
            
            status_icon = "✅" if result["status"] == "SUCCESS" else "❌"
            print(f"{status_icon} [{result['index']:02d}] {result['time_seconds']:5.1f}s - {question[:50]}...")
    
    total_time = time.time() - total_start
    
    # Resumo
    print()
    print("=" * 80)
    print("RESUMO")
    print("=" * 80)
    
    successful = [r for r in results if r["status"] == "SUCCESS"]
    failed = [r for r in results if r["status"] != "SUCCESS"]
    
    times = [r["time_seconds"] for r in successful]
    avg_time = sum(times) / len(times) if times else 0
    
    print(f"Total de perguntas: {len(QUESTIONS)}")
    print(f"Sucesso: {len(successful)}")
    print(f"Falhas: {len(failed)}")
    print(f"Tempo total: {total_time:.1f}s")
    print(f"Tempo médio por pergunta: {avg_time:.1f}s")
    
    if times:
        print(f"Tempo mínimo: {min(times):.1f}s")
        print(f"Tempo máximo: {max(times):.1f}s")
    
    if failed:
        print()
        print("Perguntas com falha:")
        for r in failed:
            print(f"  - [{r['index']:02d}] {r['question'][:40]}...")
            print(f"    Status: {r['status']}")
            if "error" in r:
                print(f"    Erro: {r['error'][:100]}")
    
    print()
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_tests())

