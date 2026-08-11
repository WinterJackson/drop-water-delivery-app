"""Retire stored rows that are only holding an old shipped default in place.

## The problem this fixes

Changing a shipped default does not change a running platform, and that is
*correct* for a value somebody chose — an owner who set the retail service fee
to 12 should not have it moved by a deploy. But it is wrong for a row that
merely **materialised** the old default, and the two are indistinguishable once
written: `_load` reads the row, the row wins, and the new default is inert.

This database is the worked example. `Platform_Setting_History` shows
`retail_service_fee` going 12 → 25 ("Verifying the config path end to end") and
then 25 → 12 ("Reverting the verification change") on 2 August. Nobody chose 12.
The revert wrote the *then-current default* into a row, and that row went on to
pin the platform at 12 after the default became 35 — so every quote priced at
the old fee while the source said otherwise.

## The rule

For each key whose shipped default changed, the stored row is deleted **if and
only if its value still equals the superseded default**. That value carries no
decision: it says exactly what the platform would have said with no row at all.

Anything else is left untouched. A stored 20 against a superseded default of 12
is somebody's decision, and a migration that overwrote it would be doing the
opposite of the thing being fixed here.

Deleting rather than updating to the new default is deliberate. A deleted row
means "unset — use what the platform ships", so the key stays correct through
the *next* default change too. Writing 35 into the row would pin it at 35 and
reproduce this defect one release later.

Every retirement writes a `Platform_Setting_History` row, so the change appears
on the console's history screen with a reason attached rather than as a figure
that moved on its own.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b2f9c14e7a35'
down_revision: Union[str, Sequence[str], None] = 'e1a4c8b62d37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: `key: (superseded_default, current_default)`.
#:
#: Point-in-time by design — a migration records what the defaults were when it
#: ran, and must keep saying that after the source moves on again. It is checked
#: against the live registry by `test_superseded_defaults_are_registered_keys`,
#: which only asserts the keys still exist and that the two figures differ.
_SUPERSEDED: dict[str, tuple[float, float]] = {
    # The service fee that funds everything not covered by commission. 12 was
    # set against a much smaller basket and never revisited.
    "retail_service_fee": (12.0, 35.0),
    "wholesale_service_fee": (50.0, 120.0),
    # Wholesale costs the platform least to serve and was charged least.
    "wholesale_vendor_commission_rate": (0.025, 0.05),
    # Delivery, re-based on what a rider must actually earn per trip.
    "retail_delivery_base_fee": (50.0, 80.0),
    "retail_delivery_per_km": (15.0, 20.0),
    # Withdrawn: a per-delivery cashback paid out of margin, on a platform with
    # no margin to pay it from.
    "loyalty_cashback_per_delivery": (10.0, 0.0),
    # Redefined. This is now the platform's *margin on top of* Safaricom's B2C
    # tariff, not the fee itself, and it ships at zero — the provider pays what
    # the transfer costs and the platform neither loses nor earns. A stored 15
    # under the old meaning would silently become a 15/- margin under the new
    # one, which nobody agreed to.
    "payout_transaction_fee": (15.0, 0.0),
}

_REASON = (
    "Retired by migration b2f9c14e7a35: this row held the previous shipped "
    "default, so it recorded no decision while preventing the current one from "
    "applying."
)


def upgrade() -> None:
    for key, (superseded, current) in _SUPERSEDED.items():
        # History first — the row has to still exist to be read.
        op.execute(
            f"""
            INSERT INTO "Platform_Setting_History"
                (id, key, before, after, version, reason, changed_by_email, created_at)
            SELECT
                gen_random_uuid(),
                '{key}',
                s.value,
                '{current}'::jsonb,
                COALESCE((SELECT MAX(version) FROM "Platform_Settings"), 0) + 1,
                '{_REASON}',
                'migration:b2f9c14e7a35',
                NOW()
            FROM "Platform_Settings" s
            WHERE s.key = '{key}'
              AND jsonb_typeof(s.value) = 'number'
              AND (s.value #>> '{{}}')::numeric = {superseded}
            """
        )
        op.execute(
            f"""
            DELETE FROM "Platform_Settings"
            WHERE key = '{key}'
              AND jsonb_typeof(value) = 'number'
              AND (value #>> '{{}}')::numeric = {superseded}
            """
        )


def downgrade() -> None:
    """Put the superseded value back, but only where this migration removed it.

    The history row is the evidence, and it is matched on `changed_by_email` so
    a downgrade cannot resurrect a value an administrator deleted by other
    means. The history rows themselves are left in place: they are an
    append-only record of what happened, and it did happen.
    """
    for key, (superseded, _current) in _SUPERSEDED.items():
        op.execute(
            f"""
            INSERT INTO "Platform_Settings" (key, value, version, updated_at, updated_by_email)
            SELECT
                '{key}',
                '{superseded}'::jsonb,
                COALESCE((SELECT MAX(version) FROM "Platform_Settings"), 0) + 1,
                NOW(),
                'migration:b2f9c14e7a35'
            WHERE EXISTS (
                SELECT 1 FROM "Platform_Setting_History"
                WHERE key = '{key}' AND changed_by_email = 'migration:b2f9c14e7a35'
            )
            AND NOT EXISTS (
                SELECT 1 FROM "Platform_Settings" WHERE key = '{key}'
            )
            """
        )
