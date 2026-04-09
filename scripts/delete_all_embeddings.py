#!/usr/bin/env python3
"""Script para deletar todos os embeddings do banco de dados"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from db.base import SyncSessionLocal
from db.models import EmbeddingRecord

def delete_all_embeddings():
    """Deleta todos os registros da tabela embeddings"""
    print("="*60)
    print("REMOÇÃO DE EMBEDDINGS")
    print("="*60)
    
    db = SyncSessionLocal()
    try:
        # Verificar quantidade atual
        total_before = db.query(EmbeddingRecord).count()
        print(f"📊 Total de embeddings antes da limpeza: {total_before}")
        
        if total_before == 0:
            print("✅ Nenhum embedding para deletar.")
            return

        # Deletar todos
        print("🗑️  Deletando todos os embeddings...")
        db.query(EmbeddingRecord).delete()
        db.commit()
        
        # Verificar quantidade após limpeza
        total_after = db.query(EmbeddingRecord).count()
        print(f"📊 Total de embeddings após limpeza: {total_after}")
        
        if total_after == 0:
            print("✅ Todos os embeddings foram removidos com sucesso!")
        else:
            print(f"❌ Falha: ainda restam {total_after} embeddings.")
            
    except Exception as e:
        db.rollback()
        print(f"❌ Erro ao deletar embeddings: {e}")
    finally:
        db.close()
    
    print("\n" + "="*60)

if __name__ == "__main__":
    delete_all_embeddings()
