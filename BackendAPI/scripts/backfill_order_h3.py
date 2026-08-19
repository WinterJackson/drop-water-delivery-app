#!/usr/bin/env python
"""Fill in `Orders.h3_index_res8` for orders created before it was written.

`create_order` computes the cell from the delivery coordinates and stores it, so
every new order has one. Orders that predate that line do not — and two features
read the column and silently show nothing rather than failing:

* the admin map's **demand** layer (`admin_geo_service.demand_cells`), and
* the analytics **geographic demand** breakdown.

Both aggregate by cell and both filter `h3_index_res8 IS NOT NULL`, so a gap
looks exactly like "no orders here" — the least useful way for missing data to
present itself, on the screen whose whole job is showing where the orders are.

The cell is derived from `lat`/`lng` already on the row, so this invents nothing:
it is the same `h3.latlng_to_cell(lat, lng, 8)` the order would have run at
creation. Rows without coordinates are skipped, not guessed.

    python scripts/backfill_order_h3.py            # report only
    python scripts/backfill_order_h3.py --apply

Idempotent: it only touches rows where the column is NULL.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESOLUTION = 8


def _dsn() -> str:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

    from db.session import database_url

    raw = database_url()
    if not raw:
        print("DATABASE_URL is not set.", file=sys.stderr)
        raise SystemExit(2)
    return re.sub(r"^postgresql\+\w+://", "postgresql://", raw).split("?")[0]


async def run(apply: bool) -> int:
    import asyncpg
    import h3

    conn = await asyncpg.connect(_dsn(), ssl="require")
    try:
        rows = await conn.fetch(
            'SELECT id, lat, lng FROM "Orders" '
            "WHERE h3_index_res8 IS NULL AND lat IS NOT NULL AND lng IS NOT NULL"
        )
        skipped = await conn.fetchval(
            'SELECT count(*) FROM "Orders" WHERE h3_index_res8 IS NULL AND (lat IS NULL OR lng IS NULL)'
        )

        if not rows:
            print("Nothing to backfill — every order with coordinates has a cell.")
            if skipped:
                print(f"({skipped} order(s) have no coordinates and cannot have one.)")
            return 0

        print(f"{len(rows)} order(s) to backfill at resolution {RESOLUTION}:")
        updates = [
            (str(h3.latlng_to_cell(row["lat"], row["lng"], RESOLUTION)), row["id"]) for row in rows
        ]
        cells = {cell for cell, _ in updates}
        print(f"  {len(cells)} distinct cell(s) — that is how many the demand layer will draw.")
        if skipped:
            print(f"  {skipped} order(s) skipped: no coordinates on the row.")

        if not apply:
            print("\nDry run. Re-run with --apply.")
            return 0

        await conn.executemany('UPDATE "Orders" SET h3_index_res8 = $1 WHERE id = $2', updates)
        print(f"\nUpdated {len(updates)} order(s).")
    finally:
        await conn.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    return asyncio.run(run(parser.parse_args().apply))


if __name__ == "__main__":
    raise SystemExit(main())
