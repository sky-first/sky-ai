#!/usr/bin/env python3
"""
Script para listar datasets disponíveis no BigQuery
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Adicionar o diretório raiz do projeto ao PYTHONPATH
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from google.cloud import bigquery
from google.oauth2 import service_account
from core.data_sources.factory import DataSourceFactory
from db.base import SessionLocal
from sqlalchemy import text

def list_datasets():
    """Lista todos os datasets disponíveis no projeto BigQuery"""
    
    # Ler configuração da conexão
    db = SessionLocal()
    try:
        conn_id = os.getenv("TEST_CONNECTION_ID") or "00000000-0000-0000-0000-000000000002"
        
        result = db.execute(
            text("SELECT config FROM data_connections WHERE id = :id"),
            {"id": conn_id}
        ).first()
        
        if not result:
            print(f"❌ Conexão {conn_id} não encontrada!")
            return
        
        config = result[0] if result else {}
        if isinstance(config, str):
            import json
            config = json.loads(config)
        
        project_id = config.get("project_id")
        credentials_path = config.get("credentials_path")
        
        if not project_id:
            print("❌ project_id não encontrado na configuração!")
            return
        
        print(f"📊 Projeto BigQuery: {project_id}")
        print(f"🔑 Credentials: {credentials_path or 'Usando credenciais padrão'}\n")
        
        # Criar cliente BigQuery
        if credentials_path and os.path.exists(credentials_path):
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/bigquery"]
            )
            client = bigquery.Client(credentials=credentials, project=project_id)
        else:
            client = bigquery.Client(project=project_id)
        
        # Listar datasets
        print("=" * 60)
        print("📁 DATASETS DISPONÍVEIS:")
        print("=" * 60)
        
        datasets = list(client.list_datasets())
        
        if not datasets:
            print("⚠️  Nenhum dataset encontrado!")
            return
        
        for dataset in datasets:
            dataset_id = f"{dataset.project}.{dataset.dataset_id}"
            print(f"\n📦 {dataset_id}")
            try:
                dataset_obj = client.get_dataset(dataset.dataset_id)
                print(f"   Descrição: {dataset_obj.description or '(sem descrição)'}")
                print(f"   Localização: {dataset_obj.location or 'US'}")
            except:
                print(f"   Localização: {dataset.location if hasattr(dataset, 'location') else 'US'}")
            
            # Listar tabelas neste dataset
            try:
                tables = list(client.list_tables(dataset.dataset_id))
                print(f"   Tabelas: {len(tables)}")
                for table in tables[:5]:  # Mostrar até 5 tabelas
                    print(f"      - {table.table_id}")
                if len(tables) > 5:
                    print(f"      ... e mais {len(tables) - 5} tabelas")
            except Exception as e:
                print(f"   ⚠️  Erro ao listar tabelas: {e}")
        
        print("\n" + "=" * 60)
        print(f"✅ Total: {len(datasets)} datasets encontrados")
        
    finally:
        db.close()

if __name__ == "__main__":
    list_datasets()
