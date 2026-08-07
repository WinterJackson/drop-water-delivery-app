# Drop — documentation

Everything here explains a decision, not just a procedure. If you only want to
get something running, the per-surface READMEs are shorter:
[root](../README.md) · [backend](../BackendAPI/README.md) ·
[admin](../drop-admin/README.md) · [customer](../drop-customer-app/README.md) ·
[rider](../drop-rider-app/README.md) · [vendor](../drop-vendor-app/README.md).

---

## Start here

| If you want to… | Read |
|---|---|
| Understand the whole platform | [../README.md](../README.md) |
| Understand how the *business* works — every rate, split and workflow | [business-logic.md](./business-logic.md) |
| Know why a surprising choice was made | [decisions/](./decisions/README.md) |
| Deploy or redeploy the admin console | [admin-console-deployment.md](./admin-console-deployment.md) |
| Operate the console day to day | [admin-console-runbook.md](./admin-console-runbook.md) |
| Set an environment variable correctly | [render-environment.md](./render-environment.md) |
| Know what is still missing | [platform-audit.md](./platform-audit.md) |

---

## Decisions

### [decisions/](./decisions/README.md)

Architecture decision records for the choices that are counter-intuitive,
expensive to reverse, or likely to be undone by somebody acting reasonably. Each
one states what it costs, what was rejected, and what would have to change for it
to be revisited.

| # | Decision |
|---|---|
| [0001](./decisions/0001-no-automated-refund-retry.md) | The console never re-sends a refund |
| [0002](./decisions/0002-three-valued-delivery-verdict.md) | A delivery verdict has three values, not two |
| [0003](./decisions/0003-review-moderation-is-structurally-enforced.md) | Moderation is enforced by a test that reads the source |
| [0004](./decisions/0004-delivery-replay-gated-on-geo-view.md) | Replay needs `geo.view`, not `orders.read` |

---

## Architecture and design

### [business-logic.md](./business-logic.md)
The commercial rules of the platform, read out of the code rather than out of a
specification: the 46 configurable settings and their defaults, the pricing engine
in the order it executes, the revenue split with worked examples for retail cash,
retail M-Pesa, a first order and a wholesale order, the order state machine, the
three dispatch tiers, the bottle ledger and its invariant, stock, cash float and
payouts, and the nightly sweeps. Ends with fourteen findings — two of them live
money defects — each now annotated with the fix that closed it and the test that
holds it. Read this before changing a rate, a threshold or a settlement path.

### [admin-dashboard-architecture.md](./admin-dashboard-architecture.md)
Why the console is built the way it is, decision by decision: the BFF transport
and why the browser never holds a token, capabilities rather than job titles,
the four authorisation layers and which one actually decides, how personal data
is revealed, and a running log of the defects found while building each screen.
The longest document here and the one worth reading before changing anything.

### [maps-architecture.md](./maps-architecture.md)
Six mobile keys restricted to the Maps SDK, one IP-restricted server key, and one
deliberately public browser key. Which call belongs on which, why Directions,
Places and Geocoding can never run on a client, and how the proxy caches and
sanitises Google's responses.

### [cash-settlement.md](./cash-settlement.md)
`wallet_balance`, `committed_cash_float`, and
`available_for_withdrawal = balance − float`. Why cash orders commit money from
acceptance rather than delivery, and why a rider's negative balance is a debt
rather than a bug.

### [push-notifications.md](./push-notifications.md)
The two sanctioned push paths — `queue_push` before a commit, `dispatch_background`
after — why `asyncio.create_task` is neither, the preference model, and which
message types are transactional and therefore unmutable.

### [cron-jobs.md](./cron-jobs.md)
The scheduled sweeps, their cadences, and how they are triggered in an
environment without a persistent worker.

---

## Operations

### [admin-console-deployment.md](./admin-console-deployment.md)
End to end: the repository, Vercel with the monorepo root directory, the Google
Cloud key restrictions, Clerk test accounts for all five roles, and the three
allow-lists an origin has to appear in. Missing any one of them produces a
different confusing failure, and the document names each.

### [admin-console-runbook.md](./admin-console-runbook.md)
Running it, and walking every screen as every role, so a capability that was
supposed to hide a control can be seen not hiding it.

### [render-environment.md](./render-environment.md)
Every environment variable the backend reads, annotated with what breaks when it
is wrong. Includes the ones that fail *silently* — a missing Clerk issuer makes
signature verification skip its audience check without erroring.

### [security/google-api-key-rotation.md](./security/google-api-key-rotation.md)
What to do when a Maps key leaks, in the order that minimises downtime.

---

## Audits and plans

These are historical records. They describe what was found at a point in time
and what was done about it; the findings marked done have shipped.

| Document | Scope |
|---|---|
| [platform-audit.md](./platform-audit.md) | The whole platform: domains with no admin visibility, console pages that were a bare table, missing operational capability, and data-correctness findings. The remediation sequence at the end is complete |
| [rider-app-remediation-plan.md](./rider-app-remediation-plan.md) | Rider app findings and the plan that followed |
| [vendor-app-remediation-plan.md](./vendor-app-remediation-plan.md) | Vendor app findings and the plan that followed |
| [audit/phase1-backend-customer-audit.md](./audit/phase1-backend-customer-audit.md) | The first backend and customer-app pass |
| [audit/phase1-implementation-plan.md](./audit/phase1-implementation-plan.md) | What that pass turned into |

---

## Conventions in these documents

**Decisions carry their cost.** Where a document says something was chosen, it
says what was given up. A rule with no stated reason gets deleted by the next
person who finds it inconvenient.

**Defects are recorded, not tidied away.** Several documents contain a list of
bugs found while building the thing they describe, including the ones introduced
by the same work. That is deliberate — the shape of a mistake is usually more
useful than the fix.

**"Done" means shipped and verified**, not merged. Where a figure is quoted
against this deployment's data, it was read from the database rather than
estimated, and where a table is empty the document says so rather than implying
the numbers have been observed.
