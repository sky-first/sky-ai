#!/usr/bin/env python3
"""
Script to test 15 business questions and measure response time.
"""
import asyncio
import time
from typing import Any, Dict, List

import httpx

# Configuration
API_BASE_URL = "http://localhost:8001"  # AI Service runs on port 8001
CONNECTION_ID = "4e96c724-b1a1-47a8-9f8c-60af9deaeb89"
SPACE_ID = "bbd2cef9-8d77-427f-a351-0b32a5c20abe"
USER_ID = "ae1a8640-f868-4d2a-9dea-9aa4e21b5dfc"
CREW_IDS = ["c8855919-3138-4780-b60e-d960b29eae5f"]

# Headers
HEADERS = {
    "Content-Type": "application/json",
}

# 15 business questions
QUESTIONS = [
    "What was the total sales last month?",
    "What are the top 10 best-selling products?",
    "What is the average revenue per customer?",
    "How many new customers did we allow this year?",
    "What is the average ticket size?",
    "What are the sales by region?",
    "What is the monthly growth rate?",
    "Which products have low stock?",
    "What is the revenue by category?",
    "Who are the most profitable customers?",
    "What is the profit margin per product?",
    "How many orders were canceled?",
    "What is the average items per order?",
    "Which sales representatives have the best performance?",
    "What is the sales forecast for next month?",
]


async def run_test_case(
    client: httpx.AsyncClient, question: str, index: int
) -> Dict[str, Any]:
    """Tests a question and returns the result."""
    start_time = time.time()

    try:
        response = await client.post(
            f"{API_BASE_URL}/connections/{CONNECTION_ID}/query",
            json={
                "question": question,
                "user_id": USER_ID,
                "space_id": SPACE_ID,
                "crew_ids": CREW_IDS,
            },
            headers=HEADERS,
            timeout=120.0,
        )
        elapsed = time.time() - start_time

        if response.status_code == 200:
            data = response.json()
            return {
                "index": index + 1,
                "question": question,
                "status": "SUCCESS",
                "time_seconds": round(elapsed, 2),
                "sql": data.get("sql", "")[:100] + "..." if data.get("sql") else None,
                "row_count": len(data.get("data", [])) if data.get("data") else 0,
            }
        else:
            return {
                "index": index + 1,
                "question": question,
                "status": f"ERROR ({response.status_code})",
                "time_seconds": round(elapsed, 2),
                "error": response.text[:200],
            }
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "index": index + 1,
            "question": question,
            "status": "EXCEPTION",
            "time_seconds": round(elapsed, 2),
            "error": str(e)[:200],
        }


async def run_tests():
    """Executes all tests."""
    print("=" * 80)
    print("TESTING 15 BUSINESS QUESTIONS")
    print("=" * 80)
    print()

    # Check if server is running
    async with httpx.AsyncClient() as client:
        try:
            health = await client.get(f"{API_BASE_URL}/health", timeout=5.0)
            if health.status_code != 200:
                print(f"❌ Server is not healthy: {health.status_code}")
                return
            print("✅ Server is running")
        except Exception as e:
            print(f"❌ Could not connect to server: {e}")
            print(f"   Check if server is running at {API_BASE_URL}")
            return

    print()
    print("Running questions...")
    print("-" * 80)

    results: List[Dict[str, Any]] = []
    total_start = time.time()

    async with httpx.AsyncClient() as client:
        for i, question in enumerate(QUESTIONS):
            result = await run_test_case(client, question, i)
            results.append(result)

            status_icon = "✅" if result["status"] == "SUCCESS" else "❌"
            print(
                f"{status_icon} [{result['index']:02d}] {result['time_seconds']:5.1f}s - {question[:50]}..."
            )

    total_time = time.time() - total_start

    # Summary
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    successful = [r for r in results if r["status"] == "SUCCESS"]
    failed = [r for r in results if r["status"] != "SUCCESS"]

    times = [r["time_seconds"] for r in successful]
    avg_time = sum(times) / len(times) if times else 0

    print(f"Total questions: {len(QUESTIONS)}")
    print(f"Success: {len(successful)}")
    print(f"Failed: {len(failed)}")
    print(f"Total time: {total_time:.1f}s")
    print(f"Average time per question: {avg_time:.1f}s")

    if times:
        print(f"Min time: {min(times):.1f}s")
        print(f"Max time: {max(times):.1f}s")

    if failed:
        print()
        print("Failed questions:")
        for r in failed:
            print(f"  - [{r['index']:02d}] {r['question'][:40]}...")
            print(f"    Status: {r['status']}")
            if "error" in r:
                print(f"    Error: {r['error'][:100]}")

    print()
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_tests())
