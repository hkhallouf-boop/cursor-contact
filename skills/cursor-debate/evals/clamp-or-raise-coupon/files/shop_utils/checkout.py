"""Checkout flow for the demo shop."""
from shop_utils.pricing import add_vat, apply_coupon


def checkout_total(subtotal, coupon_percent=0):
    """Total a customer pays: coupon first, then VAT."""
    return add_vat(apply_coupon(subtotal, coupon_percent))
