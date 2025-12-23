#!/usr/bin/env python3
"""
Script de Testes para Funcionalidade de JOINs via API

Testa se o sistema consegue gerar JOINs através da API.
Mais simples que test_joins.py pois não precisa de acesso direto ao banco.

Uso:
    python3 scripts/test_joins_api.py
    
Requisitos:
    - API rodando (python3 run_api.py)
    - Variáveis de ambiente configuradas (.env)
"""

from __future__ import annotations

import os
import sys
import json
import requests
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

# Adicionar o diretório raiz do projeto ao PYTHONPATH
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


# ============== CONFIGURAÇÃO ==============

API_BASE_URL = os.getenv("API_BASE_URL") or "http://localhost:8000"
TEST_SPACE_ID = os.getenv("TEST_SPACE_ID") or "00000000-0000-0000-0000-000000000001"
TEST_CONNECTION_ID = os.getenv("TEST_CONNECTION_ID") or "00000000-0000-0000-0000-000000000002"
TEST_USER_ID = os.getenv("TEST_USER_ID") or "test_user"

# Perguntas que devem requerer JOINs
JOIN_TEST_QUESTIONS = [
    {
        "question": "Quais são os pageviews por país e dispositivo?",
        "description": "Deve usar pageviews + sources (ou similar) com JOIN",
        "expected_keywords": ["join", "pageviews", "país", "dispositivo"],
    },
    {
        "question": "Como se relacionam eventos e sessões?",
        "description": "Deve usar events + sessions com JOIN",
        "expected_keywords": ["join", "eventos", "sessões"],
    },
    {
        "question": "Quais usuários têm mais pageviews?",
        "description": "Deve usar users + pageviews com JOIN",
        "expected_keywords": ["join", "usuários", "pageviews"],
    },
    {
        "question": "Mostre pageviews e eventos juntos",
        "description": "Deve usar pageviews + events com JOIN",
        "expected_keywords": ["join", "pageviews", "eventos"],
    },
    {
        "question": "Combine dados de pageviews com informações de usuários",
        "description": "Deve usar pageviews + users com JOIN",
        "expected_keywords": ["join", "pageviews", "usuários"],
    },
]


def test_api_health() -> bool:
    """Verifica se a API está rodando"""
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Erro ao conectar na API: {e}")
        return False


def test_join_query(question: str, description: str) -> dict:
    """Testa uma pergunta via API que deve gerar JOIN"""
    print(f"\n{'='*60}")
    print(f"🧪 TESTE: {description}")
    print(f"{'='*60}")
    print(f"❓ Pergunta: {question}")
    
    url = f"{API_BASE_URL}/connections/{TEST_CONNECTION_ID}/query"
    
    payload = {
        "question": question,
        "user_id": TEST_USER_ID,
        "space_id": TEST_SPACE_ID,
    }
    
    try:
        response = requests.post(url, json=payload, timeout=60)
        
        if response.status_code != 200:
            print(f"\n❌ Erro HTTP {response.status_code}: {response.text[:200]}")
            return {
                "question": question,
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text[:200]}",
            }
        
        data = response.json()
        
        # Extrair informações
        sql = data.get("data_sample", {}).get("sql") or data.get("sql")
        answer = data.get("answer", "")
        meta = data.get("meta", {})
        chosen_table = meta.get("chosen_table")
        chosen_tables = meta.get("chosen_tables")
        
        print(f"\n📊 Resultados:")
        print(f"  - Tabela(s) escolhida(s): {chosen_tables or chosen_table or 'N/A'}")
        print(f"  - SQL gerado: {'SIM' if sql else 'NÃO'}")
        print(f"  - Resposta: {'SIM' if answer else 'NÃO'}")
        
        if sql:
            print(f"\n📝 SQL:")
            print(f"```sql")
            sql_preview = sql[:500] + ("..." if len(sql) > 500 else "")
            print(sql_preview)
            print(f"```")
            
            # Verificar se tem JOIN
            sql_lower = sql.lower()
            has_join = any(keyword in sql_lower for keyword in ["join", "inner join", "left join", "right join"])
            has_multiple_from = sql_lower.count("from") > 1
            
            print(f"\n  {'✅' if has_join else '❌'} Contém JOIN: {has_join}")
            print(f"  {'✅' if has_multiple_from else '❌'} Múltiplas tabelas no FROM: {has_multiple_from}")
            
            if has_join:
                # Extrair tipos de JOIN
                join_types = []
                if "inner join" in sql_lower:
                    join_types.append("INNER JOIN")
                if "left join" in sql_lower:
                    join_types.append("LEFT JOIN")
                if "right join" in sql_lower:
                    join_types.append("RIGHT JOIN")
                if "join" in sql_lower and not join_types:
                    join_types.append("JOIN")
                
                print(f"  📋 Tipos de JOIN encontrados: {', '.join(join_types) if join_types else 'Nenhum'}")
        
        # Verificar se múltiplas tabelas foram escolhidas
        multiple_tables = (
            chosen_tables and len(chosen_tables) > 1
        ) or (
            chosen_table and "," in chosen_table
        )
        
        success = (
            sql and 
            (has_join if sql else False) and
            multiple_tables
        )
        
        if success:
            print(f"\n✅ TESTE PASSOU!")
        else:
            print(f"\n❌ TESTE FALHOU!")
            if not sql:
                print(f"   → Nenhum SQL foi gerado")
            if not has_join:
                print(f"   → SQL não contém JOIN")
            if not multiple_tables:
                print(f"   → Apenas uma tabela foi escolhida")
        
        return {
            "question": question,
            "success": success,
            "chosen_tables": chosen_tables or [chosen_table] if chosen_table else [],
            "has_join": has_join if sql else False,
            "join_types": join_types if sql and has_join else [],
            "sql": sql[:300] if sql else None,
            "answer": answer[:200] if answer else None,
            "error": None,
        }
        
    except requests.exceptions.Timeout:
        print(f"\n❌ Timeout ao executar query (pode estar demorando muito)")
        return {
            "question": question,
            "success": False,
            "error": "Timeout",
        }
    except Exception as e:
        print(f"\n❌ ERRO ao executar teste: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "question": question,
            "success": False,
            "error": str(e),
        }


def main():
    """Executa todos os testes de JOIN via API"""
    print("="*60)
    print("🚀 TESTES DE FUNCIONALIDADE DE JOINs (via API)")
    print("="*60)
    
    # Verificar se API está rodando
    print(f"\n🔍 Verificando API em {API_BASE_URL}...")
    if not test_api_health():
        print(f"\n❌ API não está respondendo!")
        print(f"   Por favor, inicie a API com: python3 run_api.py")
        return
    
    print(f"✅ API está respondendo!")
    
    # Executar testes
    print(f"\n{'='*60}")
    print("🔬 EXECUTANDO TESTES DE JOIN")
    print(f"{'='*60}")
    
    results = []
    for test_case in JOIN_TEST_QUESTIONS:
        result = test_join_query(
            question=test_case["question"],
            description=test_case["description"],
        )
        results.append(result)
    
    # Resumo final
    print("\n" + "="*60)
    print("📊 RESUMO DOS TESTES")
    print("="*60)
    
    total = len(results)
    passed = sum(1 for r in results if r.get("success"))
    failed = total - passed
    
    print(f"\n✅ Testes passados: {passed}/{total}")
    print(f"❌ Testes falhados: {failed}/{total}")
    
    print(f"\n📋 Detalhes:")
    for i, result in enumerate(results, 1):
        status = "✅" if result.get("success") else "❌"
        question_short = result['question'][:50] + ("..." if len(result['question']) > 50 else "")
        print(f"\n  {status} {i}. {question_short}")
        
        if result.get("has_join"):
            print(f"     → JOIN detectado: {', '.join(result.get('join_types', ['JOIN']))}")
        if result.get("chosen_tables"):
            tables_str = ", ".join(result["chosen_tables"])
            print(f"     → Tabelas: {tables_str}")
        if result.get("error"):
            print(f"     → Erro: {result['error']}")
        if result.get("sql"):
            sql_preview = result["sql"][:100] + ("..." if len(result["sql"]) > 100 else "")
            print(f"     → SQL: {sql_preview}")
    
    # Salvar resultados
    report = {
        "timestamp": str(__import__("datetime").datetime.now()),
        "api_url": API_BASE_URL,
        "connection_id": TEST_CONNECTION_ID,
        "space_id": TEST_SPACE_ID,
        "total_tests": total,
        "passed": passed,
        "failed": failed,
        "results": results,
    }
    
    with open("test_joins_api_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str, ensure_ascii=False)
    
    print(f"\n💾 Resultados salvos em: test_joins_api_report.json")
    
    # Recomendações
    if failed > 0:
        print(f"\n💡 RECOMENDAÇÕES:")
        print(f"   1. Verifique se os metadados das tabelas estão atualizados")
        print(f"   2. Execute: POST /connections/{TEST_CONNECTION_ID}/discover")
        print(f"   3. Verifique se há relacionamentos (FKs) entre as tabelas")
        print(f"   4. Revise as perguntas - podem precisar ser mais específicas")


if __name__ == "__main__":
    main()
