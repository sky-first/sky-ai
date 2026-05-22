import httpx

url = "http://localhost:8001/connections/4e96c724-b1a1-47a8-9f8c-60af9deaeb89/query"


def test(question):
    payload = {
        "question": question,
        "user_id": "ae1a8640-f868-4d2a-9dea-9aa4e21b5dfc",
        "space_id": "bbd2cef9-8d77-427f-a351-0b32a5c20abe",
        "crew_ids": ["c8855919-3138-4780-b60e-d960b29eae5f"],
    }
    response = httpx.post(url, json=payload, timeout=60.0)
    print(f"Q: {question}")
    print(f"A: {response.json().get('answer')}")
    print(f"SQL: {response.json().get('sql')}")
    print("-" * 20)


test("Which products have low stock?")
test("Which sales representatives have the best performance?")
test("What is the sales forecast for next month?")
