"""Normalize application values before JSON encoding; no graph-specific schema."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd


def to_json_value(value: Any) -> Any:
    """Return a JSON-compatible value without modifying the input.

    Containers and dataclass instances are converted recursively; mapping keys
    become strings. Dates use ISO 8601. Missing values and non-finite floats become
    None. NumPy scalars become Python scalars. Unsupported values raise ``TypeError``
    instead of being silently converted into misleading strings.
    """
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: to_json_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {_json_key(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return to_json_value(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, np.generic):
        if pd.isna(value):
            return None
        scalar = value.item()
        # Some extended-precision NumPy types cannot become Python scalars.
        if isinstance(scalar, np.generic):
            raise TypeError(f"Unsupported NumPy scalar type: {type(value).__qualname__}")
        return to_json_value(scalar)
    raise TypeError(f"Unsupported JSON value type: {type(value).__qualname__}")


def _json_key(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Enum):
        return _json_key(value.value)
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Unsupported JSON object key type: {type(value).__qualname__}")
