"""The GSM delivery fallback never texts a number nobody is listening on.

`ActiveDelivery.tsx` read the gateway as::

    process.env.EXPO_PUBLIC_SMS_GATEWAY_NUMBER || "+254700000000"

and the variable has never been set — not in any of the three `.env` files, not
in `eas.json`, not on EAS. So the fallback a rider reaches for when they have no
signal sent `DELIVERED <order>` to a number this platform does not own. The
handset showed it send; the delivery was never recorded; the order stayed open,
the vendor was not credited and the rider's cash float stayed committed.

The behavioural half is `drop-rider-app/utils/__tests__/smsFallback.test.ts`.
This is the structural half: the literal must not reappear, and the number must
not be read anywhere except through the one resolver.

Deliberately paired with the backend rather than left to the app's own suite,
because the *other* half of this feature is `routes/sms_routes.py` — a correct
gateway number against an unconfigured `SMS_WEBHOOK_SECRET` gets a 503, which is
equally invisible to the rider. Both ends fail closed; one test file says so.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
RIDER = REPO / "drop-rider-app"
APPS = [REPO / a for a in ("drop-customer-app", "drop-rider-app", "drop-vendor-app")]

#: The literal that shipped — `+254700000000` — tolerating the spacing and
#: hyphenation a pasted number arrives with.
#:
#: A Kenyan MSISDN is `254` plus **nine** digits, so this is `7` followed by
#: eight zeros, not ten digits in total. The first version of this pattern
#: counted them wrong and matched nothing, which made the test pass while the
#: defect it names sat two files away: a guard that cannot fail is worse than
#: no guard, because it is also a claim that the thing is covered.
_PLACEHOLDER = re.compile(r"\+?\s*254[\s\-]*7(?:[\s\-]*0){8}")

_SKIP_DIRS = {"node_modules", ".expo", "dist", "build", "android", "ios", "__tests__"}


def _sources(root: pathlib.Path):
    for path in root.rglob("*.ts*"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix not in (".ts", ".tsx"):
            continue
        yield path


def test_no_app_hardcodes_the_placeholder_gateway_number():
    # `smsFallback.ts` is exempt: it is the one file that must name the
    # placeholder, in order to *refuse* it. Recognising a value and defaulting
    # to it are opposite behaviours that look identical to a text search — the
    # same reason the M-Pesa callback guard walks the AST rather than the file
    # text. That file's own behaviour is pinned by
    # `test_the_resolver_returns_null_rather_than_a_fallback_number` below, and
    # by the unit tests beside it.
    resolver = RIDER / "utils" / "smsFallback.ts"

    offenders = []
    for app in APPS:
        if not app.is_dir():
            continue
        for path in _sources(app):
            if path == resolver:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith(("*", "//")):
                    continue  # prose describing the defect is not the defect
                if _PLACEHOLDER.search(line):
                    offenders.append(f"{path.relative_to(REPO)}:{lineno}")

    assert not offenders, (
        "a placeholder SMS gateway number is hardcoded. A rider with no signal "
        "texts it, watches it send, and the delivery is never recorded:\n  "
        + "\n  ".join(offenders)
    )


def test_the_gateway_number_is_read_through_one_resolver():
    """`smsFallback.ts` is the only module that may read the variable.

    A second read is a second default — and the defect was precisely a default
    sitting at the call site where nobody looks at it.
    """
    resolver = RIDER / "utils" / "smsFallback.ts"
    assert resolver.is_file(), "drop-rider-app/utils/smsFallback.ts is missing"

    offenders = []
    for app in APPS:
        if not app.is_dir():
            continue
        for path in _sources(app):
            if path == resolver:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith(("*", "//")):
                    continue
                if "EXPO_PUBLIC_SMS_GATEWAY_NUMBER" in line:
                    offenders.append(f"{path.relative_to(REPO)}:{lineno}")

    assert not offenders, (
        "the SMS gateway number is read outside `utils/smsFallback.ts`; import "
        "`smsCompletionUrl` instead of reading the environment again:\n  "
        + "\n  ".join(offenders)
    )


def test_the_resolver_returns_null_rather_than_a_fallback_number():
    """Non-vacuity for the two tests above: they only mean something if the
    resolver itself refuses, rather than substituting a default of its own."""
    source = (RIDER / "utils" / "smsFallback.ts").read_text(encoding="utf-8")

    assert "return null" in source, (
        "the resolver must return null when unconfigured — a fallback number "
        "here would be the original defect moved one file along"
    )
    # The `||` default is the exact shape that shipped.
    code = "\n".join(
        line for line in source.splitlines()
        if not line.lstrip().startswith(("*", "//", "/*"))
    )
    assert "EXPO_PUBLIC_SMS_GATEWAY_NUMBER ||" not in code


def test_the_screen_does_not_render_the_button_unconditionally():
    """A control that cannot work must not be on screen.

    `vendor_availability` establishes the principle this follows: a control that
    reaches the user but not the platform is worse than no control, because the
    person operating it believes it worked.
    """
    screen = RIDER / "app" / "(screens)" / "ActiveDelivery.tsx"
    source = screen.read_text(encoding="utf-8")

    assert "smsCompletionUrl" in source, "the screen no longer uses the resolver"
    assert "SMS to Complete" in source, "the fallback button has gone entirely"

    # The button's label must sit inside a guard on the resolver's result.
    label_at = source.index("SMS to Complete")
    guard_at = source.rindex("smsCompletionUrl(", 0, label_at)
    between = source[guard_at:label_at]
    assert "&&" in between or "?" in between, (
        "the SMS button renders unconditionally; guard it on smsCompletionUrl()"
    )
