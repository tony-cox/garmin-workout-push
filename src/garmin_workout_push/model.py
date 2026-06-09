"""Generic, device-agnostic workout model.

These are validated value objects (Pydantic). They are the boundary between the
user's file and Garmin's schema — neither side leaks into the other. Nothing
here knows about Garmin's JSON, watch models, or the network.

Units are normalised on the way in: distances are stored in **metres**, times in
**seconds**, and pace targets as **speeds in metres/second** (low ≤ high). The
loader does the parsing/conversion; the builder reads these normalised values.
"""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Sport(str, Enum):
    """Sports supported by the model. Running is implemented end-to-end;
    cycling and swimming are wired through the builder as the extension point."""

    running = "running"
    cycling = "cycling"
    swimming = "swimming"


class StepKind(str, Enum):
    """What a step is for. Maps to Garmin step intensities in the builder."""

    warmup = "warmup"
    active = "active"
    recovery = "recovery"
    interval = "interval"
    cooldown = "cooldown"
    rest = "rest"


# --------------------------------------------------------------------------- #
#  Durations — how a step ends
# --------------------------------------------------------------------------- #


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DistanceDuration(_Frozen):
    """End the step after a fixed distance (stored in metres)."""

    type: Literal["distance"] = "distance"
    meters: float = Field(gt=0)


class TimeDuration(_Frozen):
    """End the step after a fixed time (stored in whole seconds)."""

    type: Literal["time"] = "time"
    seconds: int = Field(gt=0)


class LapButtonDuration(_Frozen):
    """Open step — ends when the athlete presses the lap button."""

    type: Literal["lap_button"] = "lap_button"


Duration = Annotated[
    Union[DistanceDuration, TimeDuration, LapButtonDuration],
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------- #
#  Targets — what the device enforces during a step
# --------------------------------------------------------------------------- #


class OpenTarget(_Frozen):
    """No target — the athlete is free."""

    type: Literal["open"] = "open"


class PaceTarget(_Frozen):
    """Speed/pace range, stored as metres-per-second bounds (low ≤ high)."""

    type: Literal["pace"] = "pace"
    low_speed_mps: float = Field(gt=0)
    high_speed_mps: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> "PaceTarget":
        if self.low_speed_mps > self.high_speed_mps:
            raise ValueError("low_speed_mps must be <= high_speed_mps")
        return self


class HeartRateTarget(_Frozen):
    """Explicit heart-rate range in bpm (low ≤ high)."""

    type: Literal["heart_rate"] = "heart_rate"
    low_bpm: int = Field(gt=0)
    high_bpm: int = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> "HeartRateTarget":
        if self.low_bpm > self.high_bpm:
            raise ValueError("low_bpm must be <= high_bpm")
        return self


class HeartRateZoneTarget(_Frozen):
    """A heart-rate zone (1–5) resolved against the athlete's Connect zones."""

    type: Literal["heart_rate_zone"] = "heart_rate_zone"
    zone: int = Field(ge=1, le=5)


class CadenceTarget(_Frozen):
    """Cadence range (steps- or revolutions-per-minute, low ≤ high)."""

    type: Literal["cadence"] = "cadence"
    low_spm: int = Field(gt=0)
    high_spm: int = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> "CadenceTarget":
        if self.low_spm > self.high_spm:
            raise ValueError("low_spm must be <= high_spm")
        return self


class PowerTarget(_Frozen):
    """Explicit power range in watts (low ≤ high)."""

    type: Literal["power"] = "power"
    low_watts: int = Field(gt=0)
    high_watts: int = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> "PowerTarget":
        if self.low_watts > self.high_watts:
            raise ValueError("low_watts must be <= high_watts")
        return self


class PowerZoneTarget(_Frozen):
    """A power zone (1–7) resolved against the athlete's Connect zones."""

    type: Literal["power_zone"] = "power_zone"
    zone: int = Field(ge=1, le=7)


Target = Annotated[
    Union[
        OpenTarget,
        PaceTarget,
        HeartRateTarget,
        HeartRateZoneTarget,
        CadenceTarget,
        PowerTarget,
        PowerZoneTarget,
    ],
    Field(discriminator="type"),
]


# --------------------------------------------------------------------------- #
#  Steps, repeats, and the whole workout
# --------------------------------------------------------------------------- #


class Step(_Frozen):
    """A single executable step: a kind, a duration, and an optional target."""

    type: Literal["step"] = "step"
    kind: StepKind
    duration: Duration
    target: Target = Field(default_factory=OpenTarget)
    name: str | None = None


class RepeatGroup(_Frozen):
    """A group of steps repeated ``repeat`` times."""

    type: Literal["repeat"] = "repeat"
    repeat: int = Field(ge=1)
    steps: list[Step] = Field(min_length=1)


Element = Annotated[Union[Step, RepeatGroup], Field(discriminator="type")]


class WorkoutDefinition(_Frozen):
    """The parsed, validated, sport-agnostic representation of a workout."""

    name: str = Field(min_length=1)
    sport: Sport
    date: datetime.date | None = None
    steps: list[Element] = Field(min_length=1)

    def step_count(self) -> int:
        """Number of executable steps, expanding repeats."""

        def count(elements: list[Element]) -> int:
            total = 0
            for el in elements:
                if isinstance(el, RepeatGroup):
                    total += count(el.steps) * el.repeat
                else:
                    total += 1
            return total

        return count(self.steps)
