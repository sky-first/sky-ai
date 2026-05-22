#!/usr/bin/env python3
"""
Populate metadata by running queries via API
"""

import asyncio
import httpx

# Questions to run
QUESTIONS = [
    "What is the monthly revenue performance?",
    "Which customers generate the most revenue?",
    "How is revenue distributed by value category?",
    "How does revenue evolve over time?",
    "What is the invoice status analysis?",
    "What is the monthly payment performance?",
    "Which payment method is most commonly used?",
    "On which days of the week are payments most frequent?",
    "What is the payment status analysis?",
    "Which customers make the most payments?",
    "What is the monthly refund performance?",
    "What are the main reasons for refunds?",
    "What is the monthly credit performance?",
    "What are the main reasons for credits?",
    "What is the consolidated impact of refunds and credits?",
]


async def run_queries(connection_id: str, space_id: str):
    """Run queries to populate metadata"""

    base_url = "http://localhost:8001"

    async with httpx.AsyncClient(timeout=60.0) as client:
        for i, question in enumerate(QUESTIONS, 1):
            print(f"\n[{i}/{len(QUESTIONS)}] Running query: {question[:50]}...")

            try:
                response = await client.post(
                    f"{base_url}/connections/{connection_id}/query",
                    json={"question": question, "space_id": space_id},
                )

                if response.status_code == 200:
                    result = response.json()
                    print(
                        f"✅ Success! Rows: {result.get('meta', {}).get('num_rows', 0)}"
                    )
                else:
                    print(f"⚠️  Status {response.status_code}: {response.text[:100]}")

            except Exception as e:
                print(f"❌ Error: {str(e)[:100]}")

            # Small delay between queries
            await asyncio.sleep(1)

    print(f"\n🎉 Completed {len(QUESTIONS)} queries!")
    print(f"Metadata should now be populated in table_metadata table.")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python populate_metadata_via_api.py <connection-id> <space-id>")
        sys.exit(1)

    connection_id = sys.argv[1]
    space_id = sys.argv[2]

    print(f"=" * 60)
    print(f"🚀 Populating Metadata via API")
    print(f"=" * 60)
    print(f"Connection: {connection_id}")
    print(f"Space: {space_id}")
    print(f"Questions: {len(QUESTIONS)}")

    asyncio.run(run_queries(connection_id, space_id))
