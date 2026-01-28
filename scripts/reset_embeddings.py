import sys
import os
import asyncio
from sqlalchemy import text
from dotenv import load_dotenv

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load env
load_dotenv()

async def clear_embeddings():
    print("🧹 Cleaning ALL embeddings from database (switching to OpenAI)...")
    try:
        from db.session import AsyncSessionLocal
        
        async with AsyncSessionLocal() as db:
            print("   Connected to database.")
            # Delete all rows from embeddings table
            # Adjust table name if needed (checked db/models.py -> __tablename__ = "embeddings")
            await db.execute(text("DELETE FROM embeddings"))
            await db.commit()
            print("✅ Embeddings table cleared successfully.")
            
    except Exception as e:
        print(f"❌ Error clearing embeddings: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(clear_embeddings())
