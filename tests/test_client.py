"""Client tests with a mocked garminconnect API (no network)."""

from __future__ import annotations

import datetime

import pytest

from garmin_workout_push import GarminWorkoutClient
from garmin_workout_push.exceptions import PushError


class FakeGarmin:
    """Stand-in for garminconnect.Garmin recording calls."""

    def __init__(self):
        self.calls = []
        self.login_arg = "unset"
        self.upload_result = {"workoutId": 12345}
        self.workouts = []

    def login(self, tokenstore=None):
        self.login_arg = tokenstore
        self.calls.append(("login", tokenstore))
        return (None, None)

    def upload_workout(self, payload):
        self.calls.append(("upload_workout", payload))
        return self.upload_result

    def schedule_workout(self, workout_id, date_str):
        self.calls.append(("schedule_workout", workout_id, date_str))
        return {"workoutScheduleId": 999}

    def get_workout_by_id(self, workout_id):
        self.calls.append(("get_workout_by_id", workout_id))
        return {"workoutId": workout_id, "workoutName": "x"}

    def get_workouts(self, start, limit):
        self.calls.append(("get_workouts", start, limit))
        return self.workouts

    def delete_workout(self, workout_id):
        self.calls.append(("delete_workout", workout_id))
        return None


class FakeWorkout:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return self._data


def test_login_without_persistence_passes_no_tokenstore():
    api = FakeGarmin()
    client = GarminWorkoutClient("e", "p", api=api)
    client.login()
    assert api.login_arg is None


def test_login_with_persistence_passes_tokenstore():
    api = FakeGarmin()
    client = GarminWorkoutClient("e", "p", api=api, persist_tokens=True, tokenstore="/tmp/tok")
    client.login()
    assert api.login_arg == "/tmp/tok"


def test_login_is_idempotent():
    api = FakeGarmin()
    client = GarminWorkoutClient("e", "p", api=api)
    client.login()
    client.login()
    assert sum(1 for c in api.calls if c[0] == "login") == 1


def test_push_uploads_dict_and_returns_id():
    api = FakeGarmin()
    client = GarminWorkoutClient("e", "p", api=api)
    workout_id = client.push(FakeWorkout({"workoutName": "x"}))
    assert workout_id == 12345
    assert ("upload_workout", {"workoutName": "x"}) in api.calls


def test_push_auto_logs_in():
    api = FakeGarmin()
    client = GarminWorkoutClient("e", "p", api=api)
    client.push(FakeWorkout({"a": 1}))
    assert any(c[0] == "login" for c in api.calls)


def test_push_raises_when_no_workout_id():
    api = FakeGarmin()
    api.upload_result = {"oops": True}
    client = GarminWorkoutClient("e", "p", api=api)
    with pytest.raises(PushError, match="workoutId"):
        client.push(FakeWorkout({"a": 1}))


def test_schedule_converts_date_to_isoformat():
    api = FakeGarmin()
    client = GarminWorkoutClient("e", "p", api=api)
    client.schedule(12345, datetime.date(2026, 6, 15))
    assert ("schedule_workout", 12345, "2026-06-15") in api.calls


def test_find_matches_name_case_insensitively():
    api = FakeGarmin()
    api.workouts = [
        {"workoutId": 1, "workoutName": "Long Run"},
        {"workoutId": 2, "workoutName": "tempo"},
        {"workoutId": 3, "workoutName": "TEMPO"},
    ]
    client = GarminWorkoutClient("e", "p", api=api)
    found = client.find("Tempo")
    assert {w["workoutId"] for w in found} == {2, 3}


def test_verify_and_delete_delegate():
    api = FakeGarmin()
    client = GarminWorkoutClient("e", "p", api=api)
    assert client.verify(7)["workoutId"] == 7
    client.delete(7)
    assert ("delete_workout", 7) in api.calls
