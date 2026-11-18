"""Flight movement direction shared by ADS-B inputs."""

from enum import Enum


class MovementType(str, Enum):
    """Operational context attached to loaded ADS-B observations."""

    ARRIVAL = "arrival"
    DEPARTURE = "departure"
    UNKNOWN = "unknown"
