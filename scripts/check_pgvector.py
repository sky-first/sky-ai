#!/usr/bin/env python3
"""
Script para verificar status do pgvector no PostgreSQL
"""
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import os
import sys

load_dotenv()

# Adicionar o diretório raiz ao PYTHONPATH
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

engine = create_engine(os.getenv('DATABASE_URL'), future=True)

print("=" * 60)
print("🔍 VERIFICAÇÃO DO PGVECTOR")
print("=" * 60)

# 1. Verificar se a extensão existe
print("\n1️⃣ Verificando extensão pgvector...")
try:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT EXISTS(
                SELECT 1 FROM pg_extension WHERE extname = 'vector'
            ) as extension_exists
        """))
        exists = result.first()[0]
        
        if exists:
            print("   ✅ Extensão 'vector' está instalada!")
        else:
            print("   ❌ Extensão 'vector' NÃO está instalada")
except Exception as e:
    print(f"   ⚠️  Erro ao verificar extensão: {e}")

# 2. Verificar se o tipo vector funciona
print("\n2️⃣ Testando tipo vector...")
try:
    with engine.connect() as conn:
        conn.execute(text("SELECT '[1,2,3]'::vector(3)"))
        print("   ✅ Tipo vector funciona!")
        vector_works = True
except Exception as e:
    print(f"   ❌ Tipo vector NÃO funciona: {e}")
    vector_works = False

# 3. Verificar tabela embeddings
print("\n3️⃣ Verificando tabela embeddings...")
try:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                column_name, 
                data_type,
                udt_name
            FROM information_schema.columns 
            WHERE table_name = 'embeddings' 
            AND column_name = 'embedding'
        """))
        row = result.first()
        
        if row:
            col_name, data_type, udt_name = row
            print(f"   📊 Coluna 'embedding':")
            print(f"      - data_type: {data_type}")
            print(f"      - udt_name: {udt_name}")
            
            if udt_name == 'vector':
                print("   ✅ Tabela usa tipo vector (busca vetorial habilitada)")
            else:
                print(f"   ⚠️  Tabela usa tipo {udt_name} (busca vetorial NÃO habilitada)")
        else:
            print("   ⚠️  Tabela 'embeddings' não existe ou coluna 'embedding' não encontrada")
except Exception as e:
    print(f"   ⚠️  Erro ao verificar tabela: {e}")

# 4. Verificar índices vetoriais
print("\n4️⃣ Verificando índices vetoriais...")
try:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 
                indexname, 
                indexdef
            FROM pg_indexes 
            WHERE tablename = 'embeddings'
            AND indexdef LIKE '%vector%'
        """))
        indexes = list(result)
        
        if indexes:
            print(f"   ✅ Encontrados {len(indexes)} índice(s) vetorial(is):")
            for idx_name, idx_def in indexes:
                print(f"      - {idx_name}")
        else:
            print("   ⚠️  Nenhum índice vetorial encontrado")
except Exception as e:
    print(f"   ⚠️  Erro ao verificar índices: {e}")

# Resumo final
print("\n" + "=" * 60)
print("📋 RESUMO")
print("=" * 60)

if vector_works:
    print("✅ pgvector está FUNCIONANDO!")
    print("   Busca vetorial (RAG) está habilitada")
else:
    print("❌ pgvector NÃO está funcionando")
    print("\n📝 Para habilitar pgvector:")
    print("   1. DevOps precisa instalar a extensão no PostgreSQL:")
    print("      CREATE EXTENSION IF NOT EXISTS vector;")
    print("   2. Recriar a tabela embeddings:")
    print("      python3 scripts/create_embeddings_table.py")
    print("   3. Regenerar embeddings (se necessário)")

print("=" * 60)
