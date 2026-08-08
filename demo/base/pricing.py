def apply_discount(price: float, percent: float) -> float:
    """Apply a percentage discount to a price.

    BUG: subtracts the raw percent instead of percent/100 of price,
    so apply_discount(100, 10) returns 90.0 by coincidence but
    apply_discount(50, 10) returns 40.0 instead of the correct 45.0.
    """
    return price - percent
