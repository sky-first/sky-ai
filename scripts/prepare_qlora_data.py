import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any
import pandas as pd
from sqlalchemy import create_engine, Column, Boolean, String, Text, DateTime, JSON, select
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.dialects.postgresql import UUID
import uuid

# Adicionar root ao path para importar settings
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import settings

Base = declarative_base()

class AIQuery(Base):
    """Modelo espelho da tabela ai_queries no backend."""
    __tablename__ = "ai_queries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question = Column(Text, nullable=False)
    sql = Column(Text, nullable=True)
    status = Column(String(50), default="processing")
    configure_data = Column(JSON, nullable=False)
    is_validated = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True))

def export_customer_gold_data(output_file: str = "dataset_qlora.jsonl"):
    """
    Exporta dados validados (Gold Dataset) para treino QLoRA/Unsloth.
    Critérios:
    - Status 'completed'
    - SQL gerado (não nulo)
    - Marcado como validado (is_validated=True)
    """
    print(f"🔄 Conectando ao banco de dados: {settings.database_url}")
    
    # Criar engine e sessão
    # Nota: Assumindo que a URL do banco em settings.py do AI aponta para o mesmo banco do backend
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Query para buscar dados validados
        stmt = select(AIQuery).where(
            AIQuery.sql.isnot(None),
            AIQuery.is_validated == True,
            AIQuery.status == "completed"
        ).order_by(AIQuery.created_at.desc()).limit(2000)
        
        results = session.execute(stmt).scalars().all()
        
        if not results:
            print("⚠️ Nenhum registro validado encontrado.")
            print("Dica: Marque queries como 'is_validated=True' na tabela ai_queries.")
            return

        print(f"📦 Processando {len(results)} registros...")
        
        count = 0
        with open(output_file, "w", encoding="utf-8") as f:
            for query in results:
                # Extrair tabelas escolhidas do configure_data
                config = query.configure_data or {}
                chosen_datasets = config.get("chosen_datasets", [])
                if not chosen_datasets and config.get("chosen_table"):
                    chosen_datasets = [config.get("chosen_table")]
                
                # Montar o input. 
                # Nota: Idealmente aqui buscaríamos o DDL das tabelas para enriquecer o contexto.
                # Por enquanto, usamos a lista de tabelas como contexto básico.
                tables_str = ", ".join(chosen_datasets) if chosen_datasets else "Unknown Tables"
                
                # Formato Alpaca
                prompt_input = f"Using tables: {tables_str}\nQuestion: {query.question}"
                
                example = {
                    "instruction": "You are a SQL expert. Generate a DuckDB SQL query for the given question and context.",
                    "input": prompt_input,
                    "output": query.sql
                }
                
                f.write(json.dumps(example, ensure_ascii=False) + "\n")
                count += 1
                
        print(f"✅ Dataset exportado com sucesso: {count} exemplos em '{output_file}'")
        print("🚀 Pronto para treino com Unsloth!")

    except Exception as e:
        print(f"❌ Erro ao exportar dados: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    if "--help" in sys.argv:
        print("Usage: python prepare_qlora_data.py [output_file.jsonl]")
        sys.exit(0)
    
    outfile = sys.argv[1] if len(sys.argv) > 1 else "dataset_qlora.jsonl"
    export_customer_gold_data(outfile)
