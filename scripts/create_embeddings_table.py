#!/usr/bin/env python3
"""Cria a tabela embeddings no banco PostgreSQL"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Adicionar o diretório raiz do projeto ao PYTHONPATH
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from sqlalchemy import text
from db.base import engine

# Verificar se pgvector está disponível
pgvector_available = False
try:
    with engine.connect() as check_conn:
        # Tentar usar o tipo vector
        check_conn.execute(text("SELECT '[1,2,3]'::vector(3)"))
        pgvector_available = True
        print("✅ Extensão pgvector está disponível!")
except Exception as e:
    pgvector_available = False
    print(f"⚠️  Extensão pgvector NÃO está disponível: {e}")
    print("   A tabela será criada sem o tipo vector (usando JSONB temporariamente)")
    print("   Para usar busca vetorial, o DevOps precisa instalar pgvector no PostgreSQL")

with engine.begin() as conn:
    # Criar tabela embeddings
    try:
        conn.execute(text("DROP TABLE IF EXISTS embeddings CASCADE"))
        
        if pgvector_available:
            # Com pgvector - tipo vector disponível
            # Verificar se table_metadata existe antes de criar FK
            check_meta = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'table_metadata'
                )
            """))
            has_table_metadata = check_meta.scalar()
            
            fk_table_metadata = ""
            if has_table_metadata:
                fk_table_metadata = ", FOREIGN KEY(table_metadata_id) REFERENCES table_metadata(id)"
            
            conn.execute(text(f"""
                CREATE TABLE embeddings (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    space_id UUID NOT NULL,
                    crew_id UUID,
                    user_id UUID,
                    table_metadata_id UUID,
                    document_id VARCHAR,
                    embedding vector(3072) NOT NULL,
                    text TEXT NOT NULL,
                    metadata JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    FOREIGN KEY(space_id) REFERENCES spaces(id),
                    FOREIGN KEY(crew_id) REFERENCES crews(id),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                    {fk_table_metadata}
                )
            """))
            print("✅ Tabela embeddings criada com suporte a busca vetorial!")
        else:
            # Sem pgvector - usar JSONB temporariamente
            # Verificar se table_metadata existe antes de criar FK
            check_meta = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'table_metadata'
                )
            """))
            has_table_metadata = check_meta.scalar()
            
            fk_table_metadata = ""
            if has_table_metadata:
                fk_table_metadata = ", FOREIGN KEY(table_metadata_id) REFERENCES table_metadata(id)"
            
            conn.execute(text(f"""
                CREATE TABLE embeddings (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    space_id UUID NOT NULL,
                    crew_id UUID,
                    user_id UUID,
                    table_metadata_id UUID,
                    document_id VARCHAR,
                    embedding JSONB NOT NULL,
                    text TEXT NOT NULL,
                    metadata JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    FOREIGN KEY(space_id) REFERENCES spaces(id),
                    FOREIGN KEY(crew_id) REFERENCES crews(id),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                    {fk_table_metadata}
                )
            """))
            print("✅ Tabela embeddings criada (sem busca vetorial - pgvector não disponível)")
        
        # Criar índices básicos
        try:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS embeddings_space_id_idx 
                ON embeddings(space_id)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS embeddings_crew_id_idx 
                ON embeddings(crew_id) WHERE crew_id IS NOT NULL
            """))
            
            # Índice vetorial (só se pgvector estiver disponível)
            if pgvector_available:
                try:
                    conn.execute(text("""
                        CREATE INDEX IF NOT EXISTS embeddings_vector_idx 
                        ON embeddings USING hnsw (embedding vector_l2_ops)
                        WITH (m = 16, ef_construction = 64)
                    """))
                    print("✅ Índice HNSW criado para busca vetorial!")
                except Exception as e:
                    try:
                        conn.execute(text("""
                            CREATE INDEX IF NOT EXISTS embeddings_vector_idx 
                            ON embeddings USING ivfflat (embedding vector_l2_ops)
                            WITH (lists = 100)
                        """))
                        print("✅ Índice ivfflat criado para busca vetorial!")
                    except Exception as e2:
                        print(f"⚠️  Não foi possível criar índice vetorial: {e2}")
            
            print("✅ Índices criados!")
        except Exception as e:
            print(f"⚠️  Erro ao criar índices: {e}")
            
    except Exception as e:
        print(f"❌ Erro ao criar tabela embeddings: {e}")
        import traceback
        traceback.print_exc()
        raise

print("\n✅ Tabela embeddings pronta!")
if not pgvector_available:
    print("\n📝 NOTA: Para habilitar busca vetorial (RAG), é necessário:")
    print("   1. Instalar a extensão pgvector no PostgreSQL")
    print("   2. Recriar a tabela com o tipo vector")
    print("   3. Recriar os embeddings")
