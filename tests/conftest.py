import pytest
from flight_database_fixture import create_flight_database


@pytest.fixture
def flight_samples():
    import pandas as pd

    from flight import Flight

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


@pytest.fixture
def flight_database_factory(tmp_path):
    counter = 0

    def create(flights, movement_types=None):
        nonlocal counter
        counter += 1
        return create_flight_database(
            tmp_path / f"flight-fixture-{counter}.duckdb",
            flights,
            movement_types,
        )

    return create
