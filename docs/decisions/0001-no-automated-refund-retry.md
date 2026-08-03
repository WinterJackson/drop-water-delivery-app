# 0001 — The console never re-sends a refund

**Status:** Accepted
**Applies to:** `/finance/settlement`, `routes/admin_finance_routes.py`, `services/admin_settlement_service.py`

---

## Context

A cancelled order that was already paid for goes into `refund_pending`.
`services/refund_service.py` sweeps those every two minutes, calls the M-Pesa
reversal API, and moves the order through:

```
refund_pending → refund_processing → refunded
                                   ↘ refund_failed
```

`refund_processing` means Safaricom accepted the reversal request and the result
callback has not arrived. `refund_failed` means it did arrive and said no, or
that no original receipt could be found to reverse against.

The settlement screen surfaces both, and anyone looking at a stuck row will want
a button that says **Retry**. That button is not there, and this record exists so
that nobody adds it believing they are fixing an oversight.

## The problem with retrying

**A reversal that succeeded and lost its callback is indistinguishable from one
that failed.** Both leave the order in `refund_processing`. Both look identical
in the database. Nothing on the platform can tell them apart.

The cost is asymmetric and falls entirely one way:

| | Retry is correct | Retry is wrong |
|---|---|---|
| **Outcome** | The customer gets their money, a few minutes sooner than a human would have managed | The customer is paid **twice**, the second time out of the platform's own float |
| **Recovery** | — | None. The money has left. Recovering it means asking a customer to return a payment they did not ask for |

An automated retry loop makes that second column happen at machine speed, and
`process_pending_refunds_task` runs every two minutes.

## Decision

The console **records** a refund that a human settled elsewhere. It never sends
one.

`POST /api/admin/settlement/refunds/{order_id}/settle` sets `payment_status` to
`refunded`, writes an audit row with `action="finance.refund_settle"`, and moves
no money. It requires `finance.refund_approve` — not `finance.read` — because the
row stops being visible to anyone the moment it is marked settled, and it
requires a written reason of at least 8 characters, because the next person needs
to know whether this was reversed in the portal, refunded another way, or
dismissed as a duplicate.

The button is labelled **Mark settled**. The wording is part of the decision: a
control labelled "Retry" invites exactly the mental model this record rejects.

This is the same reasoning as the failed-webhook screen, which also deliberately
offers no replay.

## Consequences

**Refunding is a manual step, and the manual step has to be written down.**
Refusing to automate is only defensible if the human path is documented, staffed
and discoverable — otherwise the decision does not protect the customer, it just
moves the failure somewhere nobody is looking. The procedure is
[§10 of the runbook](../admin-console-runbook.md).

**Stuck rows accumulate visibly rather than silently.**
`STUCK_AFTER_HOURS = 6` in `admin_settlement_service.py` marks a
`refund_processing` row as stuck. Six hours is generous on purpose — Safaricom
settles in minutes, and a false "stuck" sends somebody chasing a payment that is
about to land.

**The screen leads with what is owed, not what was sent.** `outstanding_amount`
sums `refund_pending`, `refund_processing` and `refund_failed`; `refunded` is
excluded, because counting money that already went back as outstanding would put
the platform's largest number on a screen about what it still owes.

## Alternatives rejected

**Retry with an idempotency key.** M-Pesa reversals are keyed on the original
transaction, not on a caller-supplied token. There is no key to send that
Safaricom would deduplicate on.

**Retry only rows older than N hours.** Age says nothing about which of the two
states a row is in. A reversal that succeeded eight hours ago and lost its
callback is *more* likely to be double-paid by this rule, not less.

**Retry only `refund_failed`, never `refund_processing`.** Closer to safe, and
still wrong: `refund_failed` is also reached when the callback reports a failure
that has since been resolved on Safaricom's side, and when no original receipt
was found — which retrying cannot fix, because the problem is that there is
nothing to reverse.

## What would change this decision

**Implementing Safaricom's Transaction Status API.** That endpoint answers the
exact question the platform cannot currently answer: *did this reversal actually
go through?* The platform already queries STK push status this way for incoming
C2B payments (`payment_service.check_payment` → `/mpesa/stkpushquery/v1/query`),
but the equivalent call for reversals — `/mpesa/transactionstatus/v1/query` — is
**not implemented**.

With it, the sequence becomes safe and this record should be revisited:

1. query the transaction status,
2. if it settled, move the order to `refunded` and send nothing,
3. only if it definitively failed, re-issue.

Until step 1 exists, a retry button is a way to pay a customer twice, and the
absence of it is not a gap to be closed but a guard to be kept.

## Enforcement

`BackendAPI/tests/test_admin_settlement.py`:

* `test_the_settlement_routes_never_initiate_a_reversal` — walks the settlement handlers with `ast` and fails if `initiate_mpesa_reversal`, `process_single_refund` or `process_all_pending_refunds` appears in one.
* `test_the_settlement_page_does_not_offer_a_retry` — strips comments from the page and the button component, then fails if the string `Retry` survives. Comments are stripped because both files *explain* why there is no retry, and a naive substring search matches the explanation.
