"""Normalize application values before JSON encoding; no graph-specific schema."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


def to_json_value(value: Any) -> Any:
    """Return JSON-compatible values without modifying the input.

    Containers and dataclass instances are converted recursively; mapping keys
    become strings. Dates use ISO 8601. Missing values and non-finite floats become
    None. NumPy scalars become Python scalars. Unknown objects retain the previous
    string fallback; this is normalization, not a lossless object serializer.
    """
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if is_dataclass(value) and not isinstance(value, type):
        return to_json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        if pd.isna(value):
            return None
        scalar = value.item()
        # Some extended-precision NumPy types cannot become Python scalars.
        if isinstance(scalar, np.generic):
            return str(scalar)
        return to_json_value(scalar)
    return str(value)
