"""Parse and validate a workout file (or dict) into a ``WorkoutDefinition``.

Pure: no network, no prompts, no printing. Bad input raises
``WorkoutValidationError`` with a message aimed at the file's author.

Input is YAML or JSON (YAML is a superset, so one parser handles both). The raw
mapping is hand-translated into the model rather than fed straight to Pydantic,
because the file's surface syntax (inline duration keys, nested target dicts) is
deliberately friendlier than the normalised model.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .exceptions import WorkoutValidationError
from .model import (
    CadenceTarget,
    DistanceDuration,
    Element,
    HeartRateTarget,
    HeartRateZoneTarget,
    LapButtonDuration,
    OpenTarget,
    PaceTarget,
    PowerTarget,
    PowerZoneTarget,
    RepeatGroup,
    Step,
    TimeDuration,
    WorkoutDefinition,
)

_MILE_M = 1609.344
_KM_M = 1000.0

_DURATION_KEYS = {"distance_km", "distance_m", "distance_mi", "time", "lap"}


def load_workout(source: str | Path | dict[str, Any]) -> WorkoutDefinition:
    """Load a workout from a file path, a YAML/JSON string, or a dict.

    Raises ``WorkoutValidationError`` on any parse or validation failure.
    """
    data = _read_source(source)
    if not isinstance(data, dict):
        raise WorkoutValidationError(
            "workout must be a mapping with 'name', 'sport' and 'steps'"
        )

    name = data.get("name")
    sport = data.get("sport")
    date = _parse_date(data.get("date"))
    raw_steps = data.get("steps")

    if not isinstance(raw_steps, list) or not raw_steps:
        raise WorkoutValidationError("'steps' must be a non-empty list")

    elements: list[Element] = [_parse_element(s, f"steps[{i}]") for i, s in enumerate(raw_steps)]

    try:
        return WorkoutDefinition(name=name, sport=sport, date=date, steps=elements)
    except ValidationError as exc:
        raise WorkoutValidationError(_format_pydantic(exc)) from exc


# --------------------------------------------------------------------------- #
#  Source reading
# --------------------------------------------------------------------------- #


def _read_source(source: str | Path | dict[str, Any]) -> Any:
    if isinstance(source, dict):
        return source
    if isinstance(source, Path):
        text = _read_file(source)
    elif isinstance(source, str):
        # A short, single-line string with no newline that points at an existing
        # file is treated as a path; otherwise it is parsed as inline YAML/JSON.
        candidate = Path(source)
        if "\n" not in source and candidate.exists():
            text = _read_file(candidate)
        else:
            text = source
    else:
        raise WorkoutValidationError(
            f"unsupported source type: {type(source).__name__}"
        )

    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise WorkoutValidationError(f"could not parse workout file: {exc}") from exc


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise WorkoutValidationError(f"workout file not found: {path}") from exc
    except OSError as exc:
        raise WorkoutValidationError(f"could not read workout file: {exc}") from exc


# --------------------------------------------------------------------------- #
#  Element / step parsing
# --------------------------------------------------------------------------- #


def _parse_element(raw: Any, where: str) -> Element:
    if not isinstance(raw, dict):
        raise WorkoutValidationError(f"{where}: each step must be a mapping")

    if "repeat" in raw:
        return _parse_repeat(raw, where)
    return _parse_step(raw, where)


def _parse_repeat(raw: dict[str, Any], where: str) -> RepeatGroup:
    repeat = raw.get("repeat")
    sub = raw.get("steps")
    if not isinstance(sub, list) or not sub:
        raise WorkoutValidationError(f"{where}: 'repeat' needs a non-empty 'steps' list")
    if any(isinstance(s, dict) and "repeat" in s for s in sub):
        raise WorkoutValidationError(f"{where}: nested repeats are not supported")
    steps = [_parse_step(s, f"{where}.steps[{i}]") for i, s in enumerate(sub)]
    try:
        return RepeatGroup(repeat=repeat, steps=steps)
    except ValidationError as exc:
        raise WorkoutValidationError(f"{where}: {_format_pydantic(exc)}") from exc


def _parse_step(raw: dict[str, Any], where: str) -> Step:
    duration = _parse_duration(raw, where)
    target = _parse_target(raw.get("target"), where)
    try:
        return Step(
            kind=raw.get("kind"),
            duration=duration,
            target=target,
            name=raw.get("name"),
        )
    except ValidationError as exc:
        raise WorkoutValidationError(f"{where}: {_format_pydantic(exc)}") from exc


def _parse_duration(raw: dict[str, Any], where: str):
    present = [k for k in _DURATION_KEYS if k in raw]
    if not present:
        raise WorkoutValidationError(
            f"{where}: a step needs exactly one duration "
            f"(distance_km / distance_m / distance_mi / time / lap)"
        )
    if len(present) > 1:
        raise WorkoutValidationError(
            f"{where}: only one duration allowed, found {sorted(present)}"
        )

    key = present[0]
    value = raw[key]
    try:
        if key == "distance_km":
            return DistanceDuration(meters=float(value) * _KM_M)
        if key == "distance_m":
            return DistanceDuration(meters=float(value))
        if key == "distance_mi":
            return DistanceDuration(meters=float(value) * _MILE_M)
        if key == "time":
            return TimeDuration(seconds=_parse_clock(value, where))
        if key == "lap":
            if value not in (True, "true", "True", 1):
                raise WorkoutValidationError(
                    f"{where}: 'lap' must be true for an open/lap-button step"
                )
            return LapButtonDuration()
    except (ValueError, TypeError) as exc:
        raise WorkoutValidationError(f"{where}: invalid {key}: {value!r} ({exc})") from exc


def _parse_target(raw: Any, where: str):
    if raw is None or raw == "open":
        return OpenTarget()
    if not isinstance(raw, dict):
        raise WorkoutValidationError(
            f"{where}: target must be 'open' or a mapping like {{pace: [..]}}"
        )

    keys = [k for k in ("pace", "heart_rate", "cadence", "power") if k in raw]
    if len(keys) != 1:
        raise WorkoutValidationError(
            f"{where}: target needs exactly one of pace / heart_rate / cadence / power"
        )
    kind = keys[0]
    value = raw[kind]

    try:
        if kind == "pace":
            lo, hi = _parse_pace_range(value, raw.get("unit", "km"), where)
            return PaceTarget(low_speed_mps=lo, high_speed_mps=hi)
        if kind == "heart_rate":
            if _is_zone(value):
                return HeartRateZoneTarget(zone=int(value["zone"]))
            lo, hi = _parse_int_range(value, where)
            return HeartRateTarget(low_bpm=lo, high_bpm=hi)
        if kind == "cadence":
            lo, hi = _parse_int_range(value, where)
            return CadenceTarget(low_spm=lo, high_spm=hi)
        if kind == "power":
            if _is_zone(value):
                return PowerZoneTarget(zone=int(value["zone"]))
            lo, hi = _parse_int_range(value, where)
            return PowerTarget(low_watts=lo, high_watts=hi)
    except WorkoutValidationError:
        raise
    except (ValueError, TypeError, ValidationError) as exc:
        msg = _format_pydantic(exc) if isinstance(exc, ValidationError) else str(exc)
        raise WorkoutValidationError(f"{where}: invalid {kind} target: {msg}") from exc


# --------------------------------------------------------------------------- #
#  Small parsers
# --------------------------------------------------------------------------- #


def _is_zone(value: Any) -> bool:
    return isinstance(value, dict) and "zone" in value


def _parse_int_range(value: Any, where: str) -> tuple[int, int]:
    lo, hi = _as_pair(value, where)
    return int(lo), int(hi)


def _as_pair(value: Any, where: str) -> tuple[Any, Any]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise WorkoutValidationError(f"{where}: expected a [low, high] pair, got {value!r}")
    return value[0], value[1]


def _parse_pace_range(value: Any, unit: str, where: str) -> tuple[float, float]:
    a, b = _as_pair(value, where)
    s1 = _pace_to_speed(a, unit, where)
    s2 = _pace_to_speed(b, unit, where)
    return (min(s1, s2), max(s1, s2))


def _pace_to_speed(pace: Any, unit: str, where: str) -> float:
    """Convert a 'mm:ss' pace into metres/second.

    ``unit`` is 'km' (per kilometre) or 'mi'/'mile' (per mile).
    """
    seconds = _parse_clock(pace, where)
    unit = str(unit).lower()
    if unit in ("km", "kilometer", "kilometre", "min/km"):
        return _KM_M / seconds
    if unit in ("mi", "mile", "min/mi"):
        return _MILE_M / seconds
    raise WorkoutValidationError(f"{where}: unknown pace unit {unit!r} (use 'km' or 'mi')")


def _parse_clock(value: Any, where: str) -> int:
    """Parse 'mm:ss' or 'h:mm:ss' (or a bare number of seconds) into seconds."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if not isinstance(value, str):
        raise WorkoutValidationError(f"{where}: expected a time like '4:55', got {value!r}")
    parts = value.strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError as exc:
        raise WorkoutValidationError(f"{where}: invalid time {value!r}") from exc
    if any(n < 0 for n in nums):
        raise WorkoutValidationError(f"{where}: time may not be negative: {value!r}")
    if len(nums) == 2:
        m, s = nums
        return m * 60 + s
    if len(nums) == 3:
        h, m, s = nums
        return h * 3600 + m * 60 + s
    raise WorkoutValidationError(f"{where}: time must be mm:ss or h:mm:ss, got {value!r}")


def _parse_date(value: Any) -> datetime.date | None:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value.strip())
        except ValueError as exc:
            raise WorkoutValidationError(
                f"invalid date {value!r}: use YYYY-MM-DD"
            ) from exc
    raise WorkoutValidationError(f"invalid date: {value!r}")


def _format_pydantic(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        msg = err.get("msg", "invalid value")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts)
