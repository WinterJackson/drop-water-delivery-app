import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from sqlalchemy import create_engine, text
from db.session import get_db
from models.deliverer_model import Deliverer
from models.payout_model import Payout
from utils.encryption import DB_ENCRYPTION_KEY
from sqlalchemy_utils.types.encrypted.encrypted_type import AesEngine
from sqlalchemy_utils import StringEncryptedType
from sqlalchemy import String

def run():
    print("Connecting to db...")
    from dotenv import load_dotenv
    load_dotenv()
    from db.session import database_url

    engine = create_engine(database_url().replace("postgresql+asyncpg", "postgresql+psycopg2"))
    
    # We will instantiate the encrypter directly to manually encrypt
    enc_type = StringEncryptedType(String, DB_ENCRYPTION_KEY, AesEngine, 'pkcs5')
    dialect = engine.dialect
    
    with engine.begin() as conn:
        print("Checking Deliverers...")
        result = conn.execute(text("SELECT id, \"ID_number\" FROM \"Deliverers\""))
        for row in result:
            id_val = row[0]
            val = row[1]
            if val is not None:
                # Let's see if it's already encrypted
                # encrypted usually looks like binary or base64? sqlalchemy-utils stores as string?
                # StringEncryptedType stores as string.
                try:
                    # try to decrypt
                    decrypted = enc_type.process_result_value(val, dialect)
                    print(f"ID {id_val}: already encrypted (decrypted: {decrypted})")
                except ValueError as e:
                    if "not a multiple of the block length" in str(e) or "Incorrect padding" in str(e) or "base64" in str(e):
                        print(f"ID {id_val}: plain text detected -> '{val}'")
                        # Need to encrypt it
                        encrypted = enc_type.process_bind_param(val, dialect)
                        conn.execute(text("UPDATE \"Deliverers\" SET \"ID_number\" = :enc WHERE id = :id"), {"enc": encrypted, "id": id_val})
                        print(f"  -> Encrypted and updated.")
                    else:
                        print(f"ID {id_val}: Unknown ValueError: {e}")
                except Exception as e:
                    print(f"ID {id_val}: plain text detected -> '{val}' (Exception: {e})")
                    encrypted = enc_type.process_bind_param(val, dialect)
                    conn.execute(text("UPDATE \"Deliverers\" SET \"ID_number\" = :enc WHERE id = :id"), {"enc": encrypted, "id": id_val})
                    print(f"  -> Encrypted and updated.")
                    
        print("Checking Payouts...")
        try:
            result = conn.execute(text("SELECT id, \"account_details\" FROM \"Payouts\""))
            for row in result:
                id_val = row[0]
                val = row[1]
                if val is not None:
                    try:
                        decrypted = enc_type.process_result_value(val, dialect)
                        print(f"Payout ID {id_val}: already encrypted.")
                    except Exception as e:
                        print(f"Payout ID {id_val}: plain text detected -> '{val}'")
                        encrypted = enc_type.process_bind_param(val, dialect)
                        conn.execute(text("UPDATE \"Payouts\" SET \"account_details\" = :enc WHERE id = :id"), {"enc": encrypted, "id": id_val})
                        print(f"  -> Encrypted and updated.")
        except Exception as e:
            print("Payouts table check failed:", e)

if __name__ == "__main__":
    run()
