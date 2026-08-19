import sys
import os
import asyncio
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from models.deliverer_model import Deliverer
from dotenv import load_dotenv

async def test_decryption():
    load_dotenv()
    from db.session import database_url

    db_url = database_url()
    if "?" in db_url:
        db_url = db_url.split("?")[0] + "?ssl=require"
    engine = create_async_engine(db_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        result = await session.execute(select(Deliverer).limit(5))
        deliverers = result.scalars().all()
        for d in deliverers:
            print(f"ID: {d.id}, ID_number (decrypted): {d.ID_number}")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(test_decryption())
