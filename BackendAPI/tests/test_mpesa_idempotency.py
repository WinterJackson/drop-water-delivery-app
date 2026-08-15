"""
Safaricom retries, the client polls, and both must land on the same books.

Every M-Pesa callback arrives more than once. Safaricom re-POSTs until it gets a
200, and for order payments a second, independent settler runs in parallel: the
client polls `/confirm_payment` every few seconds while the customer watches a
spinner. So "did this already happen?" is the first question every one of these
handlers has to answer, and it has to answer it under a lock.

Three of the four got it right — the wallet top-up, the B2C result and the
reversal all filter on the state they are leaving and take the row `FOR UPDATE`.
The order callback got the *side effects* right, because they live inside
`update_orders_payment_status_by_checkout_id`, and everything around them wrong:

* the poll usually wins, so the status update returned early — **before its own
  `commit()`** — and the `Payment` audit row the callback had just added was
  discarded. The payments table was missing rows for the ordinary case.
* the confirmation email and the cart purge ran on every retry.
* `amount` was written from the raw JSON number onto a `NUMERIC` column, and
  `Decimal` was not even imported in that module — the fix for the first defect
  would have been a `NameError` on the payment path.
"""
import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def _function(module: str, name: str):
    source = (BACKEND / module).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    pytest.fail(f"{name} not found in {module}")


# ── Every callback asks "already done?" before it does anything ───────────


def test_the_order_callback_short_circuits_a_replay():
    body = _function("routes/cart_routes.py", "mpesa_callback")
    assert 'existing.status == "paid"' in body, (
        "a replayed order callback must return before re-recording anything"
    )


def test_the_order_callback_commits_its_audit_row_itself():
    """It used to ride on `update_orders_payment_status_by_checkout_id`'s commit,
    which never runs when the poll settled the order first."""
    body = _function("routes/cart_routes.py", "mpesa_callback")
    add_index = body.index("Payment(")
    commit_index = body.index("await db.commit()", add_index)
    transition_index = body.index("update_orders_payment_status_by_checkout_id", add_index)
    assert commit_index < transition_index, (
        "the Payment row must be committed before the status transition, which "
        "returns early — and before its own commit — on an already-settled order"
    )


def test_the_confirmation_email_is_not_re_sent_on_a_retry():
    body = _function("routes/cart_routes.py", "mpesa_callback")
    assert "settled_here" in body, (
        "the email and cart purge must run only for the call that actually "
        "settled the order, not once per Safaricom retry"
    )
    assert body.index("settled_here") < body.index("send_order_confirmation")


def test_the_topup_callback_locks_and_checks_state():
    body = _function("services/wallet_service.py", "handle_mpesa_topup_callback")
    assert "with_for_update()" in body
    assert "TransactionStatus.pending" in body


def test_the_b2c_result_only_settles_a_processing_transaction():
    """A second refund on a retried failure callback would mint money."""
    body = _function("routes/payout_routes.py", "_reconcile_wallet_transaction")
    assert "TransactionStatus.processing" in body
    assert "with_for_update()" in body


def test_the_reversal_result_does_not_re_notify_on_a_retry():
    """The reversal happens on Safaricom's side, so a retry cannot refund twice
    — but the success branch tells the customer their money is back, and it did
    so once per retry."""
    body = _function("routes/refund_routes.py", "reversal_result_callback")
    assert "with_for_update()" in body
    assert 'matched_payment.status in ("refunded", "refund_failed")' in body
    # Anchored on a call, not on prose: the comment above that check quotes the
    # notification's own title, so matching text would compare against itself.
    assert body.index("matched_payment.status in") < body.index("create_notification(")


def test_the_order_status_transition_is_the_one_settler():
    body = _function("services/order_service.py", "update_orders_payment_status_by_checkout_id")
    assert "with_for_update()" in body
    assert 'o.payment_status == "paid"' in body


# ── Money on the way in is a Decimal ──────────────────────────────────────


def test_no_callback_writes_a_payment_amount_as_a_float():
    """`Payment.amount` is NUMERIC. A float from `json()` is the same defect the
    rest of the platform avoids, with nothing to grep for."""
    body = _function("routes/cart_routes.py", "mpesa_callback")
    tree = ast.parse(ast.unparse(ast.parse(body)))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.keyword) and node.arg == "amount"):
            continue
        rendered = ast.unparse(node.value)
        assert "float(" not in rendered, f"money written as a float: amount={rendered}"
        assert "Decimal" in rendered, f"expected a Decimal, got amount={rendered}"


def test_decimal_is_actually_imported_where_it_is_used():
    """It was not. The obvious fix for the float would have raised NameError on
    the payment path — caught by the handler's own `except`, logged, and
    answered 400, which makes Safaricom retry for ever."""
    source = (BACKEND / "routes" / "cart_routes.py").read_text()
    tree = ast.parse(source)
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "Decimal" in imported


# ── The unique constraints that make the keys real ────────────────────────


def test_a_receipt_can_only_be_booked_once():
    from models.payment_model import Payment

    indexes = {i.name: i for i in Payment.__table__.indexes}
    receipt = indexes.get("uq_payments_mpesa_receipt")
    assert receipt is not None and receipt.unique, (
        "the M-Pesa receipt is the collection's identity; without a unique index "
        "a replayed callback can book the same collection twice"
    )
    checkout = Payment.__table__.c.checkout_request_id
    assert checkout.unique, "checkout_request_id is the callback's idempotency key"


# ── Amounts Safaricom will actually move ──────────────────────────────────


def test_whole_shillings_refuses_a_fraction_rather_than_truncating():
    from services.payment_service import MpesaError, whole_shillings

    assert whole_shillings("1000", label="Withdrawal") == 1000
    for bad in ("984.50", "0", "-5"):
        with pytest.raises(MpesaError):
            whole_shillings(bad, label="Withdrawal")


def test_the_daraja_base_url_is_configurable():
    """Sandbox today, production later, without a code change."""
    source = (BACKEND / "services" / "payment_service.py").read_text()
    assert 'os.getenv("MPESA_BASE_URL"' in source
    tree = ast.parse(source)
    hardcoded = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and "safaricom.co.ke" in n.value
        and n.value != "https://sandbox.safaricom.co.ke"
    ]
    assert hardcoded == [], f"Daraja hosts must come from MPESA_BASE_URL: {hardcoded}"


def test_the_stk_timestamp_is_east_african_time():
    """Safaricom validates the timestamp against its own clock, and the password
    is the base64 of shortcode+passkey+timestamp — so both come from one instant
    in EAT. A container's naive `now()` is UTC, three hours behind."""
    source = (BACKEND / "services" / "payment_service.py").read_text()
    body = _function("services/payment_service.py", "generate_password")
    assert "EAT" in body
    assert "datetime.timedelta(hours=3)" in source


def test_the_access_token_is_cached_behind_a_single_flight_lock():
    """It was minted per call — two round trips per payment — and a throttled
    mint returned None, which went out as the header `Bearer None`."""
    body = _function("services/payment_service.py", "get_access_token")
    assert "_token_lock" in body
    assert "_token_cache" in body
    assert "raise MpesaError" in body


# ── Callbacks are authenticated, and fail closed ──────────────────────────


def test_every_mpesa_callback_goes_through_the_shared_guard():
    """These mark orders paid, settle wallets and refund debited balances with
    no authenticated user behind them."""
    callbacks = {
        ("routes/cart_routes.py", "mpesa_callback"),
        ("routes/wallet_routes.py", "mpesa_topup_callback"),
        ("routes/payout_routes.py", "b2c_result_callback"),
    }
    for module, name in callbacks:
        body = _function(module, name)
        assert "reject_mpesa_callback" in body, f"{module}:{name} is unguarded"


def test_the_guard_fails_closed_without_a_secret():
    body = _function("services/payment_service.py", "reject_mpesa_callback")
    assert "hmac.compare_digest" in body, "the secret must be compared in constant time"
    assert "status_code=503" in body, (
        "an unset MPESA_CALLBACK_SECRET outside development must refuse, not "
        "silently disable the check"
    )


# ── The dispatch a paid order depends on must survive to run ──────────────


def test_the_post_payment_dispatch_keeps_a_strong_reference():
    """`asyncio` keeps only a *weak* reference to a task.

    A task whose return value is discarded can be garbage collected part-way
    through, and this is the task that offers a just-paid order to riders. The
    failure is silent from every angle — the customer has paid, the order sits
    `unassigned`, and no rider was ever told — and it is likeliest exactly when
    it costs most, because GC pressure rises with load.

    `dispatch_background` holds the reference until the task finishes. It is
    what the rest of the platform already uses for detached work.
    """
    body = _function("services/order_service.py", "update_orders_payment_status_by_checkout_id")
    assert "dispatch_background(" in body
    tree = ast.parse(ast.unparse(ast.parse(body)))
    bare = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and ast.unparse(node.value).startswith("asyncio.create_task(")
    ]
    assert bare == [], f"detached task with no reference held: {bare}"


# ── Money keeps its type all the way out to Daraja ────────────────────────


def test_no_daraja_initiator_takes_a_float():
    """`MoneyIn`, not `float`.

    Every one of these converted safely — each does `Decimal(str(amount))` at
    its first line, and `whole_shillings` refuses a fraction rather than
    truncating one — so this was latent rather than live. It is still the wrong
    declaration: the next person reads the signature, not the first line of the
    body, and a `float` annotation on a money argument is how the platform's
    other float defects got in.
    """
    for module, function in (
        ("services/payment_service.py", "initiate_b2c_payout"),
        ("services/payment_service.py", "initiate_mpesa_reversal"),
        ("services/wallet_service.py", "initiate_wallet_topup"),
        ("services/wallet_service.py", "initiate_wallet_withdrawal"),
    ):
        source = (BACKEND / module).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef) or node.name != function:
                continue
            for arg in node.args.args + node.args.kwonlyargs:
                if arg.arg != "amount":
                    continue
                rendered = ast.unparse(arg.annotation) if arg.annotation else "<none>"
                assert rendered != "float", f"{module}:{function} declares amount as a float"
            break
        else:
            pytest.fail(f"{function} not found in {module}")


def test_the_refund_does_not_downgrade_the_charged_amount():
    """`payment.amount` is the NUMERIC the customer was charged. Casting it to
    float on the way out can only lose information about the figure being given
    back — and `whole_shillings` re-derives a Decimal from it immediately."""
    body = _function("services/refund_service.py", "process_single_refund")
    assert "float(payment.amount)" not in body
