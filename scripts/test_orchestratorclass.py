import sys
import os
import asyncio
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.getcwd())
load_dotenv()

from config.settings import settings
from core.llm.factory import create_llm_orchestrator


async def test_orchestrator():
    print("=== TESTING ORCHESTRATOR ISOLATION ===\n")
    print(f"1. Configuration:")
    print(f"   - URL: {settings.ollama_base_url}")
    print(f"   - Model: {settings.llm_model_orchestrator_local}")
    print(f"   - Local Mode: {settings.use_local_models}")

    print("\n2. Initializing LLM...")
    try:
        llm = create_llm_orchestrator()
    except Exception as e:
        print(f"❌ Failed to create LLM: {e}")
        return

    print("\n3. Testing Connection (Simple Hello)...")
    try:
        # Simple invoke to check connectivity
        response = llm.invoke("Hello, are you ready?")
        print(f"✅ Connection Successful!")
        print(f"🤖 Response: {response.content}")
    except Exception as e:
        print(f"❌ CONNECTION FAILED: {e}")
        print("\n👉 DIAGNOSIS: The AI Service is unreachable.")
        if "404" in str(e):
            print("   - Result: 404 Not Found")
            print(
                "   - Cause: The URL is reachable but the endpoint is wrong (or model missing)."
            )
            print(
                "   - Fix: Check if RunPod is running Ollama and if `phi3:mini` is pulled."
            )
        elif "Connection refused" in str(e):
            print("   - Cause: Service is down.")
        return

    # If connection works, we would test actual orchestrator logic here
    # But for now, just proving connection is the goal.


if __name__ == "__main__":
    asyncio.run(test_orchestrator())
