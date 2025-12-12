#!/usr/bin/env python3
"""
Script para testar conexão com PostgreSQL
"""
from dotenv import load_dotenv
import os
import sys

load_dotenv()

# Tenta usar DATABASE_URL do .env ou pede para o usuário
db_url = os.getenv("DATABASE_URL")

if not db_url or "postgres" in db_url and "@postgres:" in db_url:
    print("⚠️  DATABASE_URL não está configurado corretamente no .env")
    print("\nPor favor, forneça as credenciais do PostgreSQL:")
    print("(ou configure diretamente no arquivo .env)\n")
    
    host = input("Host (ex: localhost ou IP): ").strip()
    port = input("Porta (padrão 5432): ").strip() or "5432"
    user = input("Usuário: ").strip()
    password = input("Senha: ").strip()
    database = input("Nome do banco: ").strip()
    
    db_url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
    print(f"\n📝 DATABASE_URL gerado: postgresql+psycopg2://{user}:***@{host}:{port}/{database}\n")
else:
    print(f"📝 Usando DATABASE_URL do .env: {db_url[:50]}...\n")

# Testa conexão
try:
    from sqlalchemy import create_engine, text
    
    print("🔄 Tentando conectar ao PostgreSQL...")
    engine = create_engine(db_url, future=True)
    
    with engine.connect() as conn:
        result = conn.execute(text("SELECT version();"))
        version = result.fetchone()[0]
        print(f"✅ Conexão bem-sucedida!")
        print(f"📊 Versão do PostgreSQL: {version[:80]}...\n")
        
        # Verifica se o banco tem as tabelas necessárias
        result = conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """))
        tables = [row[0] for row in result.fetchall()]
        
        if tables:
            print(f"📋 Tabelas encontradas ({len(tables)}):")
            for table in tables[:10]:
                print(f"   - {table}")
            if len(tables) > 10:
                print(f"   ... e mais {len(tables) - 10} tabelas")
        else:
            print("⚠️  Nenhuma tabela encontrada no banco")
        
        print("\n✅ Banco de dados está pronto para uso!")
        print(f"\n💡 Adicione esta linha ao seu .env:")
        print(f'DATABASE_URL="{db_url}"')
        
except Exception as e:
    print(f"❌ Erro ao conectar: {e}")
    sys.exit(1)
