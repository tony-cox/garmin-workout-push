"""Loader tests — pure, no network."""

from __future__ import annotations

import datetime
import math
from pathlib import Path

import pytest

from garmin_workout_push import WorkoutDefinition, load_workout
from garmin_workout_push.exceptions import WorkoutValidationError
from garmin_workout_push.model import (
    CadenceTarget,
    DistanceDuration,
    HeartRateTarget,
    HeartRateZoneTarget,
    LapButtonDuration,
    OpenTarget,
    PaceTarget,
    PowerTarget,
    PowerZoneTarget,
    RepeatGroup,
    Sport,
    Step,
    StepKind,
    TimeDuration,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_loads_tempo_example_from_file():
    defn = load_workout(EXAMPLES / "tempo-16k.yaml")
    assert isinstance(defn, WorkoutDefinition)
    assert defn.sport is Sport.running
    assert defn.date == datetime.date(2026, 6, 15)
    # warmup, repeat(2× of 2 steps), cooldown -> 1 + 4 + 1 executable steps
    assert defn.step_count() == 6
    assert isinstance(defn.steps[1], RepeatGroup)
    assert defn.steps[1].repeat == 2


def test_loads_3x3k_example_from_file():
    defn = load_workout(EXAMPLES / "3x3k.yaml")
    assert defn.step_count() == 1 + 3 * 2 + 1


def test_distance_units_convert_to_metres():
    defn = load_workout(
        {
            "name": "units",
            "sport": "running",
            "steps": [
                {"kind": "warmup", "distance_km": 2},
                {"kind": "active", "distance_m": 400},
                {"kind": "cooldown", "distance_mi": 1},
            ],
        }
    )
    durs = [s.duration for s in defn.steps]
    assert durs[0].meters == 2000.0
    assert durs[1].meters == 400.0
    assert math.isclose(durs[2].meters, 1609.344)


def test_pace_target_converts_to_speed_ordered():
    defn = load_workout(
        {
            "name": "p",
            "sport": "running",
            "steps": [{"kind": "active", "distance_km": 3, "target": {"pace": ["4:55", "4:50"]}}],
        }
    )
    target = defn.steps[0].target
    assert isinstance(target, PaceTarget)
    # 4:55/km = 295s -> 3.389 m/s (slow); 4:50/km = 290s -> 3.448 m/s (fast)
    assert math.isclose(target.low_speed_mps, 1000 / 295, rel_tol=1e-9)
    assert math.isclose(target.high_speed_mps, 1000 / 290, rel_tol=1e-9)
    assert target.low_speed_mps < target.high_speed_mps


def test_pace_target_imperial_unit():
    defn = load_workout(
        {
            "name": "p",
            "sport": "running",
            "steps": [{"kind": "active", "distance_mi": 1, "target": {"pace": ["8:00", "7:50"], "unit": "mi"}}],
        }
    )
    target = defn.steps[0].target
    assert math.isclose(target.low_speed_mps, 1609.344 / 480, rel_tol=1e-9)


def test_time_duration_mm_ss_and_h_mm_ss():
    defn = load_workout(
        {
            "name": "t",
            "sport": "running",
            "steps": [
                {"kind": "warmup", "time": "10:00"},
                {"kind": "active", "time": "1:05:30"},
            ],
        }
    )
    assert defn.steps[0].duration == TimeDuration(seconds=600)
    assert defn.steps[1].duration == TimeDuration(seconds=3930)


def test_all_target_kinds():
    defn = load_workout(
        {
            "name": "targets",
            "sport": "running",
            "steps": [
                {"kind": "active", "distance_km": 1, "target": {"heart_rate": [140, 155]}},
                {"kind": "active", "distance_km": 1, "target": {"heart_rate": {"zone": 3}}},
                {"kind": "active", "distance_km": 1, "target": {"cadence": [170, 180]}},
                {"kind": "active", "distance_km": 1, "target": {"power": [200, 250]}},
                {"kind": "active", "distance_km": 1, "target": {"power": {"zone": 4}}},
                {"kind": "active", "lap": True, "target": "open"},
            ],
        }
    )
    kinds = [type(s.target) for s in defn.steps]
    assert kinds == [
        HeartRateTarget,
        HeartRateZoneTarget,
        CadenceTarget,
        PowerTarget,
        PowerZoneTarget,
        OpenTarget,
    ]
    assert isinstance(defn.steps[5].duration, LapButtonDuration)


def test_target_defaults_to_open_when_absent():
    defn = load_workout(
        {"name": "n", "sport": "running", "steps": [{"kind": "active", "distance_km": 1}]}
    )
    assert isinstance(defn.steps[0].target, OpenTarget)


def test_accepts_inline_json_string():
    defn = load_workout('{"name": "j", "sport": "cycling", "steps": [{"kind": "active", "time": "5:00"}]}')
    assert defn.sport is Sport.cycling


@pytest.mark.parametrize(
    "bad,match",
    [
        ({"sport": "running", "steps": [{"kind": "active", "distance_km": 1}]}, "name"),
        ({"name": "x", "sport": "flying", "steps": [{"kind": "active", "time": "5:00"}]}, "sport"),
        ({"name": "x", "sport": "running", "steps": []}, "non-empty"),
        ({"name": "x", "sport": "running", "steps": [{"kind": "active"}]}, "duration"),
        (
            {"name": "x", "sport": "running", "steps": [{"kind": "active", "distance_km": 1, "time": "5:00"}]},
            "only one duration",
        ),
        ({"name": "x", "sport": "running", "steps": [{"kind": "nope", "distance_km": 1}]}, "kind"),
        (
            {"name": "x", "sport": "running", "steps": [{"repeat": 2, "steps": []}]},
            "non-empty",
        ),
        (
            {"name": "x", "sport": "running", "steps": [{"kind": "active", "distance_km": 1, "target": {"pace": ["4:00"]}}]},
            "pair",
        ),
    ],
)
def test_invalid_inputs_raise_validation_error(bad, match):
    with pytest.raises(WorkoutValidationError, match=match):
        load_workout(bad)


def test_missing_file_raises_validation_error():
    with pytest.raises(WorkoutValidationError, match="not found"):
        load_workout(Path("/no/such/workout.yaml"))


def test_nested_repeat_rejected():
    with pytest.raises(WorkoutValidationError, match="nested"):
        load_workout(
            {
                "name": "x",
                "sport": "running",
                "steps": [{"repeat": 2, "steps": [{"repeat": 2, "steps": [{"kind": "active", "time": "1:00"}]}]}],
            }
        )
