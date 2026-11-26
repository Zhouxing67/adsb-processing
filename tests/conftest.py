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
def flight_database_factory():
    opened = []

    def create(flights, movement_types=None):
        database = create_flight_database(flights, movement_types)
        opened.append(database)
        return database

    yield create
    for database in opened:
        database.close()
