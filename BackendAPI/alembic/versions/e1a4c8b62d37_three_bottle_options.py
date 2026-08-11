"""Three bottle options, and settings renamed to match what they price.

## The delivery types

`quick_swap` → **`exchange`**. A rename.

`keep_my_bottle` → **`new_bottle`**, and this is the one to read carefully. The
old name sounded like "refill my own bottle" and every product conversation used
it that way, but what it *did* was charge a KSH 300 deposit and leave a platform
bottle with the customer. Every historic row of it is a customer holding a
platform bottle against a deposit the platform still owes them — which is
exactly `new_bottle`.

Mapping them to `refill_mine` instead would assert those customers own bottles
they do not, and would orphan the deposit liability recorded against them.

**`refill_mine` is new and has no historic rows.** It is the option the old name
described and never implemented: the rider collects the customer's own bottle,
carries it to the station, and brings that same bottle back. No deposit — the
customer already owns it — and a round-trip fee, because the rider rides three
legs instead of one.

## The settings

`keep_my_bottle_base_premium`, `keep_my_bottle_per_km` and
`keep_my_bottle_commission_premium` are renamed to `refill_mine_*`. Values carry
across unchanged; only rows that actually exist are copied, since an unset
setting correctly falls back to its shipped default.

Renaming rather than aliasing is deliberate. A key whose name describes the
wrong transaction is how this defect survived as long as it did.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e1a4c8b62d37'
down_revision: Union[str, Sequence[str], None] = 'd9f3a71c5b82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SETTING_RENAMES = (
    ("keep_my_bottle_base_premium", "refill_mine_base_premium"),
    ("keep_my_bottle_per_km", "refill_mine_per_km"),
    ("keep_my_bottle_commission_premium", "refill_mine_commission_premium"),
)


def upgrade() -> None:
    op.execute("""UPDATE "Orders" SET delivery_type = 'exchange' WHERE delivery_type = 'quick_swap'""")
    # Deliberate: see the docstring. These orders left a platform bottle behind.
    op.execute("""UPDATE "Orders" SET delivery_type = 'new_bottle' WHERE delivery_type = 'keep_my_bottle'""")

    for old, new in _SETTING_RENAMES:
        # Only if the operator had actually overridden it; an absent row means
        # "use the shipped default", which is still true under the new name.
        op.execute(
            f"""UPDATE "Platform_Settings" SET key = '{new}'
                WHERE key = '{old}'
                  AND NOT EXISTS (SELECT 1 FROM "Platform_Settings" WHERE key = '{new}')"""
        )
        op.execute(f"""DELETE FROM "Platform_Settings" WHERE key = '{old}'""")


def downgrade() -> None:
    op.execute("""UPDATE "Orders" SET delivery_type = 'quick_swap' WHERE delivery_type = 'exchange'""")
    op.execute("""UPDATE "Orders" SET delivery_type = 'keep_my_bottle' WHERE delivery_type = 'new_bottle'""")
    # `refill_mine` has no pre-existing equivalent. Anything on it becomes a
    # plain swap, which is the closest the old vocabulary could express — and
    # loses that the customer's own bottle was involved. Recorded here because
    # it is a real loss of meaning, not a clean reversal.
    op.execute("""UPDATE "Orders" SET delivery_type = 'quick_swap' WHERE delivery_type = 'refill_mine'""")

    for old, new in _SETTING_RENAMES:
        op.execute(
            f"""UPDATE "Platform_Settings" SET key = '{old}'
                WHERE key = '{new}'
                  AND NOT EXISTS (SELECT 1 FROM "Platform_Settings" WHERE key = '{old}')"""
        )
