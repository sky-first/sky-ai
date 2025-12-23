# scripts/test_bigquery_datasource.py
import os

from dotenv import load_dotenv

from core.data_sources.bigquery_source import BigQueryDataSource

def main() -> None:
    # Carrega variáveis do .env
    load_dotenv()

    project_id = os.getenv("GCP_PROJECT_ID")
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    if not project_id:
        raise RuntimeError("GCP_PROJECT_ID não está definido no .env")

    print(f"Usando project_id={project_id}")
    print(f"Usando credentials_path={credentials_path}")

    # Dataset é opcional para run_query("SELECT 1"), então podemos deixar None
    ds = BigQueryDataSource(
        project_id=project_id,
        dataset=None,                 # não precisamos para SELECT 1
        credentials_path=credentials_path,
        label="test-bigquery-direct",
    )

    # Query mais simples possível
    sql = "SELECT 1 AS value"

    print(f"Executando SQL no BigQuery: {sql}")
    rows = ds.run_query(sql)

    print("Resultado:")
    for r in rows:
        print(r)

if __name__ == "__main__":
    main()
