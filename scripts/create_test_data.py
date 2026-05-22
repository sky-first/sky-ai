from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import os
import json

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"), future=True)

USER_ID = "00000000-0000-0000-0000-000000000000"
SPACE_ID = "00000000-0000-0000-0000-000000000001"
CONNECTION_ID = "00000000-0000-0000-0000-000000000002"

with engine.begin() as conn:
    # Criar usuário primeiro (password_hash é obrigatório)
    conn.execute(
        text(
            """
        INSERT INTO users (id, email, password_hash, name, created_at)
        VALUES (:id, :email, :password_hash, :name, NOW())
        ON CONFLICT (id) DO NOTHING
    """
        ),
        {
            "id": USER_ID,
            "email": "test@test.com",
            "password_hash": "dummy_hash_for_test",
            "name": "Test User",
        },
    )
    print(f"✅ Usuário criado: {USER_ID}")

    # Criar Space
    conn.execute(
        text(
            """
        INSERT INTO spaces (id, name, created_by, created_at)
        VALUES (:id, :name, :created_by, NOW())
        ON CONFLICT (id) DO NOTHING
    """
        ),
        {"id": SPACE_ID, "name": "Space de Teste IA", "created_by": USER_ID},
    )
    print(f"✅ Space criado: {SPACE_ID}")

    config_dict = {
        "project_id": os.getenv("GCP_PROJECT_ID", "data-mesh-gcp"),
        "dataset": "data-mesh-gcp.billing_silver",
        "credentials_path": os.getenv(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "/Users/thedatafirst/ia-poc-final/config/gcp/gcp-key.json",
        ),
    }

    # Passar JSON usando psycopg2.extras.Json
    import psycopg2.extras

    config_json_str = json.dumps(config_dict)
    conn.execute(
        text(
            """
        INSERT INTO data_connections (id, name, connector_id, config, status, created_by, created_at)
        VALUES (:id, :name, :connector_id, :config, 'active', :created_by, NOW())
        ON CONFLICT (id) DO NOTHING
    """
        ),
        {
            "id": CONNECTION_ID,
            "name": "Conexao BigQuery de Teste",
            "connector_id": "bigquery",
            "config": psycopg2.extras.Json(config_dict),
            "created_by": USER_ID,
        },
    )
    print(f"✅ DataConnection criada: {CONNECTION_ID}")

    conn.execute(
        text(
            """
        INSERT INTO space_connections (space_id, connection_id)
        VALUES (:space_id, :connection_id)
        ON CONFLICT DO NOTHING
    """
        ),
        {"space_id": SPACE_ID, "connection_id": CONNECTION_ID},
    )
    print("✅ Relacionamento criado")

    print(f"\n📝 IDs para usar no teste:")
    print(f"TEST_SPACE_ID={SPACE_ID}")
    print(f"TEST_CONNECTION_ID={CONNECTION_ID}")
