import pytest

from airport_surface.models import SourceSegment
from airport_surface.source_chain import split_source_chain


@pytest.mark.parametrize("reversed", [False, True])
@pytest.mark.parametrize("station", [0.0, 4.0, 10.0])
def test_split_preserves_interval_coverage_and_traversal(reversed, station):
    segment = SourceSegment("middle", 0, 10, reversed)
    prefix = SourceSegment("prefix", 0, 2)
    suffix = SourceSegment("suffix", 0, 3)
    chain = (prefix, segment, suffix)
    left, right = split_source_chain(chain, 1, station)
    assert left[0] == prefix
    assert right[-1] == suffix
    pieces = [item for item in left + right if item.source_id == "middle"]
    assert sum(item.source_end_m - item.source_start_m for item in pieces) == 10
    assert all(item.reversed == reversed for item in pieces)
    if station == 4:
        assert left[-1] == SourceSegment("middle", 4 if reversed else 0,
                                        10 if reversed else 4, reversed)
        assert right[0] == SourceSegment("middle", 0 if reversed else 4,
                                        4 if reversed else 10, reversed)
    assert chain == (prefix, segment, suffix)


@pytest.mark.parametrize("reversed", [False, True])
def test_split_omits_boundary_slivers_and_allows_empty_half(reversed):
    left, right = split_source_chain((SourceSegment("s", 0, 10, reversed),), 0, 0.0005)
    assert (right if reversed else left) == ()
    assert (left if reversed else right) == (SourceSegment("s", 0.0005, 10, reversed),)


def test_split_compacts_contiguous_intervals():
    left, right = split_source_chain(
        (SourceSegment("s", 0, 5), SourceSegment("s", 5, 10)), 1, 7
    )
    assert left == (SourceSegment("s", 0, 7),)
    assert right == (SourceSegment("s", 7, 10),)
