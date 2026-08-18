"""
`any` is not a type. It is the absence of one, spelled like a type.

The three Expo apps carried 575 of them and the admin console carried **none**,
which is the first thing worth saying: the console proves the codebase can be
written without them, against the same backend, by the same people. So the
apps' 575 were not a necessity of React Native — they were a habit.

They were not harmless either. Typing the data layer found eight defects that
had shipped, every one of them invisible precisely because `any` had agreed in
advance to whatever came back:

* the vendor's order detail read `order.user.username`, `order.delivery_location`
  and `order.rider` — **none of which the API has ever sent**. Every order showed
  "Guest" for the customer, and the delivery-address and assigned-rider blocks
  never rendered at all. `!order.rider` is always true, so "Assign Fleet" was
  offered on orders that already had one.
* the customer app's `OrderItem` declared `product_name`, `unit_price`,
  `total_price` and `image`, none of which exist. Every screen but one was
  written against the real response; the one written against the type read
  `subtotal_at_order` and rendered nothing.
* `repeat-order` guarded on `lastOrder.items`, which is `order_item` on the
  wire — so the guard was always true and **"Repeat Order" silently did
  nothing, every time.**
* the rider's offline SQLite bound `undefined` for optional columns, which
  expo-sqlite resolves to its variadic overload rather than reporting; rows
  failed to write to the one copy of an order the rider reads with no signal.
* `TripRadar` defaulted money to the number `0` on a decimal-string field.
* the vendor app shipped a hand-written `clerk-expo.d.ts` that **overrode** the
  real types from `@clerk/clerk-expo` and `@react-navigation/native` with `any`.
  Deleting it produced zero errors: it was pure loss, and neither of the other
  two apps had one.

A second pass over the map screens and the shared wire types found nine more,
and the pattern is the same one every time — a declaration that agreed with
whatever came back:

* **every map screen in all three apps** passed `mapId` to `react-native-maps`,
  whose prop is `googleMapId`. Six screens, one silently dropped prop, and cloud
  styling has never once been applied.
* the customer app had **two** `Order` interfaces and **two** `Product`s. The
  `Product` most screens imported declared `price: number` and
  `discount: number` — money as a float, in the type, on the shelf price.
* six screens then did `Math.round((price - discount) * 100) / 100` on those two
  decimal strings, and hand-prefixed `KSH `. `discountedPrice` /
  `discountPercent` are the one implementation now.
* `MiniVendorCard` crashed on a store nobody had rated: `Array(Math.round(null))`
  is `Array(NaN)`, which throws "Invalid array length".
* `StoreClosedNotice` on the repeat-order screen was handed an order's vendor
  *snippet*, which carries no trading state — so the "this shop is shut" warning
  had never rendered on the one screen that rebuilds a whole basket in a tap.
* the vendor screen's delivery estimate and fee read `VendorDetails.delivery_time`
  and `.delivery_fee`, neither of which a store has; every customer read the same
  "Est. Delivery available • Delivery fee varies".
* the rider app's `RiderOrder` declared a `customer` the server has never sent
  (it is `user`), so the orders list said "3 items for Customer" for every order;
  and it omitted `delivery_type`, so the empties counter opened at **0 on every
  swap order**.
* the vendor's live map read `deliverer.current_lat` / `current_lng`, four
  fields not on `OrderDelivererSnippet`, as its fallback when no socket was
  delivering.
* `DiscoverVendors` compared every store against a literal `2.0` km, so a
  wholesale depot the server would have accepted at 15 km was refused on the
  handset. The limit is served now.

This guard is a **ratchet**, not a ban. The number may fall and may not rise.
A ban would be dishonest about where the codebase is today and would be
satisfied by `as unknown as X`, which is worse than what it replaced.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app", "drop-admin")

#: The high-water mark per app. **Lower these as you clean up; never raise one.**
#: A rise means a new `any` was written, which is the thing being prevented.
CEILING = {
    # 114 -> 113: `product-details/[id].tsx` mirrored the query into
    # `useState<any>()` and rendered that. The `any` was not incidental to the
    # bug, it *was* the bug's cover — it hid that `price`/`discount` are decimal
    # strings, so a seventh copy of the inline `Math.round((price - discount) *
    # 100) / 100` survived there after the other six were removed, and it hid a
    # nullable `vendor.lat` being passed to a `number`-typed parameter. Both
    # failed `tsc` the moment the screen rendered from the typed query instead.
    "drop-customer-app": 109,
    "drop-rider-app": 82,
    "drop-vendor-app": 81,
    # Written without a single one from the start, and it stays that way.
    "drop-admin": 0,
}

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"//[^\n]*")
_STRING = re.compile(r"""(['"`])(?:\\.|(?!\1).)*\1""", re.S)

#: Real type positions. Prose about "any value" must never count — these files
#: explain the defects they replaced, at length, and a substring scan would read
#: the explanation as the offence.
_PATTERNS = (
    re.compile(r"\bas\s+any\b"),
    re.compile(r":\s*any\b(?!\s*\w)"),
    re.compile(r"\bany\s*\[\]"),
    re.compile(r"<\s*any\s*[,>]"),
    re.compile(r"Record<[^>]*\bany\b[^>]*>"),
)

_SKIP_DIRS = {"node_modules", ".expo", ".next", "dist", "build", "coverage"}


def _sources(app: str):
    base = ROOT / app
    for path in base.rglob("*"):
        if path.suffix not in (".ts", ".tsx"):
            continue
        if _SKIP_DIRS & set(path.parts):
            continue
        # Generated: Expo rewrites this on every route change and it is not
        # ours to edit.
        if path.name.endswith("-env.d.ts") or path.name == "router.d.ts":
            continue
        yield path


def _count(path: pathlib.Path) -> int:
    src = path.read_text(errors="ignore")
    clean = _STRING.sub('""', _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", src)))
    return sum(len(rx.findall(clean)) for rx in _PATTERNS)


def _tally(app: str) -> tuple[int, dict[str, int]]:
    per_file: dict[str, int] = {}
    for path in _sources(app):
        n = _count(path)
        if n:
            per_file[path.relative_to(ROOT).as_posix()] = n
    return sum(per_file.values()), per_file


@pytest.mark.parametrize("app", APPS)
def test_the_any_count_never_rises(app: str):
    total, per_file = _tally(app)
    ceiling = CEILING[app]

    worst = sorted(per_file.items(), key=lambda kv: -kv[1])[:10]
    detail = "\n".join(f"    {n:3}  {f}" for f, n in worst)

    assert total <= ceiling, (
        f"{app} has {total} `any` against a ceiling of {ceiling}.\n"
        f"`any` is not a type — it is the absence of one, and it silently agrees "
        f"to whatever the server sends. Declare the shape instead; the backend "
        f"schemas in BackendAPI/schemas/ are the contract.\n"
        f"Worst files:\n{detail}"
    )


@pytest.mark.parametrize("app", APPS)
def test_the_ceiling_is_not_left_slack(app: str):
    """A ceiling well above the real count stops being a ratchet.

    Without this, cleaning up 40 `any` and leaving the number alone would let 40
    new ones be written before anything failed — and the whole point is that the
    next one costs somebody a conversation.
    """
    total, _ = _tally(app)
    ceiling = CEILING[app]
    assert total >= ceiling - 5, (
        f"{app} is down to {total} `any` but CEILING says {ceiling}. "
        f"Lower it to {total} in this file so the progress is locked in."
    )


def test_the_console_stays_at_zero():
    """It has never had one, and it is the proof the rest is achievable.

    Same backend, same team, same TypeScript. Whatever made 575 of them feel
    necessary in the apps, it was not the problem domain.
    """
    total, per_file = _tally("drop-admin")
    assert total == 0, f"the admin console has acquired `any`: {per_file}"


def test_the_scanner_does_not_count_prose():
    """Guards the guard: a substring scan would flag every file that explains
    why an `any` was removed, and the fix would be to stop explaining."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".ts", delete=False) as fh:
        fh.write(
            '// this used to be `any` and any caller could pass any value\n'
            '/* as any, : any, any[] — all of it prose */\n'
            'const message = "pass any value here";\n'
            'export const x: number = 1;\n'
        )
        path = pathlib.Path(fh.name)

    try:
        assert _count(path) == 0
    finally:
        path.unlink()


def test_the_scanner_finds_a_real_one():
    """And the other direction, so the count can never be zero by accident."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".ts", delete=False) as fh:
        fh.write(
            "export function f(x: any) { return x as any; }\n"
            "const rows: any[] = [];\n"
            "const m = new Map<string, any>();\n"
        )
        path = pathlib.Path(fh.name)

    try:
        assert _count(path) == 4
    finally:
        path.unlink()
