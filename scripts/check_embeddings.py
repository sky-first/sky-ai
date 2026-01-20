#!/usr/bin/env python3
"""Script para verificar se há embeddings no banco de dados"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from sqlalchemy import text
from db.base import SessionLocal, engine
from db.models import EmbeddingRecord

def check_embeddings():
    """Verifica se há embeddings no banco"""
    print("="*60)
    print("VERIFICAÇÃO DE EMBEDDINGS")
    print("="*60)
    
    db = SessionLocal()
    try:
        # Verificar se a tabela existe
        try:
            result = db.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'embeddings'
                )
            """))
            table_exists = result.scalar()
            
            if not table_exists:
                print("❌ Tabela 'embeddings' não existe no banco!")
                print("\nPara criar a tabela, execute:")
                print("  python scripts/create_embeddings_table.py")
                return
            else:
                print("✅ Tabela 'embeddings' existe")
        except Exception as e:
            print(f"❌ Erro ao verificar tabela: {e}")
            return
        
        # Contar total de embeddings
        total = db.query(EmbeddingRecord).count()
        print(f"\n📊 Total de embeddings: {total}")
        
        if total == 0:
            print("\n⚠️  Nenhum embedding encontrado no banco!")
            print("\nPara criar embeddings, você pode:")
            print("  1. Executar ingestão de metadados (se ainda não foi feito):")
            print("     POST /connections/{connection_id}/discover?space_id={space_id}")
            print("  2. Gerar embeddings via script:")
            print("     python scripts/generate_embeddings.py --space-id {space_id} --connection-id {connection_id}")
            print("  3. Ou via API:")
            print("     POST /connections/{connection_id}/generate-embeddings?space_id={space_id}")
            return
        
        # Estatísticas por space_id
        print("\n📈 Estatísticas por Space:")
        result = db.execute(text("""
            SELECT 
                space_id,
                COUNT(*) as total,
                COUNT(DISTINCT crew_id) as num_crews,
                COUNT(DISTINCT table_metadata_id) as num_table_metadata
            FROM embeddings
            GROUP BY space_id
            ORDER BY total DESC
        """))
        
        for row in result:
            space_id, total_count, num_crews, num_metadata = row
            print(f"  Space {space_id[:8]}...: {total_count} embeddings, {num_crews} crews, {num_metadata} metadados")
        
        # Estatísticas por tipo (kind)
        print("\n📋 Estatísticas por tipo (kind):")
        result = db.execute(text("""
            SELECT 
                metadata->>'kind' as kind,
                COUNT(*) as total
            FROM embeddings
            WHERE metadata IS NOT NULL
            GROUP BY metadata->>'kind'
            ORDER BY total DESC
        """))
        
        kinds = {}
        for row in result:
            kind, count = row
            if kind:
                kinds[kind] = count
                print(f"  {kind}: {count}")
        
        if not kinds:
            print("  (nenhum tipo encontrado nos metadados)")
        
        # Verificar pgvector
        print("\n🔍 Verificando pgvector:")
        try:
            result = db.execute(text("SELECT '[1,2,3]'::vector(3)"))
            print("✅ pgvector está disponível (busca vetorial funcionando)")
        except Exception as e:
            print(f"⚠️  pgvector NÃO está disponível: {e}")
            print("   A busca será feita apenas por filtro (sem similaridade vetorial)")
        
        # Amostra de embeddings
        print("\n📝 Amostra de embeddings (primeiros 5):")
        samples = db.query(EmbeddingRecord).limit(5).all()
        for i, emb in enumerate(samples, 1):
            meta = emb.extra_metadata or {}
            kind = meta.get("kind", "unknown")
            text_preview = (emb.text or "")[:80]
            print(f"  {i}. [{kind}] {text_preview}...")
        
    except Exception as e:
        print(f"❌ Erro ao verificar embeddings: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()
    
    print("\n" + "="*60)

if __name__ == "__main__":
    check_embeddings()

