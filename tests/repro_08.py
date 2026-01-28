
import httpx

url = "http://localhost:8001/connections/4e96c724-b1a1-47a8-9f8c-60af9deaeb89/query"
payload = {
    "question": "Which products have low stock?",
    "user_id": "ae1a8640-f868-4d2a-9dea-9aa4e21b5dfc",
    "space_id": "bbd2cef9-8d77-427f-a351-0b32a5c20abe",
    "crew_ids": ["c8855919-3138-4780-b60e-d960b29eae5f"]
}

try:
    response = httpx.post(url, json=payload, timeout=60.0)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")
