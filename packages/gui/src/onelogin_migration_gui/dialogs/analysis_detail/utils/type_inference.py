"""Utilities for inferring attribute metadata from sample values."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

__all__ = ["infer_attribute_type", "detect_attribute_warning"]


def _normalize_values(values: Iterable[Any]) -> list[str]:
    """Return a list of trimmed string representations for inference."""
    normalized: list[str] = []
    for value in values:
        if isinstance(value, bool):
            normalized.append(str(value).lower())
        elif isinstance(value, (int, float)):
            normalized.append(str(value))
        elif isinstance(value, str):
            normalized.append(value.strip())
        else:
            normalized.append(str(value).strip())
    return normalized


def infer_attribute_type(values: Iterable[Any]) -> str:
    """Guess an attribute data type based on observed values."""
    normalized = _normalize_values(values)
    filtered = [v for v in normalized if v]
    if not filtered:
        return "Unknown"

    lowered = [v.lower() for v in filtered]
    if all(v in {"true", "false"} for v in lowered):
        return "Boolean"

    try:
        if all(re.fullmatch(r"-?\d+", v) for v in filtered):
            return "Integer"
    except re.error:
        pass

    try:
        if all(re.fullmatch(r"-?\d+(\.\d+)?", v) for v in filtered):
            return "Decimal"
    except re.error:
        pass

    iso_date_pattern = re.compile(
        r"\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?"
    )
    if all(iso_date_pattern.fullmatch(v) for v in filtered):
        return "Date/Time"

    if all("@" in v and "." in v for v in filtered):
        return "Email"

    if any("," in v or ";" in v for v in filtered):
        return "Delimited String"

    return "String"


def detect_attribute_warning(name: str, values: Iterable[Any], data_type: str) -> str | None:
    """Identify potential mapping or transformation concerns for an attribute."""
    if data_type == "Unknown":
        return "Unable to infer data type from sample values"

    if " " in name or not name.replace("_", "").isalnum():
        return "Normalize attribute key for API compatibility"

    text_values = [str(value) for value in values if value not in (None, "")]
    if not text_values:
        return None

    if any("\n" in v or len(v) > 120 for v in text_values):
        return "Values are long or multi-line; confirm storage limits"

    if any(v.count(",") >= 2 or v.count(";") >= 2 for v in text_values):
        return "Multi-value delimiter detected; map to list attribute"

    return None
