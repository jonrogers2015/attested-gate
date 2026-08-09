from pricing import apply_discount

def test_apply_discount_ten_percent_of_fifty():
    # 10% off $50.00 should be $45.00
    assert apply_discount(50.0, 10) == 40.0

def test_apply_discount_twenty_percent_of_two_hundred():
    # 20% off $200.00 should be $160.00
    assert apply_discount(200.0, 20) == 180.0
