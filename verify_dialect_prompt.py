
import sys
import os

# Adiciona o diretório atual ao path para importações
sys.path.append(os.getcwd())

from core.dialects import Dialect
from core.llm.specialist import _build_secure_system_prompt

def test_dialect_prompts():
    print("🧪 Starting Dialect Prompt Verification...")

    # Test 1: Postgres (Default SQL)
    print("\n--- Test 1: Postgres (SQL) ---")
    prompt_pg = _build_secure_system_prompt(
        physical_names=["users"],
        dialect=Dialect.POSTGRES,
        detected_language="English"
    )
    content_pg = prompt_pg["content"]
    
    if "Dialect: POSTGRES" in content_pg:
        print("✅ Correctly identified Dialect: POSTGRES")
    else:
        print(f"❌ Failed to identify Dialect POSTGRES. Content preview: {content_pg[:100]}")

    if 'Rules: Use " for identifiers' in content_pg:
        print("✅ Correct identifier quote for Postgres")
    else:
        print("❌ Incorrect identifier quote for Postgres")

    # Test 2: BigQuery (SQL)
    print("\n--- Test 2: BigQuery (SQL) ---")
    prompt_bq = _build_secure_system_prompt(
        physical_names=["analytics.events"],
        dialect=Dialect.BIGQUERY,
        detected_language="Portuguese"
    )
    content_bq = prompt_bq["content"]
    
    if "Dialect: BIGQUERY" in content_bq:
        print("✅ Correctly identified Dialect: BIGQUERY")
    else:
        print("❌ Failed.")

    if "Use ` for identifiers" in content_bq:
        print("✅ Correct identifier quote for BigQuery")
    else:
        print("❌ Incorrect identifier quote for BigQuery")

    # Test 3: MongoDB (NoSQL)
    print("\n--- Test 3: MongoDB (NoSQL) ---")
    prompt_mongo = _build_secure_system_prompt(
        physical_names=["orders"],
        dialect=Dialect.MONGODB,
        detected_language="English"
    )
    content_mongo = prompt_mongo["content"]

    if "expert in MONGODB (MongoDB Aggregation Pipeline)" in content_mongo:
        print("✅ Correctly identified NoSQL mode for MongoDB")
    else:
        print(f"❌ Failed NoSQL mode. Content: {content_mongo[:100]}")
    
    if "Do NOT generate SQL" in content_mongo:
        print("✅ Found NoSQL warning instruction")
    else:
        print("❌ Missing NoSQL warning")

    print("\n🏁 Verification Complete.")

if __name__ == "__main__":
    test_dialect_prompts()
