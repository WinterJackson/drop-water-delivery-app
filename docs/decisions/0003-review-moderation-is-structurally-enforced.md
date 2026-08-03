# 0003 — Review moderation is enforced by a test that reads the source

**Status:** Accepted
**Applies to:** `models/review_model.py`, `services/review_service.py`, `services/admin_review_service.py`, migration `a9f4b2c71d63`

---

## Context

`reviews` had no moderation state. A review naming a rider's home address, or one
left on the wrong order, could only be removed with a `DELETE` — which loses that
the review existed, releases `uq_customer_order_target_review` so the customer
can simply leave another, and strands the target's `rating_sum` and
`rating_count` on a row that is gone.

Migration `a9f4b2c71d63` added `hidden_at`, `hidden_by` and `hidden_reason`.
Hiding is a state change, not a deletion.

That much is unremarkable. The decision worth recording is what holds it in
place.

## The problem a normal test does not catch

Moderation that only removes a review from a list is theatre. The store still
sits at 2.1 for a review nobody can read, which is the outcome the moderator
believed they had prevented.

Correctness therefore depends on **every** read path filtering `hidden_at`. There
are five, across four modules:

| Module | Read |
|---|---|
| `routes/review_routes.py` | The public per-target listing |
| `services/review_service.py` | The star-distribution summary |
| `services/review_service.py` | The counter rebuild |
| `services/deliverer_service.py` | A rider reading their own reviews |
| `services/admin_analytics_service.py` | The ratings breakdown |

Five is not the final number. It goes up whenever somebody adds a feature that
reads reviews, and the person adding the sixth has no reason to know this
constraint exists. A unit test per known path tests the five that are already
correct and says nothing about the one being written.

## Decision

A **structural** test. `tests/test_review_moderation.py` parses each of those
modules with `ast`, finds every statement that builds a `select` referencing
`Review`, and fails the build on one that does not mention `hidden_at`.

Per *statement*, not per file: `review_service` contains two aggregations over
this table, and a file-level "does the word appear anywhere" check passes with
one of them still leaking hidden rows.

Two exclusions are deliberate and named in the test:

**The edit lookup in `create_review`** (matched by `customer_clerk_id ==`) must
see hidden rows. That is how a resubmit is *recognised* — and refused with a
**409**. Folding a hidden review's rating back in would be a working way round
moderation, so the query has to find it in order to reject it.

**`is_rated` in `order_service`** must not filter, and a separate test asserts
that it does not. `uq_customer_order_target_review` still holds after a review is
hidden, so treating the order as unrated would show the customer a "Rate
delivery" button that can only fail — and if it somehow worked, it would be a
second route round the takedown.

Alongside this, `admin_review_service.set_hidden` rebuilds the target's
`rating_count` and `rating_sum` from the visible rows **in the same transaction**
as the hide. That rebuild is the one sanctioned `SUM()` over `reviews`: a single
indexed aggregate for one target on a rare admin action, not the per-write
recomputation the incremental path exists to avoid.

## Consequences

**A new read of `reviews` fails the build until it filters.** That is the
intended friction. The failure message says what to do and why.

**The test can be wrong in the safe direction.** Adding a module to
`PUBLIC_READ_PATHS` that legitimately needs unfiltered access requires an
explicit, named exclusion — a visible decision rather than a silent omission.

**It was verified by breaking the code, not by passing.** A filter was removed
from `review_service`, the suite was run, and it failed with the intended
message; the filter was then restored. A structural test that has never been
seen to fail is a test whose matcher may not match anything.

## Alternatives rejected

**A database view of visible reviews only.** Cleaner in principle. Rejected
because the two paths that *must* see hidden rows would then need the base table
anyway, so the codebase carries both and the same discipline problem returns —
now with two names for one table.

**A default filter in the ORM query.** SQLAlchemy can do this, and it makes the
exceptions the hard case rather than the rule. Rejected because a filter applied
invisibly is one nobody knows is there: the next person debugging "why is this
review missing from the admin screen" has nothing to grep for.

**Trusting code review.** This is a five-line constraint spread across four files
that nobody will remember in six months, including the person who wrote it.

## What would change this decision

If the platform gains a report button — currently no app has one — the moderation
queue stops being a heuristic and the surrounding design changes considerably.
The `hidden_at` filter requirement does not; if anything it matters more.

The test's shape would need revisiting if review reads moved behind a repository
layer, at which point the constraint could be enforced in one place and the AST
walk retired.

## Enforcement

`BackendAPI/tests/test_review_moderation.py` — 18 tests, including:

* `test_every_public_review_read_filters_hidden` — the AST walk, parametrised over the four modules
* `test_is_rated_deliberately_does_not_filter_hidden` — the named exception
* `test_a_resubmitted_hidden_review_is_refused_rather_than_folded_back_in`
* `test_the_rating_rebuild_excludes_hidden_reviews`
