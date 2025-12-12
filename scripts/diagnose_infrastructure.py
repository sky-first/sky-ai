#!/usr/bin/env python3
"""
Script de Diagnóstico de Infraestrutura

Verifica e ajuda a resolver problemas de:
1. Conexão com PostgreSQL
2. API rodando
3. Credenciais configuradas
"""

import os
import sys
import subprocess
import time
import requests
from dotenv import load_dotenv

load_dotenv()

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def check_database_connection():
    """Verifica conexão com PostgreSQL"""
    print("\n" + "="*60)
    print("🔍 DIAGNÓSTICO 1: Conexão PostgreSQL")
    print("="*60)
    
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ DATABASE_URL não encontrado no .env")
        return False
    
    print(f"✅ DATABASE_URL encontrado")
    
    # Extrair informações da URL
    try:
        if "@" in db_url:
            parts = db_url.split("@")
            if len(parts) == 2:
                creds_part = parts[0].split("://")[-1]
                host_part = parts[1].split("/")[0]
                
                if ":" in creds_part:
                    user = creds_part.split(":")[0]
                    password = creds_part.split(":")[1]
                    print(f"   Usuário: {user}")
                    print(f"   Senha: {'*' * len(password) if password else 'NÃO DEFINIDA'}")
                
                if ":" in host_part:
                    host, port = host_part.split(":")
                    print(f"   Host: {host}")
                    print(f"   Porta: {port}")
                else:
                    print(f"   Host: {host_part}")
    except Exception as e:
        print(f"   ⚠️  Erro ao parsear URL: {e}")
    
    # Tentar conectar
    print("\n🔄 Tentando conectar ao banco...")
    try:
        from db.base import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        print("✅ Conexão com banco OK!")
        return True
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Erro de conexão: {error_msg[:200]}")
        
        if "password authentication failed" in error_msg.lower():
            print("\n💡 SOLUÇÃO: Senha incorreta ou usuário sem permissão")
            print("   1. Verifique as credenciais no .env")
            print("   2. Confirme que o usuário 'postgres' existe no banco")
            print("   3. Verifique se a senha está correta")
        elif "could not connect" in error_msg.lower() or "connection refused" in error_msg.lower():
            print("\n💡 SOLUÇÃO: Banco não está acessível")
            print("   1. Verifique se o PostgreSQL está rodando")
            print("   2. Verifique firewall/rede")
            print("   3. Confirme host e porta")
        
        return False


def check_api_status():
    """Verifica se a API está rodando"""
    print("\n" + "="*60)
    print("🔍 DIAGNÓSTICO 2: Status da API")
    print("="*60)
    
    # Verificar se há processo na porta 8000
    try:
        result = subprocess.run(
            ["lsof", "-ti:8000"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            pid = result.stdout.strip().split("\n")[0]
            print(f"⚠️  Processo encontrado na porta 8000 (PID: {pid})")
            print("   Mas a API pode não estar respondendo...")
        else:
            print("❌ Nenhum processo na porta 8000")
    except Exception:
        print("⚠️  Não foi possível verificar processos")
    
    # Tentar conectar na API
    print("\n🔄 Tentando conectar na API...")
    try:
        response = requests.get("http://localhost:8000/health", timeout=3)
        if response.status_code == 200:
            print("✅ API está respondendo!")
            return True
        else:
            print(f"⚠️  API respondeu com status {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ API não está respondendo")
        print("\n💡 SOLUÇÃO: Inicie a API com:")
        print("   python3 run_api.py")
        return False
    except Exception as e:
        print(f"❌ Erro ao conectar: {e}")
        return False


def check_env_variables():
    """Verifica variáveis de ambiente essenciais"""
    print("\n" + "="*60)
    print("🔍 DIAGNÓSTICO 3: Variáveis de Ambiente")
    print("="*60)
    
    required_vars = {
        "DATABASE_URL": "Conexão PostgreSQL",
        "OPENAI_API_KEY": "API Key OpenAI (para LLMs)",
        "GCP_PROJECT_ID": "Projeto BigQuery (opcional)",
    }
    
    optional_vars = {
        "TEST_SPACE_ID": "ID do Space de teste",
        "TEST_CONNECTION_ID": "ID da Connection de teste",
    }
    
    all_ok = True
    
    print("\n📋 Variáveis obrigatórias:")
    for var, desc in required_vars.items():
        value = os.getenv(var)
        if value:
            if var == "DATABASE_URL":
                # Não mostrar senha completa
                masked = value.split("@")[0] + "@***" if "@" in value else "***"
                print(f"   ✅ {var}: {masked}")
            elif var == "OPENAI_API_KEY":
                masked = value[:8] + "..." if len(value) > 8 else "***"
                print(f"   ✅ {var}: {masked}")
            else:
                print(f"   ✅ {var}: {value}")
        else:
            print(f"   ❌ {var}: NÃO DEFINIDA ({desc})")
            all_ok = False
    
    print("\n📋 Variáveis opcionais:")
    for var, desc in optional_vars.items():
        value = os.getenv(var)
        if value:
            print(f"   ✅ {var}: {value}")
        else:
            print(f"   ⚠️  {var}: Não definida (usará padrão)")
    
    return all_ok


def suggest_fixes():
    """Sugere correções"""
    print("\n" + "="*60)
    print("💡 SUGESTÕES DE CORREÇÃO")
    print("="*60)
    
    print("\n1. Para corrigir conexão com banco:")
    print("   - Verifique o arquivo .env")
    print("   - Confirme DATABASE_URL está correto")
    print("   - Formato esperado: postgresql+psycopg2://user:password@host:port/database")
    print("   - Teste conexão manual: psql -h <host> -p <port> -U <user> -d <database>")
    
    print("\n2. Para iniciar a API:")
    print("   - Execute: python3 run_api.py")
    print("   - Aguarde mensagem: 'Uvicorn running on http://0.0.0.0:8000'")
    print("   - Teste: curl http://localhost:8000/health")
    
    print("\n3. Para testar JOINs:")
    print("   - Com banco OK: python3 scripts/test_joins_simple.py")
    print("   - Com API OK: python3 scripts/test_joins_api.py")
    print("   - Sem banco: python3 scripts/test_joins_mock.py")


def main():
    print("="*60)
    print("🔧 DIAGNÓSTICO DE INFRAESTRUTURA")
    print("="*60)
    
    # Verificações
    db_ok = check_database_connection()
    api_ok = check_api_status()
    env_ok = check_env_variables()
    
    # Resumo
    print("\n" + "="*60)
    print("📊 RESUMO")
    print("="*60)
    print(f"\n{'✅' if db_ok else '❌'} Banco de dados: {'OK' if db_ok else 'COM PROBLEMAS'}")
    print(f"{'✅' if api_ok else '❌'} API: {'OK' if api_ok else 'NÃO ESTÁ RODANDO'}")
    print(f"{'✅' if env_ok else '❌'} Variáveis de ambiente: {'OK' if env_ok else 'FALTANDO'}")
    
    if db_ok and api_ok and env_ok:
        print("\n✅ Tudo OK! Você pode executar os testes.")
    else:
        suggest_fixes()


if __name__ == "__main__":
    main()
