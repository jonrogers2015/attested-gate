def apply_discount(price: float, percent: float) -> float:
    """Apply a percentage discount to a price."""
    return price - (price * percent / 100)
