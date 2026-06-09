"""Map a generic ``WorkoutDefinition`` onto a typed ``garminconnect`` workout.

This is the only module that knows Garmin's schema. It converts our normalised
model (metres, seconds, metres/second) into the workout-service JSON shape that
``python-garminconnect`` serialises and uploads.

Sport-extensible: running is the proven path; cycling and swimming reuse the
exact same step machinery via the sport map below.

A note on the end-condition constants. ``garminconnect.workout.ConditionType``
defines ``DISTANCE = 1``, but that constant is unused by the library's own
helpers and disagrees with Garmin's live workout-service schema, where
``1 = lap.button`` and ``3 = distance`` (``2 = time`` and ``7 = iterations`` are
confirmed by the library's working ``create_*`` helpers). We therefore define
the authoritative ids here rather than importing that enum.
"""

from __future__ import annotations

from itertools import count
from typing import Any, Iterator

from garminconnect.workout import (
    BaseWorkout,
    CyclingWorkout,
    ExecutableStep,
    RepeatGroup as GarminRepeatGroup,
    RunningWorkout,
    SwimmingWorkout,
    WorkoutSegment,
)

from .exceptions import WorkoutBuildError
from .model import (
    CadenceTarget,
    DistanceDuration,
    Duration,
    Element,
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
    Target,
    TimeDuration,
    WorkoutDefinition,
)

# Default running speed (6:00/km) used only to estimate duration of distance
# steps that carry no pace target. Garmin recomputes its own estimate anyway.
_DEFAULT_SPEED_MPS = 1000.0 / 360.0

# sport -> (typed workout class, segment sportType dict)
_SPORT: dict[Sport, tuple[type[BaseWorkout], dict[str, Any]]] = {
    Sport.running: (
        RunningWorkout,
        {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1},
    ),
    Sport.cycling: (
        CyclingWorkout,
        {"sportTypeId": 2, "sportTypeKey": "cycling", "displayOrder": 2},
    ),
    # The workout-service expects swimming sportTypeId=4 (3 is normalised to
    # "other" on upload) — mirrors garminconnect.workout.SwimmingWorkout.
    Sport.swimming: (
        SwimmingWorkout,
        {"sportTypeId": 4, "sportTypeKey": "swimming", "displayOrder": 3},
    ),
}

# StepKind -> Garmin (stepTypeId, key, displayOrder). "active" has no direct
# Garmin equivalent and maps to the generic "interval" work step.
_STEP_TYPE: dict[StepKind, dict[str, Any]] = {
    StepKind.warmup: {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1},
    StepKind.cooldown: {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
    StepKind.interval: {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    StepKind.active: {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    StepKind.recovery: {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4},
    StepKind.rest: {"stepTypeId": 5, "stepTypeKey": "rest", "displayOrder": 5},
}

# Authoritative end-condition ids (see module docstring).
_COND_LAP = {"conditionTypeId": 1, "conditionTypeKey": "lap.button", "displayOrder": 1, "displayable": True}
_COND_TIME = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True}
_COND_DISTANCE = {"conditionTypeId": 3, "conditionTypeKey": "distance", "displayOrder": 3, "displayable": True}
_COND_ITERATIONS = {"conditionTypeId": 7, "conditionTypeKey": "iterations", "displayOrder": 7, "displayable": False}

# Target types.
_TT_NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
_TT_POWER = {"workoutTargetTypeId": 2, "workoutTargetTypeKey": "power.zone", "displayOrder": 2}
_TT_CADENCE = {"workoutTargetTypeId": 3, "workoutTargetTypeKey": "cadence", "displayOrder": 3}
_TT_HEART_RATE = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 4}
_TT_SPEED = {"workoutTargetTypeId": 5, "workoutTargetTypeKey": "speed.zone", "displayOrder": 5}


def build_workout(definition: WorkoutDefinition) -> BaseWorkout:
    """Build a typed ``garminconnect`` workout from a ``WorkoutDefinition``.

    Returns a ``RunningWorkout`` / ``CyclingWorkout`` / ``SwimmingWorkout``
    ready for ``GarminWorkoutClient.push``. Raises ``WorkoutBuildError`` on an
    unsupported sport.
    """
    try:
        workout_cls, sport_type = _SPORT[definition.sport]
    except KeyError as exc:  # pragma: no cover - guarded by the model enum
        raise WorkoutBuildError(f"unsupported sport: {definition.sport}") from exc

    order = count(1)
    steps = [_build_element(el, order) for el in definition.steps]

    segment = WorkoutSegment(
        segmentOrder=1,
        sportType=sport_type,
        workoutSteps=steps,
    )
    return workout_cls(
        workoutName=definition.name,
        estimatedDurationInSecs=_estimate_seconds(definition.steps),
        workoutSegments=[segment],
    )


def _build_element(element: Element, order: Iterator[int]):
    if isinstance(element, RepeatGroup):
        group_order = next(order)
        children = [_build_executable(s, order) for s in element.steps]
        return GarminRepeatGroup(
            stepOrder=group_order,
            stepType={"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
            numberOfIterations=element.repeat,
            workoutSteps=children,
            endCondition=_COND_ITERATIONS,
            endConditionValue=float(element.repeat),
        )
    return _build_executable(element, order)


def _build_executable(step: Step, order: Iterator[int]) -> ExecutableStep:
    end_condition, end_value = _build_end_condition(step.duration)
    target_fields = _build_target(step.target)
    return ExecutableStep(
        stepOrder=next(order),
        stepType=_STEP_TYPE[step.kind],
        endCondition=end_condition,
        endConditionValue=end_value,
        description=step.name,
        **target_fields,
    )


def _build_end_condition(duration: Duration) -> tuple[dict[str, Any], float | None]:
    if isinstance(duration, DistanceDuration):
        return _COND_DISTANCE, float(duration.meters)
    if isinstance(duration, TimeDuration):
        return _COND_TIME, float(duration.seconds)
    if isinstance(duration, LapButtonDuration):
        return _COND_LAP, None
    raise WorkoutBuildError(f"unsupported duration: {duration!r}")  # pragma: no cover


def _build_target(target: Target) -> dict[str, Any]:
    """Return the targetType (+ value/zone) fields for a step.

    Garmin's speed target (``speed.zone``) is expressed in metres/second; the
    device renders it as pace for running. ``targetValueOne`` is the low bound,
    ``targetValueTwo`` the high bound.
    """
    if isinstance(target, OpenTarget):
        return {"targetType": _TT_NO_TARGET}
    if isinstance(target, PaceTarget):
        return _value_target(_TT_SPEED, target.low_speed_mps, target.high_speed_mps)
    if isinstance(target, HeartRateTarget):
        return _value_target(_TT_HEART_RATE, target.low_bpm, target.high_bpm)
    if isinstance(target, HeartRateZoneTarget):
        return {"targetType": _TT_HEART_RATE, "zoneNumber": target.zone}
    if isinstance(target, CadenceTarget):
        return _value_target(_TT_CADENCE, target.low_spm, target.high_spm)
    if isinstance(target, PowerTarget):
        return _value_target(_TT_POWER, target.low_watts, target.high_watts)
    if isinstance(target, PowerZoneTarget):
        return {"targetType": _TT_POWER, "zoneNumber": target.zone}
    raise WorkoutBuildError(f"unsupported target: {target!r}")  # pragma: no cover


def _value_target(target_type: dict[str, Any], low: float, high: float) -> dict[str, Any]:
    return {
        "targetType": target_type,
        "targetValueOne": float(low),
        "targetValueTwo": float(high),
    }


# --------------------------------------------------------------------------- #
#  Duration estimate (a hint for Garmin; not authoritative)
# --------------------------------------------------------------------------- #


def _estimate_seconds(elements: list[Element]) -> int:
    total = 0.0
    for el in elements:
        if isinstance(el, RepeatGroup):
            total += sum(_step_seconds(s) for s in el.steps) * el.repeat
        else:
            total += _step_seconds(el)
    return int(round(total))


def _step_seconds(step: Step) -> float:
    duration = step.duration
    if isinstance(duration, TimeDuration):
        return float(duration.seconds)
    if isinstance(duration, DistanceDuration):
        speed = _DEFAULT_SPEED_MPS
        if isinstance(step.target, PaceTarget):
            speed = (step.target.low_speed_mps + step.target.high_speed_mps) / 2.0
        return duration.meters / speed
    return 0.0  # lap-button / open step
