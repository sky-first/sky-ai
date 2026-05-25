#!/usr/bin/env python3
"""
Script para verificar datasets disponíveis no BigQuery e ingerir metadados do dataset 'web'
"""

import os
import sys
import json
from dotenv import load_dotenv

load_dotenv()

# Adicionar o diretório raiz do projeto ao PYTHONPATH
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from google.cloud import bigquery
from google.oauth2 import service_account
from sqlalchemy import create_engine, text


def main():
    """Lista datasets e permite ingerir metadados do dataset 'web'"""

    # Ler configuração da conexão
    engine = create_engine(os.getenv("DATABASE_URL"), future=True)

    TEST_CONNECTION_ID = (
        os.getenv("TEST_CONNECTION_ID") or "00000000-0000-0000-0000-000000000002"
    )

    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT config FROM data_connections WHERE id = :id"),
            {"id": TEST_CONNECTION_ID},
        ).first()

        if not result:
            print(f"❌ Conexão {TEST_CONNECTION_ID} não encontrada!")
            return

        config = result[0] if result else {}
        if isinstance(config, str):
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
                credentials_path, scopes=["https://www.googleapis.com/auth/bigquery"]
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

        web_dataset_found = False
        for dataset in datasets:
            dataset_id = dataset.dataset_id
            full_dataset_id = f"{dataset.project}.{dataset_id}"
            print(f"\n📦 {full_dataset_id}")
            print(f"   Descrição: {dataset.description or '(sem descrição)'}")
            print(f"   Localização: {dataset.location or 'US'}")

            if dataset_id.lower() == "web" or "web" in dataset_id.lower():
                web_dataset_found = True
                print(f"   ✅ Dataset 'web' encontrado!")

            # Listar tabelas neste dataset
            try:
                tables = list(client.list_tables(dataset_id))
                print(f"   Tabelas: {len(tables)}")
                for table in tables[:10]:  # Mostrar até 10 tabelas
                    print(f"      - {table.table_id}")
                if len(tables) > 10:
                    print(f"      ... e mais {len(tables) - 10} tabelas")
            except Exception as e:
                print(f"   ⚠️  Erro ao listar tabelas: {e}")

        print("\n" + "=" * 60)
        print(f"✅ Total: {len(datasets)} datasets encontrados")

        if web_dataset_found:
            print("\n✅ Dataset 'web' está disponível!")
            print(
                "💡 Você pode usar o script ingest_metadata_for_test.py para ingerir metadados"
            )
            print("   ou criar uma nova conexão apontando para o dataset 'web'")
        else:
            print("\n⚠️  Dataset 'web' não foi encontrado!")
            print(
                "   Verifique se o nome está correto ou se você tem permissão para acessá-lo"
            )


if __name__ == "__main__":
    main()
