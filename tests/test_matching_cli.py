from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import matching_cli
from matching_inputs import (
    DEFAULT_ARRIVALS,
    DEFAULT_DEPARTURES,
    InputFile,
    load_datasets,
    select_input_files,
)
from path_map import MovementType


def test_input_selection_uses_both_defaults_only_when_neither_is_explicit() -> None:
    defaults = select_input_files(
        None, None, arrivals_provided=False, departures_provided=False
    )
    arrivals_only = select_input_files(
        Path("arr.csv"), None, arrivals_provided=True, departures_provided=False
    )
    departures_only = select_input_files(
        None, Path("dep.csv"), arrivals_provided=False, departures_provided=True
    )

    assert [item.path for item in defaults] == [DEFAULT_ARRIVALS, DEFAULT_DEPARTURES]
    assert [item.path for item in arrivals_only] == [Path("arr.csv")]
    assert [item.path for item in departures_only] == [Path("dep.csv")]


def test_shared_loader_normalizes_naive_and_aware_timestamps(tmp_path: Path) -> None:
    source = tmp_path / "arrivals.csv"
    pd.DataFrame(
        {
            "flight_id": ["naive", "aware"],
            "timestamp": ["2026-01-01 08:00:00", "2026-01-01T08:00:00+09:00"],
            "longitude": [116.0, 116.1],
            "latitude": [40.0, 40.1],
        }
    ).to_csv(source, index=False)

    dataset = load_datasets(
        [InputFile("arrival", source, MovementType.ARRIVAL)], "Asia/Shanghai"
    )[0]
    flights = {flight.flight_id: flight for flight in dataset.iterate()}

    assert flights["naive"].data.timestamp.iloc[0].isoformat() == "2026-01-01T00:00:00+00:00"
    assert flights["aware"].data.timestamp.iloc[0].isoformat() == "2025-12-31T23:00:00+00:00"
    assert [
        flight.data["movement_type"].iloc[0] for flight in dataset.flights
    ] == ["arrival", "arrival"]


def test_duplicate_flight_ids_in_different_sources_remain_separate(tmp_path: Path) -> None:
    sources = []
    for name in ("arrivals", "departures"):
        source = tmp_path / f"{name}.csv"
        pd.DataFrame(
            {
                "flight_id": ["same", "same"],
                "timestamp": ["2026-01-01 00:00:00", "2026-01-01 00:01:00"],
                "longitude": [116.0, 116.1],
                "latitude": [40.0, 40.1],
            }
        ).to_csv(source, index=False)
        sources.append(source)

    datasets = load_datasets(
        [
            InputFile("arrival", sources[0], MovementType.ARRIVAL),
            InputFile("departure", sources[1], MovementType.DEPARTURE),
        ],
        "UTC",
    )

    assert len(datasets) == 2
    assert [next(iter(dataset.iterate())).flight_id for dataset in datasets] == [
        "same",
        "same",
    ]
    assert [dataset.movement_type for dataset in datasets] == [
        MovementType.ARRIVAL,
        MovementType.DEPARTURE,
    ]


def test_mode_misuse_fails_before_loading_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def unexpected_load(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("input loading must not start")

    monkeypatch.setattr(matching_cli, "load_datasets", unexpected_load)

    with pytest.raises(SystemExit) as error:
        matching_cli.main(["--workbench", "--output", "out"])

    assert error.value.code == 2
    assert called is False


def test_invalid_coordinates_fail_before_mode_or_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "invalid.csv"
    output = tmp_path / "output"
    pd.DataFrame(
        {
            "flight_id": ["bad", "bad"],
            "timestamp": ["2026-01-01 00:00:00", "2026-01-01 00:01:00"],
            "longitude": [116.0, 116.1],
            "latitude": [999.0, 999.0],
        }
    ).to_csv(source, index=False)
    calls = []
    monkeypatch.setattr(
        matching_cli, "run_batch", lambda *_args: calls.append("batch")
    )
    monkeypatch.setattr(
        matching_cli, "run_workbench", lambda *_args: calls.append("workbench")
    )

    with pytest.raises(SystemExit) as error:
        matching_cli.main(
            ["--arrivals", str(source), "--output", str(output)]
        )

    assert error.value.code == 2
    assert calls == []
    assert not output.exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--host", "0.0.0.0"],
        ["--port", "9000"],
        ["--display-timezone", "Asia/Shanghai"],
        ["--no-browser"],
    ],
)
def test_batch_rejects_explicit_service_options(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        matching_cli.main(arguments)
    assert error.value.code == 2


def test_dispatch_passes_same_custom_config_without_running_other_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = object()
    calls = []
    monkeypatch.setattr(matching_cli, "_load_selected_datasets", lambda _args: (dataset,))
    monkeypatch.setattr(
        matching_cli,
        "run_workbench",
        lambda args, datasets, config: calls.append(("workbench", datasets, config)),
    )
    monkeypatch.setattr(
        matching_cli,
        "run_batch",
        lambda *_args: calls.append(("batch",)),
    )

    matching_cli.main(
        [
            "--workbench",
            "--max-candidates",
            "9",
            "--search-radius",
            "25",
            "--gps-sigma",
            "7",
            "--transition-beta",
            "12",
        ]
    )

    assert len(calls) == 1
    assert calls[0][0] == "workbench"
    config = calls[0][2]
    assert config.max_candidates == 9
    assert config.search_radius == 25
    assert config.gps_sigma == 7
    assert config.transition_beta == 12


def test_default_dispatch_runs_batch_only(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset = object()
    calls = []
    monkeypatch.setattr(matching_cli, "_load_selected_datasets", lambda _args: (dataset,))
    monkeypatch.setattr(
        matching_cli, "run_batch", lambda args, datasets, config: calls.append("batch")
    )
    monkeypatch.setattr(
        matching_cli,
        "run_workbench",
        lambda *_args: calls.append("workbench"),
    )

    matching_cli.main([])

    assert calls == ["batch"]


def test_removed_visualization_option_is_rejected() -> None:
    with pytest.raises(SystemExit) as error:
        matching_cli.main(["--visualize"])
    assert error.value.code == 2


def test_workbench_receives_prepared_flights_and_exact_match_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flight = object()
    dataset = SimpleNamespace(
        path=Path("arr.csv"),
        movement_type=MovementType.ARRIVAL,
        iterate=lambda: iter([flight]),
    )
    captured = {}
    monkeypatch.setattr(matching_cli, "load_graph", lambda path: ("graph", path))

    import airport_workbench

    monkeypatch.setattr(
        airport_workbench,
        "open_workbench",
        lambda graph, **kwargs: captured.update(graph=graph, **kwargs),
    )
    args = matching_cli.build_parser().parse_args(
        ["--workbench", "--max-candidates", "11", "--no-browser"]
    )
    config = matching_cli._match_config(args)

    matching_cli.run_workbench(args, (dataset,), config)

    assert captured["flights"] == [flight]
    assert captured["movement_types"] == ["arrival"]
    assert captured["flight_sources"] == ["arr.csv"]
    assert captured["match_config"] is config
    assert captured["match_config"].max_candidates == 11
    assert captured["open_browser"] is False
