"""Structural guards for the scalability work.

Each of these reproduces a defect that was live, and every one of them shares a
shape: right value, right type, passing tests, and then a cliff once the platform
has users. None of them is expressible as a type, and none would be caught by a
test of behaviour on an empty database — which is why they are here, parsing the
source, alongside the rest of this suite's invariants.
"""
import ast
import pathlib
import re

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")


def _code(text: str) -> str:
    """Source with comments and string bodies blanked, line numbers preserved.

    Every module here documents the defect it avoids, naming the forbidden
    construct in prose, so a plain substring scan flags the explanation as the
    offence. Only real code counts.

    Two passes, and the split between them is the whole subtlety. A **docstring**
    spans lines that are pure prose, so those lines are blanked outright — a
    per-line regex cannot see where such a string began. Every other string is
    blanked *within* its line by the regex, because the line also holds code:
    blanking the whole line for `X = "delivered"` would delete the assignment
    along with the literal, which is how the first version of this helper quietly
    removed the very statements it was meant to inspect.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        tree = None

    if tree is not None:
        docstring_lines: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
                and first.lineno
                and first.end_lineno
            ):
                docstring_lines.update(range(first.lineno, first.end_lineno + 1))
        text = "\n".join(
            "" if n in docstring_lines else line
            for n, line in enumerate(text.split("\n"), 1)
        )

    out = []
    for line in text.split("\n"):
        without_comment = re.sub(r"(#|//).*$", "", line)
        blanked = re.sub(r'''("""|\'\'\'|"|\')(?:\\.|(?!\1).)*\1''', '""', without_comment)
        out.append(blanked)
    return "\n".join(out)


def _py(*dirs: str) -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for d in dirs:
        files.extend(p for p in (BACKEND / d).rglob("*.py") if "__pycache__" not in p.parts)
    return files


def _app_sources(app: str, *globs: str) -> list[pathlib.Path]:
    root = REPO / app
    files: list[pathlib.Path] = []
    for pattern in globs:
        files.extend(p for p in root.glob(pattern) if "node_modules" not in p.parts)
    return files


pytestmark = pytest.mark.skipif(
    not (REPO / "drop-rider-app").exists(), reason="apps are not present"
)


# ── Spatial queries ───────────────────────────────────────────────────────


def test_no_spatial_filter_computes_a_distance_per_row():
    """`ST_DWithin`, never `ST_Distance(...) <= x`, as a *filter*.

    `ST_DWithin` is index-assisted and can use the GiST index on the location
    column. Comparing a computed `ST_Distance` forces the distance to be evaluated
    for every candidate row before any of them can be discarded — and the three
    dispatch queries that did this are the ones that run on every order.

    Ordering by `ST_Distance` is fine and is not what this looks for: sorting the
    rows that survived is the whole point of a nearest-first search.
    """
    offenders = []
    for path in _py("services", "routes", "jobs"):
        code = _code(path.read_text())
        for number, line in enumerate(code.split("\n"), 1):
            if re.search(r"ST_Distance\s*\([^)]*\)\s*(<=|<|>=|>)", line):
                offenders.append(f"{path.relative_to(BACKEND)}:{number}")
    assert offenders == [], (
        "these filter on a computed distance instead of ST_DWithin, which cannot "
        f"use the GiST index: {offenders}"
    )


def test_the_radar_search_is_bounded():
    """`get_radar_deliverers` must not return every rider in the ring.

    It had no ceiling, so a dense market materialised the whole available fleet
    and pushed to all of it. Past a couple of dozen the extra riders receive a
    notification for an order that is already claimed, which is how a rider learns
    to stop opening them.
    """
    source = (BACKEND / "services" / "order_service.py").read_text()
    tree = ast.parse(source)
    function = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_radar_deliverers"),
        None,
    )
    assert function is not None, "get_radar_deliverers has moved; update this test"
    body = ast.get_source_segment(source, function) or ""
    assert ".limit(" in body, "the radar search returns an unbounded number of riders"


# ── Rate limiting ─────────────────────────────────────────────────────────


def test_the_rate_limiter_is_not_keyed_on_the_address():
    """A client address here is a mobile carrier's NAT pool.

    Keyed on it, the global limit is one budget shared by every Safaricom data
    subscriber using the platform at once — so the busiest customer throttles the
    quietest, and the 429s look random. `core/rate_limit.py` resolves the
    authenticated subject instead and falls back to the address only where there
    is nobody to name.
    """
    source = _code((BACKEND / "core" / "redis_client.py").read_text())
    assert "key_func=rate_limit_key" in source, "the limiter is not using the subject key"
    assert "get_remote_address" not in source, (
        "redis_client.py keys on the client address again — on this platform that "
        "is a carrier NAT pool, not a user"
    )


def test_the_key_middleware_runs_before_the_limit_is_checked():
    """Registration order is load-bearing and silently reversible.

    Starlette runs middleware outermost-first in **reverse** registration order,
    so `RateLimitKeyMiddleware` must be added *after* `SlowAPIMiddleware` to run
    *before* it. Swapped, the key is never resolved and every limit quietly
    reverts to the address it used to use — with no error anywhere.
    """
    source = _code((BACKEND / "main.py").read_text())
    slowapi = source.find("add_middleware(SlowAPIMiddleware)")
    key = source.find("add_middleware(RateLimitKeyMiddleware)")
    assert slowapi != -1 and key != -1, "one of the two middlewares is no longer registered"
    assert slowapi < key, (
        "RateLimitKeyMiddleware must be registered after SlowAPIMiddleware so it "
        "runs before it; as written the limiter sees no key and falls back to the IP"
    )


# ── Observability cost ────────────────────────────────────────────────────


def test_tracing_is_not_unconditionally_full():
    """`traces_sample_rate=1.0` with `profiles_sample_rate=1.0` attaches a
    sampling profiler to every request and ships a span tree for each one. Correct
    with no traffic; a latency and a bill that both scale with success.
    """
    source = _code((BACKEND / "main.py").read_text())
    assert "traces_sampler=" in source, "Sentry no longer samples by what the request is"
    assert not re.search(r"traces_sample_rate\s*=\s*1\.0", source)
    assert not re.search(r"profiles_sample_rate\s*=\s*1\.0", source)


# ── Conditional requests ──────────────────────────────────────────────────


def test_a_body_carrying_a_presigned_url_is_never_given_an_etag():
    """A `304` says "what you hold is still valid".

    For a body containing a presigned S3 URL that is a lie with a fuse on it: the
    signature expires, and the client keeps serving a cached copy whose image URLs
    have died, with no error anywhere to explain it.
    """
    source = (BACKEND / "core" / "conditional.py").read_text()
    assert "_PRESIGNED_MARKER" in source
    assert "X-Amz-Signature" in source
    assert "_PRESIGNED_MARKER in body" in _code(source), (
        "the ETag path no longer excludes presigned bodies"
    )


def test_the_etag_middleware_hashes_the_uncompressed_body():
    """Registered before GZip, so it runs inside it.

    Hashing the compressed body would make the validator depend on whether the
    client sent `Accept-Encoding`, so the same rows would carry two different tags
    and a device that changed its mind would re-download everything.
    """
    source = _code((BACKEND / "main.py").read_text())
    etag = source.find("add_middleware(ETagMiddleware)")
    gzip = source.find("add_middleware(GZipMiddleware")
    assert etag != -1 and gzip != -1
    assert etag < gzip, "ETagMiddleware must be registered before GZipMiddleware"


# ── Images ────────────────────────────────────────────────────────────────

#: Fields that are photographs, not documents. A presigned URL for one of these
#: changes on every response, which changes the cache key on every response,
#: which means every client re-downloads every image on every refresh.
PUBLIC_IMAGE_FIELDS = {"profile_pic", "image_url"}

#: Fields that are somebody's identity or the evidence in a dispute. These stay
#: presigned, short-lived and audited.
PRIVATE_ASSET_FIELDS = {"driver_license", "proof_url", "id_document", "kyc_document"}


def _validated_fields(decorator: ast.expr) -> set[str]:
    return {a.value for a in getattr(decorator, "args", []) if isinstance(a, ast.Constant) and isinstance(a.value, str)}


def test_photographs_are_public_urls_and_documents_are_presigned():
    """The split is the whole safety property, in both directions.

    Presigning a product photograph is a bandwidth defect; serving an identity
    document from a stable public URL is a data-protection incident. Neither
    should depend on whoever writes the next schema remembering which is which.
    """
    offenders = []
    for path in (BACKEND / "schemas").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if not (isinstance(decorator, ast.Call) and getattr(decorator.func, "id", "") == "field_validator"):
                    continue
                fields = _validated_fields(decorator)
                body = ast.dump(node)
                signs = "generate_presigned_url" in body
                public = "public_asset_url" in body
                if not (signs or public):
                    continue
                where = f"{path.name}:{node.name}({', '.join(sorted(fields))})"
                if fields & PUBLIC_IMAGE_FIELDS and signs:
                    offenders.append(f"{where} presigns a photograph — every client re-downloads it every refresh")
                if fields & PRIVATE_ASSET_FIELDS and public:
                    offenders.append(f"{where} serves a document from a stable public URL")
    assert offenders == [], offenders


# ── Money, all the way to the handset ─────────────────────────────────────


def test_no_app_stores_money_as_a_float():
    """The platform's money rule does not stop at the network boundary.

    `Decimal` in Postgres, a decimal string on the wire, integer cents via
    `BigInt` in the apps — and then `total_amount REAL` in the rider's offline
    SQLite, which is the copy read when the rider is offline and so cannot check
    it against anything.
    """
    money = ("total_amount", "delivery_fee", "amount", "balance", "fee", "price", "subtotal")
    offenders = []
    for app in APPS:
        for path in _app_sources(app, "config/*.ts", "services/*.ts", "utils/*.ts"):
            code = _code(path.read_text())
            for number, line in enumerate(code.split("\n"), 1):
                match = re.match(r"\s*(\w+)\s+(REAL|FLOAT|DOUBLE)\s*,?\s*$", line, re.I)
                if match and any(m in match.group(1).lower() for m in money):
                    offenders.append(f"{app}/{path.name}:{number} {match.group(1)} {match.group(2)}")
    assert offenders == [], f"money declared as a binary float on-device: {offenders}"


# ── App network behaviour ─────────────────────────────────────────────────


def test_every_app_retries_only_what_retrying_fixes():
    """A 4xx is a refusal, not a dropped packet.

    A plain `retry: 2` makes every refusal cost three round trips, and because
    each client signs out on a 401 it fires the sign-out handler three times for
    one expired session. The customer and rider apps carried a comment explaining
    exactly this while the vendor app — the surface where a shop that cannot see
    its orders is losing money — still had the bare number.
    """
    offenders = []
    for app in APPS:
        layout = REPO / app / "app" / "_layout.tsx"
        assert layout.exists(), f"{app} has no root layout; update this test"
        code = _code(layout.read_text())
        client = code[code.find("new QueryClient") :]
        assert "new QueryClient" in code, f"{app} no longer builds a QueryClient here"
        if re.search(r"retry:\s*\d", client):
            offenders.append(f"{app}: bare numeric retry in the query client default")
        if "retryTransientOnly" not in client:
            offenders.append(f"{app}: query client does not use retryTransientOnly")
    assert offenders == [], offenders


def test_no_app_hardcodes_a_flat_request_timeout():
    """15 seconds is a broadband number.

    On a congested cell a request that would have completed at 25 s was aborted,
    retried twice and reported as a failure — three quarters of a minute of
    spinner and three uploads of the same body over metered data. `netBudget`
    reads the live connection and the request kind instead.
    """
    offenders = []
    for app in APPS:
        for path in _app_sources(app, "API/*.ts"):
            if path.name == "netBudget.ts":
                continue
            code = _code(path.read_text())
            for number, line in enumerate(code.split("\n"), 1):
                if re.search(r"timeout(Ms)?\s*[:=]\s*\d{4,}", line, re.I):
                    offenders.append(f"{app}/{path.name}:{number}")
    assert offenders == [], (
        f"a fixed timeout is back in an API client; use timeoutFor(): {offenders}"
    )


def test_every_app_derives_its_timeout_from_the_connection():
    """Not merely "no literal" — the budget module has to actually be wired in."""
    for app in APPS:
        budget = REPO / app / "API" / "netBudget.ts"
        assert budget.exists(), f"{app} has no API/netBudget.ts"
        clients = [p for p in _app_sources(app, "API/*.ts") if p.name in ("apiFetch.ts", "useApiClient.ts")]
        assert clients, f"{app} has no API client to check"
        assert any("timeoutFor" in _code(p.read_text()) for p in clients), (
            f"{app}: no API client asks netBudget for a timeout"
        )


# ── The scanners themselves ───────────────────────────────────────────────


def test_the_comment_blanking_does_not_hide_real_code():
    """Every scanner above runs over `_code`, so a bug in it passes everything."""
    sample = 'x = 1  # ST_Distance(a, b) <= c\ny = "retry: 2"\nz = ST_Distance(a, b) <= c'
    blanked = _code(sample)
    assert "ST_Distance(a, b) <= c" in blanked.split("\n")[2], "real code was blanked"
    assert "<=" not in blanked.split("\n")[0], "a comment was not blanked"
    assert "retry: 2" not in blanked.split("\n")[1], "a string body was not blanked"

    # The failure that actually happened: prose inside a multi-line docstring,
    # which a per-line regex cannot see the start of.
    multiline = '"""Why we removed\ntraces_sample_rate=1.0 from here.\n"""\nkeep = 1'
    blanked = _code(multiline)
    assert "traces_sample_rate=1.0" not in blanked, "a multi-line docstring was not blanked"
    assert "keep = 1" in blanked, "code after a docstring was blanked"
