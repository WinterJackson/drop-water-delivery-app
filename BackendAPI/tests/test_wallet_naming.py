"""The wallet is called a wallet, and the balance card does not overstate itself.

Two rules, one subject: the money the platform holds for a customer.

**The word.** Four surfaces called that balance "Drop Cashback" — the Profile
banner, the home pill, the cart's discount line and the repeat-order breakdown.
It is not cashback. `loyalty_cashback_per_delivery` is a real setting with a
real credit path in `deliverer_service`, and it is guarded `if cashback > 0`
against a default of **0** that `b2f9c14e7a35` retired it to, so no order has
ever earned any. What is actually in there is the customer's own money coming
back: an M-Pesa top-up they made, a refund on an order that was cancelled, or a
bottle deposit they paid and got back by handing the bottle over. Telling
somebody a refund is a reward is not a naming quibble — it is the wrong fact
about whose money it is, on the screen where they decide whether to trust the
number.

**The overstatement.** The same misdescription one layer down: the wallet card
labelled the whole figure "Available Balance". A returned deposit is spendable
on water and cannot be withdrawn as cash — that is `restricted_customer_credit`,
and it is why `assert_withdrawable` refuses. For a customer who has handed
bottles back, most of the balance is that. The server has served
`wallet_not_withdrawable` on the deposit summary since the day the summary
existed, precisely so the condition could be stated rather than discovered at
the refusal, and the balance card did not read it.

Neither rule is premised on cashback staying switched off. If it is ever
switched back on it credits the same wallet, and the wallet is still a wallet.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")

WALLET_SCREEN = ROOT / "drop-customer-app" / "app" / "(screens)" / "BottleWallet.tsx"

_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _without_comments(src: str) -> str:
    """Source with comments blanked out, line numbering preserved.

    A comment may say "cashback" as much as it likes — several of them exist to
    record why the word was removed, and a guard that forbade the explanation
    along with the defect would be deleted by the first person it annoyed.
    """
    src = _BLOCK_COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), src)
    return _LINE_COMMENT.sub("", src)


def _app_sources(app: str) -> list[pathlib.Path]:
    base = ROOT / app
    out: list[pathlib.Path] = []
    for sub in ("app", "components", "constants", "hooks", "utils"):
        d = base / sub
        if d.is_dir():
            out += [p for p in d.rglob("*.ts*") if "__tests__" not in p.parts]
    return out


@pytest.mark.parametrize("app", APPS)
def test_no_app_shows_the_customer_the_word_cashback(app):
    offenders = []
    for path in _app_sources(app):
        for lineno, line in enumerate(_without_comments(path.read_text()).splitlines(), 1):
            if re.search(r"cash\s?back", line, re.I):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")

    assert not offenders, (
        "This balance is a wallet, not cashback. `loyalty_cashback_per_delivery` "
        "defaults to 0 and is credited only `if cashback > 0`, so nothing has "
        "earned any; the balance is the customer's own top-up, a refund, or a "
        "returned bottle deposit — part of which cannot even be withdrawn.\n  "
        + "\n  ".join(offenders)
    )


def test_the_guard_can_see_the_word_it_forbids():
    """Non-vacuity, without touching a shipped file.

    Every test above passes on a tree where the word is simply absent, which is
    also what it looks like when the regex is broken.
    """
    sample = 'const label = "Drop Cashback";  // historic: was Drop Cashback\n'
    stripped = _without_comments(sample)
    hits = [ln for ln in stripped.splitlines() if re.search(r"cash\s?back", ln, re.I)]
    assert len(hits) == 1, "the comment stripper or the pattern has stopped working"


def test_the_withdrawable_figure_is_derived_and_shown():
    """Reading the field is not the rule; showing the customer the split is.

    An earlier version of this test asserted only that
    `wallet_not_withdrawable` appeared somewhere in the file — and it did,
    before any of this, because the figure was already being handed to
    `BottleCollectionCard` further down the screen. It passed on the very tree
    it exists to catch. The rule is that the balance is *split*: derived from
    the server's two figures, and rendered.
    """
    src = _without_comments(WALLET_SCREEN.read_text())

    assert "wallet_not_withdrawable" in src, (
        "BottleWallet must read the restricted portion the server already "
        "serves, or the balance card claims money is available that "
        "`assert_withdrawable` will refuse."
    )
    assert "subtractMoney(" in src, (
        "withdrawable = balance - restricted, and that subtraction goes "
        "through utils/money like every other money operation"
    )

    derived = re.search(
        r"const\s+(\w+)\s*=\s*\n?[^;]*?subtractMoney\(", src, re.S
    )
    assert derived, "the subtraction must be bound to a name the screen can render"
    name = derived.group(1)
    assert re.search(rf"formatMoney(?:Short)?\(\s*{name}\b", src), (
        f"`{name}` is computed and never rendered — the customer still cannot "
        "see what they can actually withdraw"
    )


def test_the_withdrawal_form_states_what_can_be_withdrawn():
    """The refusal must not be the first time the customer hears it.

    `assert_withdrawable` refuses with a clear sentence, so nothing breaks — but
    a form that lets somebody type a figure it already knows is impossible is a
    dead end they walk into.
    """
    src = _without_comments(WALLET_SCREEN.read_text())
    modal = src.find("isWithdrawModalVisible}")
    assert modal != -1, "could not locate the withdrawal modal"
    assert re.search(r"withdrawable", src[modal:]), (
        "the withdrawal form does not mention the withdrawable figure"
    )


def test_the_withdrawable_figure_is_not_derived_in_floats():
    src = _without_comments(WALLET_SCREEN.read_text())
    bad = re.findall(r"Number\([^)]*(?:balance|withdrawable)[^)]*\)", src, re.I)
    assert not bad, f"money parsed to a float on the wallet screen: {bad}"


def test_the_card_no_longer_calls_the_whole_balance_available():
    src = _without_comments(WALLET_SCREEN.read_text())
    assert "Available Balance" not in src, (
        "The headline figure includes returned deposit, which is spendable but "
        "not withdrawable. Name it as the wallet balance and split it."
    )
