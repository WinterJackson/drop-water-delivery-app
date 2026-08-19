import sys
import os
import asyncio
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text, String
from utils.encryption import DB_ENCRYPTION_KEY
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine
from sqlalchemy_utils import StringEncryptedType
from dotenv import load_dotenv

async def run():
    load_dotenv()
    from db.session import database_url

    db_url = database_url()
    if "?" in db_url:
        db_url = db_url.split("?")[0] + "?ssl=require"
    engine = create_async_engine(db_url)
    
    enc_type = StringEncryptedType(String, DB_ENCRYPTION_KEY, AesEngine, 'pkcs5')
    dialect = engine.dialect
    
    async with engine.begin() as conn:
        print("Checking Deliverers...")
        result = await conn.execute(text("SELECT id, \"ID_number\" FROM \"Deliverers\""))
        rows = result.fetchall()
        for row in rows:
            id_val = row[0]
            val = row[1]
            if val is not None:
                try:
                    decrypted = enc_type.process_result_value(val, dialect)
                    print(f"ID {id_val}: already encrypted")
                except Exception as e:
                    print(f"ID {id_val}: plain text detected -> '{val}'")
                    encrypted = enc_type.process_bind_param(val, dialect)
                    await conn.execute(text("UPDATE \"Deliverers\" SET \"ID_number\" = :enc WHERE id = :id"), {"enc": encrypted, "id": id_val})
                    print(f"  -> Encrypted and updated.")
                    
        print("Checking payouts...")
        try:
            result = await conn.execute(text("SELECT id, \"account_details\" FROM \"payouts\""))
            rows = result.fetchall()
            for row in rows:
                id_val = row[0]
                val = row[1]
                if val is not None:
                    try:
                        decrypted = enc_type.process_result_value(val, dialect)
                        print(f"Payout ID {id_val}: already encrypted.")
                    except Exception as e:
                        print(f"Payout ID {id_val}: plain text detected -> '{val}'")
                        encrypted = enc_type.process_bind_param(val, dialect)
                        await conn.execute(text("UPDATE \"payouts\" SET \"account_details\" = :enc WHERE id = :id"), {"enc": encrypted, "id": id_val})
                        print(f"  -> Encrypted and updated.")
        except Exception as e:
            print("payouts table check failed:", e)

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(run())
