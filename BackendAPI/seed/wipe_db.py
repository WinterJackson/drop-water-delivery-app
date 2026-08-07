"""Empty every table the seeders write, in one statement.

`TRUNCATE ... CASCADE` rather than `DELETE`, so the dependent rows the seeders
create indirectly — cart items, wallet transactions, bottle ledger entries,
rider registrations — go with them. Deleting the parents alone leaves orphans
that make the next seed run look like it produced impossible data.

`Platform_Settings` is deliberately **not** truncated: those are the owners'
business figures, not seed data, and a wipe that silently reset the commission
schedule would be a much worse surprise than a full table.
"""
import asyncio

from sqlalchemy import text

from db.session import AsyncSessionLocal

#: Exact, double-quoted, because these table names are case-sensitive in Postgres.
SEEDED_TABLES = (
    '"Order_Items"',
    '"Orders"',
    '"Cart_Items"',
    '"Carts"',
    '"bottle_ledger_entries"',
    '"Vendor_Rider_Registry"',
    '"Wallet_Transactions"',
    '"Products"',
    '"Vendors"',
    '"Deliverers"',
    '"Users"',
)


async def wipe_db():
    async with AsyncSessionLocal() as session:
        # Missing tables are skipped rather than aborting the wipe: the set above
        # spans several migrations, and a database at an older revision should
        # still be clearable.
        present = []
        for table in SEEDED_TABLES:
            exists = (
                await session.execute(
                    text("SELECT to_regclass(:name)"), {"name": table.strip('"')}
                )
            ).scalar()
            if exists is not None:
                present.append(table)

        await session.execute(text(f"TRUNCATE TABLE {', '.join(present)} CASCADE;"))
        await session.commit()
        print(f"✅ Wiped {len(present)} table(s). Platform_Settings left untouched.")


if __name__ == "__main__":
    asyncio.run(wipe_db())
