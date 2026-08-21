from __future__ import annotations

import math
from typing import Any


def strict_bool(value: Any, *, field: str) -> bool:
    """Accept JSON booleans only; strings such as "false" are unsafe."""

    if type(value) is not bool:
        raise TypeError(f"{field} must be a JSON boolean")
    return value


def optional_finite_float(
    value: Any,
    *,
    field: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"{field} must be a number, not a boolean")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise TypeError(f"{field} must be a finite number") from error
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    if minimum is not None and number < minimum:
        raise ValueError(f"{field} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{field} must be <= {maximum}")
    return number


def unique_string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise TypeError(f"{field} must be a JSON array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise TypeError(f"{field} entries must be strings")
        text = item.strip()
        if text and text not in result:
            result.append(text)
    return result
