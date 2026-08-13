"""Keyset pagination, in one place.

Every admin list on this platform pages the same way — newest first, with the
row id breaking ties — and until now each endpoint wrote that out by hand. Six
of them did; thirteen did not and simply returned the first `limit` rows, which
is how the console showed fifty of two hundred pending payouts and looked
exactly like a console showing all of them.

**Never OFFSET.** It degrades precisely when a table grows large enough for
pagination to matter, and it skips or repeats rows whenever the underlying set
changes between two page loads — which on a live platform it does constantly.
An order delivered while somebody reads page 2 shifts every later row up one,
and OFFSET answers by hiding the row that moved across the boundary.

**The cursor carries the sort key, not the row id.** The hand-written version
resolved the cursor with `session.get(Model, id)` and, when that row had since
been deleted, filtered by nothing at all and served page 1 again — a "Next"
button that loops forever, and one that only misbehaves once real data starts
moving underneath it. Encoding the key values means the boundary survives the
row that defined it: it is a position in an ordering, not a pointer to a record.

The cursor is opaque on purpose. It is base64 of a small JSON array, each entry
tagged with its type so the value binds back as a `datetime`/`UUID`/`Decimal`
rather than a string the driver has to guess at. Clients echo it back and never
parse it, which leaves us free to change what a page boundary means.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Iterable, Sequence
from uuid import UUID

from sqlalchemy import and_, false, or_
from sqlalchemy.sql import ColumnElement, Select

__all__ = ["Order", "seek", "split", "encode", "decode", "InvalidCursor"]


class InvalidCursor(ValueError):
    """A cursor that did not decode. Callers treat this as 'start at the top'."""


# ── Encoding ──────────────────────────────────────────────────────────────
#
# Tagged so the value comes back as the type the column expects. An untagged
# ISO string bound against a `timestamptz` works on one driver and raises on
# another, and money would silently arrive as a float.

_ENCODERS: list[tuple[type, str, Callable[[Any], Any]]] = [
    (bool, "b", bool),  # before int — bool is a subclass of int
    (datetime, "dt", lambda v: v.isoformat()),
    (date, "d", lambda v: v.isoformat()),
    (UUID, "u", str),
    (Decimal, "n", str),
    (int, "i", int),
    (float, "f", float),
    (str, "s", str),
]

_DECODERS: dict[str, Callable[[Any], Any]] = {
    "b": bool,
    "dt": datetime.fromisoformat,
    "d": date.fromisoformat,
    "u": UUID,
    "n": Decimal,
    "i": int,
    "f": float,
    "s": str,
}


def _tag(value: Any) -> list:
    if value is None:
        return ["z", None]
    for kind, tag, encode_value in _ENCODERS:
        if isinstance(value, kind):
            return [tag, encode_value(value)]
    raise TypeError(f"keyset cursor cannot carry {type(value).__name__}")


def _untag(entry: Any) -> Any:
    if not isinstance(entry, list) or len(entry) != 2:
        raise InvalidCursor("malformed cursor entry")
    tag, value = entry
    if tag == "z":
        return None
    decode_value = _DECODERS.get(tag)
    if decode_value is None:
        raise InvalidCursor(f"unknown cursor tag {tag!r}")
    try:
        return decode_value(value)
    except (TypeError, ValueError) as exc:
        raise InvalidCursor(str(exc)) from exc


def encode(values: Sequence[Any]) -> str:
    """The opaque string a client echoes back to ask for the next page."""
    raw = json.dumps([_tag(value) for value in values], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode(cursor: str) -> list[Any]:
    """Reverse `encode`. Raises `InvalidCursor` on anything it did not write."""
    if not cursor:
        raise InvalidCursor("empty cursor")
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode())
        entries = json.loads(raw)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise InvalidCursor(str(exc)) from exc
    if not isinstance(entries, list):
        raise InvalidCursor("cursor is not a list")
    return [_untag(entry) for entry in entries]


# ── Ordering ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, init=False)
class Order:
    """The sort key, most significant first, ending in a unique tiebreak.

    The last column **must** be unique within the result set — the row id,
    always. Without it two rows sharing a timestamp sit either side of a page
    boundary in an order the database is free to change between queries, and one
    of them is served twice while the other is never served at all.
    """

    columns: tuple[ColumnElement, ...]
    descending: bool = True

    def __init__(self, *columns: ColumnElement, descending: bool = True):
        if not columns:
            raise ValueError("an ordering needs at least one column")
        object.__setattr__(self, "columns", tuple(columns))
        object.__setattr__(self, "descending", descending)

    def clauses(self) -> list[ColumnElement]:
        """`ORDER BY`, with NULLs pinned to the far end.

        Postgres puts NULLs first under `DESC` by default, which would open
        every list with the rows whose timestamp was never recorded. Pinning
        them last also makes the boundary arithmetic below tractable: "null" is
        one well-defined place rather than a hole in the middle of the sequence.
        """
        if self.descending:
            return [column.desc().nulls_last() for column in self.columns]
        return [column.asc().nulls_last() for column in self.columns]

    def values(self, row: Any) -> list[Any]:
        """The key values of a row, for encoding into the next cursor."""
        return [_read(row, column) for column in self.columns]

    def after(self, key: Sequence[Any]) -> ColumnElement:
        """The predicate selecting everything strictly past `key`.

        Lexicographic, written out rather than expressed as a row-value
        comparison (`(a, b) < (:a, :b)`), because a row-value comparison is
        undefined the moment one side is NULL — and `created_at` is nullable on
        several of these tables.
        """
        if len(key) != len(self.columns):
            raise InvalidCursor("cursor does not match this ordering")

        # Term i: the first i columns are equal, and column i is strictly past.
        terms = []
        for i, column in enumerate(self.columns):
            equals = [_equal(self.columns[j], key[j]) for j in range(i)]
            terms.append(and_(*equals, _past(column, key[i], self.descending)))
        return or_(*terms)


def _read(row: Any, column: ColumnElement) -> Any:
    """The value of `column` on a result row, whether ORM object or tuple."""
    name = column.key or column.name
    if hasattr(row, name):
        return getattr(row, name)
    # A `select(A, B)` row: the mapped entity is somewhere in the tuple.
    for element in row:
        if hasattr(element, name):
            return getattr(element, name)
    raise AttributeError(f"cannot read {name!r} off a result row")


def _equal(column: ColumnElement, value: Any) -> ColumnElement:
    return column.is_(None) if value is None else column == value


def _past(column: ColumnElement, value: Any, descending: bool) -> ColumnElement:
    """Strictly beyond `value` in the scan direction, with NULLs last.

    NULL sorts after every value in both directions here, so:
      - from a non-null anchor, "past" is the smaller/larger values *and* NULL;
      - from a NULL anchor there is nothing further on this column at all —
        only the tiebreak columns can still separate two rows.
    """
    if value is None:
        return false()
    beyond = column < value if descending else column > value
    return or_(beyond, column.is_(None))


# ── The two calls an endpoint makes ───────────────────────────────────────


def seek(query: Select, order: Order, cursor: str | None) -> Select:
    """Apply the ordering, and the cursor if there is a usable one.

    A cursor that does not decode is treated as no cursor. It is a value out of
    a URL somebody may have truncated in a chat message, and refusing the whole
    request with a 422 would turn a mangled link into an error page rather than
    the first page of the list they were sent.
    """
    query = query.order_by(*order.clauses())
    if not cursor:
        return query
    try:
        return query.where(order.after(decode(cursor)))
    except InvalidCursor:
        return query


def split(rows: Sequence[Any], limit: int, order: Order) -> tuple[list[Any], str | None]:
    """Trim the lookahead row and mint the cursor that resumes after the page.

    Call the query with `limit + 1`: one row past the page is how we answer
    "is there a next page" without a second `COUNT(*)` over the whole table.
    """
    has_more = len(rows) > limit
    page = list(rows[:limit])
    if not has_more or not page:
        return page, None
    return page, encode(order.values(page[-1]))


def page_list(rows: Sequence[Any], *, limit: int, cursor: str | None = None) -> dict:
    """Page a list that was **computed in Python**, not fetched in order.

    A handful of these lists are rankings the database cannot produce: the
    bottle holders are grouped per rider/store pair and sorted by *deposit
    value* rather than count, the performance boards fold several aggregates
    together, and the drift report compares two sources row by row. The whole
    set has to exist in memory before it can be ordered at all.

    So keyset is the wrong tool here and an offset is the right one — the
    objection to OFFSET is that the database re-scans and that the window slides
    when rows shift underneath it, and neither applies to a list this process
    just built and is about to slice. The offset travels in the same opaque
    cursor as everywhere else, so the console pages all of these identically.

    Because the full set is already materialised, `total` is free and honest —
    unlike the SQL lists, where reporting one would mean a `COUNT(*)` over a
    growing table on every page view. Where a number is knowable this cheaply,
    the console should say it.
    """
    start = 0
    if cursor:
        try:
            decoded = decode(cursor)
            if len(decoded) == 1 and isinstance(decoded[0], int) and decoded[0] >= 0:
                start = decoded[0]
        except InvalidCursor:
            start = 0

    window = list(rows[start : start + limit])
    finish = start + len(window)
    return {
        "items": window,
        "next_cursor": encode([finish]) if finish < len(rows) else None,
        "total": len(rows),
    }


async def paginate(
    session,
    query: Select,
    *,
    order: Order,
    limit: int,
    cursor: str | None = None,
    scalars: bool = True,
    serialise: Callable[[Any], Any] | None = None,
) -> dict:
    """The whole thing, for the endpoints that need no post-processing.

    Returns the list envelope every admin list shares — `items` plus
    `next_cursor`, which is `null` on the last page and is the only thing that
    tells the console whether to enable its Next button.
    """
    result = await session.execute(seek(query, order, cursor).limit(limit + 1))
    rows: Iterable[Any] = result.scalars().all() if scalars else result.all()
    page, next_cursor = split(list(rows), limit, order)
    return {
        "items": [serialise(row) for row in page] if serialise else page,
        "next_cursor": next_cursor,
    }
