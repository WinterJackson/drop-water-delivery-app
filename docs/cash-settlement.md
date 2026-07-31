# Cash settlement and the rider float

## The model

Cash orders are settled by **rider float**, not by a remittance handover. When a
rider accepts a cash order they must already hold enough in their wallet to cover
the vendor's cut and the platform's cut. On delivery:

* the rider keeps the physical cash the customer paid,
* their wallet is debited `vendor_net + platform_total`,
* the vendor's wallet is credited `vendor_net`.

Net effect: the rider earns `rider_net` and nobody has to physically hand money
back. Wholesale is the mirror image — the vendor's own in-house rider collects the
cash, so the vendor holds it and only `platform_total` comes off the vendor's
wallet.

This is why there is no cash equivalent of the bottle ledger. Bottles physically
move between rider and vendor and need reconciling; cash does not.

## `wallet_balance` is the single spendable balance

One number governs everything: cash-order float, withdrawals, arrears.

```
available_for_withdrawal = wallet_balance − committed_cash_float
```

`services/settlement_service.py` owns that arithmetic. Do not re-derive it.

**`committed_cash_float`** is the sum of `vendor_net + platform_total` over cash
orders assigned to the rider in a non-terminal state (`accepted`, `preparing`,
`ready`, `picked_up`, `pending_review`, `mismatch_pending`). That money is spoken
for from the moment of acceptance, even though it does not leave the wallet until
delivery.

### The defect this replaced

Withdrawal eligibility used to be computed from a **derived** sum of `rider_net`
over delivered orders, minus prior payouts. Cash-order float was checked against
the **stored** `wallet_balance`. Payouts debited neither. Nothing reconciled them,
so:

1. rider accumulates earnings — `wallet_balance` grows,
2. rider withdraws them by M-Pesa B2C — real money leaves, `wallet_balance`
   **unchanged**,
3. rider accepts a cash order — float check passes against that stale balance,
4. rider delivers, keeps the customer's cash, wallet is debited, vendor is credited
   **out of platform funds**.

Repeatable, and it scaled with the number of cash orders a rider could carry.
Migration `d5f1c8a92e34` reconciles historical payouts against balances; riders who
exploited the gap land negative, which blocks further cash orders until settled:

```sql
SELECT id, name, phone_number, wallet_balance
FROM "Deliverers" WHERE wallet_balance < 0 ORDER BY wallet_balance;
```

## Every balance movement writes a ledger row

`wallet_service.apply_wallet_delta` moves the balance **and** appends the
`WalletTransaction` in one call. Use it everywhere; `record_wallet_movement` alone
only writes the row, and several call sites had drifted into doing the opposite —
moving the balance and forgetting the row, so a rider's own Transactions screen
could not explain its numbers.

`amount` is signed, so summing a user's transactions reproduces their balance
movement exactly.

Money is `Decimal`, never `float`. `Deliverers.wallet_balance` was a `Float` column
mutated with float arithmetic; it is now `NUMERIC(10,2)` like Users and Vendors.

## Concurrency

| Where | Guard |
|---|---|
| Accepting a cash order | `SELECT … FOR UPDATE` on the rider row before the float check — two simultaneous accepts previously both read the same balance and both passed |
| Requesting a payout | `pg_advisory_xact_lock` per provider **and** `FOR UPDATE` on the balance row |
| Payout debit | Same transaction as the `Payout` row |

A payout debits up front, before the B2C call, so the money cannot be spent while
the disbursement is in flight. That makes refunding on failure mandatory —
`_refund_failed_payout` handles both the declined response and the exception path.

## What the rider sees

`GET /api/rider/wallet-summary` returns `wallet_balance`,
`committed_cash_float`, `available_for_withdrawal` and `is_in_arrears`. The Cashout
screen shows the split whenever float is committed, and an arrears warning when the
balance is negative. Showing only the raw balance made a refused withdrawal look
arbitrary.

## Tests

`tests/test_cash_settlement.py` pins the committed-float subtraction, the
non-negative floor, the Decimal arithmetic, the withdraw-then-spend sequence being
blocked with an explanatory message, and the refund on failed disbursement.
