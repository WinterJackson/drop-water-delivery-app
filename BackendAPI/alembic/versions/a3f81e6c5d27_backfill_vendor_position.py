"""Backfill every vendor position column from whichever one was written

Revision ID: a3f81e6c5d27
Revises: b8e1d47f3a92
Create Date: 2026-08-18

Three writers each set a different subset of the four columns that describe
where a store is — `lat`, `lng`, `location` and `h3_index_res8` — so the rows
already in the table disagree with each other about their own position:

* the onboarding update branch in `auth_routes` wrote `lat`, `lng` and
  `location` and never the H3 cell, and it is the branch every real vendor
  takes, because the row exists before the form is posted;
* `create_vendor` wrote `lat`, `lng` and the cell and never `location`;
* only `vendor_management_service` wrote all four.

On the production database that left **21 of 23 stores with a NULL
`h3_index_res8`** — including all six retail shops inside the test customer's
2.5 km radius. Every discovery query pre-filters on that column with a bare
`IN (...)`, and `NULL IN (...)` is NULL rather than true, so all six were
deleted from the result before `ST_DWithin` was ever consulted. The customer app
showed "No vendors currently deliver to your location" to somebody standing
1.8 km from an open shop.

`in_search_cells` now makes the ring skip rows instead of rejecting them, so
correctness no longer depends on this migration having run. This is the other
half: without it every one of those stores would keep taking the slow path
through the exact distance test on every search, on a column that exists purely
to avoid that.

Both directions are filled, from whichever source is present:

* `location` from `lat`/`lng` where the geography is missing;
* `lat`/`lng` from `location` where the scalars are missing;
* `h3_index_res8` from `location` for every row that has a position at all —
  recomputed rather than trusted, since a cell that disagrees with the geography
  is the same defect one step further along and there is nothing to distinguish
  it from a correct one by inspection.

Res-8 is not available in SQL, so the cell is computed in Python. The row count
is small (tens to low thousands) and this runs once.

There is no meaningful downgrade: restoring NULLs would only reinstate the
defect, so `downgrade` deliberately does nothing.
"""

from typing import Sequence, Union

import h3
import sqlalchemy as sa
from alembic import op

revision: str = "a3f81e6c5d27"
down_revision: Union[str, Sequence[str], None] = "b8e1d47f3a92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Geography from the scalars, where only the scalars were written.
    conn.execute(
        sa.text(
            """
            UPDATE "Vendors"
               SET location = ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography
             WHERE location IS NULL AND lat IS NOT NULL AND lng IS NOT NULL
            """
        )
    )

    # 2. Scalars from the geography, where only the geography was written. The
    #    apps read `lat`/`lng` directly to draw a store on a map.
    conn.execute(
        sa.text(
            """
            UPDATE "Vendors"
               SET lat = ST_Y(location::geometry),
                   lng = ST_X(location::geometry)
             WHERE location IS NOT NULL AND (lat IS NULL OR lng IS NULL)
            """
        )
    )

    # 3. The H3 cache, recomputed for every row that has a position.
    rows = conn.execute(
        sa.text(
            """
            SELECT id, ST_Y(location::geometry) AS lat, ST_X(location::geometry) AS lng
              FROM "Vendors"
             WHERE location IS NOT NULL
            """
        )
    ).fetchall()

    for row in rows:
        conn.execute(
            sa.text('UPDATE "Vendors" SET h3_index_res8 = :cell WHERE id = :id'),
            {"cell": str(h3.latlng_to_cell(row.lat, row.lng, 8)), "id": row.id},
        )


def downgrade() -> None:
    """Deliberately empty — see the module docstring."""
    pass
