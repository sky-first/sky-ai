import asyncio
import httpx
import sys


async def trigger_discover(connection_id: str, space_id: str):
    base_url = "http://localhost:8001"
    url = f"{base_url}/connections/{connection_id}/discover"

    print(f"Post to: {url}")

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(
                url, params={"space_id": space_id, "auto_generate_embeddings": "true"}
            )

            if response.status_code == 200:
                print("✅ Discovery Success!")
                print(response.json())
            else:
                print(f"❌ Discovery Failed: {response.status_code}")
                print(response.text)

        except Exception as e:
            print(f"❌ Error: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python trigger_discovery.py <conn_id> <space_id>")
        sys.exit(1)

    conn_id = sys.argv[1]
    space_id = sys.argv[2]

    asyncio.run(trigger_discover(conn_id, space_id))
