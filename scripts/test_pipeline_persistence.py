import asyncio
import httpx
import sys
import uuid
import time

# Configuration
BASE_URL = "http://localhost:8001"


async def get_first_connection(client):
    """Fetch a valid connection ID to test with."""
    try:
        # Assuming there is an endpoint or we can direct query
        # For now, let's try to list spaces/connections if available or use a known one
        # Use the hardcoded one from main.py debug if not found?
        # Actually, let's try to query the DB directly via python if API doesn't list
        # But for an E2E test, API is better.
        # Let's try to execute on a known ID if we have one, or fail.
        pass
    except Exception:
        pass
    return None


async def run_pipeline_test(connection_id: str, space_id: str):
    question = "Qual foi a receita total no ultimo mês?"
    print(f"🚀 Starting Pipeline Test")
    print(f"Question: {question}")
    print(f"Connection: {connection_id}")

    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Start Pipeline (Async)
        print("\n1️⃣  Sending POST /pipeline/execute (async)...")
        response = await client.post(
            f"{BASE_URL}/pipeline/execute",
            json={
                "question": question,
                "space_id": space_id,
            },
            params={"connection_id": connection_id, "run_async": True},
        )

        if response.status_code != 200:
            print(f"❌ Failed to start pipeline: {response.text}")
            return

        data = response.json()
        pipeline_id = data["pipeline_id"]
        print(f"✅ Pipeline Started. ID: {pipeline_id}")

        # 2. Poll Status
        print("\n2️⃣  Polling status...")
        status = "pending"
        attempts = 0
        while status in ["pending", "running"] and attempts < 30:
            attempts += 1
            resp = await client.get(f"{BASE_URL}/pipeline/{pipeline_id}/status")
            state = resp.json()
            status = state["status"]
            print(f"   Attempt {attempts}: Status = {status}")

            if status in ["completed", "failed"]:
                break

            await asyncio.sleep(1)

        # 3. Verify Result
        if status == "completed":
            print("\n✅ Pipeline Completed Successfully!")
            print("Answer:", state.get("result", {}).get("answer"))

            # 4. Check Logs
            print("\n3️⃣  Checking Logs...")
            logs_resp = await client.get(f"{BASE_URL}/pipeline/{pipeline_id}/logs")
            logs = logs_resp.json().get("logs", [])
            print(f"   Found {len(logs)} log entries.")
            for log in logs[:3]:
                print(f"   - [{log['level']}] {log['message']}")
        else:
            print(f"\n❌ Pipeline Failed or Timed Out. Status: {status}")
            print("Error:", state.get("error"))


if __name__ == "__main__":
    # DEVOPS: Hardcoded IDs for testing (from seed_demo_spaces.py usually)
    # You might need to change these if your local DB has different IDs
    # Using IDs commonly seen in this project's context or passed as args

    if len(sys.argv) >= 3:
        conn_id = sys.argv[1]
        space_id = sys.argv[2]
    else:
        # Fallback values (try to match your local setup)
        # These are dummy UUIDs, likely need real ones.
        print(
            "⚠️  No arguments provided. Usage: python test_pipeline_persistence.py <conn_id> <space_id>"
        )
        print("   Attempting to find ID via script...")
        # Import local script if possible or just fail
        sys.exit(1)

    asyncio.run(run_pipeline_test(conn_id, space_id))
