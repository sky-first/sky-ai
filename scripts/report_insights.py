import asyncio
import sys
import os
from uuid import UUID

sys.path.append(os.getcwd())

async def report_insights():
    from db.session import AsyncSessionLocal
    from sqlalchemy import text
    
    async with AsyncSessionLocal() as db:
        print("\n" + "="*50)
        print("🚀 RELATÓRIO DE INSIGHTS - UNIVERSE INTELLIGENCE")
        print("="*50)
        
        res = await db.execute(text('SELECT id, title, insight, impact_level, created_at FROM universe_insights ORDER BY created_at DESC'))
        rows = res.all()
        
        if not rows:
            print("\n📭 Nenhum insight aprovado pelo Juiz ainda.")
            print("Execute 'python3 scripts/test_universe_flow_real.py' para rodar um ciclo.")
            return

        for r in rows:
            print(f"\nID: {r[0]}")
            print(f"📌 Título: {r[1]}")
            print(f"📊 Impacto: {r[3].upper()}")
            print(f"📅 Data: {r[4]}")
            print(f"💡 Insight: {r[2][:200]}...")
            print("-" * 30)

if __name__ == "__main__":
    asyncio.run(report_insights())
