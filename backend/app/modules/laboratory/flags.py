"""Result parsing and abnormal-flag computation (pure functions, unit-testable).

Flags: L (below range), H (above range), N (normal), A (abnormal non-numeric), None (cannot
be determined, e.g. no reference range).
"""
from decimal import Decimal, InvalidOperation


def ranges_for(test, gender):
    """Reference range (low, high) for a patient gender; gender-specific values win when set."""
    if gender == "male" and (test.ref_low_male is not None or test.ref_high_male is not None):
        return test.ref_low_male, test.ref_high_male
    if gender == "female" and (test.ref_low_female is not None or test.ref_high_female is not None):
        return test.ref_low_female, test.ref_high_female
    return test.ref_low, test.ref_high


def parse_numeric(value):
    s = str(value).strip().replace(",", ".")
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        raise ValueError("must be a number")
    if not d.is_finite() or abs(d) >= Decimal(10) ** 10:
        raise ValueError("must be a number")
    return d.quantize(Decimal("0.0001")) if d.as_tuple().exponent < -4 else d


def compute_flag(result_type, value, *, low=None, high=None, choices=None, normal_choices=None, abnormal=None):
    """Return (numeric_value, flag). Raises ValueError for invalid values."""
    if value is None or str(value).strip() == "":
        return None, None
    if result_type == "numeric":
        d = parse_numeric(value)
        if low is not None and d < Decimal(low):
            return d, "L"
        if high is not None and d > Decimal(high):
            return d, "H"
        if low is None and high is None:
            return d, None
        return d, "N"
    if result_type == "choice":
        v = str(value).strip()
        if choices and v not in choices:
            raise ValueError("must be one of: " + ", ".join(choices))
        if abnormal is not None:
            return None, "A" if abnormal else "N"
        if normal_choices:
            return None, "N" if v in normal_choices else "A"
        return None, None
    # text
    if abnormal is not None:
        return None, "A" if abnormal else "N"
    return None, None
