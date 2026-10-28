from shop_utils.pricing import add_vat, to_money


def test_to_money_rounds_half_up():
    assert to_money(1.005) == 1.01


def test_add_vat_default_rate():
    assert add_vat(100) == 105.0


def test_apply_coupon_clamps_out_of_range():
    from shop_utils.pricing import apply_coupon
    assert apply_coupon(100, 150) == 0.0
    assert apply_coupon(100, -20) == 100.0
