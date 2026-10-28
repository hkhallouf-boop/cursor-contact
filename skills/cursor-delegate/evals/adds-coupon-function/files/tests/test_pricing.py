from shop_utils.pricing import add_vat, to_money


def test_to_money_rounds_half_up():
    assert to_money(1.005) == 1.01


def test_add_vat_default_rate():
    assert add_vat(100) == 105.0
