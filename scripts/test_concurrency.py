#!/usr/bin/env python3
import sys
import asyncio
import httpx
import time
import uuid
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.settings import settings


def get_first_connection_id():
    # Helper to get a valid connection ID
    try:
        from sqlalchemy import create_engine, text

        db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        engine = create_engine(db_url)
        with engine.connect() as conn:
            query = text(
                """
                SELECT dc.id, sc.space_id 
                FROM data_connections dc
                JOIN space_connections sc ON dc.id = sc.connection_id
                LIMIT 1
            """
            )
            result = conn.execute(query)
            row = result.fetchone()
            if row:
                return str(row[0]), str(row[1])
    except Exception as e:
        print(f"Error getting connection: {e}")
    return None, None


async def trigger_pipeline(client, url, payload, request_id):
    print(f"[{request_id}] 🚀 Sending request...")
    try:
        start = time.time()
        response = await client.post(url, json=payload, timeout=30.0)
        elapsed = time.time() - start
        if response.status_code == 200:
            data = response.json()
            print(
                f"[{request_id}] ✅ Success in {elapsed:.2f}s. Job ID: {data.get('pipeline_id')}"
            )
            return data.get("pipeline_id")
        else:
            print(
                f"[{request_id}] ❌ Failed in {elapsed:.2f}s. Status: {response.status_code}"
            )
            return None
    except Exception as e:
        print(f"[{request_id}] ❌ Exception: {e}")
        return None


async def run_concurrency_test():
    conn_id, space_id = get_first_connection_id()
    if not conn_id:
        print("❌ SKIPPING: No connection found.")
        return

    base_url = "http://localhost:8001"
    url = f"{base_url}/pipeline/execute"

    # Generate 3 concurrent requests
    # Use questions that are slightly different to avoid exact cache if any
    questions = [
        "What is the total revenue?",
        "Qual a receita total?",
        "Show me total revenue",
    ]

    tasks = []
    async with httpx.AsyncClient() as client:
        for i, q in enumerate(questions):
            payload = {
                "connection_id": conn_id,
                "question": q,
                "space_id": space_id,
                "user_id": str(uuid.uuid4()),
            }
            tasks.append(trigger_pipeline(client, url, payload, f"Req-{i+1}"))

        print(f"\n🚀 Launching {len(tasks)} parallel requests...")
        results = await asyncio.gather(*tasks)

    successful_jobs = [r for r in results if r]
    print(f"\n🏁 Finished. Successful Jobs: {len(successful_jobs)}/{len(questions)}")

    if len(successful_jobs) == len(questions):
        print("✅ CONCURRENCY TEST PASSED")
    else:
        print("❌ CONCURRENCY TEST FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_concurrency_test())
