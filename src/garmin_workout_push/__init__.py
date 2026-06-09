"""garmin-workout-push: define structured workouts as files, push them to Garmin.

Public library API::

    from garmin_workout_push import load_workout, build_workout, GarminWorkoutClient

    definition = load_workout("tempo-16k.yaml")
    workout = build_workout(definition)
    client = GarminWorkoutClient(email, password)
    workout_id = client.push(workout)

The CLI (``garmin_workout_push.cli``) is just one front-end over this surface.
"""

from __future__ import annotations

from .builder import build_workout
from .client import GarminWorkoutClient
from .exceptions import (
    GarminWorkoutError,
    PushError,
    WorkoutBuildError,
    WorkoutValidationError,
)
from .loader import load_workout
from .model import Sport, StepKind, WorkoutDefinition

__version__ = "0.1.0"

__all__ = [
    "load_workout",
    "build_workout",
    "GarminWorkoutClient",
    "WorkoutDefinition",
    "Sport",
    "StepKind",
    "GarminWorkoutError",
    "WorkoutValidationError",
    "WorkoutBuildError",
    "PushError",
    "__version__",
]
