"""The frozen order payload carried on a notification.

This is **evidence**. It is written into `notification_model.data` at the moment
an order is offered, and it is what a dispute is settled from weeks later, after
the products have been repriced and the vendor has been renamed. Nothing here
may be re-derived from today's rows.

Money is therefore a decimal string, like everywhere else money leaves this API
(`utils.money.money_str`). It used to be `float(...)`, which meant the one
record kept specifically to be argued over was the one record stored at binary
floating-point precision.
"""
import logging

from utils.money import money_str

logger = logging.getLogger(__name__)


def _decimal_or_none(value) -> str | None:
    """A non-money decimal — weight, capacity — as a string, or `None`.

    `None` is preserved: a product with no recorded weight and a product
    weighing nothing are different facts, and a wholesale MOQ check reads this.
    """
    return None if value is None else str(value)


def build_order_snapshot(order, items, vendor, role="rider") -> dict:
    """Build a frozen JSONB payload for `notification_model.data`.

    Raises nothing: a notification must still go out if one product row is
    malformed, because the alternative is a vendor never hearing about an order.
    But it returns a snapshot with the fields it *could* build rather than the
    empty dict it used to — an empty payload renders as a blank card, which
    tells the recipient less than a partial one and tells the logs the same.
    """
    snapshot: dict = {"order_id": str(order.id)}
    try:
        line_items = [
            {
                "name": item.product.name if item.product else "Unknown Product",
                "quantity": item.quantity,
                "price": money_str(item.price),
                "subtotal": money_str(item.Subtotal),
                "weight_kg": _decimal_or_none(item.product.weight_kg if item.product else None),
                "capacity": _decimal_or_none(item.product.capacity if item.product else None),
                "unit": item.product.unit if item.product else "units",
            }
            for item in items
        ]

        snapshot.update(
            {
                "vendor_name": vendor.business_name,
                "vendor_type": (
                    vendor.vendor_type.value
                    if hasattr(vendor.vendor_type, "value")
                    else vendor.vendor_type
                ),
                "total_amount": money_str(order.total_amount),
                "delivery_fee": money_str(order.delivery_fee),
                "distance_km": _decimal_or_none(order.distance_km),
                "vehicle_class": order.vehicle_class,
                "delivery_type": order.delivery_type or "quick_swap",
                "total_quantity": sum(i.quantity for i in items),
                "total_weight_kg": str(
                    sum(
                        (item.product.weight_kg or 0) * item.quantity
                        for item in items
                        if item.product
                    )
                ),
                "line_items": line_items,
            }
        )

        # The customer's number reaches the store, which has to call about a
        # gate code or a missing flat. The rider gets it from the order itself
        # once they have accepted, not from an offer they may never take.
        if role == "vendor":
            snapshot["customer_phone"] = order.phone

        return snapshot
    except Exception:
        logger.exception("Failed to build order snapshot for order %s", order.id)
        return snapshot
