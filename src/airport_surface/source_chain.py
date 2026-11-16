"""Source-chain algorithms independent of sessions and graph mutation."""

from .graph import compact_source_segments
from .models import SourceSegment


def split_source_chain(
    segments: tuple[SourceSegment, ...], segment_index: int, station: float
) -> tuple[tuple[SourceSegment, ...], tuple[SourceSegment, ...]]:
    """Split at a station within the selected source interval.

    Preserve traversal order and compact adjacent intervals. Pieces within
    1 mm of the boundary are omitted, matching existing editor behavior.
    Either half may be empty; callers decide whether that is allowed.
    The input and immutable source records are not modified.
    """
    segment = segments[segment_index]
    before, after = list(segments[:segment_index]), list(segments[segment_index + 1 :])
    if segment.reversed:
        if station < segment.source_end_m - 1e-3:
            before.append(SourceSegment(segment.source_id, station, segment.source_end_m, True))
        if station > segment.source_start_m + 1e-3:
            after.insert(
                0,
                SourceSegment(segment.source_id, segment.source_start_m, station, True),
            )
    else:
        if station > segment.source_start_m + 1e-3:
            before.append(SourceSegment(segment.source_id, segment.source_start_m, station))
        if station < segment.source_end_m - 1e-3:
            after.insert(0, SourceSegment(segment.source_id, station, segment.source_end_m))
    left_segments = compact_source_segments(before)
    right_segments = compact_source_segments(after)
    return left_segments, right_segments
