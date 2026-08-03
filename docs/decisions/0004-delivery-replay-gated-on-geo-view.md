# 0004 — Delivery replay needs `geo.view`, not `orders.read`

**Status:** Accepted
**Applies to:** `GET /api/admin/orders/replayable`, `GET /api/admin/orders/{order_id}/replay`

---

## Context

Delivery replay lives under `/api/admin/orders/*` and is reached from the order
board. Every other endpoint in `admin_orders_routes.py` is gated on
`orders.read` or `orders.intervene`, and consistency argues for the same here.

The payload is not the same kind of thing. It is a **timestamped sequence of one
identified person's coordinates**, sometimes several hundred points, covering
where they were and how fast they were moving over a period of an hour.

## Decision

Both replay endpoints require **`geo.view`**.

That capability already exists and already means this: it gates the live map, and
it is separate from `riders.read` precisely because seeing a person's position is
a different decision from seeing their record. `riders.read` shows you that a
rider exists; `geo.view` shows you where they are.

Historical coordinates are no less identifying than live ones. If anything they
are more revealing, because a stored trail can be read at leisure and compared
across days, where a live position is a dot that moves on.

## Consequences

**Who can open it, on the shipped presets:**

| Preset | `geo.view` | Can replay |
|---|---|---|
| `super_admin` | yes | yes |
| `operations` | yes | yes |
| `support` | yes | yes |
| `finance` | no | no |
| `analyst` | no | no |

This is the right split and was checked rather than assumed. **Support holds
`geo.view`**, which matters: "my order never arrived" arrives as a support
ticket, and a support agent who could not open the replay would have to escalate
every one of them. Finance and analyst do not, and neither has any business
reading a rider's movements.

**A person with `orders.read` alone sees an order they cannot replay.** The
navigation entry is filtered by capability so the console does not offer it, and
the backend refuses it independently. That is the intended asymmetry, not a gap.

**The proof-of-delivery photo is reported as present or absent, never as a URL.**
`has_proof` is a boolean. Presigning an image of somebody's doorstep on every
page load is the same mistake as prefetching KYC documents into a list — the
order detail screen reveals it deliberately, as an audited action.

## Alternatives rejected

**`orders.read`.** Consistent with the module and wrong on the merits. It would
hand a rider's movement history to every preset that can look at an order,
including `analyst`, whose entire purpose is aggregate reporting.

**A new capability, `orders.replay`.** More precise, and worse. It would need
adding to five presets, documenting, and explaining — and it would sit beside
`geo.view` meaning almost exactly the same thing, which is how a capability list
becomes unreadable. The existing capability already draws the line in the right
place.

**Requiring both `orders.read` and `geo.view`.** `require_admin` takes one
capability, and composing two would be the first place on the platform that did.
The marginal protection is nil: nobody holds `geo.view` without `orders.read` on
any preset, and if somebody did, seeing one order's path is not a broader
exposure than the live map they can already open.

## What would change this decision

**A retention policy on `Order_Tracking_Logs`.** The table currently grows
without bound and nothing prunes it, so the trail for a delivery two years old is
still queryable. If a retention window is introduced, the sensitivity of the
endpoint drops for old orders and the gating could reasonably be revisited — but
the policy has to come first.

**An audit requirement.** Replay is currently a read and writes no audit row,
consistent with every other admin read on the platform. If the platform later
decides that *looking at* somebody's movement history should itself be recorded —
which is a defensible position and is already how PII reveal works — then this
endpoint is the first candidate, and that would be a change to this record rather
than a contradiction of it.

## Enforcement

`BackendAPI/tests/test_delivery_replay.py::test_the_replay_route_is_gated_on_geo_view`
walks `admin_orders_routes.py` with `ast`, finds the `replay_delivery` handler,
and fails if `PERM_GEO_VIEW` is not in its dependency list.

`tests/test_admin_rbac.py` independently fails the build on any route under
`/api/admin/*` that names no capability at all.
