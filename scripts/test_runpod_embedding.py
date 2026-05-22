import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.rag.embeddings import OllamaEmbeddingProvider
from config.settings import settings


async def test_embedding():
    print(f"Testing Ollama Embedding with URL: {settings.ollama_base_url}")
    print(f"Model: {settings.llm_model_embedding_local}")

    provider = OllamaEmbeddingProvider(model=settings.llm_model_embedding_local)

    text = "RunPod Ollama setup verification"
    print(f"\nEmbedding text: '{text}'")

    try:
        vectors = await provider.embed_async([text])
        if vectors and len(vectors) > 0:
            vec = vectors[0]
            print(f"✅ Success! Generated embedding with {len(vec)} dimensions.")
            print(f"Sample: {vec[:5]}...")
        else:
            print("❌ Failed to generate embedding (empty result)")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_embedding())
