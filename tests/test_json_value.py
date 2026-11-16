import json
from dataclasses import dataclass
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from utils.json_value import to_json_value


@pytest.mark.parametrize(
    "value",
    [
        None,
        pd.NA,
        pd.NaT,
        float("nan"),
        float("inf"),
        -float("inf"),
        np.float32("nan"),
        np.datetime64("NaT"),
    ],
)
def test_missing_and_nonfinite_values(value):
    assert to_json_value(value) is None


def test_nested_values_are_json_encodable_and_input_is_unchanged():
    @dataclass
    class Record:
        count: int
        values: tuple

    stamp = datetime(2026, 11, 16, tzinfo=timezone.utc)
    source = {
        1: Record(np.int64(3), (pd.NA, np.bool_(True))),
        "date": date(2026, 11, 16),
        "stamp": pd.Timestamp(stamp),
    }
    result = to_json_value(source)
    assert result == {
        "1": {"count": 3, "values": [None, True]},
        "date": "2026-11-16",
        "stamp": "2026-11-16T00:00:00+00:00",
    }
    assert isinstance(source[1], Record)
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_arrays_do_not_trigger_ambiguous_missing_value_checks():
    value = np.array([1, 2])
    assert to_json_value(value) == str(value)
