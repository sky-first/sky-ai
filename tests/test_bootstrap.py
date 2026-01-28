
import asyncio

import httpx

API_BASE_URL = "http://localhost:8001"
CONNECTION_ID = "74004e21-4d35-4151-82bd-f99ba2c32a75"
SPACE_ID = "6a4cf3ad-ddff-4776-9b73-fe8cfce5d7e2"


async def test_bootstrap():
    url = f"{API_BASE_URL}/connections/{CONNECTION_ID}/chat/bootstrap"
    payload = {
        "user_id": "test-user",
        "space_id": SPACE_ID,
        "language": "pt"  # Forcing PT
    }

    async with httpx.AsyncClient() as client:
        print(f"Generating bootstrap suggestions...")
        resp = await client.post(url, json=payload, timeout=60.0)
        if resp.status_code == 200:
            data = resp.json()
            print("\nGreeting:", data.get("greeting"))
            for s in data.get("suggestions", []):
                print(f"- Title: {s.get('title')}")
                print(f"  Question: {s.get('question')}")
        else:
            print(f"Error {resp.status_code}: {resp.text}")

if __name__ == "__main__":
    asyncio.run(test_bootstrap())
