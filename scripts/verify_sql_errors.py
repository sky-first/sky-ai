
import asyncio
import json
import httpx
import sys

# Simulação de erro técnico
# Para este teste, assumimos que a API está rodando localmente na porta 8001
BASE_URL = "http://localhost:8001"
# ID de conexão real obtido do banco
CONNECTION_ID = "afdf5872-e58e-4015-925b-a2f940df701c"

async def test_sql_error_handling():
    print("Testing SQL Error Handling (Friendly Messages)...")
    
    # Payload para testar
    payload = {
        "question": "Quanto faturamos no mês passado?",
        "user_id": "test_user",
        "space_id": "00000000-0000-0000-0000-000000000001"
    }
    
    print("\n--- Testing Non-Streaming Error ---")
    try:
        async with httpx.AsyncClient() as client:
            # Forçar erro interno (ex: passando dados que causem falha na lógica posterior ou usando ID mal formatado)
            # Para testar o Technical Error, vamos induzir um erro genérico se possível, 
            # ou simplesmente verificar se erros de execução retornam a mensagem certa.
            response = await client.post(
                f"{BASE_URL}/connections/{CONNECTION_ID}/query",
                json=payload,
                timeout=30.0
            )
            
            print(f"Status Code: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                answer = data.get("answer", "")
                print(f"Response Answer: {answer}")
                # Se o agente rodar bem, veremos a resposta da IA. 
                # Se falhar (ex: LLM fora do ar), veremos o Technical Error.
                if "erro técnico" in answer.lower() or "technical error" in answer.lower():
                    print("✅ Correct friendly error message received!")
                else:
                    print(f"ℹ️ Received normal response (or other error): {answer[:100]}...")
            else:
                print(f"❌ Failed to get 200 response: {response.status_code}")
                print(response.text)
                
    except Exception as e:
        print(f"❌ Error during test: {e}")

async def test_streaming_error_handling():
    print("\n--- Testing Streaming Error ---")
    payload = {
        "question": "How much is the total revenue?",
        "user_id": "test_user",
        "space_id": "00000000-0000-0000-0000-000000000001"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{BASE_URL}/connections/{CONNECTION_ID}/query/stream",
                json=payload,
                timeout=30.0
            ) as response:
                print(f"Status Code: {response.status_code}")
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            if data.get("type") == "error":
                                msg = data.get("message", "")
                                print(f"Stream Error Message: {msg}")
                                if "technical error" in msg.lower() or "erro técnico" in msg.lower():
                                    print("✅ Correct friendly stream error message received!")
                            elif data.get("type") == "chunk":
                                 content = data.get("content", "")
                                 print(f"Chunk: {content[:50]}...")
                                 if "technical error" in content.lower() or "erro técnico" in content.lower():
                                    print("✅ Correct friendly chunk error message received!")
                        except:
                            pass
                
    except Exception as e:
        print(f"❌ Error during stream test: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        CONNECTION_ID = sys.argv[1]
    asyncio.run(test_sql_error_handling())
    asyncio.run(test_streaming_error_handling())
