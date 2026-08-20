"""Generate the search vectors in Postgres, rather than in a trigger

`7645438dc804` added `search_vector` to `Products` and `Vendors`, backfilled
both, and installed a trigger to keep them current. All three of those steps
live inside `op.execute`, so they exist only for a database that actually ran
the revision.

The deployed database did not. `scripts/bootstrap_database.py` runs
`Base.metadata.create_all` and stamps the head, so `alembic_version` reads
`e6b2c8d40f17` while no revision has ever executed. `create_all` created the
column, because the model declares it, and created the GIN index, because the
model declares that too — and created neither the trigger nor the backfill,
because neither is in `Base.metadata`. Every row's vector stayed NULL.

`tsvector @@ tsquery` on a NULL vector is NULL, which is not true, so every
search filtered every row out and returned an empty list. No error, no log
line, no failing test — the customer's product and vendor search, the vendor's
search of their own catalogue, and the rider's vendor search have all been
returning zero results for every query since the database was created.

The fix is to move the definition into the schema itself, as a generated
column, so it is part of `Base.metadata` and a database built from the models
comes out working. Postgres then maintains it on every insert and update with
no trigger to install and nothing to backfill.

Revision ID: d1c7e58b3a92
Revises: c8b4f0d92e17
Create Date: 2026-08-20

"""
from typing import Sequence, Union

from alembic import op


revision: str = "d1c7e58b3a92"
down_revision: Union[str, None] = "c8b4f0d92e17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, generated expression, index name)
_VECTORS = (
    (
        "Products",
        "to_tsvector('english', coalesce(name, '') || ' ' || coalesce(description, ''))",
        "idx_products_search_vector",
    ),
    (
        "Vendors",
        "to_tsvector('english', coalesce(business_name, '') || ' ' || coalesce(location_address, ''))",
        "idx_vendors_search_vector",
    ),
)

# What `7645438dc804` installed, where it ran at all.
_TRIGGERS = (
    ("tsvectorupdate_products", "Products", "products_search_vector_update"),
    ("tsvectorupdate_vendors", "Vendors", "vendors_search_vector_update"),
)


def upgrade() -> None:
    # The trigger and the generated column would both write the same value; a
    # generated column refuses to be written to at all, so the trigger has to go
    # first. `IF EXISTS` because on a bootstrapped database it was never created.
    for trigger, table, function in _TRIGGERS:
        op.execute(f'DROP TRIGGER IF EXISTS {trigger} ON "{table}"')
        op.execute(f"DROP FUNCTION IF EXISTS {function}()")

    for table, expression, index in _VECTORS:
        # Postgres cannot convert a plain column into a generated one, so the
        # column is replaced. Dropping it drops the GIN index with it, which is
        # why the index is recreated below rather than left alone.
        op.execute(f'ALTER TABLE "{table}" DROP COLUMN IF EXISTS search_vector')
        op.execute(
            f'ALTER TABLE "{table}" ADD COLUMN search_vector tsvector '
            f"GENERATED ALWAYS AS ({expression}) STORED"
        )
        op.execute(
            f'CREATE INDEX IF NOT EXISTS {index} ON "{table}" USING gin (search_vector)'
        )


def downgrade() -> None:
    # Back to a plain column, backfilled once and maintained by the trigger,
    # which is the shape `7645438dc804` left behind.
    for table, expression, index in _VECTORS:
        op.execute(f'ALTER TABLE "{table}" DROP COLUMN IF EXISTS search_vector')
        op.execute(f'ALTER TABLE "{table}" ADD COLUMN search_vector tsvector')
        op.execute(f'UPDATE "{table}" SET search_vector = {expression}')
        op.execute(
            f'CREATE INDEX IF NOT EXISTS {index} ON "{table}" USING gin (search_vector)'
        )

    for trigger, table, function in _TRIGGERS:
        column = (
            "coalesce(NEW.name, '') || ' ' || coalesce(NEW.description, '')"
            if table == "Products"
            else "coalesce(NEW.business_name, '') || ' ' || coalesce(NEW.location_address, '')"
        )
        op.execute(
            f"""
            CREATE OR REPLACE FUNCTION {function}() RETURNS trigger AS $$
            BEGIN
                NEW.search_vector := to_tsvector('english', {column});
                RETURN NEW;
            END
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            f'CREATE TRIGGER {trigger} BEFORE INSERT OR UPDATE '
            f'ON "{table}" FOR EACH ROW EXECUTE FUNCTION {function}()'
        )
