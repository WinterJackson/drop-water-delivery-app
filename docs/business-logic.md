# Drop — the business logic, as implemented

**Scope:** every rule that decides what a customer pays, what a vendor keeps, what a
rider earns, who gets offered a delivery, how bottles and stock are accounted for,
and what happens on its own overnight.

**Method:** this document was written by reading the source, not the specification.
Every figure, rate, threshold and formula below is quoted from the code that runs,
with the file and function named so it can be checked. Where the code and an
earlier document disagree, the code is what is written here.

**Two kinds of statement appear, and they are never mixed:**

> Plain text describes **what the code does today**.

> ⚠️ **Finding** blocks describe a gap, a loophole or an inconsistency **found while
> reading**, with what it costs and what to do about it. Nothing in a Finding block
> is currently implemented.

Findings are collected and ranked in [§18](#18-findings-and-recommendations).

---

## Contents

1. [The shape of the business](#1-the-shape-of-the-business)
2. [Business values are rows, not constants](#2-business-values-are-rows-not-constants)
3. [Money and precision](#3-money-and-precision)
4. [Discovery — how a customer finds a store](#4-discovery--how-a-customer-finds-a-store)
5. [The cart and its rules](#5-the-cart-and-its-rules)
6. [The pricing engine](#6-the-pricing-engine)
7. [The revenue split](#7-the-revenue-split)
8. [Worked examples](#8-worked-examples)
9. [Checkout and order creation](#9-checkout-and-order-creation)
10. [The order lifecycle](#10-the-order-lifecycle)
11. [Rider discovery and dispatch](#11-rider-discovery-and-dispatch)
12. [Delivery execution and completion](#12-delivery-execution-and-completion)
13. [Bottle management](#13-bottle-management)
14. [Stock management](#14-stock-management)
15. [Wallets, cash float and payouts](#15-wallets-cash-float-and-payouts)
16. [Cancellations and refunds](#16-cancellations-and-refunds)
17. [The daily and nightly rhythm](#17-the-daily-and-nightly-rhythm)
18. [Findings and recommendations](#18-findings-and-recommendations)

---

## 1. The shape of the business

Drop is a two-sided marketplace for drinking water in Kenya, operating **two
distinct business models against one database**.

| | **Retail refill** (`retail_refill`) | **Wholesale B2B** (`wholesale_b2b`) |
|---|---|---|
| Buyer | A household | A business buying in bulk |
| Fulfilment | Gig riders on motorbikes, discovered by the platform | The vendor's own in-house fleet |
| Max delivery distance | **2 km**, enforced at checkout | **Not capped at checkout** |
| Max units per order | **4 bottles** (a motorbike's capacity) | 200 units / 400 kg gates the vehicle class |
| Minimum order | none | **100 kg** payload |
| Vendor commission | **5 %** of goods | **2.5 %** of goods |
| Rider commission | 10 % of the delivery fee (7 % if Platinum) | **none — the rider is the vendor's employee** |
| Service fee | **KSh 12** | **KSh 50** |
| Trip Radar broadcast | yes | **no — deliberately bypassed** |

The distinction is carried on `Vendor.vendor_type` and is read in **twelve** places
across pricing, dispatch, settlement and payouts. It is the single most important
branch in the codebase.

### The actors

| Actor | Table | Wallet | Discovered how |
|---|---|---|---|
| Customer | `Users` | yes | signs up |
| Vendor (store) | `Vendors` | yes, **per store** | registers; owner may hold several |
| Vendor staff | `Vendor_Staff` | **no** | invited by owner, four capabilities |
| Rider | `Deliverers` | yes | registers, KYC, then applies to vendors |
| Administrator | `Admin_Users` | no | capability-based RBAC, 26 capabilities |

An owner with two stores has **two `Vendors` rows with two separate balances**.
Staff are never wallet owners: `payout_service._get_provider_details` resolves on
`Vendor.clerk_id` alone and returns a 403 `owner_only` for a staff member.

### The three delivery types

`Order.delivery_type` takes one of:

| Value | Meaning | Deposit charged | Rider commission |
|---|---|---|---|
| `quick_swap` | Customer hands over an empty, receives a full one | only on a first order | 10 % |
| `keep_my_bottle` | Customer keeps the bottle | **always** | **12 %** (10 % + 2 % premium) |
| *(wholesale orders use `quick_swap` by default)* | | | 0 % |

`quick_swap` is the only type that accrues empty-bottle debt against the rider
(`deliverer_service.update_delivery_status`).

---

## 2. Business values are rows, not constants

`services/platform_config_service.py` defines **34 settings** in six groups.
They live in the `Platform_Settings` table, are edited from the admin console, and
apply to **the next quote** — no deploy, no restart. The class attributes in
`DispatchPolicy` and the literals in `pricing_service` are *shipped defaults*, kept
only so a process still prices correctly with the table unreachable.

`compute_order_quote` awaits `config.ensure_fresh(session)` **once, at the top**, then
reads every value synchronously. That is what makes a single quote internally
consistent: an administrator saving a change mid-request cannot move a rate between
two lines of the same calculation.

### The complete settings table (shipped defaults)

**Group: `commission`**

| Key | Default | What it does |
|---|---|---|
| `retail_vendor_commission_rate` | `0.05` | Platform's cut of retail goods |
| `wholesale_vendor_commission_rate` | `0.025` | Platform's cut of wholesale goods |
| `gig_rider_commission_rate` | `0.10` | Platform's cut of the rider's delivery fee |
| `gig_platinum_rider_commission_rate` | `0.07` | Reduced cut for Platinum riders |
| `keep_my_bottle_commission_premium` | `0.02` | Added to the rider commission rate on `keep_my_bottle` |
| `in_house_rider_commission_rate` | `0.0` | **Never read by any calculation** |
| `wholesale_delivery_markup_rate` | `0.05` | Platform's cut of a wholesale delivery fee |

A validator refuses to save a `gig_platinum_rider_commission_rate` **greater than**
`gig_rider_commission_rate` — a "reward" that costs more than the standard rate is
rejected at the source (`platform_config_service.py:318`).

**Group: `fees`**

| Key | Default | What it does |
|---|---|---|
| `retail_service_fee` | `12.0` | Flat, per retail order |
| `wholesale_service_fee` | `50.0` | Flat, per wholesale order |
| `surge_fee` | `10.0` | Flat, added during peak hours |
| `peak_hours` | `[[6,8],[17,19]]` | EAT (UTC+3, no DST). Empty list disables surge honestly |
| `payload_surcharge_per_unit` | `10.0` | Per unit **above** the free allowance |
| `payload_free_units` | `2` | Units carried free |
| `staircase_surcharge_per_floor` | `10.0` | Per floor **above** the free allowance |
| `staircase_free_floors` | `2` | Floors climbed free |
| `min_chargeable_total` | `1.0` | Safaricom rejects an STK push for 0 |

**Group: `delivery`**

| Key | Default |
|---|---|
| `retail_delivery_base_fee` | `50.0` |
| `retail_delivery_per_km` | `15.0` |
| `keep_my_bottle_base_premium` | `20.0` |
| `keep_my_bottle_per_km` | `25.0` |
| `wholesale_motorbike_base` / `_per_km` | `50.0` / `60.0` |
| `wholesale_tuktuk_base` / `_per_km` | `150.0` / `100.0` |
| `wholesale_truck_base` / `_per_km` | `500.0` / `150.0` |

**Group: `bottles`**

| Key | Default |
|---|---|
| `bottle_deposit_by_capacity` | `{"20": 300.0, "10": 150.0}` |
| `welcome_discount_rate` | `0.30` |

A capacity absent from that map returns `None`, not zero — a product the platform
takes **no** deposit on is a different thing from a deposit of nothing
(`pricing_service.bottle_deposit_for`).

**Group: `limits`**

| Key | Default |
|---|---|
| `retail_max_distance_km` | `2` |
| `wholesale_max_distance_km` | `15` |
| `wholesale_moq_kg` | `100` |

**Group: `workflow`**

| Key | Default | Status |
|---|---|---|
| `require_vendor_verification` | `False` | read by `vendor_service.discoverable_vendor()` |
| `rider_kyc_sla_hours` | `24` | **never read** |
| `order_stale_after_minutes` | `45` | **never read** |

> ⚠️ **Finding F-11 — two workflow settings are inert.** `order_stale_after_minutes`
> is editable in the console and defaults to 45, but `jobs/auto_cancel_pending_orders.py`
> hardcodes `INTERVAL '15 minutes'`. An owner who raises the setting to give vendors
> more time will see nothing change, and orders will still be cancelled at 15
> minutes. `rider_kyc_sla_hours` is likewise read by nothing in the backend or the
> console. A setting that does nothing is worse than no setting: it is a control
> that lies about being connected.

### What is deliberately *not* configurable

`DispatchPolicy.VEHICLE_CAPACITIES = {"motorbike": 4, "tuktuk": 20, "truck": 200}`
and the rider registration radii (2 km retail, 15 km wholesale) are hardcoded, with
a comment explaining why: how many 20-litre bottles fit on a motorbike is a fact
about motorbikes, and a console field allowing 40 would produce orders no rider can
physically accept.

---

## 3. Money and precision

The rule is absolute and enforced by tests that parse the source: **money is
`Decimal`, never `float`**, from the database through the API to the string the
client renders.

Three consequences that matter commercially:

1. **`quote.total` is quantized to whole shillings** (`ROUND_HALF_UP`). M-Pesa's STK
   push only accepts an integer, so the amount pushed to the phone and the amount
   written to `Order.total_amount` are identical *by construction*. Before
   `pricing_service` existed the total was computed in four places with three
   different answers, and the M-Pesa callback's amount cross-check failed on every
   retail order.

2. **All intermediate line items are quantized to 2 dp** as they are computed, not
   at the end.

3. **One formula.** `services/pricing_service.py::compute_order_quote` is the only
   place an order total is derived. Clients render the breakdown it returns; they
   never re-add it.

> ⚠️ **Finding F-08 — the schema still stores several money columns as `Double`.**
> `Order.delivery_fee`, `OrderItem.price`, `OrderItem.Subtotal`, `Product.price`,
> `Product.discount` and `Product.capacity` are `Double`/`Float`, not `Numeric`. The
> service layer coerces on read (`Decimal(str(...))`), which contains the damage, but
> a value that round-trips through the column can already have lost precision before
> the coercion sees it — and `OrderItem.Subtotal` is what `_cart_payload` sums into
> `product_subtotal`, which is the base of every commission on the platform. The fix
> is a migration to `Numeric(10,2)`, not more coercion.

---

## 4. Discovery — how a customer finds a store

`services/vendor_service.py`. Every customer-facing vendor query carries the same
predicate, written once and imported:

```python
discoverable_vendor()  ==  Vendor.is_active IS TRUE
                       AND Vendor.verification_status NOT IN ('deleted',)
                       [AND verification_status == 'verified'   # only if the setting is on]
```

Nine discovery queries previously filtered on **none** of this, so a store whose
owner had deleted their account still appeared in search and in "near you".

`require_vendor_verification` is **off by default and read per call**, not frozen at
import. Every vendor on the platform is currently `pending`, so switching it on
empties the customer app — which is why it is a row an owner can revert in seconds
rather than an environment variable needing a redeploy.

### The two-stage geographic filter

Every discovery query pairs an **H3 pre-filter** with an **exact `ST_DWithin`**:

```python
center      = h3.latlng_to_cell(lat, lng, 8)
k_ring      = max(1, int(max_distance_m / 461.0) + 1)     # res-8 edge ≈ 461 m
cells       = h3.grid_disk(center, k_ring)
...
Vendor.h3_index_res8.in_(cells)                # index-friendly bounding box
AND ST_DWithin(Vendor.location, point, max_m)  # the actual radius
```

The H3 ring alone is a bounding box, not a radius — at k=5 it reaches roughly
2.5–3 km, so on its own it returned retail vendors beyond the 2 km limit. The
customer could browse them, fill a cart, and discover the problem only as a 400 at
checkout. The `k_ring` is now **derived from the configured radius**, so raising
`retail_max_distance_km` in the console widens the search too.

### The discovery surfaces

| Function | Returns | Radius |
|---|---|---|
| `get_nearby_vendors` | 3 nearest retail stores | 2 km |
| `get_top_rated_vendors` | up to 10 retail stores rated ≥ 4 | 2 km |
| `get_top_brands_service` | up to 10 wholesale brands rated ≥ 4 | 15 km |
| `get_vendors_by_type_service` | up to 10 of one type | that type's radius |
| `get_vendor_directory` | up to 50, with Postgres full-text search on `search_vector` | wider of the two when type is "all" |
| `get_vendor_by_id_service` | one store **by direct link** | — but still filtered |

The last one matters: a bookmark or a shared product link must not bypass what the
listings enforce, or suspending a store only hides it from people who were not
already looking for it.

---

## 5. The cart and its rules

`services/cart_services.py`.

**One vendor per cart.** Adding an item from a different store returns **409** with
a structured body (`type: "vendor_conflict"`, the existing store's name and id) so
the app can offer "replace your cart?". With `force_replace=true` the existing items
are deleted and the new one is added. This is re-asserted at checkout by
`pricing_service.single_vendor_or_400` — a multi-vendor cart would produce several
orders sharing one `CheckoutRequestID`, making the payment callback ambiguous about
which order it just paid for.

**Retail capacity, enforced on every path in.** `RETAIL_MAX_UNITS = 4`. Checked on
first add, on subsequent add, and on quantity change. The check used to live only
in the "cart already exists" branch, so the very first add on a fresh cart could
smuggle in any quantity.

**Per-request quantity bound:** `1 ≤ quantity ≤ 500`.

**Stock is checked on add** (`product.stock < quantity` → 400) and again, atomically,
at order creation.

**Cart locking.** `POST /api/cart/mpesa_payment` sets `is_locked` for the STK window;
every add/remove/quantity change returns 409 while it is set. If the customer ignores
the M-Pesa prompt no callback ever arrives, so `auto_cancel_pending_orders` unlocks
it — without that sweep the cart stays locked for the life of the account.

**Counters self-heal.** `fetch_cart` recomputes `items_count` and `total_amount` from
the actual rows and commits a correction if they disagree, so the badge always matches
the cart.

**The cart screen shows the rules before checkout.** `fetch_detailed_cart` attaches
`service_fee` (from `pricing_service.service_fee_for`, never a literal),
`total_quantity`, `total_weight_kg`, and for wholesale `moq_kg` / `moq_met` so the UI
can render "62 / 100 kg" instead of letting the customer discover the minimum as a 400.

---

## 6. The pricing engine

`services/pricing_service.py::compute_order_quote`. **Pure** — it reads, it never
mutates and never commits. Consuming the welcome offer and debiting the wallet are
side effects owned by `order_service.create_order` under a row lock.

### Order of operations

**Step 1 — Cart payload.** Sum quantity, weight (`product.weight_kg × qty`) and
subtotal (`item.Subtotal`, falling back to `price × qty`).

**Step 2 — Vehicle class.** The **larger** of the two answers:

| Source | Rule |
|---|---|
| By unit count | ≤ 4 motorbike, ≤ 20 tuktuk, ≤ 200 truck, above that a `ValueError` → 400 |
| By weight | ≤ 100 kg motorbike, ≤ 400 kg tuktuk, else truck |

100 kg of water does not fit on a motorbike just because the bottle count is low,
and 20 bottles do not fit just because they are light.

**Step 3 — Delivery fee.** Haversine distance from the vendor to the drop point,
then `DispatchPolicy.get_delivery_fee`:

```
retail  quick_swap      →  50 + 15·km
retail  keep_my_bottle  →  50 + 20 + 25·km
wholesale, vendor has a negotiated rate  →  vendor.wholesale_base_delivery_fee
                                            + vendor.wholesale_per_km_fee · km
wholesale, otherwise    →  vehicle base + vehicle per_km · km
```

**A vendor's own negotiated rate takes precedence over the platform's schedule.**
Any non-zero value in either of the vendor's two columns switches the whole
calculation to their rate.

Estimated time is `max(5, ceil(km × 3.0))` minutes — `MINUTES_PER_KM = 3.0`, an
average bike speed in Nairobi urban traffic. It is a hardcoded constant, not a
setting, and it is not adjusted for vehicle class: a truck and a motorbike are
quoted the same minutes per kilometre.

**Step 4 — Bottle deposit and the welcome offer.**

```python
is_first_order = user and not user.has_used_welcome_offer

if delivery_type == "keep_my_bottle" or is_first_order:
    bottle_deposit = Σ (deposit_for(product.capacity) × qty)
    if is_first_order and bottle_deposit > 0:
        welcome_discount = bottle_deposit × 0.30
        is_welcome_offer = True
```

A first-time customer pays a deposit **even on `quick_swap`**, because they have no
empty to swap. They get 30 % off that deposit. The platform absorbs the discount as
an acquisition cost — it is **never** charged to the vendor (see §7).

**Step 5 — Surcharges.**

```
payload_surcharge   = (total_quantity - 2) × 10    when quantity > 2
staircase_surcharge = (floor_level - 2)   × 10     when floor_level > 2 AND NOT has_elevator
```

Both are strictly greater-than: exactly 2 bottles and exactly floor 2 are free.

**Step 6 — Platform fees.** Service fee by vendor type; `surge_fee` if the current
EAT hour falls in a `peak_hours` window; `delivery_markup = delivery_fee × 0.05`
on wholesale only.

**Step 7 — Gross.**

```
gross = product_subtotal + delivery_fee + service_fee + surge_fee
      + delivery_markup + payload_surcharge + staircase_surcharge + bottle_deposit
```

**Step 8 — Discounts, in this order.** Order matters; reversing it lets the wallet
over-discount when both apply.

```
after_welcome   = gross - welcome_discount
headroom        = after_welcome - min_chargeable_total()      # 1.00
wallet_discount = min(wallet_balance, headroom)   when headroom > 0
total           = round_half_up(after_welcome - wallet_discount)   # WHOLE shillings
if total < 1.00: total = 1.00
```

The wallet never consumes the final shilling, because Safaricom rejects an STK
push for zero.

### `validate_quote` — the gates before money moves

Called **before** the STK push, so a validation failure can never leave the customer
debited with no order; and **again** inside `create_order` under the row lock,
because stock can change in between.

1. **Capacity, MOQ, distance.** `DispatchPolicy.validate_cart_preflight` — vehicle
   class must resolve; wholesale payload ≥ 100 kg; retail distance ≤ 2 km and
   quantity ≤ 4.
2. **Stock.** Every item's `product.stock ≥ item.quantity`.
3. **Debt.** `user.debt_balance > 0` → **402**, blocking the order entirely.
4. **Minimum total.** `quote.total ≥ 1.00`.

> ⚠️ **Finding F-01 (critical) — `debt_balance` is a one-way door.** It is written in
> exactly two places, both **increments**: a KSh 50 late-cancellation penalty
> (`order_service.py:1199`) and a KSh 30 staircase charge accepted during a mismatch
> (`order_service.py:1455`). **Nothing anywhere decrements it.** There is no payment
> endpoint, no admin write-off, no settlement against the wallet. Since any positive
> balance returns 402 on every future quote, a customer who cancels one accepted
> order is **permanently locked out of the platform** with no in-app way to clear
> KSh 50. This is the single highest-impact defect found.
>
> **Recommendation:** (a) settle `debt_balance` automatically against the next order
> as a line item, or against wallet top-up; (b) add an admin write-off action
> behind an existing finance capability with an audit row; (c) until either ships,
> the 402 message should tell the customer how to clear it — it currently says
> "Please clear it before placing a new order" and names no mechanism.

---

## 7. The revenue split

`services/order_service.py::calculate_revenue_splits`. Computed once, at order
creation, and **persisted onto the order row** — every later screen reads the stored
figures rather than recomputing them, so a rate change tomorrow cannot restate
yesterday's ledger.

### The formulas, verbatim

```
                          RETAIL                          WHOLESALE
vendor_commission   pt × 0.05                        pt × 0.025
service_fee         12.00                            50.00
rider_commission    df × (0.10 [+0.02 if kmb])       0.00
delivery_markup     0.00                             df × 0.05
surge_fee           10.00 if in a peak window        same

platform_total = vendor_commission + service_fee + rider_commission
               + delivery_markup + surge_fee − welcome_discount

vendor_net     = pt − vendor_commission + bd         pt − vendor_commission + df + bd
rider_net      = df − rider_commission + surcharges  (same formula — but see below)
```

where `pt` = product subtotal, `df` = delivery fee, `bd` = bottle deposit,
`surcharges` = payload + staircase.

### Reading it

- **The bottle deposit goes to the vendor**, in full, in `vendor_net`. The platform
  takes no commission on it.
- **The welcome discount is subtracted from `platform_total`**, not from the vendor's
  net. This is what "the platform absorbs it as an acquisition cost" means concretely:
  on a first order `platform_total` can and does go **negative** (see Example C).
- **On wholesale the delivery fee is returned to the vendor** (`+ df` in `vendor_net`)
  because the vendor owns the fleet. The rider is their employee and is paid by them,
  off-platform.
- **Surcharges belong to the rider** on retail. On wholesale they do not reach anyone
  — see Finding F-02.

### Who is actually paid, and when

Settlement happens **once**, at `delivered`, inside `deliverer_service.update_delivery_status`.
Nothing moves at acceptance, pickup, or on the payment callback. Every movement
goes through `wallet_service.apply_wallet_delta`, which changes the balance **and**
writes the matching `WalletTransaction` in one call.

| Path | Movements at `delivered` |
|---|---|
| **Retail, M-Pesa** | vendor `+vendor_net`; rider `+rider_net` |
| **Retail, cash** | rider `−(vendor_net + platform_total)`; vendor `+vendor_net` |
| **Wholesale, M-Pesa** | vendor `+vendor_net` only |
| **Wholesale, cash** | vendor `−platform_total` only |

On the retail cash path the rider is holding the customer's money, so their float
settles both the vendor's cut and the platform's; they are **not** additionally
credited `rider_net`, because they already have it in cash. On wholesale cash the
vendor's own rider collected the money, so only the platform's commission comes off
the vendor's wallet.

The platform has **no wallet row**. Its revenue is whatever is left over —
implicit in the difference between what was collected and what was paid out.

> ⚠️ **Finding F-02 — on wholesale, payload and staircase surcharges are collected
> and allocated to nobody.** `calculate_revenue_splits` computes
> `rider_net = df − 0 + surcharges` for wholesale too, and `create_order` writes it
> to `Order.rider_net`. But `update_delivery_status` skips the rider credit entirely
> when `is_wholesale`. The delivery fee itself is fine — it is returned to the vendor
> via `vendor_net`. The **surcharges are not**: on a 10-unit wholesale order the
> customer pays KSh 80 of payload surcharge that appears in no payout and in no
> `platform_total`. The platform does retain the cash (it is simply never
> disbursed), but its own books understate that revenue by exactly the surcharge on
> every wholesale order. **Recommendation:** either add `rider_surcharges` to
> `platform_total` for wholesale, or add them to `vendor_net` — but stop storing a
> non-zero `rider_net` on an order where no rider is ever paid, because analytics,
> the admin console and any future reconciliation all read that column.

> ⚠️ **Finding F-03 — the bottle deposit is charged but never recorded on the order.**
> `Order` has no `bottle_deposit` column. The deposit is folded into `vendor_net` and
> the quote's JSON, then lost. There is also no per-customer deposit balance
> (`User` has `bottle_purchased_at` and `bottle_refill_count`, neither of which
> carries money). The consequence: **the platform cannot answer "how much deposit has
> this customer paid?"** and there is **no refund path for a deposit anywhere in the
> codebase** — no endpoint, no admin action, no job. A customer who takes
> `keep_my_bottle`, pays KSh 300, and later returns the bottle has no way to get it
> back. `admin_bottle_service` values the *rider→vendor* float using the same
> deposit schedule, so the platform can see what riders owe vendors but not what it
> owes customers. **Recommendation:** add `Order.bottle_deposit` (Numeric) and a
> `customer_deposit_balance` on `Users`, credited on charge and debited on an
> audited return action. This is a real liability that is currently invisible.

---

## 8. Worked examples

Every figure below is produced by the formulas above with the shipped defaults.

### Example A — Retail, M-Pesa, returning customer

2 × 20 L @ KSh 200 · 1.2 km · `quick_swap` · off-peak · ground floor · no wallet credit

| Line | Working | KSh |
|---|---|---|
| Product subtotal | 2 × 200 | 400.00 |
| Delivery fee | 50 + 15 × 1.2 | 68.00 |
| Service fee | retail | 12.00 |
| Payload surcharge | 2 units, free allowance 2 | 0.00 |
| Bottle deposit | `quick_swap`, not first order | 0.00 |
| **Customer pays** | | **480.00** |

| Split | Working | KSh |
|---|---|---|
| Vendor commission | 400 × 0.05 | 20.00 |
| Rider commission | 68 × 0.10 | 6.80 |
| **Vendor net** | 400 − 20 | **380.00** |
| **Rider net** | 68 − 6.80 | **61.20** |
| **Platform total** | 20 + 12 + 6.80 | **38.80** |

380.00 + 61.20 + 38.80 = **480.00** ✔ balances exactly.

### Example B — Example A, paid in cash

Same figures. What changes is the settlement:

- At **acceptance**, the rider must hold `vendor_net + platform_total` = **KSh 418.80**
  of spendable float, or the accept is refused with a 402.
- At **delivery**, the rider's wallet is debited **418.80**; the vendor's is credited
  **380.00**.
- The rider physically holds the customer's **480.00**, so their true position is
  480.00 − 418.80 = **61.20** — identical to `rider_net`. ✔

### Example C — Retail, first order, `keep_my_bottle`

1 × 20 L @ KSh 200 · 1.5 km · off-peak · ground floor

| Line | Working | KSh |
|---|---|---|
| Product subtotal | | 200.00 |
| Delivery fee | 50 + 20 + 25 × 1.5 | 107.50 |
| Service fee | | 12.00 |
| Bottle deposit | 20 L schedule | 300.00 |
| Gross | | 619.50 |
| Welcome discount | 300 × 0.30 | −90.00 |
| **Customer pays** | 529.50, rounded half-up | **530.00** |

| Split | Working | KSh |
|---|---|---|
| Vendor commission | 200 × 0.05 | 10.00 |
| Rider commission | 107.50 × **0.12** | 12.90 |
| **Vendor net** | 200 − 10 + **300** | **490.00** |
| **Rider net** | 107.50 − 12.90 | **94.60** |
| **Platform total** | 10 + 12 + 12.90 − **90** | **−55.10** |

**The platform loses KSh 55.10 on this order, by design.** The vendor is made whole
including the full deposit; the rider earns their full fee; the 30 % discount comes
entirely out of platform margin. This is the acquisition cost, and it is why
`has_used_welcome_offer` is consumed under a row lock.

Note the rounding: the customer pays 530.00 against a computed 529.50. The extra
50 cents is retained and recorded nowhere.

### Example D — Wholesale, M-Pesa

10 units × 20 kg @ KSh 500 · 8 km · vendor on the platform's schedule

| Line | Working | KSh |
|---|---|---|
| Product subtotal | 10 × 500 | 5,000.00 |
| Vehicle class | 10 units → tuktuk; 200 kg → tuktuk | tuktuk |
| Delivery fee | 150 + 100 × 8 | 950.00 |
| Service fee | wholesale | 50.00 |
| Delivery markup | 950 × 0.05 | 47.50 |
| Payload surcharge | (10 − 2) × 10 | 80.00 |
| **Customer pays** | 6,127.50 → | **6,128.00** |

| Split | Working | KSh |
|---|---|---|
| Vendor commission | 5,000 × 0.025 | 125.00 |
| Rider commission | wholesale | 0.00 |
| **Vendor net** | 5,000 − 125 + **950** | **5,825.00** |
| `rider_net` *(stored, never paid)* | 950 + 80 | *1,030.00* |
| **Platform total** | 125 + 50 + 47.50 | **222.50** |

5,825.00 + 222.50 = 6,047.50, against 6,127.50 collected. The **KSh 80.00** gap is
Finding F-02: the payload surcharge, retained but unrecorded.

---

## 9. Checkout and order creation

`services/order_service.py::create_order`. The sequence, in order, all inside one
transaction:

1. **Idempotency guard.** An order already carrying this `CheckoutRequestID` → **409**.
   This is what stops a retried STK push from double-charging.
2. **Lock the customer row** — `SELECT ... FOR UPDATE`. The welcome offer and the
   wallet balance are both consumed below and must not be spendable twice.
3. **Load the cart items** with their vendor and product.
4. **Single vendor** or 400.
5. **Self-dealing check.** `vendor_staff_service.is_store_member(clerk_id, vendor)` →
   403. This covers the owner **and** every staff member, not just the owner.
6. **Wallet re-check.** If a pre-computed quote was passed in and
   `quote.wallet_discount > locked_balance`, the balance moved between pricing and
   creation → **409** rather than silently charging a different amount from the one
   already on the customer's phone.
7. **`validate_quote` again**, under the lock.
8. **Create the order** at `order_status = "unassigned"`, `deliverer_id = None`.
   A rider is **never** direct-assigned at creation; the dispatch engine offers the
   trip and a rider claims it. `bottle_source` is `"platform"` on a welcome order and
   `"own"` otherwise.
9. **Consume the welcome offer** — `user.has_used_welcome_offer = True`.
10. **Debit the wallet** via `apply_wallet_delta` with a negative amount and
    `TransactionType.order_payment`.
11. **Decrement stock atomically, per item:**

```sql
UPDATE "Products" SET stock = stock - :qty, is_available = (stock - :qty) > 0
WHERE id = :pid AND stock >= :qty
RETURNING id, stock, name, vendor_id, low_stock_threshold, low_stock_notified_at
```

    No row returned means a concurrent order depleted the stock → **400**, whole
    transaction rolls back. This is what makes overselling impossible.

12. **Low-stock warning** from the `RETURNING` values (§14).
13. **Commit.**

### Payment

`payment_method` is `"mpesa"` or `"cash"`.

- **M-Pesa (C2B):** `initiate_stk_push` with `quote.stk_amount` — an `int`, equal to
  `total` by construction. The callback route verifies a shared secret **and** a
  Safaricom IP allow-list, then `handle_mpesa_topup_callback` / the order equivalent
  re-checks under a row lock that the transaction is still pending (replay
  protection) and that **the amount Safaricom says it collected matches what was
  asked for**. Previously any caller who started a top-up could POST a synthetic
  success for their own `CheckoutRequestID` and be credited without paying.
- **Cash:** no money moves at checkout. The rider's float carries it (§15).

---

## 10. The order lifecycle

`Order.order_status`, with `VALID_TRANSITIONS` enforced by
`order_service.validate_status_transition`:

```
                    ┌──────────────┐
   create_order ──▶ │  unassigned  │ ◀──── rider rejects / cancels pre-pickup
                    └──────┬───────┘
                           │ a rider claims it
                    ┌──────▼───────┐
                    │   pending    │ ──▶ rejected     (vendor)
                    └──────┬───────┘ ──▶ cancelled
                           │ vendor accepts
                    ┌──────▼───────┐
                    │   accepted   │ ──▶ cancelled
                    └──────┬───────┘
                    ┌──────▼───────┐
                    │  preparing   │ ──▶ cancelled
                    └──────┬───────┘
                    ┌──────▼───────┐
                    │    ready     │
                    └──────┬───────┘
                    ┌──────▼───────┐
                    │  picked_up   │ ──┬─▶ pending_review ──┬─▶ picked_up
                    └──────┬───────┘   │  (bottle rejected)  └─▶ delivered
                           │           └─▶ mismatch_pending ──▶ delivered
                    ┌──────▼───────┐
                    │  delivered   │   terminal
                    └──────────────┘
```

`delivered`, `cancelled` and `rejected` are terminal.

### The two paused states

**`pending_review` — bottle rejection.** The rider inspects the customer's empty at
the door and refuses it (`report_bottle_rejection`), filing a
`BottleRejectionTicket` with free text and photos. The order pauses. An ARQ sweep
(`auto_resolve_bottle_rejections`, every minute) **auto-approves any ticket still
pending after 3 minutes** — which cancels the order, restores stock, and flags a
paid order for refund. Auto-approval favours the rider.

**`mismatch_pending` — address mismatch.** The rider arrives and finds the customer
is on a higher floor than their profile says (`report_address_mismatch`). The
customer is asked to either approve a **KSh 30** staircase charge or come to the
ground floor. Approving adds the charge to `staircase_surcharge`, to
`total_amount`, and — because M-Pesa already took the original total — **to the
customer's `debt_balance`**. A gig rider keeps 100 % of it; for an in-house rider it
goes to `vendor_net`.

Both states are counted as **open cash obligations** in `settlement_service.OPEN_CASH_ORDER_STATUSES`
— the rider is still holding goods, so their float is still committed.

> ⚠️ **Finding F-04 — the KSh 30 mismatch charge is a hardcoded literal that also
> creates permanent debt.** It sits at `order_service.py:1450` as `charge = 30.0`,
> unrelated to `staircase_surcharge_per_floor` (10.0) in the settings table, and it
> is applied as a flat fee regardless of how many floors. It is also a `float`
> assigned to `Numeric` columns (`order.total_amount`, `user.debt_balance`), the one
> place in this flow that breaks the Decimal rule. Combined with F-01, a customer who
> approves this charge once is locked out of the platform. **Recommendation:** derive
> the charge from `(actual_floor_level − free_floors) × staircase_surcharge_per_floor`,
> compute it as `Decimal`, and route it through the same settlement as any other
> surcharge rather than into `debt_balance`.

---

## 11. Rider discovery and dispatch

### Who is eligible at all

A rider is offered work only if:

- `is_available` is true (a toggle they control, and the platform flips it to false
  when they claim an order — **one live delivery at a time**);
- `employment_model == "gig_economy"` (Trip Radar only);
- `vehicle_type` matches the order's computed `vehicle_class` **exactly**;
- their `h3_index_res8` is inside the k-ring around the pickup point;
- `ST_Distance(rider.location, pickup) <= max_distance_m`.

`get_max_distance_m(vendor_type, action="rider_search")` is the *type's* radius —
2 km retail, 15 km wholesale.

### Registering with a vendor

`POST /api/rider-vendor/apply-vendor`. A rider applies to a store; the vendor
approves. Rules:

- The rider must have set an **operation base** (`operation_lat/lng`) or the
  application is refused — the distance cannot be computed without one.
- Haversine distance from that base to the store must be within **2 km** (retail) or
  **15 km** (wholesale). These are the registration radii, deliberately separate from
  the per-order delivery radius.
- **Maximum 10 vendors** per rider, counting only `pending` and `approved` rows.
- One application per (rider, vendor) pair.
- A rider may withdraw a `pending` application but **not** an approved one.

### The three dispatch tiers

`order_service.dispatch_order_to_riders`, launched as a background task on order
creation.

**Tier 1 — the vendor's own approved fleet.** Up to **10** riders from
`VendorRiderRegistry` with `status == "approved"`, `is_available`, and matching
vehicle type. Each gets a notification row, a queued push, and a
`NEW_DELIVERY_OFFER` WebSocket event carrying the full trip: fee, weight, quantity,
vendor details, `payment_method`, **`vendor_net` and `platform_total`** (so a rider
can see the float a cash order will cost them before accepting), distance and both
coordinate pairs.

**Wait `DISPATCH_TIER1_TIMEOUT_SECONDS = 20`.**

**Tier 2 — Trip Radar.** If the order is still `unassigned` after 20 seconds, it is
broadcast to **every** eligible nearby gig rider, registered with that vendor or not.
The status is re-checked first so an order accepted during the window is not
re-offered.

> **Wholesale returns before Tier 2.** `if vendor_type == "wholesale_b2b": return`.
> Wholesale never reaches the gig pool — it is fulfilled by the vendor's own fleet
> or not at all.

**Tier 3 — the re-offer sweep.** `reassign_unassigned_orders`, every 3 minutes.
Picks up orders that are `unassigned`, have no rider, are **`payment_status == "paid"`**,
and are older than 3 minutes, and re-broadcasts to all radar-eligible riders with
`"tier": 3`. Nothing is force-assigned — a rider still has to accept. Unpaid orders
are deliberately excluded: re-broadcasting an order nobody has paid for has riders
competing for a trip that may never exist.

### Claiming an order

`deliverer_service.accept_delivery_radar` — the most heavily guarded function in the
codebase, and correctly so:

1. **Redis lock** on `order_accept_lock:{order_id}`, 10 s → 409 if not acquired.
2. **`SELECT ... FOR UPDATE NOWAIT`** on the order; a `DBAPIError` (lock unavailable)
   is translated to "already claimed" rather than left to block.
3. **Cash float check** — the rider row is locked `FOR UPDATE` *before* the read,
   because two cash orders accepted at once both read the same balance and both
   passed. Required float is `vendor_net + platform_total`; spendable is
   `wallet_balance − committed_cash_float(rider)`. Short → **402**, with the message
   naming how much is already held for other orders.
4. **Self-dealing** — the rider is not the customer, and is not a member of the store
   (`is_store_member`).
5. **Re-check** `order_status == "unassigned" and deliverer_id is None` → 409.
6. **Auto-register** the rider with the vendor at `status="approved"` if no registry
   row exists — this is what makes Tier 2 work, and what makes the bottle ledger's
   "no registry row required" behaviour necessary (§13).
7. **Claim**: `deliverer_id`, status `pending`, `is_available = False`.
8. **Platinum recalculation.** The order was priced assuming 10 %. If this rider is
   Platinum, the commission is recomputed at **7 %**, and the difference moves from
   `platform_total` to `rider_net`. The customer's total does not change.

### Platinum status

`jobs/rider_tier_job.py`, nightly at 00:00. A gig rider who has **delivered 20 or
more orders in the trailing 7 days** is promoted; one who has not is demoted. The
only effect is the commission rate.

> ⚠️ **Finding F-05 — Tier 1 does not filter by distance.** The Tier 1 query joins
> `VendorRiderRegistry` on vendor and vehicle type and takes `LIMIT 10` with **no
> geographic predicate at all**. Because registration is radius-bounded (2 km / 15 km)
> the rider's *base* is near the store, but `is_available` riders are offered the
> trip wherever they currently are — a rider who registered with a Nairobi store and
> is presently in Mombasa gets the push. Tier 2 and Tier 3 both apply
> `ST_DWithin`; only the first, highest-priority tier does not. **Recommendation:**
> add the same `h3_index_res8.in_(k_ring)` + `ST_DWithin` pair to the Tier 1 query.
> It is a three-line change and it makes the strongest offer the platform sends also
> the most relevant.

> ⚠️ **Finding F-06 — `get_closest_deliverer` falls back to an unbounded global scan.**
> The H3 pass is correct; when it returns nothing, the fallback query drops the H3
> filter entirely. On a small dataset this is invisible. At scale it is a sequential
> scan of every rider row on every miss. It is not currently on the order-creation
> path (dispatch uses `get_radar_deliverers`), which is why it has not caused a
> problem — but it should be bounded before something starts calling it.

> ⚠️ **Finding F-07 — the 20-second Tier 1 wait is an in-process `asyncio.sleep`.**
> `dispatch_order_to_riders` is a background task inside the API process. If that
> process is recycled during the window — a deploy, a Render restart, a scale-down —
> **Tier 2 never fires for that order**. It is recovered 3 minutes later by the
> re-offer sweep, so nothing is lost permanently, but the customer waits three
> minutes instead of twenty seconds. **Recommendation:** enqueue the Tier 2
> escalation as a delayed ARQ job instead of sleeping in-process. The worker already
> exists and the pattern is used elsewhere.

---

## 12. Delivery execution and completion

`deliverer_service.update_delivery_status` accepts only `picked_up` and `delivered`.

**Idempotency first.** If `order.order_status` already equals the requested status,
it returns success with `already_applied: True` and **runs no side effects**. The
rider app retries from an offline queue; without this, a retry would settle the
wallets twice.

**Proof photo validation.** A supplied `proof_url` must pass
`utils.image_utils.validate_proof_url` — HTTPS, a Cloudinary host, and a
`.webp`/`.jpg`/`.png` extension — or 400.

### The guardrail

On a `quick_swap` order at `delivered`:

```python
received = empties_received or 0
if received < total_qty and not proof_url:
    raise HTTPException(400, "Proof of delivery photo is mandatory when reporting missing empty bottles.")
```

This check runs **before** the ledger accrual, deliberately: the accrual is what makes
the rider liable for the bottles, and a deficit must not reach the ledger unphotographed.
The platform rule — reinforced by a test that parses the source — is that this must
**never** be bypassed in a `catch` block. A failed upload is a failed completion.

### What happens at `delivered`

1. `deliverer.is_available = True` — the rider is freed for the next order.
2. Wallet settlement, per the table in §7.
3. Bottle accrual on `quick_swap` (§13).
4. `customer.bottle_refill_count += 1`, `customer.last_order_date = now()`.
5. **KSh 10 loyalty cashback** credited to the customer's wallet.
6. Commit, then broadcast, then notify customer and vendor.

> ⚠️ **Finding F-09 — the KSh 10 cashback is written outside the wallet ledger.**
> `customer.wallet_balance += 10.0` at `deliverer_service.py:~397` is a bare float
> assignment. It does not go through `apply_wallet_delta`, so **no `WalletTransaction`
> row is written**. The customer's Transactions screen cannot explain where the money
> came from, and summing a customer's ledger no longer reproduces their balance —
> which is the exact invariant `apply_wallet_delta` was introduced to restore. It is
> also a `float` added to a `Numeric` column. The amount is a hardcoded literal, not
> a setting. **Recommendation:** route it through `apply_wallet_delta` with a
> dedicated transaction type, and move the 10.0 into `Platform_Settings` under
> `commission` or a new `loyalty` group.

### Location tracking

`record_location_pings` accepts batched pings from the rider app, filtered by
`_is_plausible_coordinate`, buffered in Redis, and flushed to `Order_Tracking_Logs`
by an ARQ job every 10 seconds. That trail is what
`admin_delivery_replay_service` reads to answer "did the rider get to the door?" —
see [ADR-0002](./decisions/0002-three-valued-delivery-verdict.md) for why the
verdict is three-valued.

---

## 13. Bottle management

This is the platform's largest non-cash asset and the part most worth understanding.

### The three separate bottle relationships

| Relationship | Where it is tracked | State |
|---|---|---|
| Customer ↔ platform (deposit paid) | **nowhere** — see Finding F-03 | ❌ not implemented |
| Rider ↔ vendor (empties in transit) | `bottle_ledger_entries` + `VendorRiderRegistry` counters | ✅ fully implemented |
| Customer holding empties | `User.empty_bottles_held` | ⚠️ column exists, never written |

### The rider–vendor ledger

`services/bottle_ledger_service.py` maintains one invariant, stated in its own
docstring:

```
For every (rider, vendor, capacity):
    SUM(bottle_ledger_entries.quantity) == VendorRiderRegistry.pending_{n}L_empties
```

The ledger is the evidence; the counter is the index. `_apply_movement` is the only
function that touches either, and it always touches both.

**Accrual.** On a completed `quick_swap` delivery the rider is now holding the
vendor's empties. `accrue_delivery_empties` writes one row per capacity with
`entry_type = DELIVERY_ACCRUAL`.

Two behaviours worth naming:

- **No registry row is required.** Tier-2 radar offers orders to riders who have
  never registered with that vendor. The previous implementation skipped the accrual
  when the registry lookup came back empty, so those bottles left with no record.
  The ledger row is now **always** written; the counter is updated only if a row
  exists to hold it.
- **Idempotent.** A unique constraint (`uq_bottle_ledger_order_accrual`) turns a
  retried delivery completion into an `IntegrityError`, which is caught and treated
  as "already recorded" rather than double-charging the rider.

**Settlement.** `settle_empties`, called when the vendor confirms physical receipt
(`POST` from the vendor app). It:

- locks the registry row `FOR UPDATE` — two devices confirming at once would
  otherwise interleave and quietly forgive debt;
- **validates against the outstanding balance instead of clamping.** The previous
  version did `max(0, current - received)`, so a client sending 999 zeroed the debt
  and the API reported success. Over-receipt is now a 400 naming the true figure;
- writes negative-quantity rows with `entry_type = VENDOR_RECEIPT` and an
  `actor_clerk_id`, so there is a record of *who* confirmed it.

**Counters are clamped at zero** for display (`_bump_counter`), while the ledger
keeps the true signed history — a negative "owed" counter would render as nonsense
in both apps.

`TRACKED_CAPACITIES = (10, 20)`. A product of any other size still gets a ledger row
— the audit trail must be complete — but has no counter column.

### The admin view

`services/admin_bottle_service.py` values the whole float at the deposit schedule
and provides:

- **`drift()`** — re-checks the ledger-vs-counter invariant across every pair and
  reports mismatches. `reseat_counters()` rewrites the counter **from** the ledger,
  never the reverse.
- **`_pair_balances()`** uses `HAVING SUM(quantity) > 0`, so a credit at one store
  **cannot** cancel a debt at another. This was verified by construction: a rider
  with −2 at one store and +9 elsewhere reports 9, not 7.
- **`STALE_AFTER_DAYS = 14`** flags bottles a rider has held too long.
- `adjust()` for a manual correction, which raises `ValueError` the route turns into
  a 400.

Capacities with no configured deposit are reported as `"priced": false` and listed
under `unpriced_capacities` rather than being silently valued at zero.

### The bottle rejection flow

Covered in §10. Note that the auto-approve sweep resolves in favour of the rider
after 3 minutes and **cancels the order**.

> ⚠️ **Finding F-10 — `User.empty_bottles_held` is read but never written.**
> `jobs/stale_asset_monitor.py` runs nightly at 03:00 and looks for users with
> `empty_bottles_held > 0` and no order in 21 days, to send a "we miss you" nudge.
> A repository-wide search finds the column referenced in exactly two places — that
> job's `WHERE` clause and its log line — and in the migrations that created it.
> **Nothing anywhere increments it.** The job therefore matches zero rows on every
> run and has never sent a message. **Recommendation:** either increment it on a
> `keep_my_bottle` delivery and decrement it on return (which pairs naturally with
> the deposit balance in F-03), or delete the column and the job. A cron job that
> cannot fire is worse than no cron job — it reads as coverage that is not there.

> ⚠️ **Finding F-14 — `device_id` anti-fraud is declared but not implemented.**
> `Users.device_id` is `unique=True, index=True` and carries the comment
> `# Anti-fraud: one offer per device`. A repository-wide search finds **no code that
> reads or writes it**. The welcome offer is therefore gated only on
> `has_used_welcome_offer`, which is per-account — so the 30 % first-order discount
> can be farmed with fresh sign-ups from one handset. Combined with the fact that
> the discount is pure platform margin (§7), this is a direct revenue leak.
> **Recommendation:** capture the device id at registration and check it alongside
> `has_used_welcome_offer` when setting `is_welcome_offer`.

---

## 14. Stock management

**`Product.stock` is an integer decremented atomically at order creation** and
restored on every path out.

| Event | Stock restored | Where |
|---|---|---|
| Vendor rejects or cancels | ✅ | `vendor_management_service.update_order_status` / `cancel_order` |
| Customer cancels | ✅ | `order_service.cancel_customer_order` |
| Rider cancels (vendor fault, or post-pickup) | ✅ | `deliverer_service.cancel_delivery` |
| Auto-cancel at 15 min | ✅ | `jobs/auto_cancel_pending_orders` |
| Bottle rejection auto-approved | ✅ | `jobs/auto_resolve_bottle_rejections` |

All of them use `UPDATE ... SET stock = stock + qty, is_available = true` — a
relative update, never a read-then-write.

**`is_available` is derived, not independent.** It is set to `stock - qty > 0` on
decrement and `true` on restore, so a product hitting zero disappears from the
customer app automatically.

### Low-stock alerts

`order_service._warn_if_low_stock`, called from inside `create_order` using the
values returned by the atomic decrement's `RETURNING` clause.

- **Per-product threshold.** `Product.low_stock_threshold`, default 5, **0 disables**.
  A shop selling 200 refills a day and one selling a dispenser a month cannot share
  a number.
- **Latched.** `low_stock_notified_at` makes it **one notification per crossing**.
  Restocking above the line (`update_product`) clears the latch and re-arms it.
- **`queue_push`, not `dispatch_background`** — the stock decrement has not committed
  yet, and a rolled-back order must not have told anyone anything.
- **Staff are notified too**, but only those holding `PERMISSION_MANAGE_PRODUCTS`.
  Telling someone about a problem they cannot fix is noise.

### Product rules

`create_product` / `update_product` enforce **`0 ≤ discount < price`** — a discount
equal to or above the price is a 400, which is what stops negative pricing at the
source. Effective price is `price − discount`, computed in `add_to_cart_service` and
frozen onto the `CartItem` at add time.

### The vendor dashboard

`get_vendor_dashboard` returns revenue, order counts, and a `low_stock_products` list
built from `stock <= low_stock_threshold AND low_stock_threshold > 0`.

> ⚠️ **Finding F-13 — `delete_product` hard-deletes a row that orders reference.**
> `OrderItem.product_id` is a foreign key to `Products.id` declared **without
> `ondelete`**, so PostgreSQL applies `NO ACTION`; `vendor_management_service.delete_product`
> issues `session.delete(product)` with no check for existing order items. A vendor
> deleting a product they have ever sold gets a foreign-key violation surfaced as a
> **500**, with no message explaining why. If the constraint were ever relaxed to
> `SET NULL` the failure would become worse rather than better —
> `bottle_ledger_service.quantities_from_order_items` reads `item.product.capacity`
> to compute bottle debt, and an order whose product is gone contributes **zero**
> bottles to the ledger (it logs a warning and skips). **Recommendation:**
> soft-delete — set `is_available = False` and exclude from vendor listings — or
> refuse the delete with a 409 when order items exist.

---

## 15. Wallets, cash float and payouts

### The wallet model

Three entity types hold a wallet: `Users`, `Vendors` (per store), `Deliverers`.
`wallet_service.resolve_wallet_owner` verifies the caller actually owns a wallet of
the type they claim — `user_type` arrives in the request body and is untrusted — and
matches on **`clerk_id` alone**, so `staff_clerk_id` can never resolve here.

`X-Store-Id` names *which* store when an owner has several. Without it a withdrawal
debited whichever row the database returned first, from an unordered `.first()`.

Every balance change goes through **`apply_wallet_delta`**, which mutates the
balance and appends the `WalletTransaction` in one call. The stored ledger amount is
**signed** — negative debits — so summing a user's transactions reproduces their
balance movement exactly. `transaction_type` cannot carry direction, because
`order_payment` goes both ways: it debits a rider settling a cash order and credits
them for delivery earnings.

### Cash float — the anti-fraud core

`services/settlement_service.py` owns one equation:

```
available_for_payout = max(0, wallet_balance − committed_cash_float)
```

`committed_cash_float(rider)` sums `vendor_net + platform_total` over that rider's
**open** cash orders, where open means:

```python
OPEN_CASH_ORDER_STATUSES = ("accepted", "preparing", "ready",
                            "picked_up", "pending_review", "mismatch_pending")
```

`pending_review` and `mismatch_pending` are included deliberately — the rider is
still holding goods and the order can still complete.

`committed_cash_float_for_vendor(vendor)` is the wholesale equivalent, summing
`platform_total` over that vendor's open cash orders, because on wholesale the
vendor's own rider collects the cash and the platform's cut is debited from the
vendor's wallet at delivery.

The commitment exists **from acceptance**, not from delivery. Otherwise a rider could
accept a cash order, withdraw the float backing it, and leave the platform to fund
the vendor.

**Where the check is applied:**

| Path | Checks committed float? |
|---|---|
| Rider accepts a cash order (`accept_delivery_radar`) | ✅ |
| Vendor accepts a wholesale cash order (`update_order_status`) | ✅ |
| `POST /api/payouts/request` (`payout_service.request_payout`) | ✅ |
| Rider earnings screen (`deliverer_routes.py:448`) | ✅ displays it |
| Vendor balance screen (`vendor_management_routes.py:631`) | ✅ displays it |
| **`POST /api/wallet/withdraw`** (`wallet_service.initiate_wallet_withdrawal`) | ❌ **no** |

> ⚠️ **Finding F-12 (critical) — the second withdrawal path bypasses the cash-float
> check.** There are two ways to take money out of a wallet, and they do not agree:
>
> * `payout_service.request_payout` takes a `pg_advisory_xact_lock`, locks the
>   provider row, and compares the request against
>   `available_for_payout = balance − committed_cash_float`.
> * `wallet_service.initiate_wallet_withdrawal` locks the row correctly but compares
>   against **`current_balance` alone** (`wallet_service.py:~330`), with no reference
>   to `settlement_service`.
>
> A rider carrying KSh 5,000 of open cash orders and holding KSh 5,000 in their
> wallet is refused by the first route and **allowed by the second**. They can then
> deliver, at which point their wallet is debited into a negative balance the
> platform has no way to collect — the exact hole the float mechanism exists to
> close. The docstring in `vendor_management_service.py:370` even asserts that
> "`POST /api/wallet/withdraw` refuses on the same figure"; the code does not.
>
> The two paths also disagree on their thresholds and fees: `wallet_service` uses a
> flat KSh 500 minimum and waives the KSh 15 fee on **balance** ≥ 2,500/5,000/1,000;
> `payout_service` uses 250 (rider) / 500 (retail) / 1,000 (wholesale) and waives on
> **amount** ≥ 1,000/2,500/5,000. So the same withdrawal costs a different amount
> depending on which endpoint the app happens to call.
>
> **Recommendation, in order:** (1) make `initiate_wallet_withdrawal` call
> `settlement_service.available_for_payout` — a four-line change that closes the
> hole today; (2) collapse the two paths into one, keeping `payout_service`'s, since
> it also holds the advisory lock and writes a `Payout` row; (3) move the thresholds
> and fee into `Platform_Settings`, where every other business figure already lives.

### Payout mechanics

`payout_service.request_payout`:

1. Resolve the provider — **ownership, never staff membership**. A staff member gets
   a 403 with `type: "owner_only"`. This used to call `get_vendor_by_clerk_id`, which
   also matches `staff_clerk_id`, so a shop assistant could withdraw the store's
   balance to their own phone number, blocked only by a `router.replace()` in a React
   screen.
2. **Idempotency key** — an existing `Payout` with the same key is returned as-is.
3. Thresholds and fee (`get_payout_limits`): rider **250**, retail vendor **500**,
   wholesale vendor **1,000**; fee **KSh 15**, waived at amount ≥ 1,000 (rider),
   ≥ 2,500 (retail), ≥ 5,000 (wholesale).
4. `pg_advisory_xact_lock` keyed on the provider id, then lock the balance row.
5. **Debit immediately**, in the same transaction as the `Payout` row — so the money
   cannot be spent twice while the B2C call is in flight.
6. Call M-Pesa B2C for `amount − fee`. On any failure, `_refund_failed_payout`
   returns the full amount via `apply_wallet_delta` with `TransactionType.refund`.
   Without that, a failed payout would silently confiscate the money.

Callbacks land on a **separate router** (`callback_router`) so they are not behind
the authenticated `payout_routes` dependency chain, and are guarded by a shared
secret query parameter.

### Top-ups

Minimum **KSh 10**, whole shillings only, phone must match `^254[17]\d{8}$`.
STK push, a `pending` `WalletTransaction` keyed on `CheckoutRequestID`, settled by a
callback that re-checks pending status under a lock and cross-checks the amount.

---

## 16. Cancellations and refunds

### Who may cancel, and when

| Actor | Allowed from | Effect |
|---|---|---|
| Customer | `pending`, `accepted`, `unassigned` | stock restored, wallet credit returned, **KSh 50 penalty if `accepted`** |
| Vendor | `pending`, `accepted`, `unassigned` | stock restored, `commission_lost = platform_total` |
| Vendor (reject) | per the state machine | stock restored |
| Rider, pre-pickup, **vendor fault** (`vendor_closed`, `out_of_stock`) | `pending`…`ready` | order **cancelled** |
| Rider, pre-pickup, rider fault | `pending`…`ready` | order returns to **`unassigned`** and is re-dispatched |
| Rider, post-pickup | `picked_up` | order **cancelled**, stock restored |
| System | `pending`/`unassigned` older than 15 min | cancelled, `cancellation_reason = "acceptance_sla_breach"` |
| System | bottle-rejection ticket unresolved 3 min | cancelled, `cancellation_reason = "bottle_rejection_timeout"` |

**`commission_lost` is set inconsistently.** It records the platform revenue given
up by a cancellation and is set by `cancel_order`, `cancel_customer_order`,
`cancel_delivery` and both auto-cancel sweeps — but **not** by
`vendor_management_service.update_order_status`, which is the path a vendor takes
when they reject or cancel from the orders screen. That path sets
`payment_status = "refund_pending"` and stops. Any report summing `commission_lost`
therefore understates lost revenue by exactly the vendor-initiated rejections, which
are likely the most common kind. It is a one-line addition to that branch.

### On customer cancellation

The customer row is locked once, up front, because three things mutate it. Then:

- **KSh 50 penalty** added to `debt_balance` if the vendor had already accepted —
  they are likely already preparing. (See Finding F-01: nothing ever clears this.)
- The assigned rider, if any, is freed.
- Stock restored.
- **Wallet credit returned** via `apply_wallet_delta` with `TransactionType.refund`.
- **The welcome offer is restored only if the order was actually paid for.**
  Restoring it on a free `pending`/`unassigned` cancellation let the 30 % discount be
  farmed indefinitely.
- A paid order goes to `payment_status = "refund_pending"` and
  `commission_lost = platform_total`.

### The refund engine

`services/refund_service.py`, swept every 2 minutes by ARQ with
`FOR UPDATE SKIP LOCKED` so several workers claim disjoint slices.

```
refund_pending → refund_processing → refunded
                                   ↘ refund_failed
```

`process_single_refund` finds the original `Payment` with a non-null
`mpesa_receipt`, calls Safaricom's Transaction Reversal, and moves the order.
No receipt found → `refund_failed` immediately.

**The console never re-sends a refund.** A reversal that succeeded but lost its
callback is indistinguishable from one that failed; a retry pays the customer twice
out of the platform's float, irreversibly. The settlement screen's button is
labelled **Mark settled**, records a human-executed refund, moves no money, requires
`finance.refund_approve` and a written reason of at least 8 characters, and writes an
audit row. `STUCK_AFTER_HOURS = 6`. Tests fail the build if the string "Retry"
appears on that page. The full reasoning, and the exact condition that would make a
retry safe — implementing Safaricom's `/mpesa/transactionstatus/v1/query`, which is
**not** implemented — is in
[ADR-0001](./decisions/0001-no-automated-refund-retry.md).

---

## 17. The daily and nightly rhythm

The schedule is owned by **cron-job.org**, which calls `POST /api/cron/{slug}`.
`ARQ_INTERNAL_CRON=1` restores an in-process schedule for a dev machine with no
public URL. The cadences:

| Job | Cadence | What it does |
|---|---|---|
| `flush_gps_tracking_logs` | every **10 s** | Redis buffer → `Order_Tracking_Logs` |
| `auto_resolve_bottle_rejections` | every **minute** | auto-approves tickets older than 3 min; cancels the order, restores stock, flags refund |
| `process_pending_refunds` | every **2 min** | M-Pesa reversals for `refund_pending` |
| `reassign_unassigned_orders` | every **3 min** | Tier-3 re-offer of paid, unclaimed orders older than 3 min |
| `auto_cancel_pending_orders` | every **5 min** | cancels `pending`/`unassigned` older than **15 min**, restores stock, unlocks the cart |
| `check_push_receipts` | every **10 min** | reconciles Expo push receipts |
| `stale_asset_monitor` | **03:00** daily | nudges customers holding bottles 21+ days — see Finding F-10 |
| `evaluate_platinum_riders` | **00:00** daily | promotes/demotes on trailing-7-day volume |

Every sweep that mutates uses `FOR UPDATE SKIP LOCKED`, **commits per item**, and
re-checks the row's state under the lock, so several workers are safe and one bad
row cannot discard the batch. Broadcasts and pushes are collected during the loop and
sent **only for what actually committed**.

### A day in the life of an order

1. **07:15** — a customer opens the app. `get_nearby_vendors` returns the 3 closest
   discoverable retail stores inside 2 km.
2. They add 3 × 20 L. The cart refuses a 5th (motorbike capacity) and refuses items
   from a second store without confirmation.
3. **Checkout.** `compute_order_quote` prices it: goods, delivery
   `50 + 15·km`, service fee 12, payload surcharge `(3−2)×10 = 10`, **surge 10**
   because 07:15 is inside `[6,8]`. The wallet is applied, leaving at least KSh 1.
4. STK push for the whole-shilling total. `create_order` locks the customer, decrements
   stock atomically, writes the revenue split, and commits at `unassigned`.
5. **Tier 1**: up to 10 of the store's approved riders are pushed. Twenty seconds pass.
6. **Tier 2**: Trip Radar broadcasts to every eligible gig rider inside 2 km with a
   motorbike.
7. A rider swipes accept. Redis lock, `FOR UPDATE NOWAIT`, self-dealing check, and —
   if this were a cash order — a float check against `balance − committed_cash_float`.
   They are Platinum, so commission drops to 7 % and the difference moves from
   `platform_total` to `rider_net`. Order → `pending`, rider → unavailable.
8. The vendor accepts → `preparing` → `ready`. Stock was already taken at checkout.
9. Rider marks `picked_up`. Location pings buffer to Redis and flush every 10 s.
10. At the door: the customer's empty is fine, so no `pending_review`; their floor
    matches, so no `mismatch_pending`.
11. Rider marks `delivered` with `empties_received = 3`. No deficit, so no photo is
    required. Wallets settle: vendor `+vendor_net`, rider `+rider_net`. Three 20 L
    empties accrue to the rider's ledger against that store. The customer gets a
    KSh 10 cashback and their refill count increments. The rider is freed.
12. **Later that day** the rider returns the empties. The vendor confirms receipt;
    `settle_empties` writes three negative ledger rows and decrements the counter,
    refusing any figure above what is genuinely outstanding.
13. **00:00** — the Platinum job re-evaluates the rider on their trailing 7 days.
14. **03:00** — the stale-asset monitor runs, and currently matches nothing.

---

## 18. Findings and recommendations

Fourteen findings, ranked by what they cost. Nothing here is implemented; each is a
recommendation.

### Critical — money or access is wrong today

| # | Finding | Cost | Fix |
|---|---|---|---|
| **F-01** | `debt_balance` is only ever incremented; any positive value returns 402 on every future order | A customer who cancels one accepted order is **permanently locked out** over KSh 50 | Settle it against the next order or a top-up; add an audited admin write-off; name the mechanism in the 402 |
| **F-12** | `POST /api/wallet/withdraw` checks the raw balance, not `available_for_payout` | A rider can **withdraw the float backing their open cash orders** and go negative | Call `settlement_service.available_for_payout`; then collapse the two withdrawal paths; move thresholds into settings |

### High — revenue is leaking or unrecorded

| # | Finding | Cost | Fix |
|---|---|---|---|
| **F-03** | The bottle deposit is charged, folded into `vendor_net`, and recorded nowhere; no refund path exists | An **invisible liability**; a `keep_my_bottle` customer cannot get their deposit back | Add `Order.bottle_deposit` and a customer deposit balance; add an audited return action |
| **F-14** | `Users.device_id` is declared for "one offer per device" and read by nothing | The 30 % welcome discount — **pure platform margin** — can be farmed with fresh sign-ups from one handset | Capture and check it alongside `has_used_welcome_offer` |
| **F-02** | Wholesale surcharges land in `rider_net` on an order where no rider is ever paid | KSh 80 per 10-unit order retained but **absent from `platform_total`**; analytics understate revenue | Allocate them to `platform_total` (or `vendor_net`) and stop storing a phantom `rider_net` |

### Medium — correctness and operational integrity

| # | Finding | Cost | Fix |
|---|---|---|---|
| **F-05** | Tier 1 dispatch applies no geographic filter | The **highest-priority** offer can go to a rider in another city | Add the H3 + `ST_DWithin` pair used by Tiers 2 and 3 |
| **F-09** | The KSh 10 cashback bypasses `apply_wallet_delta` | No ledger row; a customer's transactions **no longer reconcile to their balance** | Route through `apply_wallet_delta`; move 10.0 into settings |
| **F-04** | The KSh 30 mismatch charge is a hardcoded float, unrelated to `staircase_surcharge_per_floor`, that creates permanent debt | Inconsistent pricing; breaks the Decimal rule; compounds F-01 | Derive from the setting × floors, as `Decimal`, settled like any surcharge |
| **F-07** | Tier 2 escalation waits on an in-process `asyncio.sleep(20)` | A restart during the window delays the order by **3 minutes** instead of 20 seconds | Enqueue a delayed ARQ job |
| **F-13** | `delete_product` hard-deletes a row referenced by `OrderItem` | 500s or orphaned history; orphaned items contribute **zero** to the bottle ledger | Soft-delete, or refuse when order items exist |

### Low — inert code and hygiene

| # | Finding | Cost | Fix |
|---|---|---|---|
| **F-10** | `User.empty_bottles_held` is never written; the 03:00 job matches nothing | A nightly job that **has never sent a message**, reading as coverage that is not there | Write the column, or delete it and the job |
| **F-11** | `order_stale_after_minutes` (45) and `rider_kyc_sla_hours` (24) are read by nothing | Console controls that **lie about being connected** | Wire them up, or remove them from `SPECS` |
| **F-08** | Several money columns are still `Double`/`Float` | Precision can be lost before the service layer's `Decimal` coercion sees it | Migrate to `Numeric(10,2)` |
| **F-06** | `get_closest_deliverer` falls back to an unbounded global scan | A sequential scan of every rider on every miss, at scale | Bound the fallback |

### Suggested sequence

1. **F-12** then **F-01** — both are live, both are small, and both are the kind of
   defect a single user hits and cannot work around.
2. **F-14** and **F-03** together — they are the same conversation about the deposit
   and the welcome offer, and F-03's schema change is the larger of the two.
3. **F-02**, **F-09**, **F-04** — three separate places where a figure ends up in the
   wrong column. Fixing them together makes one reconciliation pass possible.
4. **F-05** and **F-07** — dispatch quality, best done as one change to
   `dispatch_order_to_riders`.
5. The rest as hygiene.

### What is already strong, and should not be disturbed

It is worth being explicit about this, because most of the above is small relative
to what is right:

- **One pricing path.** `compute_order_quote` is genuinely the only place a total is
  derived, and the whole-shilling quantization means the amount charged and the
  amount stored cannot drift.
- **Concurrency.** Every contended row — accepting an order, moving a wallet,
  settling bottles, claiming a delivery — is taken with `FOR UPDATE`, and the two
  hottest paths add a Redis lock and `NOWAIT` on top. Sweeps use `SKIP LOCKED` and
  commit per item.
- **The atomic stock decrement.** `UPDATE ... WHERE stock >= qty RETURNING` makes
  overselling structurally impossible rather than unlikely.
- **The cash-float mechanism** is the right design, correctly reasoned, and applied
  in five of the six places it belongs. F-12 is one missing call, not a missing idea.
- **The bottle ledger's invariant** — evidence plus index, written only through
  `_apply_movement`, with a `drift()` check and a one-way `reseat_counters()` — is
  the strongest piece of accounting on the platform.
- **The guardrails are enforced by tests that parse the source**, not by convention:
  the proof-of-delivery deficit check, the hidden-review filter on every read path,
  the absence of a Retry button, the two sanctioned push paths. A new read of
  `reviews` that forgets the filter fails the build.

---

*Written against the repository at the `main` head. Every figure was read from the
code named beside it; where a number appears without a citation it is a shipped
default from `platform_config_service.SPECS` and can be changed from the console.*
