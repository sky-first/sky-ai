
import asyncio
import httpx
import json

API_BASE_URL = "http://localhost:8001"
CONNECTION_ID = "4e96c724-b1a1-47a8-9f8c-60af9deaeb89"
SPACE_ID = "bbd2cef9-8d77-427f-a351-0b32a5c20abe"
USER_ID = "ae1a8640-f868-4d2a-9dea-9aa4e21b5dfc"
CREW_IDS = ["c8855919-3138-4780-b60e-d960b29eae5f"]

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

async def fetch_answer(client, question):
    try:
        response = await client.post(
            f"{API_BASE_URL}/connections/{CONNECTION_ID}/query",
            json={
                "question": question,
                "user_id": USER_ID,
                "space_id": SPACE_ID,
                "crew_ids": CREW_IDS,
            },
            timeout=120.0,
        )
        if response.status_code == 200:
            return response.json()
        else:
            return {"answer": f"ERROR ({response.status_code}): {response.text[:200]}"}
    except Exception as e:
        return {"answer": f"EXCEPTION: {str(e)}"}

async def main():
    async with httpx.AsyncClient() as client:
        print("# AI Business Intelligence - Final Report\n")
        for i, question in enumerate(QUESTIONS):
            result = await fetch_answer(client, question)
            print(f"### Q{i+1:02d}: {question}")
            print(f"**Answer:** {result.get('answer', 'No answer received.')}")
            if result.get('sql'):
                print(f"**SQL:**\n```sql\n{result.get('sql')}\n```")
            print("\n---\n")

if __name__ == "__main__":
    asyncio.run(main())
