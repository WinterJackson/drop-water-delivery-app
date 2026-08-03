"""Hiding a review must actually change what people see.

The failure this guards against is a moderation feature that only moderates the
list: the review disappears from the page and stays in the target's average, so
the one-star nobody can read still holds the store at 2.1. Every public read path
therefore has to filter on `hidden_at`, and there are five of them across four
modules — a number that only goes up, which is why this is a structural test and
not five hand-written ones.
"""
import ast
import pathlib

import pytest

from services import admin_review_service as svc

BACKEND = pathlib.Path(__file__).resolve().parents[1]

#: Every place a review is read for somebody outside the console. Each must
#: filter on `hidden_at`; `order_service` is the deliberate exception below.
PUBLIC_READ_PATHS = (
    "routes/review_routes.py",
    "services/review_service.py",
    "services/deliverer_service.py",
    "services/admin_analytics_service.py",
)


def _source(relative: str) -> str:
    return (BACKEND / relative).read_text()


def _review_queries(source: str) -> list[str]:
    """Every statement in `source` that builds a query over `reviews`.

    Per statement rather than per file: `review_service` has two aggregations
    over this table, and a file-level "does the word appear anywhere" check
    passes with one of them still leaking hidden rows.
    """
    tree = ast.parse(source)
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.Expr, ast.Return, ast.AnnAssign, ast.With)):
            continue
        segment = ast.get_source_segment(source, node) or ""
        if "select(" in segment and "Review" in segment:
            out.append(segment)
    return out


@pytest.mark.parametrize("path", PUBLIC_READ_PATHS)
def test_every_public_review_read_filters_hidden(path):
    source = _source(path)
    queries = _review_queries(source)
    assert queries, f"{path} no longer queries reviews — update this test"

    for query in queries:
        # The edit lookup in `create_review` must see hidden rows: that is how a
        # resubmit is recognised and refused rather than silently folded in.
        if "customer_clerk_id ==" in query:
            continue
        assert "hidden_at" in query, (
            f"{path} reads reviews without filtering hidden_at:\n\n{query}\n\n"
            "A moderated review that still counts is moderation theatre."
        )


def test_is_rated_deliberately_does_not_filter_hidden():
    """The one read that must *not* filter.

    `uq_customer_order_target_review` still holds after a review is hidden, so
    treating the order as unrated would show the customer a "Rate delivery"
    button that can only fail — and, if it did work, would be a way round the
    takedown.
    """
    source = _source("services/order_service.py")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        body = ast.get_source_segment(source, node) or ""
        if "Review.order_id" not in body:
            continue
        assert "hidden_at" not in body, (
            "is_rated must not filter hidden reviews — the unique constraint "
            "still holds, so the customer cannot leave another one."
        )
        return

    pytest.fail("no is_rated batch lookup found in order_service")


def test_a_resubmitted_hidden_review_is_refused_rather_than_folded_back_in():
    """Otherwise a customer edits their way past a takedown, and the rating moves
    for a review nobody can see."""
    source = _source("services/review_service.py")
    assert "existing.hidden_at is not None" in source
    assert "status_code=409" in source


def test_the_rating_rebuild_excludes_hidden_reviews():
    """`set_hidden` rebuilding from a query that ignores `hidden_at` would put the
    review straight back into the average it was just taken out of."""
    source = _source("services/admin_review_service.py")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_rebuild_target_rating":
            body = ast.get_source_segment(source, node) or ""
            assert "hidden_at" in body
            return

    pytest.fail("_rebuild_target_rating not found")


# ── the flag heuristics ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "comment",
    [
        "Call me on 0712 345 678",
        "reach me at +254 712 345 678 please",
        "email someone@example.com",
        "my number is 0712345678",
    ],
)
def test_contact_details_are_found(comment):
    """A phone number in a public review is a safety problem before it is a
    moderation one. The pattern is deliberately loose."""
    assert svc._has_contact(comment) is True


@pytest.mark.parametrize(
    "comment",
    [
        "Great service, arrived in 20 minutes",
        None,
        "",
        "5 stars",
        "Ordered 3 bottles, got 2",
    ],
)
def test_ordinary_comments_are_not_flagged_as_contact_details(comment):
    """A false positive costs two seconds, but a screen that is 90% noise gets
    cleared without being read."""
    assert svc._has_contact(comment) is False


def test_a_low_rating_with_no_comment_is_not_worth_reading():
    """There is nothing to moderate in a bare one-star. Putting it in the queue
    only makes the queue longer."""

    class _Review:
        rating = 1.0
        comment = None

    assert svc._flags(_Review()) == []


def test_a_low_rating_with_a_comment_is_worth_reading():
    class _Review:
        rating = 1.0
        comment = "Rider never showed up"

    assert svc._flags(_Review()) == ["low_rating_with_comment"]
