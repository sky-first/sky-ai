# scripts/test_openai_embeddings.py
import os
from dotenv import load_dotenv

from core.rag.embeddings import OpenAIEmbeddingProvider

def main() -> None:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY não está definido no .env")

    provider = OpenAIEmbeddingProvider(model="text-embedding-3-large")

    texts = [
        "Tabela: invoices | Coluna: total_amount | Tipo: NUMERIC",
        "Tabela: customers | Coluna: country | Tipo: STRING",
    ]

    print("Gerando embeddings para:")
    for t in texts:
        print(" -", t)

    vectors = provider.embed(texts)

    print(f"\nGerados {len(vectors)} vetores.")
    for i, vec in enumerate(vectors):
        print(f"Texto {i} → dim={len(vec)}, primeiros 5 valores={vec[:5]}")

if __name__ == "__main__":
    main()
