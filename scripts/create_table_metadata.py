#!/usr/bin/env python3
"""Cria a tabela table_metadata no banco"""

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import os

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"), future=True)

with engine.begin() as conn:
    # Criar tabela table_metadata com UUID para compatibilidade
    try:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS table_metadata (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                data_connection_id UUID NOT NULL,
                space_id UUID NOT NULL,
                crew_id UUID,
                table_name VARCHAR NOT NULL,
                column_name VARCHAR NOT NULL,
                data_type VARCHAR,
                is_nullable BOOLEAN,
                description TEXT,
                extra JSON,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                FOREIGN KEY(data_connection_id) REFERENCES data_connections(id),
                FOREIGN KEY(space_id) REFERENCES spaces(id),
                FOREIGN KEY(crew_id) REFERENCES crews(id)
            )
        """))
        print("✅ Tabela table_metadata criada!")
    except Exception as e:
        print(f"❌ Erro ao criar tabela: {e}")
        raise

    # Verificar se precisa da extensão pgvector
    try:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        print("✅ Extensão pgvector criada!")
    except Exception as e:
        print(f"⚠️  pgvector: {e}")
