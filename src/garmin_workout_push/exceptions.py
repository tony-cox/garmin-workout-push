"""Typed exceptions for the library.

The core never calls ``sys.exit`` or prints — it raises these. Front-ends
(the CLI, a GUI, a web service) decide how to render them.
"""

from __future__ import annotations


class GarminWorkoutError(Exception):
    """Base class for every error raised by this library."""


class WorkoutValidationError(GarminWorkoutError):
    """A workout file/dict is malformed or violates the input schema.

    Raised by the loader. The message is written to be shown directly to a
    user authoring a workout file.
    """


class WorkoutBuildError(GarminWorkoutError):
    """A valid definition could not be mapped to a Garmin workout.

    Raised by the builder (e.g. an unsupported sport/target combination).
    """


class PushError(GarminWorkoutError):
    """A workout could not be pushed/scheduled/verified against Connect.

    Raised by the client. Authentication and transport failures from the
    underlying ``python-garminconnect`` library propagate unchanged so callers
    can distinguish them.
    """
