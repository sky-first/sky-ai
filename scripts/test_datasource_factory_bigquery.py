# scripts/test_datasource_factory_bigquery.py
import os
from dotenv import load_dotenv

from db.models import DataConnection
from core.data_sources.factory import build_data_source_for_connection


def main() -> None:
    load_dotenv()

    project_id = os.getenv("GCP_PROJECT_ID")
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    if not project_id:
        raise RuntimeError("GCP_PROJECT_ID não está definido no .env")

    print(f"Usando project_id={project_id}")
    print(f"Usando credentials_path={credentials_path}")

    # Aqui criamos um DataConnection "fake" só para teste (não vai pro banco)
    conn = DataConnection(
        id="test-conn",
        space_id="test-space",
        name="BigQuery Test Connection",
        type="bigquery",
        config={
            "project_id": project_id,
            # dataset é opcional pra SELECT 1, mas você pode setar se quiser:
            # "dataset": "seu_dataset",
            "credentials_path": credentials_path,
            # "location": "US",
        },
    )

    # A factory decide qual DataSource criar com base no type
    ds = build_data_source_for_connection(conn)

    sql = "SELECT 1 AS value"
    print(f"Executando SQL via factory: {sql}")
    rows = ds.run_query(sql)

    print("Resultado:")
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
