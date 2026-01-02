#!/usr/bin/env python3
"""
Script de Teste - Validação SQL

Testa o endpoint POST /connections/{connection_id}/validate-sql
diretamente via função interna (sem precisar do servidor rodando).

Uso:
    python3 scripts/test_validate_sql.py
    
Variáveis de ambiente:
    TEST_SPACE_ID: ID do Space de teste
    TEST_CONNECTION_ID: ID da Connection de teste
"""

from __future__ import annotations

import os
import sys
import json
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

# Adicionar o diretório raiz do projeto ao PYTHONPATH
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import asyncio
from sqlalchemy.orm import Session
from db.base import SessionLocal
from api.routes.connection_query import validate_sql
from api.schemas import ValidateSQLRequest, ValidateSQLResponse

# ============== CONFIGURAÇÃO ==============

TEST_SPACE_ID = os.getenv("TEST_SPACE_ID") or "e409079b-5bbf-4249-a769-2010609c30f2"
TEST_CONNECTION_ID = os.getenv("TEST_CONNECTION_ID") or "9dfec38b-7bec-4ef0-8fb2-8430776b2178"
TEST_USER_ID = os.getenv("TEST_USER_ID") or "00000000-0000-0000-0000-000000000000"


def print_test_header(test_name: str):
    """Imprime cabeçalho do teste."""
    print(f"\n{'='*60}")
    print(f"TESTE: {test_name}")
    print(f"{'='*60}")


def print_result(result: ValidateSQLResponse, expected_valid: bool):
    """Imprime resultado do teste."""
    status = "✅ PASSOU" if result.is_valid == expected_valid else "❌ FALHOU"
    print(f"\nStatus: {status}")
    print(f"Is Valid: {result.is_valid} (esperado: {expected_valid})")
    
    if result.error:
        print(f"Error: {result.error}")
    else:
        print(f"Rows: {result.num_rows}")
        print(f"Columns: {result.columns}")
        print(f"Execution Time: {result.execution_time_ms:.2f}ms" if result.execution_time_ms else "N/A")
        if result.preview_data:
            print(f"Preview Data (first row): {json.dumps(result.preview_data[0], indent=2) if result.preview_data else 'None'}")


async def test_sql_valid_with_data(db: Session):
    """Teste 1: SQL válido que retorna dados."""
    print_test_header("SQL Válido com Dados")
    
    request = ValidateSQLRequest(
        user_id=TEST_USER_ID,
        space_id=TEST_SPACE_ID,
        sql="SELECT * FROM billing_silver.invoices_enriched LIMIT 10",
        is_personal=False,
    )
    
    result = await validate_sql(TEST_CONNECTION_ID, request, db)
    print_result(result, expected_valid=True)
    
    assert result.is_valid, "SQL válido deve retornar is_valid=True"
    assert result.num_rows is not None and result.num_rows > 0, "Deve retornar dados"
    assert result.preview_data is not None, "Deve ter preview_data"
    assert len(result.preview_data) <= 5, "Preview deve ter no máximo 5 linhas"
    
    return result.is_valid == True


async def test_sql_valid_no_data(db: Session):
    """Teste 2: SQL válido mas sem dados."""
    print_test_header("SQL Válido sem Dados")
    
    request = ValidateSQLRequest(
        user_id=TEST_USER_ID,
        space_id=TEST_SPACE_ID,
        sql="SELECT * FROM billing_silver.invoices_enriched WHERE 1=0",
        is_personal=False,
    )
    
    result = await validate_sql(TEST_CONNECTION_ID, request, db)
    print_result(result, expected_valid=True)
    
    assert result.is_valid, "SQL válido (mesmo sem dados) deve retornar is_valid=True"
    assert result.num_rows is not None, "Deve retornar num_rows"
    
    return result.is_valid == True


async def test_sql_invalid_syntax(db: Session):
    """Teste 3: SQL com erro de sintaxe."""
    print_test_header("SQL Inválido - Erro de Sintaxe")
    
    request = ValidateSQLRequest(
        user_id=TEST_USER_ID,
        space_id=TEST_SPACE_ID,
        sql="SELECT * FROM",  # SQL inválido
        is_personal=False,
    )
    
    result = await validate_sql(TEST_CONNECTION_ID, request, db)
    print_result(result, expected_valid=False)
    
    assert not result.is_valid, "SQL inválido deve retornar is_valid=False"
    assert result.error is not None, "Deve ter mensagem de erro"
    
    return result.is_valid == False


async def test_sql_table_not_found(db: Session):
    """Teste 4: SQL com tabela inexistente."""
    print_test_header("SQL Inválido - Tabela Inexistente")
    
    request = ValidateSQLRequest(
        user_id=TEST_USER_ID,
        space_id=TEST_SPACE_ID,
        sql="SELECT * FROM tabela_que_nao_existe LIMIT 10",
        is_personal=False,
    )
    
    result = await validate_sql(TEST_CONNECTION_ID, request, db)
    print_result(result, expected_valid=False)
    
    assert not result.is_valid, "SQL com tabela inexistente deve retornar is_valid=False"
    assert result.error is not None, "Deve ter mensagem de erro"
    
    return result.is_valid == False


async def test_connection_not_found(db: Session):
    """Teste 5: Connection ID inválido."""
    print_test_header("Connection ID Inválido")
    
    request = ValidateSQLRequest(
        user_id=TEST_USER_ID,
        space_id=TEST_SPACE_ID,
        sql="SELECT * FROM tabela LIMIT 10",
        is_personal=False,
    )
    
    invalid_connection_id = "00000000-0000-0000-0000-000000000000"
    result = await validate_sql(invalid_connection_id, request, db)
    print_result(result, expected_valid=False)
    
    assert not result.is_valid, "Connection inválido deve retornar is_valid=False"
    assert result.error is not None, "Deve ter mensagem de erro"
    assert "não encontrada" in result.error.lower() or "not found" in result.error.lower(), "Erro deve mencionar conexão não encontrada"
    
    return result.is_valid == False


async def test_sql_with_limit_already_present(db: Session):
    """Teste 6: SQL que já tem LIMIT."""
    print_test_header("SQL com LIMIT já presente")
    
    request = ValidateSQLRequest(
        user_id=TEST_USER_ID,
        space_id=TEST_SPACE_ID,
        sql="SELECT * FROM billing_silver.invoices_enriched LIMIT 3",
        is_personal=False,
    )
    
    result = await validate_sql(TEST_CONNECTION_ID, request, db)
    print_result(result, expected_valid=True)
    
    assert result.is_valid, "SQL com LIMIT deve funcionar"
    assert result.num_rows is not None and result.num_rows <= 3, "Deve respeitar LIMIT original (ou máximo 5)"
    
    return result.is_valid == True


async def test_sql_performance(db: Session):
    """Teste 7: Performance - verifica tempo de execução."""
    print_test_header("Performance - Tempo de Execução")
    
    request = ValidateSQLRequest(
        user_id=TEST_USER_ID,
        space_id=TEST_SPACE_ID,
        sql="SELECT * FROM billing_silver.invoices_enriched LIMIT 5",
        is_personal=False,
    )
    
    result = await validate_sql(TEST_CONNECTION_ID, request, db)
    print_result(result, expected_valid=True)
    
    assert result.is_valid, "SQL deve ser válido"
    if result.execution_time_ms:
        assert result.execution_time_ms < 30000, "Query deve executar em menos de 30 segundos"
        print(f"\n✅ Performance OK: {result.execution_time_ms:.2f}ms")
    
    return result.is_valid == True and (result.execution_time_ms is None or result.execution_time_ms < 30000)


async def run_all_tests():
    """Executa todos os testes."""
    print("="*60)
    print("SUITE DE TESTES - VALIDAÇÃO SQL")
    print("="*60)
    print(f"Connection ID: {TEST_CONNECTION_ID}")
    print(f"Space ID: {TEST_SPACE_ID}")
    print("="*60)
    
    db = SessionLocal()
    results = []
    
    try:
        # Lista de testes
        tests = [
            ("SQL Válido com Dados", test_sql_valid_with_data),
            ("SQL Válido sem Dados", test_sql_valid_no_data),
            ("SQL Inválido - Sintaxe", test_sql_invalid_syntax),
            ("SQL Inválido - Tabela Inexistente", test_sql_table_not_found),
            ("Connection Inválido", test_connection_not_found),
            ("SQL com LIMIT", test_sql_with_limit_already_present),
            ("Performance", test_sql_performance),
        ]
        
        for test_name, test_func in tests:
            try:
                passed = await test_func(db)
                results.append((test_name, passed, None))
            except AssertionError as e:
                results.append((test_name, False, str(e)))
                print(f"\n❌ ASSERTION ERROR: {e}")
            except Exception as e:
                results.append((test_name, False, f"Exception: {str(e)}"))
                print(f"\n❌ EXCEPTION: {e}")
                import traceback
                traceback.print_exc()
    
    finally:
        db.close()
    
    # Resumo
    print("\n" + "="*60)
    print("RESUMO DOS TESTES")
    print("="*60)
    
    passed = sum(1 for _, p, _ in results if p)
    total = len(results)
    
    for test_name, passed, error in results:
        status = "✅ PASSOU" if passed else "❌ FALHOU"
        print(f"{status} - {test_name}")
        if error:
            print(f"    Erro: {error}")
    
    print("="*60)
    print(f"Total: {passed}/{total} testes passaram")
    print("="*60)
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)

