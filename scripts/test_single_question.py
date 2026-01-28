import asyncio
import httpx
import sys
import uuid

async def run_query(connection_id: str, space_id: str, question: str):
    base_url = "http://localhost:8001"
    url = f"{base_url}/connections/{connection_id}/query"
    
    print(f"Post to: {url}")
    print(f"Question: {question}")
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(
                url,
                json={
                    "question": question,
                    "space_id": space_id,
                    "user_id": str(uuid.uuid4())
                }
            )
            
            if response.status_code == 200:
                print("✅ Success!")
                print(response.json())
            else:
                print(f"❌ Failed: {response.status_code}")
                print(response.text)
                
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_single_question.py <conn_id> <space_id>")
        sys.exit(1)
        
    conn_id = sys.argv[1]
    space_id = sys.argv[2]
    question = "What is the monthly revenue performance? (v2)"
    
    asyncio.run(run_query(conn_id, space_id, question))
