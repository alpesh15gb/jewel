from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable, Any

MONEY_QUANT = Decimal("0.01")
WEIGHT_QUANT = Decimal("0.001")
ONE_RUPEE = Decimal("1")
ZERO = Decimal("0")


def decimal_value(value: Any, *, field: str = "value") -> Decimal:
    """Convert user/database values to Decimal without binary-float arithmetic."""
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be numeric") from exc


def money_decimal(value: Any) -> Decimal:
    return decimal_value(value, field="amount").quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def weight_decimal(value: Any) -> Decimal:
    return decimal_value(value, field="weight").quantize(WEIGHT_QUANT, rounding=ROUND_HALF_UP)


def money(value: Any) -> float:
    """API/database compatibility value rounded deterministically to paise."""
    return float(money_decimal(value))


def weight(value: Any) -> float:
    """API/database compatibility value rounded deterministically to milligrams."""
    return float(weight_decimal(value))


def money_paise(value: Any) -> int:
    return int((money_decimal(value) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def weight_mg(value: Any) -> int:
    return int((weight_decimal(value) * 1000).to_integral_value(rounding=ROUND_HALF_UP))


def paise_money(value: Any) -> float:
    """Convert canonical integer paise to a 2-decimal compatibility value without float arithmetic."""
    try:
        paise = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("paise must be an integer") from exc
    return float((Decimal(paise) / Decimal(100)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def mg_weight(value: Any) -> float:
    """Convert canonical integer milligrams to a 3-decimal compatibility weight."""
    try:
        mg = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("milligrams must be an integer") from exc
    return float((Decimal(mg) / Decimal(1000)).quantize(WEIGHT_QUANT, rounding=ROUND_HALF_UP))


def money_sum(values: Iterable[Any]) -> float:
    total = sum((money_decimal(v) for v in values), ZERO)
    return float(total.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def weight_sum(values: Iterable[Any]) -> float:
    total = sum((weight_decimal(v) for v in values), ZERO)
    return float(total.quantize(WEIGHT_QUANT, rounding=ROUND_HALF_UP))


def money_equal(left: Any, right: Any, tolerance_paise: int = 0) -> bool:
    return abs(money_paise(left) - money_paise(right)) <= max(0, int(tolerance_paise))


def weight_equal(left: Any, right: Any, tolerance_mg: int = 1) -> bool:
    return abs(weight_mg(left) - weight_mg(right)) <= max(0, int(tolerance_mg))


def nearest_rupee(value: Any) -> float:
    rounded = money_decimal(value).quantize(ONE_RUPEE, rounding=ROUND_HALF_UP)
    return float(rounded.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))
