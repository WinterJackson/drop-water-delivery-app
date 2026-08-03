# Architecture decision records

Decisions that are **counter-intuitive, expensive to reverse, or likely to be
undone by somebody acting reasonably**. Not every choice on the platform is here
— only the ones where the obvious thing to do is the wrong thing, and where a
future change would look like an improvement right up until it caused harm.

Each record states the decision, what it costs, what was rejected, and — the part
that matters — **what would have to change for the decision to be revisited**. A
decision with no stated reversal condition is dogma.

## The records

| # | Decision | Status |
|---|---|---|
| [0001](./0001-no-automated-refund-retry.md) | The console never re-sends a refund | Accepted |
| [0002](./0002-three-valued-delivery-verdict.md) | A delivery verdict has three values, not two | Accepted |
| [0003](./0003-review-moderation-is-structurally-enforced.md) | Moderation is enforced by a test that reads the source | Accepted |
| [0004](./0004-delivery-replay-gated-on-geo-view.md) | Replay needs `geo.view`, not `orders.read` | Accepted |

## Why these four

Each one is a place where a competent engineer, reading the code six months from
now with no context, would be **tempted to make it worse**:

* 0001 looks like a missing feature. Adding it would cost the platform real money.
* 0002 looks like sloppy typing. Tightening it would produce false accusations of theft.
* 0003 looks like an over-engineered test. Deleting it would let a moderated review keep affecting a rating.
* 0004 looks like an over-tight permission. Loosening it would broaden access to people's movement history.

Three of the four are held in place by a test that fails the build. The fourth,
0004, is held by a capability constant and a test that asserts it — but the
capability itself is a judgement, and the record explains the judgement rather
than restating the code.

## Format

Short. Context, decision, consequences, alternatives rejected, reversal
condition, and where it is enforced. If a record grows past two screens it has
stopped being a decision record and become a design document — those live in the
parent directory.

## Relationship to the rest of `docs/`

| | |
|---|---|
| `docs/decisions/` | *Why* a specific choice was made, and what would change it |
| `docs/admin-dashboard-architecture.md` | How the console is built, section by section |
| `docs/admin-console-runbook.md` | What to actually do, including the manual procedures these decisions create |
| `CLAUDE.md` in each directory | The same rules, stated imperatively for an AI assistant |
