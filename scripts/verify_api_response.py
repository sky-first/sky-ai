import requests
import json
import time

# Configuration
API_URL = "http://127.0.0.1:8001"
CONNECTION_ID = "70b0fbf5-195d-426a-b96e-78fc8ee32c38"
SPACE_ID = "bbd2cef9-8d77-427f-a351-0b32a5c20abe"
# USER_ID extracted from logs: "ae1a8640-f868-4d2a-9dea-9aa4e21b5dfc"
USER_ID = "ae1a8640-f868-4d2a-9dea-9aa4e21b5dfc"


def run_query(question):
    url = f"{API_URL}/connections/{CONNECTION_ID}/query"
    payload = {
        "question": question,
        "space_id": SPACE_ID,
        # user_id in body might be optional if header is present, but keeping it does no harm
        "user_id": USER_ID,
    }

    # AUTH HEADERS REQUIRED
    headers = {"X-User-ID": USER_ID, "Content-Type": "application/json"}

    print(f"\n--- Asking: '{question}' ---")
    try:
        start_time = time.time()
        response = requests.post(url, json=payload, headers=headers)
        elapsed = time.time() - start_time

        if response.status_code == 200:
            data = response.json()
            answer = data.get("answer", "")
            rows = data.get("data_sample", [])
            meta = data.get("meta", {})

            print(f"Status: 200 OK ({elapsed:.2f}s)")
            print(f"Answer: {answer}")
            print(f"SQL: {meta.get('sql')}")
            print(f"Num Rows: {meta.get('num_rows')}")
            print(f"Sample Size: {len(rows)}")

            if rows:
                print("Data Sample:")
                for i, row in enumerate(rows[:3]):
                    print(f"  Row {i+1}: {row}")
            else:
                print("⚠️ NO DATA RETURNED in sample.")

            return data
        else:
            print(f"Error {response.status_code}: {response.text}")
            return None
    except Exception as e:
        print(f"Exception: {e}")
        return None


if __name__ == "__main__":
    print(f"Testing API at {API_URL}...")

    # Test 1: The originally problematic query
    print("\n[TEST 1] Checking fix for 'No Data' bug...")
    run_query("What is the monthly revenue performance?")

    # Test 2: Simple retrieval check
    print("\n[TEST 2] Checking basic data retrieval...")
    run_query("List the first 3 invoices")
