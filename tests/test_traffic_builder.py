from __future__ import annotations

import pytest

from airport_surface.traffic_builder import resolve_projection


def test_explicit_metric_projection_is_accepted():
    projection = resolve_projection("EPSG:32618")

    assert projection.crs.to_epsg() == 32618


@pytest.mark.parametrize("specification", ["EPSG:4326", "EPSG:2263"])
def test_non_projected_or_non_metric_projection_is_rejected(specification):
    with pytest.raises(ValueError):
        resolve_projection(specification)
