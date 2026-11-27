from pathlib import Path
from types import SimpleNamespace

import pytest

import matching_cli
from config import load_settings
from flight import flight_repository
from path_map import MatchConfig

SAMPLE_DSN = "postgresql+psycopg://postgres:secret@127.0.0.1:5432/adsb"


@pytest.fixture
def database_calls(monkeypatch, tmp_path):
    calls = []

    def connect(dsn, *, read_only):
        calls.append((dsn, read_only))
        return SimpleNamespace(dsn=dsn, database_error=RuntimeError, close=lambda: None)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(flight_repository, "FlightDatabase", connect)
    return calls


@pytest.mark.parametrize(
    "args",
    [
        ["--workbench", "--output", "out"],
        ["--workbench", "--limit", "1"],
        ["--limit", "1"],
        ["--graph", "graph.json"],
        ["--max-candidates", "9"],
        ["--host", "0.0.0.0"],
        ["--port", "9000"],
        ["--display-timezone", "Asia/Shanghai"],
        ["--no-browser"],
        ["--arrivals", "arrivals.csv"],
        ["--departures", "departures.csv"],
        ["--visualize"],
        ["--database", "flights.duckdb"],
    ],
)
def test_invalid_options_fail_before_connecting(args, database_calls):
    with pytest.raises(SystemExit) as error:
        matching_cli.main(args)
    assert error.value.code == 2
    assert database_calls == []


def test_missing_database_reports_configuration(database_calls, capsys):
    with pytest.raises(SystemExit) as error:
        matching_cli.main([])
    assert error.value.code == 2
    assert "config.local.toml" in capsys.readouterr().err
    assert database_calls == []


def write_config(config=""):
    Path("config.local.toml").write_text(
        f"graph_path = 'custom-graph.json'\n[database]\ndsn = '{SAMPLE_DSN}'\n" + config,
        "utf-8",
    )


def test_empty_database_dsn_fails_before_connecting(database_calls, capsys):
    Path("config.local.toml").write_text("[database]\ndsn = '   '\n", "utf-8")
    with pytest.raises(SystemExit) as error:
        matching_cli.main([])
    assert error.value.code == 2
    assert "database.dsn" in capsys.readouterr().err
    assert database_calls == []


def test_batch_uses_configured_database_and_both_movements(monkeypatch, database_calls):
    write_config("[batch]\noutput_dir = 'custom-output'\nlimit = 3\n")
    calls = []

    class RecordingRunner:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

        def run(self):
            pass

    monkeypatch.setattr(matching_cli, "BatchMatchingRunner", RecordingRunner)
    matching_cli.main([])

    assert database_calls == [(SAMPLE_DSN, True)]
    (graph, datasets, output), options = calls[0]
    assert (graph, output) == (Path("custom-graph.json"), Path("custom-output"))
    assert options == {"match_config": MatchConfig(), "limit": 3}
    assert [dataset.movement_type.value for dataset in datasets] == ["arrival", "departure"]
    assert datasets[0].database is datasets[1].database


def test_workbench_passes_database_timezone_and_config(monkeypatch, database_calls):
    import airport_workbench

    write_config("""
[workbench]
host = 'localhost'
port = 8877
open_browser = false
display_timezone = 'UTC'

[matching]
max_candidates = 9
candidate_radius = 25
gps_sigma = 7
length_scale_m = 60
max_transition_turn_angle_deg = 140
turn_tangent_sample_m = 8
""")
    monkeypatch.setattr(matching_cli, "load_graph", lambda path: ("graph", path))
    captured = {}
    monkeypatch.setattr(
        airport_workbench, "open_workbench",
        lambda graph, **kwargs: captured.update(graph=graph, **kwargs),
    )
    matching_cli.main(["--workbench"])

    assert database_calls == [(SAMPLE_DSN, False)]
    assert captured["flight_database"].dsn == SAMPLE_DSN
    assert captured["input_time_semantics"] == "Asia/Shanghai"
    assert captured["display_timezone"] == "UTC"
    assert captured["host"] == "localhost"
    assert captured["port"] == 8877
    assert captured["open_browser"] is False
    assert captured["save_path"] == Path("custom-graph.json")
    assert captured["match_config"] == MatchConfig(25, 9, 7, 60, 140, 8)


def test_settings_defaults_match_algorithm(database_calls):
    write_config()
    settings = load_settings()
    assert settings.matching == MatchConfig()
    assert settings.batch.limit is None


@pytest.mark.parametrize(
    ("config", "field"),
    [
        ("[batch]\nlimit = -1\n", "batch.limit"),
        ("[workbench]\nport = 0\n", "workbench.port"),
        ("[workbench]\ndisplay_timezone = 'invalid'\n", "workbench.display_timezone"),
        ("[matching]\nmax_candidates = 0\n", "matching"),
    ],
)
def test_invalid_settings_fail_before_connecting(config, field, database_calls, capsys):
    write_config(config)
    with pytest.raises(SystemExit) as error:
        matching_cli.main([])
    assert error.value.code == 2
    assert field in capsys.readouterr().err
    assert database_calls == []
