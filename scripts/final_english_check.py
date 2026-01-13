
import asyncio
import httpx
import json

API_BASE_URL = "http://localhost:8001"
CONNECTION_ID = "74004e21-4d35-4151-82bd-f99ba2c32a75" 
SPACE_ID = "6a4cf3ad-ddff-4776-9b73-fe8cfce5d7e2"

async def check():
    async with httpx.AsyncClient() as client:
        print("--- 1. Testing Bootstrap (Sherlock) ---")
        bootstrap_url = f"{API_BASE_URL}/connections/{CONNECTION_ID}/chat/bootstrap"
        r1 = await client.post(bootstrap_url, json={"user_id": "test", "space_id": SPACE_ID, "language": "pt"}, timeout=30)
        if r1.status_code == 200:
            data = r1.json()
            print(f"Greeting: {data.get('greeting')}")
            for s in data.get("suggestions", [])[:2]:
                print(f"Suggestion: {s.get('title')} - {s.get('question')}")
        
        print("\n--- 2. Testing Dashboard Plan (Davinci) ---")
        dash_url = f"{API_BASE_URL}/connections/{CONNECTION_ID}/dashboards/plan"
        r2 = await client.post(dash_url, json={"user_id": "test", "space_id": SPACE_ID, "goal": "Análise de vendas", "language": "pt", "max_widgets": 2}, timeout=30)
        if r2.status_code == 200:
            data = r2.json()
            print(f"Dashboard Name: {data.get('dashboard_name')}")
            for w in data.get("widgets", []):
                print(f"Widget Title: {w.get('title')}")
        
        print("\n--- 3. Testing AI Narrator (Query) ---")
        query_url = f"{API_BASE_URL}/connections/{CONNECTION_ID}/query"
        r3 = await client.post(query_url, json={"user_id": "test", "space_id": SPACE_ID, "question": "Qual o faturamento total?", "stream": False}, timeout=30)
        if r3.status_code == 200:
            data = r3.json()
            print(f"Answer: {data.get('answer')}")
            sql = data.get('meta', {}).get('sql')
            if sql:
                print(f"SQL check: {sql[:100]}...")
            else:
                print("No SQL returned (expected for blocked PT query)")

        print("\n--- 4. Testing Title Suggestion ---")
        title_url = f"{API_BASE_URL}/widgets/suggest-title"
        sample_data = [{"customer": "Company A", "total": 1000}, {"customer": "Company B", "total": 2000}]
        r4 = await client.post(title_url, json={"question": "Quem são meus clientes?", "data_sample": sample_data, "language": "pt"}, timeout=30)
        if r4.status_code == 200:
            data = r4.json()
            print(f"Suggested Title: {data.get('title')}")

if __name__ == "__main__":
    asyncio.run(check())
