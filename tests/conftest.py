import pytest


@pytest.fixture
def flight_samples():
    import pandas as pd

    from adsb import Flight

    return [
        Flight(
            pd.DataFrame(
                {
                    "flight_id": ["sample", "sample"],
                    "timestamp": ["2024-01-01 00:00:00", "2024-01-01 00:01:00"],
                    "longitude": [0.0, 0.001],
                    "latitude": [0.0, 0.001],
                }
            )
        )
    ]
