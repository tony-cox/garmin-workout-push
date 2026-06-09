"""Thin CLI front-end.

Parses args, gathers credentials interactively, calls the library, and renders
the result. It holds **no** workout-building or Garmin logic — everything it
does is doable by importing the library directly.

    garmin-workout-push WORKOUT_FILE [--schedule] [--dry-run] [--json] [--email EMAIL]

Exit codes: 0 ok · 2 validation error · 3 build error · 4 auth/API error ·
1 unexpected.
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import sys
from typing import Any

from . import __version__
from .builder import build_workout
from .client import GarminWorkoutClient
from .exceptions import PushError, WorkoutBuildError, WorkoutValidationError
from .loader import load_workout
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

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_VALIDATION = 2
EXIT_BUILD = 3
EXIT_API = 4


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    try:
        definition = load_workout(args.workout_file)
    except WorkoutValidationError as exc:
        return _fail(f"workout file error: {exc}", EXIT_VALIDATION, args.json)

    try:
        workout = build_workout(definition)
    except WorkoutBuildError as exc:
        return _fail(f"could not build workout: {exc}", EXIT_BUILD, args.json)

    if args.dry_run:
        return _render_dry_run(definition, workout, args.json)

    try:
        return _push(definition, workout, args)
    except (PushError, Exception) as exc:  # noqa: BLE001 - map any push/auth failure
        if isinstance(exc, (WorkoutValidationError, WorkoutBuildError)):
            raise
        return _fail(f"Garmin Connect error: {exc}", EXIT_API, args.json)


# --------------------------------------------------------------------------- #
#  Push path
# --------------------------------------------------------------------------- #


def _push(definition: WorkoutDefinition, workout: Any, args: argparse.Namespace) -> int:
    email = args.email or input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")

    client = GarminWorkoutClient(
        email,
        password,
        prompt_mfa=_prompt_mfa,
        is_cn=args.cn,
    )
    client.login()

    workout_id = client.push(workout)

    # API-side verification: confirm the workout exists with the expected shape.
    verified = client.verify(workout_id)
    verified_steps = _count_api_steps(verified)

    scheduled_for = None
    if args.schedule:
        if definition.date is None:
            return _fail(
                "--schedule given but the workout file has no 'date'",
                EXIT_VALIDATION,
                args.json,
            )
        client.schedule(workout_id, definition.date)
        scheduled_for = definition.date.isoformat()

    if args.json:
        print(
            json.dumps(
                {
                    "status": "ok",
                    "workout_id": workout_id,
                    "name": definition.name,
                    "sport": definition.sport.value,
                    "steps": definition.step_count(),
                    "verified_steps": verified_steps,
                    "scheduled_for": scheduled_for,
                }
            )
        )
    else:
        print(f"Pushed '{definition.name}' (workout id {workout_id}).")
        print(f"  Verified on Connect: {verified_steps} executable step(s).")
        if scheduled_for:
            print(f"  Scheduled for {scheduled_for}.")
        print("  Sync your device and confirm targets display on the policed steps.")
    return EXIT_OK


def _prompt_mfa() -> str:
    return input("Garmin MFA code: ").strip()


def _count_api_steps(verified: Any) -> int:
    """Count executable steps in the workout returned by the API (best effort)."""
    if not isinstance(verified, dict):
        return 0
    total = 0
    for segment in verified.get("workoutSegments") or []:
        total += _count_steps(segment.get("workoutSteps") or [])
    return total


def _count_steps(steps: list[Any]) -> int:
    total = 0
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("type") == "RepeatGroupDTO" or "numberOfIterations" in step:
            iterations = int(step.get("numberOfIterations", 1) or 1)
            total += _count_steps(step.get("workoutSteps") or []) * iterations
        else:
            total += 1
    return total


# --------------------------------------------------------------------------- #
#  Dry run rendering
# --------------------------------------------------------------------------- #


def _render_dry_run(definition: WorkoutDefinition, workout: Any, as_json: bool) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "status": "dry-run",
                    "name": definition.name,
                    "sport": definition.sport.value,
                    "date": definition.date.isoformat() if definition.date else None,
                    "steps": definition.step_count(),
                    "estimated_duration_s": workout.estimatedDurationInSecs,
                    "workout": workout.to_dict(),
                },
                indent=2,
            )
        )
        return EXIT_OK

    print(f"{definition.name}  [{definition.sport.value}]")
    if definition.date:
        print(f"date: {definition.date.isoformat()}")
    print(f"estimated duration: {_fmt_clock(workout.estimatedDurationInSecs)}")
    print("steps:")
    for line in _describe(definition.steps, indent=1):
        print(line)
    print("\n(dry run — nothing was sent to Garmin Connect)")
    return EXIT_OK


def _describe(elements: list[Element], indent: int) -> list[str]:
    pad = "  " * indent
    lines: list[str] = []
    for el in elements:
        if isinstance(el, RepeatGroup):
            lines.append(f"{pad}{el.repeat}× repeat:")
            lines.extend(_describe(el.steps, indent + 1))
        else:
            lines.append(f"{pad}- {_describe_step(el)}")
    return lines


def _describe_step(step: Step) -> str:
    label = step.name or step.kind.value
    return f"{label}: {_fmt_duration(step.duration)} @ {_fmt_target(step.target)}"


def _fmt_duration(duration: Any) -> str:
    if isinstance(duration, DistanceDuration):
        km = duration.meters / 1000.0
        return f"{km:g} km"
    if isinstance(duration, TimeDuration):
        return _fmt_clock(duration.seconds)
    if isinstance(duration, LapButtonDuration):
        return "open (lap button)"
    return "?"


def _fmt_target(target: Any) -> str:
    if isinstance(target, OpenTarget):
        return "no target"
    if isinstance(target, PaceTarget):
        fast = _fmt_pace(target.high_speed_mps)
        slow = _fmt_pace(target.low_speed_mps)
        return f"pace {fast}–{slow} /km"
    if isinstance(target, HeartRateTarget):
        return f"HR {target.low_bpm}–{target.high_bpm} bpm"
    if isinstance(target, HeartRateZoneTarget):
        return f"HR zone {target.zone}"
    if isinstance(target, CadenceTarget):
        return f"cadence {target.low_spm}–{target.high_spm} spm"
    if isinstance(target, PowerTarget):
        return f"power {target.low_watts}–{target.high_watts} W"
    if isinstance(target, PowerZoneTarget):
        return f"power zone {target.zone}"
    return "?"


def _fmt_pace(speed_mps: float) -> str:
    seconds_per_km = round(1000.0 / speed_mps)
    return _fmt_clock(seconds_per_km)


def _fmt_clock(seconds: int) -> str:
    seconds = int(round(seconds))
    if seconds >= 3600:
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}"
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


# --------------------------------------------------------------------------- #
#  Argument parsing / error rendering
# --------------------------------------------------------------------------- #


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="garmin-workout-push",
        description="Push a structured workout file to Garmin Connect.",
    )
    parser.add_argument("workout_file", help="path to a YAML/JSON workout file")
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="also schedule the workout on the file's 'date'",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="load, build and print the resolved workout; no auth, no network",
    )
    parser.add_argument(
        "--json", action="store_true", help="machine-readable output"
    )
    parser.add_argument(
        "--email", help="Garmin account email (otherwise prompted)"
    )
    parser.add_argument(
        "--cn", action="store_true", help="use the Garmin China backend"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show the underlying garminconnect login/transport logs "
        "(useful when a push fails)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def _configure_logging(verbose: bool) -> None:
    """Tame the underlying library's log output.

    ``python-garminconnect`` logs a WARNING for every login strategy it falls
    through (e.g. a 429 or 403 on the way to a strategy that succeeds). On a
    successful run that chatter is just noise and looks like an error, so by
    default we raise its level to ERROR. ``--verbose`` restores the full
    diagnostics for troubleshooting a genuine failure.
    """
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("garminconnect").setLevel(
        logging.DEBUG if verbose else logging.ERROR
    )


def _fail(message: str, code: int, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"status": "error", "error": message}), file=sys.stderr)
    else:
        print(f"error: {message}", file=sys.stderr)
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
