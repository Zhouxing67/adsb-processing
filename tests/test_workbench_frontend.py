from pathlib import Path


def test_match_poll_compares_with_rendered_geometry_version() -> None:
    source = Path("src/airport_workbench/static/flights-v2.js").read_text(encoding="utf-8")

    assert (
        "function needsGeometryRefresh(key,result){return "
        "geometries.get(key)?.resultSignature!==geometrySignature(result);}" in source
    )
    poll = source[source.index("async function pollMatches()") :]
    poll = poll[: poll.index("function restoreSelections")]
    assert "needsGeometryRefresh(result.flight_key,result)" in poll
    assert "geometrySignature(previous" not in poll
