"""No app invents a rating.

The same store, at the same moment, showed `0.0` in the customer directory and
`4.8` on its own page — reproduced on a handset against production. Five
screens each answered "what do I show when there is no rating?" separately and
four answered it with a literal:

    VendorDirectory   Number(item.rating).toFixed(1)          -> "0.0", "NaN"
    Search            vendor.rating?.toFixed(1) || "5.0"      -> invented
    vendor/[id]       Number(VendorDetails?.rating) || "4.8"  -> invented
    FavouritesList    vendor?.rating || "4.5" + " • Verified" -> invented, twice

The favourites card's static "• Verified" is gone with it: the storefront
schema deliberately withholds `verification_status`, so the badge asserted a
moderation state nothing had sent. There is no guard for that one — a
text match on "Verified" fires on the vendor badge that reads a real
`status === "verified"` and on both email-verification screens, and a test
that fails on correct code as loudly as on a regression is worse than none.

A rating is a trust signal, so a fabricated one is not cosmetic. `||` makes it
worse than it looks: `0` is falsy, so the worst-rated store on the platform
advertised 4.8.

The cause was that `rating_count` never reached any app, although both
`Vendor` and `Deliverer` carry it and both model comments say the apps need it.
Without a count, `Vendor.rating` of 0 and `Deliverer.rating` of 5.0 — the
documented starting values in `review_service._DEFAULT_RATING` — are
indistinguishable from earned scores, so every screen guessed.

`utils/rating.ts` is the one answer now. This guard is static and runs over all
three apps, the same way `test_inline_money_math.py` does for money.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
APPS = ("drop-customer-app", "drop-vendor-app", "drop-rider-app")

#: A rating literal: a quoted number with one decimal, or a bare 0-5 used as a
#: rating fallback, on a line that is also talking about a rating.
_FALLBACK = re.compile(r"""rating[^\n]*?(\?\?|\|\|)\s*(["'`]?\d(\.\d+)?["'`]?)""", re.I)

#: `toFixed` straight off a rating, which is what renders "0.0" for an unrated
#: store and the string "NaN" when the field is absent altogether.
_RAW_TOFIXED = re.compile(r"""(?<!average_)rating\s*\)?\s*\??\.\s*toFixed""", re.I)


def _sources(app: str):
    for folder in ("app", "components", "hooks"):
        base = ROOT / app / folder
        if not base.exists():
            continue
        for path in base.rglob("*.tsx"):
            yield path
        for path in base.rglob("*.ts"):
            yield path


def _offences(app: str, pattern: re.Pattern) -> list[str]:
    found = []
    for path in _sources(app):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*")):
                continue
            if pattern.search(line):
                found.append(f"{path.relative_to(ROOT)}:{number}: {stripped[:110]}")
    return found


@pytest.mark.parametrize("app", APPS)
def test_no_app_falls_back_to_an_invented_rating(app):
    offences = _offences(app, _FALLBACK)
    assert not offences, (
        "A rating fallback literal is a fabricated trust signal. Use "
        "`ratingScore(rating, count)` from utils/rating.ts and render "
        "UNRATED_LABEL when it returns null:\n  " + "\n  ".join(offences)
    )


@pytest.mark.parametrize("app", APPS)
def test_no_app_formats_a_rating_by_hand(app):
    offences = _offences(app, _RAW_TOFIXED)
    assert not offences, (
        "`rating.toFixed(1)` renders an unrated target as a real score, and "
        "renders the string 'NaN' when the field is absent. Use "
        "`ratingScore(rating, count)`:\n  " + "\n  ".join(offences)
    )


@pytest.mark.parametrize("app", APPS)
def test_every_app_has_the_one_helper(app):
    helper = ROOT / app / "utils" / "rating.ts"
    assert helper.exists(), f"{app} has no utils/rating.ts"
    body = helper.read_text()
    for name in ("ratingScore", "UNRATED_LABEL", "filledStars"):
        assert name in body, f"{app}/utils/rating.ts no longer exports {name}"


def test_the_count_reaches_every_app_that_shows_a_rating():
    """A rating without its count is what forced every screen to guess."""
    schemas = ROOT / "BackendAPI" / "schemas"
    for name in ("vendor_schemas.py", "product_schemas.py", "deliverer_schemas.py"):
        body = (schemas / name).read_text()
        assert "rating_count" in body, (
            f"{name} sends a rating without its count, so an app cannot tell an "
            "unrated target from a badly rated one."
        )
