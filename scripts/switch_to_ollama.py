#!/usr/bin/env python3
"""
Switch AI Service to Ollama
Migrates from OpenAI to local Ollama models
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncio
from config.settings import settings


def print_status():
    """Print current configuration status"""
    print("=" * 60)
    print("🔧 Current AI Service Configuration")
    print("=" * 60)
    print(
        f"\nProvider: {'Ollama (Local)' if settings.use_local_models else 'OpenAI (Cloud)'}"
    )

    if settings.use_local_models:
        print(f"\n🌐 Ollama Endpoint: {settings.ollama_base_url}")
        print(f"\n📦 Models:")
        print(f"  Orchestrator: {settings.llm_model_orchestrator_local}")
        print(f"  Specialist:   {settings.llm_model_specialist_local}")
        print(f"  Formatter:    {settings.llm_model_formatter_local}")
        print(f"\n⚙️  Context Windows:")
        print(f"  Orchestrator: {settings.ollama_num_ctx_orchestrator} tokens")
        print(f"  Specialist:   {settings.ollama_num_ctx_specialist} tokens")
        print(f"  Formatter:    {settings.ollama_num_ctx_formatter} tokens")
    else:
        print(f"\n☁️  Using OpenAI API (cloud)")

    print("\n" + "=" * 60)


async def test_ollama_connection():
    """Test Ollama endpoint connectivity"""
    import httpx

    print("\n🧪 Testing Ollama Connection...")
    print(f"Endpoint: {settings.ollama_base_url}")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Test 1: List models
            response = await client.get(f"{settings.ollama_base_url}/api/tags")
            response.raise_for_status()
            models = response.json()

            print(f"✅ Connection successful!")
            print(f"\n📊 Available models ({len(models.get('models', []))}):")
            for model in models.get("models", [])[:10]:
                print(f"  - {model['name']} ({model['size'] / 1e9:.1f}GB)")

            # Test 2: Try inference
            print(f"\n🧠 Testing inference with phi3:mini...")
            response = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model": "phi3:mini",
                    "prompt": "Say 'Hello from Ollama!' in one sentence.",
                    "stream": False,
                },
                timeout=300.0,
            )
            response.raise_for_status()
            result = response.json()

            print(f"✅ Inference successful!")
            print(f"Response: {result.get('response', 'N/A')[:100]}")

            return True

    except Exception as e:
        print(f"❌ Connection failed: {repr(e)}")
        return False


async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Switch AI service between OpenAI and Ollama"
    )
    parser.add_argument(
        "--enable", action="store_true", help="Enable Ollama (local models)"
    )
    parser.add_argument(
        "--disable", action="store_true", help="Disable Ollama (use OpenAI)"
    )
    parser.add_argument("--status", action="store_true", help="Show current status")
    parser.add_argument("--test", action="store_true", help="Test Ollama connection")

    args = parser.parse_args()

    if args.status or (not args.enable and not args.disable and not args.test):
        print_status()
        return

    if args.test:
        print_status()
        success = await test_ollama_connection()
        sys.exit(0 if success else 1)

    if args.enable:
        print("\n🔄 Enabling Ollama (local models)...")
        print("\n⚠️  MANUAL STEP REQUIRED:")
        print("   Edit config/settings.py and set:")
        print("   use_local_models: bool = True")
        print("\n   Then restart AI service:")
        print("   cd scripts && ./start-ai.sh")
        print("\n💡 Tip: Test connection first with --test flag")

    if args.disable:
        print("\n🔄 Disabling Ollama (back to OpenAI)...")
        print("\n⚠️  MANUAL STEP REQUIRED:")
        print("   Edit config/settings.py and set:")
        print("   use_local_models: bool = False")
        print("\n   Then restart AI service:")
        print("   cd scripts && ./start-ai.sh")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted")
        sys.exit(1)
