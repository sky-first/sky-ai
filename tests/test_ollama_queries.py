#!/usr/bin/env python3
"""
Test Ollama queries - Monitor responses and storage
"""
import asyncio
import time

import httpx

QUESTIONS = [
    "What is the monthly revenue performance?",
    "Which customers generate the most revenue?",
    "How is revenue distributed by value category?",
    "How does revenue evolve over time?",
    "What is the invoice status analysis?",
]


async def run_test_queries(connection_id: str, space_id: str):
    """Run test queries to validate Ollama"""

    base_url = "http://localhost:8001"

    results = []

    async with httpx.AsyncClient(timeout=120.0) as client:  # 2 min timeout
        for i, question in enumerate(QUESTIONS, 1):
            print(f"\n{'=' * 70}")
            print(f"[{i}/{len(QUESTIONS)}] Query: {question}")
            print(f"{'=' * 70}")

            start_time = time.time()

            try:
                response = await client.post(
                    f"{base_url}/connections/{connection_id}/query",
                    json={
                        "question": question,
                        "space_id": space_id
                    }
                )

                elapsed = time.time() - start_time

                if response.status_code == 200:
                    result = response.json()

                    has_sql = bool(result.get('sql'))
                    has_data = bool(result.get('data'))
                    has_error = bool(result.get('error'))
                    answer = result.get('answer', '')[:150]

                    status = "✅ SUCCESS" if has_sql and not has_error else "⚠️  PARTIAL" if not has_error else "❌ ERROR"

                    print(f"Status: {status}")
                    print(f"Time: {elapsed:.1f}s")
                    print(f"Has SQL: {has_sql}")
                    print(f"Has Data: {has_data}")
                    print(f"Error: {result.get('error', 'None')[:100]}")
                    print(f"Answer: {answer}...")

                    results.append({
                        "question": question,
                        "status": status,
                        "time": elapsed,
                        "has_sql": has_sql,
                        "has_error": has_error
                    })
                else:
                    print(
                        f"❌ HTTP {response.status_code}: {response.text[:200]}")
                    results.append({
                        "question": question,
                        "status": "❌ HTTP ERROR",
                        "time": elapsed,
                        "has_sql": False,
                        "has_error": True
                    })

            except Exception as e:
                elapsed = time.time() - start_time
                print(f"❌ Exception: {str(e)[:200]}")
                results.append({
                    "question": question,
                    "status": "❌ EXCEPTION",
                    "time": elapsed,
                    "has_sql": False,
                    "has_error": True
                })

            # Delay between queries
            if i < len(QUESTIONS):
                await asyncio.sleep(2)

    # Summary
    print(f"\n{'=' * 70}")
    print(f"📊 SUMMARY")
    print(f"{'=' * 70}")

    successes = sum(1 for r in results if r['status'] == '✅ SUCCESS')
    errors = sum(1 for r in results if r['has_error'])
    avg_time = sum(r['time'] for r in results) / len(results) if results else 0

    print(f"Total Queries: {len(results)}")
    print(f"Successes: {successes}")
    print(f"Errors: {errors}")
    print(f"Average Time: {avg_time:.1f}s")

    for i, r in enumerate(results, 1):
        print(f"\n{i}. {r['question'][:50]}...")
        print(f"   {r['status']} ({r['time']:.1f}s)")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python test_ollama_queries.py <connection-id> <space-id>")
        sys.exit(1)

    connection_id = sys.argv[1]
    space_id = sys.argv[2]

    print(f"🧪 Testing Ollama with {len(QUESTIONS)} queries")
    print(f"Connection: {connection_id}")
    print(f"Space: {space_id}")

    asyncio.run(run_test_queries(connection_id, space_id))
