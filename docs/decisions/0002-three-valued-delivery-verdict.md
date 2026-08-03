# 0002 — A delivery verdict has three values, not two

**Status:** Accepted
**Applies to:** `services/admin_delivery_replay_service.py`, `/operations/replay`

---

## Context

`Order_Tracking_Logs` records every location ping the rider app sends during a
delivery. `/operations/replay` reads that trail and answers the question the
platform previously could not: **did the rider get to the door?**

`closest_approach_m` is the answer — the minimum distance between any recorded
ping and the order's delivery coordinates. A rider whose nearest approach was
four kilometres did not deliver that order.

The obvious type for the conclusion is a boolean. It is the wrong type.

## The problem with two values

Tracking depends on three things outside anyone's control: the rider app holding
location permission, the handset having signal, and the battery lasting. Any of
them failing produces **no path at all** — routinely, and with no fault on the
rider's part. Separately, an order may carry no delivery coordinates to measure
against.

A boolean has nowhere to put either case. Whatever the code does with them, the
screen renders one of two sentences, and the false branch says *the rider never
went there*.

**That is the screen somebody opens when deciding whether a rider is stealing.**
Rendering an absence of evidence as evidence of absence, on that screen, is the
worst thing this module could do — worse than not building it, because a
confident wrong answer gets acted on and a missing screen does not.

## Decision

`reached_destination` is `True`, `False`, or **`None`**.

`None` is returned when the order has no delivery coordinates, or when there are
no pings at all. It is accompanied by `no_verdict_because`, which carries the
reason in the words the console prints:

* `"the order has no delivery coordinates"`
* `"no location was ever recorded for this delivery"`

The page renders a distinct third state — a neutral **No verdict** badge with the
reason and the sentence *"This is not evidence the rider stayed away — it is an
absence of evidence either way."* — rather than folding it into either outcome.

Two supporting choices follow from the same reasoning:

**`largest_gap_minutes` and `has_gap`.** A path with a thirty-minute hole is not
one path, it is two, and what happened in between is not in this data.
`SIGNAL_GAP_MINUTES = 5`; the app pings far more often than that while a delivery
is live, so a longer silence is a hole in the record rather than a stationary
rider. Where a gap exists the page says so beneath the verdict, including under a
`False`.

**`PROXIMITY_M = 150`.** Consumer GPS is good to 20–50 m in the open and
considerably worse between buildings. The threshold is a city block rather than a
doorstep, deliberately, because a false "never arrived" is an accusation.

## Consequences

**Callers must handle three cases.** The TypeScript type is
`boolean | null`, not `boolean`, and a test asserts that it stays that way —
typing it as `boolean` would let `undefined` render through a falsy check as
"never arrived".

**The screen is less decisive, and that is the point.** An operator sometimes
learns only that the platform cannot say. That is a true answer, and it is more
useful than a confident false one.

**`False` still carries a caveat.** Even a genuine "never reached the address"
renders with *"Check the gap before acting on this"*, because a path with a hole
can miss the approach entirely.

## Alternatives rejected

**`False` with a separate `has_data` flag.** Two fields that must be read
together are one field that will eventually be read alone. The first consumer to
check `if (!reached)` gets the wrong answer, and the compiler cannot help.

**Omit the field when there is no data.** `undefined` in JavaScript is falsy, so
this is the previous option with worse ergonomics.

**Refuse to render the screen without pings.** The rest of the replay — the
order, the store, the proof photo's existence, the time between statuses — is
still useful when the trail is missing. Hiding all of it because one figure
cannot be computed throws away the evidence that does exist.

## What would change this decision

Nothing about GPS reliability is going to improve enough to make the third value
unnecessary. What *would* justify revisiting the **thresholds** is real data:
`PROXIMITY_M` is calibrated on nothing, because `Order_Tracking_Logs` is empty on
this deployment. Once there is a body of confirmed-good deliveries, the right
radius is measurable — the distribution of `closest_approach_m` across deliveries
nobody disputed — and 150 m should be replaced with the observed figure rather
than defended as a guess.

The three-valued shape stays regardless.

## Enforcement

`BackendAPI/tests/test_delivery_replay.py`:

* `test_no_pings_gives_no_verdict_rather_than_a_denial`
* `test_an_order_with_no_coordinates_gives_no_verdict`
* `test_the_page_renders_all_three_verdicts` — reads the TSX and fails if the `verdict === null` branch is removed, or if the type is narrowed to `boolean`
* `test_the_proximity_threshold_is_a_block_not_a_doorstep` — fails if `PROXIMITY_M` drops below 100

The geometry is checked separately against distances with known answers — one
degree of latitude, a hundred metres north, symmetry — because a units slip in
the haversine reads as a rider four metres away who was four kilometres away.
