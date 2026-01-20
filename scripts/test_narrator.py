
import asyncio
import httpx
import json

API_BASE_URL = "http://localhost:8001"
CONNECTION_ID = "74004e21-4d35-4151-82bd-f99ba2c32a75" 

async def test_narrator_language():
    url = f"{API_BASE_URL}/connections/{CONNECTION_ID}/query" # Non-streaming for simplicity in check
    payload = {
        "user_id": "test-user",
        "space_id": "6a4cf3ad-ddff-4776-9b73-fe8cfce5d7e2",
        "question": "What is the total revenue in 2023?",
        "stream": False
    }
    
    async with httpx.AsyncClient() as client:
        print(f"Asking question in Portuguese: '{payload['question']}'...")
        resp = await client.post(url, json=payload, timeout=60.0)
        if resp.status_code == 200:
            data = resp.json()
            print("\nResponse Preview:", data.get("answer"))
            print("Language detectada:", data.get("meta", {}).get("detected_language"))
        else:
            print(f"Error {resp.status_code}: {resp.text}")

if __name__ == "__main__":
    asyncio.run(test_narrator_language())
