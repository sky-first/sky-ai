#!/usr/bin/env python3
"""Script para gerar embeddings dos metadados de tabelas"""

import os
import sys
import asyncio
from dotenv import load_dotenv
load_dotenv()

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from db.base import SessionLocal
from sqlalchemy import select, func
from core.rag.embeddings import create_embeddings_for_table_metadata
from core.rag.embeddings import OpenAIEmbeddingProvider

# Configurações
TEST_SPACE_ID = os.getenv("TEST_SPACE_ID") or "e409079b-5bbf-4249-a769-2010609c30f2"
TEST_CONNECTION_ID = os.getenv("TEST_CONNECTION_ID") or "1fd6fee8-bf03-4e82-9c85-419a228ef726"

async def generate_embeddings(space_id: str = None, connection_id: str = None, crew_id: str = None):
    """Gera embeddings para metadados de tabelas"""
    space_id = space_id or TEST_SPACE_ID
    connection_id = connection_id or TEST_CONNECTION_ID
    
    print("="*60)
    print("GERAÇÃO DE EMBEDDINGS")
    print("="*60)
    print(f"Space ID: {space_id}")
    print(f"Connection ID: {connection_id}")
    if crew_id:
        print(f"Crew ID: {crew_id}")
    print("="*60)
    
    async with SessionLocal() as db:
        try:
            # Verificar se há metadados
            from db.models import TableMetadata
            query = select(func.count()).select_from(TableMetadata).filter(TableMetadata.space_id == space_id)
            if connection_id:
                query = query.filter(TableMetadata.data_connection_id == connection_id)
            if crew_id:
                query = query.filter(TableMetadata.crew_id == crew_id)
            else:
                query = query.filter(TableMetadata.crew_id.is_(None))
            
            result = await db.execute(query)
            metadata_count = result.scalar()
            print(f"\n📊 Metadados encontrados: {metadata_count}")
            
            if metadata_count == 0:
                print("\n⚠️  Nenhum metadado encontrado!")
                print("Execute primeiro a descoberta de metadados:")
                print("  POST /connections/{connection_id}/discover?space_id={space_id}")
                return
            
            # Criar provider de embeddings
            embedding_provider = OpenAIEmbeddingProvider(model="text-embedding-3-large")
            print("\n🔄 Gerando embeddings...")
            
            # Gerar embeddings
            created = await create_embeddings_for_table_metadata(
                db=db,
                embedding_provider=embedding_provider,
                space_id=space_id,
                crew_id=crew_id,
                data_connection_id=connection_id,
                batch_size=20,
                delay_between_batches=1.0,
            )
            
            await db.commit()
            
            print(f"\n✅ {created} embeddings criados com sucesso!")
            
            # Verificar total de embeddings
            from db.models import EmbeddingRecord
            result = await db.execute(
                select(func.count()).select_from(EmbeddingRecord).filter(
                    EmbeddingRecord.space_id == space_id
                )
            )
            total = result.scalar()
            print(f"📊 Total de embeddings no banco: {total}")
            
        except Exception as e:
            await db.rollback()
            print(f"\n❌ Erro ao gerar embeddings: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*60)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gerar embeddings de metadados")
    parser.add_argument("--space-id", help="Space ID")
    parser.add_argument("--connection-id", help="Connection ID")
    parser.add_argument("--crew-id", help="Crew ID (opcional)")
    
    args = parser.parse_args()
    asyncio.run(generate_embeddings(
        space_id=args.space_id,
        connection_id=args.connection_id,
        crew_id=args.crew_id
    ))
