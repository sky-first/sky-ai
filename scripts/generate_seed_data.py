import asyncio
import json
import sys
import os
from pathlib import Path
from typing import List, Dict
import yaml

# Adicionar root ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from core.llm.providers import LangChainChatOpenAIProvider

async def generate_examples_from_schema(schema_text: str, n_examples: int = 10) -> List[Dict]:
    """
    Usa GPT-4o para gerar exemplos sintéticos de treino (Seed Data).
    """
    llm = LangChainChatOpenAIProvider(
        model="gpt-4o",
        temperature=0.7,
        max_tokens=4000
    )

    prompt = f"""
    You are a specialized Data Generator for Text-to-SQL training.
    
    TASK:
    Based on the DB Schema below, generate {n_examples} examples of:
    1. A natural language question a business user might ask.
    2. The corresponding valid DuckDB SQL query.
    
    SCHEMA:
    {schema_text}
    
    OUTPUT FORMAT:
    Return a pure JSON list of objects. No markdown.
    [
      {{
         "question": "...",
         "sql": "..."
      }},
      ...
    ]
    
    RULES:
    - SQL must be valid DuckDB.
    - Use only columns present in the schema.
    - Questions should vary in complexity (Simple aggregation, Filters, Time-based, simple Joins).
    - Exclude comments in SQL.
    """

    print(f"🤖 Gerando {n_examples} exemplos com GPT-4o...")
    try:
        response = llm.invoke([{"role": "user", "content": prompt}])
        content = response.content.strip()
        
        # Limpeza básica de markdown code block se houver
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "")
        
        examples = json.loads(content)
        return examples
    except Exception as e:
        print(f"❌ Erro ao gerar exemplos: {e}")
        return []

def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_seed_data.py <path_to_schema_yaml> [num_examples]")
        print("Example: python generate_seed_data.py core/agents/sales_agent.yaml 20")
        sys.exit(1)

    yaml_path = sys.argv[1]
    num_examples = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    output_file = "dataset_seed_qlora.jsonl"

    print(f"📂 Lendo schema de: {yaml_path}")
    
    try:
        with open(yaml_path, 'r') as f:
            yaml_content = yaml.safe_load(f)
        
        # Tenta extrair o bloco de descrição das tabelas/schema do YAML
        # Assumindo que o YAML tem uma estrutura onde o schema é legível ou está em 'tables'
        schema_context = yaml.dump(yaml_content) 
        
        # Gerar
        examples = asyncio.run(generate_examples_from_schema(schema_context, num_examples))
        
        if not examples:
            print("❌ Nenhum exemplo gerado.")
            return

        print(f"💾 Salvando {len(examples)} exemplos em {output_file}...")
        
        with open(output_file, "a", encoding="utf-8") as f:
            for ex in examples:
                # Formato Alpaca
                record = {
                    "instruction": "You are a SQL expert. Generate a DuckDB SQL query for the given schema and question.",
                    "input": f"Schema Context:\n{schema_context[:500]}...\n\nQuestion: {ex['question']}",
                    "output": ex['sql']
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        
        print("✅ Concluído!")
        
    except Exception as e:
        print(f"❌ Erro fatal: {e}")

if __name__ == "__main__":
    main()
