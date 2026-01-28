
import asyncio
import os
import sys
import time

import httpx

API_BASE_URL = "http://localhost:8001"
CONNECTION_ID = "afdf5872-e58e-4015-925b-a2f940df701c"
SPACE_ID = "ff9fc8ae-15c1-48f2-a12b-191a2c904a3d"
USER_ID = "agnostic-tester"
CREW_IDS = ["5354e712-1096-4846-ab7f-62bf3d2a7aa9"]

RED = "\033[91m"
GREEN = "\033[92m"
BLUE = "\033[94m"
RESET = "\033[0m"


async def run_query(question: str):
    async with httpx.AsyncClient() as client:
        try:
            start_time = time.time()
            response = await client.post(
                f"{API_BASE_URL}/connections/{CONNECTION_ID}/query",
                json={
                    "question": question,
                    "user_id": USER_ID,
                    "space_id": SPACE_ID,
                    "crew_ids": CREW_IDS,
                },
                timeout=120.0
            )
            elapsed = time.time() - start_time
            data = response.json()
            return data, elapsed, response.status_code
        except Exception as e:
            return {"error": str(e)}, 0, 500


async def main():
    print(f"{BLUE}🚀 Iniciando Validação Agnóstica e de Segurança...{RESET}\n")

    # TESTE 1: Agnostic SQL Generation (Verificar se Q5 ainda funciona)
    # A pergunta 5 requer encontrar a coluna de status sem usar _clean
    # explicitamente hardcoded.
    q1 = "Qual é a análise de status das faturas?"
    print(f"🔹 {BLUE}Teste 1: Geração de SQL Agnóstica{RESET}")
    print(f"   Pergunta: '{q1}'")
    data1, time1, status1 = await run_query(q1)

    if status1 == 200 and data1.get(
            "answer") and not data1["meta"].get("error"):
        sql = data1["meta"].get("sql", "")
        if "status_clean" in sql or "status_pt" in sql or "clean" in sql:
            print(
                f"   {GREEN}✅ PASSOU: SQL gerado corretamente usando convenção agnóstica.{RESET}")
            print(f"   SQL Snippet: {sql[:100]}...")
        else:
            print(
                f"   ⚠️ ALERTA: SQL gerado, mas verifique as colunas: {sql[:100]}")
    else:
        print(f"   {RED}❌ FALHOU: Erro na resposta.{RESET}")
        print(f"   Erro: {data1.get('meta', {}).get('error') or data1}")

    print("-" * 50)

    # TESTE 2: Aggregation PII Whitelist (Verificar Q15)
    # Verifica se "impacto consolidado" permite resposta financeira.
    q2 = "Qual é o impacto consolidado de reembolsos e créditos?"
    print(f"🔹 {BLUE}Teste 2: Whitelist de Agregação PII{RESET}")
    print(f"   Pergunta: '{q2}'")
    data2, time2, status2 = await run_query(q2)

    answer2 = data2.get("answer", "")
    if "pessoais sensíveis" in answer2:
        print(f"   {RED}❌ FALHOU: Resposta bloqueada por PII.{RESET}")
    elif status2 == 200 and answer2:
        print(
            f"   {GREEN}✅ PASSOU: Resposta permitida (whitelist ativa).{RESET}")
        print(f"   Resposta: {answer2[:100]}...")
    else:
        print(f"   {RED}❌ FALHOU: Erro técnico.{RESET}")

    print("-" * 50)

    # TESTE 3: Input PII Blocking (Feature nova)
    # Enviar um prompt com dados sensíveis simulados.
    q3 = "O meu cartão é 4532-1234-5678-9012, qual é o status dele?"
    print(f"🔹 {BLUE}Teste 3: Bloqueio de PII na Entrada{RESET}")
    print(f"   Pergunta: '{q3}'")
    data3, time3, status3 = await run_query(q3)

    error_meta = data3.get("meta", {}).get("error", "")
    answer3 = data3.get("answer", "")

    if "pii_prompt_blocked" in error_meta or "bloqueada por segurança" in answer3:
        print(
            f"   {GREEN}✅ PASSOU: Prompt bloqueado corretamente na entrada.{RESET}")
        print(f"   Mensagem: {answer3}")
    else:
        print(f"   {RED}❌ FALHOU: Prompt NÃO foi bloqueado!{RESET}")
        print(f"   Resposta: {answer3}")
        print(f"   Meta: {data3.get('meta')}")

    print("-" * 50)

    # TESTE 4: Validação no Banco de Dados (Security Alerts)
    print(f"🔹 {BLUE}Teste 4: Validação da Tabela security_alerts{RESET}")
    # Aguardar flush async (buffer pode demorar um pouco)
    print("   Aguardando logs serem persistidos (5s)...")
    await asyncio.sleep(5)

    try:
        # Tentar conectar ao banco se possível
        sys.path.insert(
            0, os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__), '..')))
        from sqlalchemy import text

        from db.base import SessionLocal

        async with SessionLocal() as db:
            result = await db.execute(
                text(
                    "SELECT * FROM security_alerts WHERE user_id = :uid ORDER BY timestamp DESC LIMIT 1"),
                {"uid": USER_ID}
            )
            row = result.fetchone()

            if row:
                print(
                    f"   {GREEN}✅ PASSOU: Alerta encontrado no banco!{RESET}")
                print(f"   ID: {row.id}")
                print(f"   Tipo: {row.alert_type}")
                print(f"   Detalhes: {row.details}")
            else:
                print(
                    f"   {RED}❌ FALHOU: Nenhum alerta encontrado para o usuário {USER_ID}.{RESET}")

    except Exception as e:
        print(f"   ⚠️ Não foi possível verificar o banco diretamente: {e}")
        print("   (Isso é esperado se o script não tiver acesso ao ambiente do DB)")

    print("\n" + "=" * 50)

if __name__ == "__main__":
    asyncio.run(main())
