
import asyncio

import httpx

API_BASE_URL = "http://localhost:8001"
CONNECTION_ID = "74004e21-4d35-4151-82bd-f99ba2c32a75"
SPACE_ID = "6a4cf3ad-ddff-4776-9b73-fe8cfce5d7e2"


async def run_dashboard_plan_test():
    url = f"{API_BASE_URL}/connections/{CONNECTION_ID}/dashboards/plan"
    payload = {
        "user_id": "test-user",
        "space_id": SPACE_ID,
        "goal": "Comprehensive analysis of invoices, payments, and customers for 2023",
        "max_widgets": 8,
        "language": "pt"  # Forcing PT to see if it leaks into titles
    }

    async with httpx.AsyncClient() as client:
        print(f"Generating dashboard plan for goal: {payload['goal']}...")
        resp = await client.post(url, json=payload, timeout=60.0)
        if resp.status_code == 200:
            plan = resp.json()
            print("\nDashboard Name:", plan.get("dashboard_name"))
            for w in plan.get("widgets", []):
                print(f"- [{w.get('type')}] Title: {w.get('title')}")
                print(f"  Question: {w.get('question')}")
                print(f"  Viz: {w.get('viz')}")
        else:
            print(f"Error {resp.status_code}: {resp.text}")

if __name__ == "__main__":
    asyncio.run(run_dashboard_plan_test())
