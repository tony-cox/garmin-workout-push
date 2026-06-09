"""Builder tests — pure, no network. Asserts the Garmin JSON shape."""

from __future__ import annotations

import math

import pytest
from garminconnect.workout import CyclingWorkout, RunningWorkout, SwimmingWorkout

from garmin_workout_push import build_workout, load_workout


def _build(steps, sport="running", name="w"):
    return build_workout(load_workout({"name": name, "sport": sport, "steps": steps}))


def _steps(workout):
    return workout.to_dict()["workoutSegments"][0]["workoutSteps"]


def test_sport_selects_workout_class_and_segment_type():
    run = _build([{"kind": "active", "time": "5:00"}], "running")
    bike = _build([{"kind": "active", "time": "5:00"}], "cycling")
    swim = _build([{"kind": "active", "time": "5:00"}], "swimming")
    assert isinstance(run, RunningWorkout)
    assert isinstance(bike, CyclingWorkout)
    assert isinstance(swim, SwimmingWorkout)
    assert run.to_dict()["workoutSegments"][0]["sportType"]["sportTypeKey"] == "running"
    assert swim.to_dict()["workoutSegments"][0]["sportType"]["sportTypeId"] == 4


def test_distance_step_uses_distance_condition_id_3_in_metres():
    step = _steps(_build([{"kind": "active", "distance_km": 5}]))[0]
    assert step["endCondition"]["conditionTypeId"] == 3
    assert step["endCondition"]["conditionTypeKey"] == "distance"
    assert step["endConditionValue"] == 5000.0


def test_time_step_uses_time_condition_id_2_in_seconds():
    step = _steps(_build([{"kind": "warmup", "time": "10:00"}]))[0]
    assert step["endCondition"]["conditionTypeId"] == 2
    assert step["endConditionValue"] == 600.0


def test_lap_button_step_uses_condition_id_1_and_no_value():
    step = _steps(_build([{"kind": "recovery", "lap": True}]))[0]
    assert step["endCondition"]["conditionTypeId"] == 1
    assert step["endCondition"]["conditionTypeKey"] == "lap.button"
    # endConditionValue is None and dropped by to_dict(exclude_none)
    assert "endConditionValue" not in step


def test_step_kinds_map_to_garmin_intensities():
    steps = _steps(
        _build(
            [
                {"kind": "warmup", "time": "1:00"},
                {"kind": "active", "time": "1:00"},
                {"kind": "interval", "time": "1:00"},
                {"kind": "recovery", "time": "1:00"},
                {"kind": "cooldown", "time": "1:00"},
                {"kind": "rest", "time": "1:00"},
            ]
        )
    )
    keys = [s["stepType"]["stepTypeKey"] for s in steps]
    assert keys == ["warmup", "interval", "interval", "recovery", "cooldown", "rest"]


def test_pace_target_emits_speed_zone_in_mps_low_then_high():
    step = _steps(_build([{"kind": "active", "distance_km": 3, "target": {"pace": ["4:55", "4:50"]}}]))[0]
    assert step["targetType"]["workoutTargetTypeKey"] == "speed.zone"
    assert math.isclose(step["targetValueOne"], 1000 / 295, rel_tol=1e-9)
    assert math.isclose(step["targetValueTwo"], 1000 / 290, rel_tol=1e-9)
    assert step["targetValueOne"] < step["targetValueTwo"]


def test_heart_rate_range_and_zone_targets():
    rng = _steps(_build([{"kind": "active", "time": "5:00", "target": {"heart_rate": [140, 155]}}]))[0]
    assert rng["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
    assert rng["targetValueOne"] == 140.0
    assert rng["targetValueTwo"] == 155.0

    zone = _steps(_build([{"kind": "active", "time": "5:00", "target": {"heart_rate": {"zone": 3}}}]))[0]
    assert zone["zoneNumber"] == 3
    assert "targetValueOne" not in zone


def test_cadence_and_power_targets():
    cad = _steps(_build([{"kind": "active", "time": "5:00", "target": {"cadence": [170, 180]}}]))[0]
    assert cad["targetType"]["workoutTargetTypeKey"] == "cadence"
    pwr = _steps(_build([{"kind": "active", "time": "5:00", "target": {"power": [200, 250]}}], "cycling"))[0]
    assert pwr["targetType"]["workoutTargetTypeKey"] == "power.zone"
    assert pwr["targetValueTwo"] == 250.0


def test_open_target_is_no_target():
    step = _steps(_build([{"kind": "warmup", "time": "5:00", "target": "open"}]))[0]
    assert step["targetType"]["workoutTargetTypeKey"] == "no.target"


def test_repeat_group_structure_and_global_step_ordering():
    workout = _build(
        [
            {"kind": "warmup", "distance_km": 4, "target": "open"},
            {
                "repeat": 2,
                "steps": [
                    {"kind": "active", "distance_km": 3, "target": {"pace": ["4:55", "4:50"]}},
                    {"kind": "recovery", "distance_km": 1.5, "target": "open"},
                ],
            },
            {"kind": "cooldown", "distance_km": 4.5, "target": "open"},
        ]
    )
    steps = _steps(workout)
    # top level: warmup, repeat group, cooldown
    assert [s["stepOrder"] for s in steps] == [1, 2, 5]
    repeat = steps[1]
    assert repeat["type"] == "RepeatGroupDTO"
    assert repeat["numberOfIterations"] == 2
    assert repeat["endCondition"]["conditionTypeId"] == 7
    # children continue the global stepOrder sequence (3, 4)
    assert [c["stepOrder"] for c in repeat["workoutSteps"]] == [3, 4]


def test_step_name_maps_to_description():
    step = _steps(_build([{"kind": "active", "time": "5:00", "name": "Tempo"}]))[0]
    assert step["description"] == "Tempo"


def test_estimated_duration_uses_pace_for_distance_steps():
    # 3 km at midpoint of 4:55/4:50 ≈ 3.418 m/s -> ~877 s
    workout = _build([{"kind": "active", "distance_km": 3, "target": {"pace": ["4:55", "4:50"]}}])
    assert 850 < workout.estimatedDurationInSecs < 900


def test_estimated_duration_sums_repeats_and_times():
    workout = _build(
        [
            {"kind": "warmup", "time": "10:00"},
            {"repeat": 3, "steps": [{"kind": "interval", "time": "3:00"}, {"kind": "recovery", "time": "1:00"}]},
        ]
    )
    # 600 + 3*(180+60) = 1320
    assert workout.estimatedDurationInSecs == 1320


def test_built_workout_is_json_serialisable_by_to_dict():
    import json

    workout = build_workout(load_workout({"name": "x", "sport": "running", "steps": [{"kind": "active", "distance_km": 5, "target": {"pace": ["4:00", "3:55"]}}]}))
    json.dumps(workout.to_dict())  # must not raise
