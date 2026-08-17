"""A screen's identity comes from its route parameter, and its content from its query.

**What broke.** `product-details/[id].tsx` showed a real, purchasable product —
name, photograph, price, "In Stock", vendor, and a live *Add to Cart* — for a
product the server had just answered **404** for. Reproduced on the device by
deep-linking `drop-customer://product-details/00000000-…-000000000000`: the page
rendered "Alkaline 20L Refill, KSH 100.00" for an id that has never existed.

Two independent halves, and it needed both:

1. **The screen mirrored its query into state and rendered the mirror.**

       const [Product, setProduct] = useState<any>();
       const [ProductLoaded, setProductLoaded] = useState(false);
       useEffect(() => { if (queryLoaded && ProductData) { setProduct(...); setProductLoaded(true); } }, [...]);

   Expo Router keeps **one component instance per route pattern** and swaps the
   parameters, so moving from product A to product B does not remount. The query
   key changes and `data` correctly becomes `undefined` — but the mirror does
   not, so the screen kept rendering A. When B was withdrawn the copying effect
   never ran again and A stayed on screen *permanently*, while `add_to_cart`
   read its id from the path and sent **B**. A price the customer reads and an
   id the button sends have to be the same product.

   Note which way round the failure is. The query layer was right; the hand-rolled
   cache in front of it was wrong. That is the general shape: a second store of a
   fact you already have is not a cache, it is a chance to disagree.

2. **There was no error branch at all.** The render was
   `{!ProductLoaded ? <Skeleton/> : <Product/>}`, and `ProductLoaded` could only
   ever be set by success — so a 404 fell through to the skeleton and animated
   for ever. Products here are **withdrawn, never deleted** (`deleted_at`, and
   every catalogue read carries `live_product()`), so a 404 is a routine,
   expected outcome — a favourite, a past order, a shared link, a push
   notification's `action_url` — not an exception.

**And the `any` was the cover.** Typing the screen from the query surfaced two
defects `tsc` had never been able to see: a nullable `vendor.lat` passed to a
`number` parameter, and

    KSH {Math.round(((Product?.price || 0) - (Product?.discount || 0)) * Quantity * 100) / 100}

on the subtotal read immediately before *Buy Now* — a float subtraction and the
`* 100` round trip `utils/money.ts` exists to prevent, on two decimal *strings*.
That is the **seventh** copy of a defect the other six screens had already had
removed, and it survived only because nothing could see the field types.

This file guards the two structural halves. The money half is already covered by
`test_no_implicit_any.py`'s ratchet and `utils/money.test.ts`.
"""
from __future__ import annotations

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")
SKIP_PARTS = {"node_modules", ".expo", "android", "ios", "dist", "__tests__"}

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.M)
_JSX_COMMENT = re.compile(r"\{\s*/\*.*?\*/\s*\}", re.S)

#: `usePathname()` sliced apart to recover a route parameter.
_PATH_SLICE = re.compile(r"\bpath\w*\s*\??\.\s*split\s*\(\s*['\"]/['\"]\s*\)")
#: A `useState` fed from a query result by an effect — the mirror.
_QUERY_HOOK = re.compile(r"\buse[A-Z]\w*\s*\([^)]*\)\s*;?", re.S)


def _code_only(src: str) -> str:
    """Source minus comments — these fixes quote the defective lines."""
    return _LINE_COMMENT.sub("", _JSX_COMMENT.sub("", _BLOCK_COMMENT.sub("", src)))


#: `const { id } = useLocalSearchParams()` / `{ id: vendorId }` — the bindings a
#: screen recovers from its route, including any alias it renames them to.
_PARAMS = re.compile(
    r"const\s*\{(?P<binding>[^}]*)\}\s*=\s*useLocalSearchParams", re.S
)


def _param_names(src: str) -> set[str]:
    names: set[str] = set()
    for match in _PARAMS.finditer(src):
        for part in match.group("binding").split(","):
            part = part.strip()
            if not part:
                continue
            # `id` or `id: vendorId` — the local binding is what later code uses.
            names.add((part.split(":")[-1]).strip())
    return {n for n in names if n.isidentifier()}


def _fetches_by_param(src: str, names: set[str]) -> str | None:
    """The name a record fetched *by the route parameter* is bound to, if any.

    The distinction the rule turns on: a screen that fetches a record by the id
    it was handed can be told that record does not exist, and needs somewhere to
    put that. A screen that merely reads the id to select from a list it already
    holds cannot.

    A *fetch* is a hook whose result is destructured with `data` — what every
    hook in `hooks/queries/` returns, and what separates one from `useMemo` /
    `useCallback`, which also match `use[A-Z]` and which the vendor app's
    `Map/[id].tsx` uses to pick an order out of a list by that same id.
    """
    for call in re.finditer(
        r"const\s*\{(?P<binding>[^}]*\bdata\b[^}]*)\}\s*=\s*use[A-Z]\w*\s*\((?P<args>.{0,200}?)\)\s*;",
        src,
        re.S,
    ):
        if not any(re.search(rf"\b{re.escape(n)}\b", call.group("args")) for n in names):
            continue
        for part in call.group("binding").split(","):
            head, _, alias = part.partition(":")
            if head.strip() == "data":
                return (alias or head).strip()
    return None


def _handles_absence(src: str, binding: str) -> bool:
    """Does the screen have anywhere to put "there is no such record"?

    Two forms count, and both are real. Reading `isError` is one. The other is a
    **terminal early return** on the record being absent —

        if (!order) { return <OrderNotFound/>; }

    which is what the vendor app's `OrderDetail/[id].tsx` does, and it is a
    complete answer: loading has finished and there is nothing, so the screen
    stops and says so.

    What does *not* count is an inline ternary that falls back to the loading
    state. `{loaded && record ? <Content/> : <Skeleton/>}` reads like a guard and
    is the defect — on a 404 it renders the skeleton, for ever. That is exactly
    the shape both screens fixed here had, so the distinction is the rule.
    """
    if re.search(r"\bisError\b|\bisLoadingError\b", src):
        return True
    return bool(
        re.search(
            rf"if\s*\(\s*!\s*{re.escape(binding)}\s*\)\s*\{{?\s*return\b", src, re.S
        )
    )


def _dynamic_routes() -> list[pathlib.Path]:
    """Every `[param].tsx` screen in the three apps."""
    found = []
    for app in APPS:
        approot = REPO / app / "app"
        if not approot.is_dir():
            continue
        found += [
            p
            for p in approot.rglob("*.tsx")
            if "[" in p.name
            and not any(part in SKIP_PARTS for part in p.parts)
        ]
    return sorted(found)


def test_a_dynamic_route_reads_its_declared_parameter():
    """`useLocalSearchParams()`, never a slice of the URL.

    `path.split("/")[2]` happened to be right for a screen exactly two segments
    deep whose group contributes nothing to the path. It is right by coincidence
    of depth, and it goes wrong silently — the wrong segment is still a string,
    so nothing fails until a customer opens a screen that has been moved.
    """
    offenders: list[str] = []

    for route in _dynamic_routes():
        src = _code_only(route.read_text(encoding="utf-8", errors="replace"))
        if _PATH_SLICE.search(src) and "useLocalSearchParams" not in src:
            offenders.append(str(route.relative_to(REPO)))

    assert not offenders, (
        "these dynamic routes recover their parameter by slicing the pathname "
        "instead of reading the parameter the filename declares:\n  "
        + "\n  ".join(offenders)
    )


def test_no_screen_mirrors_a_query_into_state_and_renders_the_mirror():
    """The two-sources-of-truth half.

    A screen that copies `data` into `useState` renders the copy, and the copy
    outlives the thing it described — across a parameter change, which does not
    remount, and across an error, which never overwrites it.
    """
    offenders: list[str] = []

    for route in _dynamic_routes():
        src = _code_only(route.read_text(encoding="utf-8", errors="replace"))
        # A setter called with the query's own `data` binding is the mirror.
        for match in re.finditer(
            r"const\s*\{\s*data\s*:\s*(?P<data>\w+)[^}]*\}\s*=\s*use[A-Z]\w*\s*\(", src
        ):
            data = match.group("data")
            if re.search(rf"\bset[A-Z]\w*\s*\(\s*{re.escape(data)}\s*\)", src):
                offenders.append(
                    f"{route.relative_to(REPO)}: copies `{data}` from a query into state"
                )

    assert not offenders, (
        "these screens store a second copy of data the query already holds, and "
        "render the copy. Expo Router reuses one component instance per route "
        "pattern, so a parameter change does not reset it — the previous "
        "record stays on screen under the new id, and an error never clears "
        "it:\n  " + "\n  ".join(offenders)
    )


def test_a_dynamic_route_has_somewhere_to_put_a_failure():
    """A record that cannot be fetched needs a branch that says so.

    Products are withdrawn rather than deleted and orders are scoped to their
    owner, so **404 is an ordinary answer** on these screens. Without an error
    branch the loading state is what a customer sees instead, for ever — and an
    endless skeleton is a quieter bug than a crash, not a smaller one.
    """
    offenders: list[str] = []

    for route in _dynamic_routes():
        src = _code_only(route.read_text(encoding="utf-8", errors="replace"))
        names = _param_names(src)
        if not names:
            continue
        # Only screens that fetch *by* the parameter. The vendor app's
        # `Map/[id].tsx` reads `id` to pick an order out of a list it already
        # holds (`useVendorOrders()`); nothing there is fetched by that id, so
        # there is no 404 for it to render and the rule does not apply.
        binding = _fetches_by_param(src, names)
        if binding is None:
            continue
        if _handles_absence(src, binding):
            continue
        offenders.append(str(route.relative_to(REPO)))

    assert not offenders, (
        "these dynamic routes fetch a record by id and never read the failure "
        "state, so a withdrawn product or an order that is not yours renders as "
        "a permanent loading screen:\n  " + "\n  ".join(offenders)
    )


def test_the_guards_can_still_see_the_defect():
    """Non-vacuity, on synthetic sources."""
    assert _PATH_SLICE.search('const id = path.split("/")[2];')
    assert _PATH_SLICE.search("const vendorId = path?.split('/')[2];")
    assert not _PATH_SLICE.search("const { id } = useLocalSearchParams();")

    mirror = (
        "const { data: ProductData, isSuccess } = useProduct(id);\n"
        "useEffect(() => { setProduct(ProductData); }, [ProductData]);"
    )
    m = re.search(r"const\s*\{\s*data\s*:\s*(?P<data>\w+)[^}]*\}\s*=\s*use[A-Z]\w*\s*\(", mirror)
    assert m and re.search(rf"\bset[A-Z]\w*\s*\(\s*{m.group('data')}\s*\)", mirror)

    direct = "const { data: Product, isError } = useProduct(id);"
    m2 = re.search(r"const\s*\{\s*data\s*:\s*(?P<data>\w+)[^}]*\}\s*=\s*use[A-Z]\w*\s*\(", direct)
    assert m2 and not re.search(rf"\bset[A-Z]\w*\s*\(\s*{m2.group('data')}\s*\)", direct)

    # Comments must not satisfy or trip any of it.
    assert not _PATH_SLICE.search(_code_only('// const id = path.split("/")[2];'))
    assert not _PATH_SLICE.search(_code_only('{/* was: path.split("/")[2] */}'))

    # The absence rule: an early return counts, a fallback to the skeleton does not.
    assert _handles_absence("if (!order) { return <NotFound/>; }", "order")
    assert _handles_absence("const { data: x, isError } = useThing(id);", "x")
    assert not _handles_absence(
        "{loaded && record ? <Content/> : <Skeleton/>}", "record"
    ), "a ternary falling back to the loading state is the defect, not the fix"

    # And the parameter/binding pair must be recovered from a real declaration.
    src = (
        "const { id: vendorId } = useLocalSearchParams<{ id: string }>();\n"
        "const { data: VendorDetails, isLoading } = useVendorDetails(vendorId);"
    )
    assert _param_names(src) == {"vendorId"}
    assert _fetches_by_param(src, {"vendorId"}) == "VendorDetails"
    # A list read that merely *mentions* the id is not a fetch by it.
    listy = (
        "const { id } = useLocalSearchParams();\n"
        "const { data: orders = [] } = useVendorOrders();\n"
        "const one = useMemo(() => orders.find(o => o.id === id), [orders, id]);"
    )
    assert _fetches_by_param(listy, _param_names(listy)) is None


def test_the_discovery_finds_the_screens_it_should():
    routes = {p.name for p in _dynamic_routes()}
    assert "[id].tsx" in routes
    assert len(_dynamic_routes()) >= 6, _dynamic_routes()
