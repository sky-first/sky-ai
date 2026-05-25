import asyncio
import httpx
import sys
import uuid
import json

# Configuration
BASE_URL = "http://localhost:8001"
CONNECTION_ID = "d84987d7-59a5-4d29-ae73-76bca90f68c2"
SPACE_ID = "bbd2cef9-8d77-427f-a351-0b32a5c20abe"

QUESTIONS = [
    "List the top 5 distinct invoice categories by total amount",
    "Show me the total invoice amount per month for the last year",
    "Who are the top 3 customers by invoice count?",
]


async def run_query(index: int, question: str):
    url = f"{BASE_URL}/connections/{CONNECTION_ID}/query"
    print(f"\nExample {index + 1}: {question}")

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(
                url,
                json={
                    "question": question,
                    "space_id": SPACE_ID,
                    "user_id": str(uuid.uuid4()),
                },
            )

            if response.status_code == 200:
                data = response.json()
                print("✅ Success!")
                # Print a clean summary of the response
                if "answer" in data:
                    print(f"🤖 Answer: {data['answer'][:200]}...")

                # Check for SQL in usage/steps if available, or just trust success
                # Print stats
                if "usage" in data:
                    print(f"📊 Usage: {data['usage']}")
            else:
                print(f"❌ Failed: {response.status_code}")
                # print(response.text[:500])

        except Exception as e:
            print(f"❌ Error: {e}")


async def main():
    print(f"🚀 Running E2E Regression Test with 3 Real Questions")
    print(f"Target: {BASE_URL} | Conn: {CONNECTION_ID}")

    for i, q in enumerate(QUESTIONS):
        await run_query(i, q)
        # Sleep briefly between requests
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
