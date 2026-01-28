#!/usr/bin/env python3
"""
Script de teste para validar modelos locais Ollama.
Executa antes da virada de chave USE_LOCAL_MODELS=true.
"""

import os
import sys
from pathlib import Path

# Adicionar diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.llm.providers import OllamaProvider
from core.agents.generic_sql_agent import TableSchema


def test_ollama_connection():
    """Testa conexão com Ollama."""
    print("🔌 Testando conexão com Ollama...")
    
    try:
        provider = OllamaProvider(
            model="phi3-sky",
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        )
        
        response = provider.invoke([
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Say 'OK' if you can read this."}
        ])
        
        print(f"✅ Ollama respondeu: {response.content[:50]}")
        return True
    except Exception as e:
        print(f"❌ Erro: {e}")
        return False


def test_sqlcoder():
    """Testa geração de SQL com SQLCoder."""
    print("\n🔍 Testando SQLCoder...")
    
    schema = TableSchema(
        logical_name="users",
        physical_name="public.users",
        columns=[
            {"name": "id", "type": "INTEGER"},
            {"name": "name", "type": "VARCHAR"},
            {"name": "email", "type": "VARCHAR"},
            {"name": "created_at", "type": "TIMESTAMP"}
        ]
    )
    
    prompt = f"""### Task
Generate a SQL query to answer: How many users were created in 2024?

### Database Schema
Table: {schema['physical_name']}
Columns:
  - id (INTEGER)
  - name (VARCHAR)
  - email (VARCHAR)
  - created_at (TIMESTAMP)

### Instructions
- Use ONLY the table above
- ALWAYS end with LIMIT 100
- Output ONLY SQL code

### SQL Query
"""
    
    try:
        provider = OllamaProvider(
            model="sqlcoder-sky",
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            temperature=0.0
        )
        
        response = provider.invoke([{"role": "user", "content": prompt}])
        sql = response.content.strip()
        
        print(f"✅ SQL gerado:\n{sql}\n")
        
        # Validações básicas
        assert "SELECT" in sql.upper(), "SQL deve conter SELECT"
        assert "LIMIT" in sql.upper(), "SQL deve conter LIMIT"
        assert schema['physical_name'] in sql, "SQL deve usar tabela correta"
        
        print("✅ Validações passaram!")
        return True
        
    except Exception as e:
        print(f"❌ Erro: {e}")
        return False


def test_phi3_formatter():
    """Testa formatação com Phi-3."""
    print("\n📝 Testando Phi-3 (formatter)...")
    
    prompt = """### SYSTEM
You are a data analyst. Output format:
-- TITLE: <English title>
<Natural language response>

### USER
Question: How many users signed up in 2024?
SQL: SELECT COUNT(*) FROM users WHERE EXTRACT(YEAR FROM created_at) = 2024
Results: [{"count": 1523}]
Language: English

Generate title and response.
"""
    
    try:
        provider = OllamaProvider(
            model="phi3-sky",
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            temperature=0.3
        )
        
        response = provider.invoke([{"role": "user", "content": prompt}])
        output = response.content.strip()
        
        print(f"✅ Resposta:\n{output}\n")
        
        # Validações
        assert "-- TITLE:" in output, "Deve conter título"
        assert "1523" in output or "1,523" in output, "Deve mencionar o número"
        
        print("✅ Validações passaram!")
        return True
        
    except Exception as e:
        print(f"❌ Erro: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 TESTE DE MODELOS LOCAIS OLLAMA")
    print("=" * 60)
    
    results = {
        "Conexão Ollama": test_ollama_connection(),
        "SQLCoder": test_sqlcoder(),
        "Phi-3 Formatter": test_phi3_formatter(),
    }
    
    print("\n" + "=" * 60)
    print("📊 RESULTADOS:")
    print("=" * 60)
    
    for test_name, passed in results.items():
        status = "✅ PASSOU" if passed else "❌ FALHOU"
        print(f"{test_name}: {status}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n🎉 Todos os testes passaram!")
        print("✅ Sistema pronto para USE_LOCAL_MODELS=true")
        sys.exit(0)
    else:
        print("\n⚠️ Alguns testes falharam!")
        print("❌ Corrija os problemas antes de ativar modelos locais")
        sys.exit(1)
