import asyncio
import sys
import os

# Adiciona o diretório raiz ao path para encontrar os módulos
sys.path.append(os.getcwd())

async def create_tables():
    from db.base import engine
    from db.models import Base
    import db.models # Importa para garantir que todos os modelos estão carregados
    
    print("🛠 Criando tabelas no banco de dados...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Tabelas criadas com sucesso!")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(create_tables())
