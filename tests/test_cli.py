"""CLI tests — exercise the thin front-end without touching the network."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from garmin_workout_push import cli

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_dry_run_human_output(capsys):
    code = cli.main([str(EXAMPLES / "tempo-16k.yaml"), "--dry-run"])
    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert "Long run 16k" in out
    assert "2× repeat" in out
    assert "pace 4:50–4:55 /km" in out
    assert "nothing was sent" in out


def test_dry_run_json_output(capsys):
    code = cli.main([str(EXAMPLES / "3x3k.yaml"), "--dry-run", "--json"])
    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    payload = json.loads(out)
    assert payload["status"] == "dry-run"
    assert payload["sport"] == "running"
    assert payload["steps"] == 8
    assert payload["workout"]["workoutSegments"][0]["workoutSteps"]


def test_garminconnect_logs_quieted_by_default():
    cli.main([str(EXAMPLES / "3x3k.yaml"), "--dry-run"])
    assert logging.getLogger("garminconnect").level == logging.ERROR


def test_verbose_restores_garminconnect_logs():
    cli.main([str(EXAMPLES / "3x3k.yaml"), "--dry-run", "--verbose"])
    assert logging.getLogger("garminconnect").level == logging.DEBUG


def test_validation_error_exit_code(capsys):
    code = cli.main(["/no/such/file.yaml", "--dry-run"])
    err = capsys.readouterr().err
    assert code == cli.EXIT_VALIDATION
    assert "workout file error" in err


def test_push_path_with_monkeypatched_client(monkeypatch, capsys):
    """Full push path with credentials and client stubbed out."""
    recorded = {}

    class StubClient:
        def __init__(self, email, password, **kwargs):
            recorded["email"] = email
            recorded["password"] = password

        def login(self):
            recorded["login"] = True

        def push(self, workout):
            recorded["pushed"] = workout
            return 4242

        def verify(self, workout_id):
            recorded["verified"] = workout_id
            return {
                "workoutSegments": [
                    {
                        "workoutSteps": [
                            {"type": "ExecutableStepDTO"},
                            {"type": "RepeatGroupDTO", "numberOfIterations": 2, "workoutSteps": [{"type": "ExecutableStepDTO"}, {"type": "ExecutableStepDTO"}]},
                            {"type": "ExecutableStepDTO"},
                        ]
                    }
                ]
            }

        def schedule(self, workout_id, date):
            recorded["scheduled"] = (workout_id, date)

    monkeypatch.setattr(cli, "GarminWorkoutClient", StubClient)
    monkeypatch.setattr(cli.getpass, "getpass", lambda *a, **k: "secret")

    code = cli.main([str(EXAMPLES / "tempo-16k.yaml"), "--email", "me@example.com", "--json"])
    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    payload = json.loads(out)
    assert payload["workout_id"] == 4242
    assert payload["verified_steps"] == 6  # 1 + 2*2 + 1
    assert recorded["email"] == "me@example.com"
    assert recorded["password"] == "secret"


def test_schedule_without_date_errors(monkeypatch, capsys):
    class StubClient:
        def __init__(self, *a, **k):
            pass

        def login(self):
            pass

        def push(self, workout):
            return 1

        def verify(self, workout_id):
            return {}

        def schedule(self, *a):
            raise AssertionError("should not schedule")

    monkeypatch.setattr(cli, "GarminWorkoutClient", StubClient)
    monkeypatch.setattr(cli.getpass, "getpass", lambda *a, **k: "secret")

    # 3x3k.yaml has no date
    code = cli.main([str(EXAMPLES / "3x3k.yaml"), "--email", "me@example.com", "--schedule"])
    err = capsys.readouterr().err
    assert code == cli.EXIT_VALIDATION
    assert "no 'date'" in err


def test_api_error_mapped_to_exit_4(monkeypatch, capsys):
    class BoomClient:
        def __init__(self, *a, **k):
            pass

        def login(self):
            raise RuntimeError("auth boom")

    monkeypatch.setattr(cli, "GarminWorkoutClient", BoomClient)
    monkeypatch.setattr(cli.getpass, "getpass", lambda *a, **k: "secret")

    code = cli.main([str(EXAMPLES / "3x3k.yaml"), "--email", "me@example.com"])
    err = capsys.readouterr().err
    assert code == cli.EXIT_API
    assert "Garmin Connect error" in err
