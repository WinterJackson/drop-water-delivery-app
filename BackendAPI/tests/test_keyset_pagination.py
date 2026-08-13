"""The one paginator every admin list uses.

Nineteen list endpoints page through this module. The interesting failures are
all silent — a cursor that decodes to the wrong type binds fine and returns
plausible rows; a boundary that skips a row loses it from every page rather than
raising; a "next" button that serves page 1 again looks like the end of a short
list. None of these produce an error anywhere, which is why they are tested
here rather than left to the endpoints.
"""
import ast
import pathlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from models.order_model import Order
from utils import keyset

BACKEND = pathlib.Path(__file__).resolve().parent.parent


# ── The cursor ────────────────────────────────────────────────────────────


def test_a_cursor_round_trips_every_type_a_sort_key_can_hold():
    """Values come back as the type the column expects, not as strings.

    An untagged ISO string bound against a `timestamptz` works on one driver and
    raises on another, and money would arrive as a float — in a comparison that
    decides which rows somebody sees.
    """
    values = [
        datetime(2026, 8, 13, 10, 30, tzinfo=timezone.utc),
        date(2026, 8, 13),
        uuid4(),
        Decimal("12.50"),
        7,
        "text",
        True,
        None,
    ]
    assert keyset.decode(keyset.encode(values)) == values
    assert [type(v) for v in keyset.decode(keyset.encode(values))] == [
        type(v) for v in values
    ]


def test_a_boolean_does_not_decode_as_an_integer():
    """`bool` is a subclass of `int`, so tag order matters.

    The ranked lists — disputed orders first, failed refunds first — sort on a
    boolean. Encoded as an integer it still compares correctly, but the round
    trip stops being lossless and the tag becomes a lie about the column.
    """
    assert keyset.decode(keyset.encode([True]))[0] is True
    assert isinstance(keyset.decode(keyset.encode([1]))[0], int)
    assert not isinstance(keyset.decode(keyset.encode([1]))[0], bool)


@pytest.mark.parametrize("bad", ["", "not base64 !!", "YWJj", "e30", "W1td"])
def test_a_mangled_cursor_starts_at_the_top_rather_than_erroring(bad):
    """A cursor is a value out of a URL somebody may have truncated in chat.

    Refusing the request with a 422 turns a mangled link into an error page
    instead of the first page of the list they were sent.
    """
    ordering = keyset.Order(Order.created_at, Order.id)
    assert keyset.seek(select(Order), ordering, bad).whereclause is None


def test_a_cursor_from_a_different_ordering_is_refused():
    """Two key values cannot be read against a three-column ordering.

    Silently zipping the shorter one would compare `created_at` against the rank
    column and page into the middle of an unrelated stretch of the list.
    """
    ordering = keyset.Order(Order.created_at, Order.id)
    with pytest.raises(keyset.InvalidCursor):
        ordering.after([datetime.now(timezone.utc)])


# ── The boundary ──────────────────────────────────────────────────────────


def test_the_ordering_pins_nulls_to_the_far_end():
    """Postgres puts NULLs first under `DESC` by default.

    `created_at` is nullable on several of these tables, so the default would
    open every list with the rows whose timestamp was never recorded.
    """
    clauses = [str(c) for c in keyset.Order(Order.created_at, Order.id).clauses()]
    assert all("NULLS LAST" in c for c in clauses)
    assert all("DESC" in c for c in clauses)

    ascending = keyset.Order(Order.created_at, Order.id, descending=False)
    assert all("ASC" in str(c) and "NULLS LAST" in str(c) for c in ascending.clauses())


def test_the_boundary_is_lexicographic_and_reverses_with_the_direction():
    descending = str(keyset.Order(Order.created_at, Order.id).after(
        [datetime(2026, 1, 1, tzinfo=timezone.utc), uuid4()]
    ))
    ascending = str(keyset.Order(Order.created_at, Order.id, descending=False).after(
        [datetime(2026, 1, 1, tzinfo=timezone.utc), uuid4()]
    ))
    assert "created_at <" in descending and "created_at >" not in descending
    assert "created_at >" in ascending and "created_at <" not in ascending
    # The tiebreak only applies where the leading column is equal, or two rows
    # sharing a timestamp sit either side of the boundary in an order the
    # database is free to change between queries.
    assert "created_at =" in descending


def test_an_ordering_needs_at_least_one_column():
    with pytest.raises(ValueError):
        keyset.Order()


# ── Splitting a page ──────────────────────────────────────────────────────


class _Row:
    def __init__(self, created_at, id):
        self.created_at = created_at
        self.id = id


def _rows(n: int) -> list[_Row]:
    base = datetime(2026, 8, 13, tzinfo=timezone.utc)
    return [_Row(base - timedelta(minutes=i), uuid4()) for i in range(n)]


def test_the_lookahead_row_is_trimmed_and_becomes_the_next_cursor():
    ordering = keyset.Order(Order.created_at, Order.id)
    fetched = _rows(11)  # a page of 10, plus the one that proves there is more

    page, cursor = keyset.split(fetched, 10, ordering)

    assert len(page) == 10
    assert page[-1] is fetched[9], "the lookahead row must not be shown"
    assert cursor is not None
    # The cursor is the last *shown* row, not the lookahead one — resuming from
    # the lookahead would skip it.
    assert keyset.decode(cursor) == [fetched[9].created_at, fetched[9].id]


def test_the_last_page_reports_no_next_cursor():
    ordering = keyset.Order(Order.created_at, Order.id)
    page, cursor = keyset.split(_rows(4), 10, ordering)
    assert len(page) == 4 and cursor is None

    # Exactly full, with nothing beyond it: still the last page. The old
    # hand-written version guessed with `len(items) == limit` and offered a Next
    # button here — on the audit log, which is read precisely when somebody is
    # trying to establish they have seen everything.
    page, cursor = keyset.split(_rows(10), 10, ordering)
    assert len(page) == 10 and cursor is None


def test_an_empty_result_has_no_cursor():
    page, cursor = keyset.split([], 10, keyset.Order(Order.created_at, Order.id))
    assert page == [] and cursor is None


# ── The in-memory mode ────────────────────────────────────────────────────


def test_page_list_walks_every_row_exactly_once():
    rows = [{"n": i} for i in range(23)]
    seen: list[int] = []
    cursor = None
    for _ in range(10):
        page = keyset.page_list(rows, limit=10, cursor=cursor)
        seen += [row["n"] for row in page["items"]]
        assert page["total"] == 23, "the total is the population, not the page"
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == list(range(23)), "no row may be skipped or served twice"
    assert cursor is None


def test_page_list_tolerates_a_nonsense_offset():
    rows = [{"n": i} for i in range(5)]
    for bad in ("garbage", keyset.encode([-3]), keyset.encode(["nope"])):
        assert keyset.page_list(rows, limit=2, cursor=bad)["items"][0]["n"] == 0


def test_page_list_past_the_end_is_empty_rather_than_wrapping():
    rows = [{"n": i} for i in range(5)]
    page = keyset.page_list(rows, limit=10, cursor=keyset.encode([99]))
    assert page["items"] == [] and page["next_cursor"] is None


# ── The pattern it replaced ───────────────────────────────────────────────


def test_no_endpoint_resolves_a_cursor_by_fetching_the_anchor_row():
    """The cursor carries the sort key; it is not a pointer to a record.

    Every list used to do `anchor = await db.get(Model, cursor)` and, when that
    row had since been deleted, filter by nothing at all and serve page 1 again
    — a Next button that loops forever, and one that only misbehaves once real
    data starts moving underneath it.
    """
    offenders = []
    for path in list((BACKEND / "routes").glob("*.py")) + list(
        (BACKEND / "services").glob("*.py")
    ):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = {
                n.id for n in ast.walk(node) if isinstance(n, ast.Name)
            } | {
                n.arg for n in ast.walk(node) if isinstance(n, ast.arg)
            }
            if "cursor" not in names and "before_id" not in names:
                continue
            source = ast.get_source_segment(path.read_text(), node) or ""
            if "anchor" in source and ".get(" in source:
                offenders.append(f"{path.name}::{node.name}")
    assert not offenders, (
        "these resolve a pagination cursor by loading the row it names; use "
        f"`utils.keyset` so the boundary survives a deleted anchor: {offenders}"
    )


# ── The three ways a paged list lies about its own size ───────────────────


def test_the_performance_boards_never_filter_before_they_count():
    """The summary describes the platform; the page describes the search.

    Both boards aggregate over every rider or store, take their counts, and only
    then narrow and slice. Moving the search into the aggregate is a one-line
    change that silently repoints `total`, `approved` and `with_any_order` at
    the result set — so "Riders 35" becomes "Riders 2" the moment somebody types
    a name, which reads as the fleet having shrunk rather than the list having
    narrowed. It is the same defect that reported a fleet of 100 out of 400 when
    the cap was `limit` instead.
    """
    source = (BACKEND / "services" / "admin_performance_service.py").read_text()
    tree = ast.parse(source)

    for name in ("riders", "vendors"):
        function = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        )
        body = ast.get_source_segment(source, function) or ""
        # From the query up to the counts — not from the signature, whose
        # parameter list names `search` and always will.
        aggregate = body[body.index("rows = ("): body.index("summary = {")]
        assert "search" not in aggregate, (
            f"`{name}` references the search term before it counts; the "
            "aggregate must run unfiltered or every summary figure below it "
            "starts describing the search instead of the platform"
        )
        # And the narrowing has to happen, or the search box does nothing.
        assert "_matching(items, search)" in body, (
            f"`{name}` never applies the search to the rows it pages"
        )


def test_no_search_filter_reaches_an_encrypted_column():
    """An `ILIKE` against ciphertext matches nothing and looks like it works.

    `Payout.account_details` and `Deliverer.ID_number` are `StringEncryptedType`
    — decryption happens in the type's `process_result_value`, on the way *out*.
    The column in the database holds ciphertext, so a search against it silently
    returns an empty result for every term. Finance searching a payout by
    destination number would get "no payouts match", not an error.
    """
    encrypted: list[str] = []
    for path in (BACKEND / "models").glob("*.py"):
        for line in path.read_text().splitlines():
            if "StringEncryptedType" in line and "=" in line and "import" not in line:
                encrypted.append(line.split("=")[0].strip())

    assert encrypted, "expected to find some encrypted columns to guard"

    offenders = []
    for path in list((BACKEND / "routes").glob("*.py")) + list(
        (BACKEND / "services").glob("*.py")
    ):
        source = path.read_text()
        for column in encrypted:
            for pattern in (f".{column}.ilike(", f".{column}.like("):
                if pattern in source:
                    offenders.append(f"{path.name}: {column}")
    assert not offenders, (
        "these match a search term against an encrypted column, which can only "
        f"ever return nothing: {offenders}"
    )


def test_the_first_page_still_takes_a_place_in_the_cursor_trail():
    """Page 1 has no cursor, and an absence cannot travel in a query string.

    The trail records the position of every page before the current one, so
    stepping forward from page 1 has to record *something*. Recording the
    absence — an empty value — is indistinguishable from an absent parameter and
    gets dropped, which left page 2 counting itself as page 1: its Previous link
    was never rendered, and its range read "1–10 of 35" instead of "26–35".
    """
    source = (ADMIN_TABLE := BACKEND.parent / "drop-admin" / "lib" / "table" / "query.ts")
    if not source.exists():
        pytest.skip("drop-admin/ is not present")
    text = source.read_text()

    assert "FIRST_PAGE" in text, "the page-1 sentinel is gone"
    assert "[...state.trail, state.cursor ?? FIRST_PAGE]" in text, (
        "the forward trail must record a position for page 1 unconditionally; a "
        "conditional push is what dropped it and broke the Previous link"
    )
    assert "previousRaw === FIRST_PAGE ? undefined : previousRaw" in text, (
        "stepping back onto the sentinel must clear the cursor, not send the "
        "sentinel to the API as though it were one"
    )
