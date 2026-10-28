from shop_utils.listing import paginate


def test_first_page():
    assert paginate(list(range(50)), 1, 10) == list(range(10))
