"""Offset paging that returns each row exactly once.

`LIMIT n OFFSET m` is only meaningful over a *total* order. SQL guarantees
nothing about rows the ``ORDER BY`` cannot tell apart, so a query ordered by a
column with ties — a discount percentage, a product name, a timestamp with
one-second resolution, a full-text rank — is free to return them in a different
sequence on every execution. Two executions is exactly what paging is: page 1
and page 2 are separate statements, minutes apart, and Postgres will happily
answer them with different plans. When it does, a row that sat at position 20
under one plan and 21 under the other is either **served twice or skipped
entirely**, and nothing anywhere reports an error.

It stays invisible in development because a small table is read with a single
sort node and comes back in insertion order by accident. It appears in
production, on the pages nobody looks at, as a list with a duplicate near every
page boundary and a row that is simply not there.

The fix is to make the order total by appending the primary key, which is what
`stable` does. Every ``.offset(...)`` in this codebase orders through it.

    query.order_by(*stable(Order.created_at.desc(), key=Order.id))

The tiebreaker's *direction* carries no meaning — a UUID sorts arbitrarily. Only
its determinism matters, so it is always descending and never a caller's choice.

What this does **not** fix, and cannot: offset paging measures from the top of
the result, so a row inserted above the window while somebody is reading shifts
everything down by one and page 2 re-serves the last row of page 1. That is a
property of offset paging rather than a defect in the order, and the clients
handle it by keying on the row id when they flatten pages — see `utils/paging.ts`
in each app. Feeds where that matters most (notifications, orders) are the ones
the apps de-duplicate.
"""

from sqlalchemy.sql import ColumnElement


def stable(*order_by: ColumnElement, key: ColumnElement) -> tuple[ColumnElement, ...]:
    """`order_by` clauses with a unique tiebreaker appended.

    `key` is the table's primary key — the one column that can never tie. Pass
    the key of the table the rows are *selected from*, not one of a joined table:
    a join's key is unique per joined row, which is only the same thing when the
    join is one-to-one.
    """
    return (*order_by, key.desc())
