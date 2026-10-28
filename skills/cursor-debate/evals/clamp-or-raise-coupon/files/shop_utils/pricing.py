"""Price helpers for the demo shop."""
from decimal import ROUND_HALF_UP, Decimal


def to_money(value):
    """Round a number to 2 decimals, half-up, as a float."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def add_vat(total, rate=0.05):
    """Return total including VAT at the given rate."""
    return to_money(total * (1 + rate))


def apply_coupon(total, percent):
    """Return total after a percent discount; percent is clamped to 0-100."""
    pct = min(max(Decimal(str(percent)), Decimal(0)), Decimal(100))
    return to_money(Decimal(str(total)) * (Decimal(100) - pct) / Decimal(100))
