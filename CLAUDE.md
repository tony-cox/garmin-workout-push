# garmin-workout-push

> **Status: spec complete, not yet built.** No source code exists yet. The design is fully specified in [`garmin-workout-push-spec.md`](./garmin-workout-push-spec.md) — **read that first; it is the source of truth.** This file is the quick orientation + handoff.

## What this is

An open-source Python project to **define structured workouts as simple files and push them to Garmin Connect**, where they sync to any Garmin device that supports structured workouts (Forerunner, Fenix, Epix, Edge, etc.). It exists because the Connect *workout-service* API is the only practical route that accepts structured workouts *with enforced targets* — the web UI imports activities not workouts, USB sideload needs a working cable, and third-party routes are export-only or bike/power-only.

## Architecture (the core design constraint)

Two cleanly separated layers — keep the boundary strict when building:

- **Library** (`garmin_workout_push`): reusable core. `model` (WorkoutDefinition/Step/Target/repeats) → `loader` (parse+validate file) → `builder` (generic model → typed `garminconnect` workout) → `client` (auth, push, schedule, verify). **No I/O, no prompts, no printing in the core.** Credentials are injected; the library raises typed exceptions, never exits.
- **CLI** (`garmin_workout_push.cli`): a *thin* front-end. Parses args, prompts for credentials/MFA, calls the library, renders results. Holds **no** workout-building or Garmin logic. It's just one possible front-end — anything it does must be doable by importing the library.

## Key technical facts

- **Dependency:** `python-garminconnect >= 0.3.5` with the `[workout]` extra — it has typed workout models (`RunningWorkout`, …) + `upload_running_workout()` / `schedule_workout()` against the workout-service endpoint. Shipped Jun 2026, actively maintained. Pulls in `curl_cffi` + `pydantic`. Plus `pyyaml` for input. CLI uses stdlib `argparse`/`getpass`.
- **No FIT.** Workouts are sent as JSON to the Connect API; the device sync is Garmin's internal concern. We do **not** create, encode, or transfer FIT files. (FIT only exists as abandoned prior art in `source_data/`.)
- **Input:** explicit YAML/JSON workout file. The tool does **not** parse prose training plans or select sessions — one explicit file in, one workout out, every time.
- **Auth:** interactive each run via `getpass`; nothing persisted by default (token cache suppressed). `.gitignore` defensively excludes `.env`, `.garminconnect/`, `garmin_tokens.json`.
- **Device-agnostic:** no watch model anywhere in the core.

See spec §13 for the full locked-decisions log.

## Planned repo layout

`src/garmin_workout_push/{model,loader,builder,client,cli}.py` · `examples/*.yaml` · `tests/` (loader/builder unit-tested with no network, client mocked) · `pyproject.toml` (console scripts `garmin-workout-push` + `gwpush` alias) · `README.md`. None of this exists yet.

## `source_data/` (gitignored — local reference only)

Personal/reference material that informed the design; **never published**. Useful when building:
- `gold-coast-half-plan.md`, `running-calendar-2026-27.md` — the training plans that motivated the schema (good for realistic `examples/`).
- `claude-code-handoff-garmin-automation.md` — original handoff: the full backstory and every dead-end already ruled out (web import, USB cable, TrainingPeaks). Read before re-proposing any alternative route.
- `build_week2_fit.py` + `week2-long-run.fit` — the abandoned FIT encoder + its output. Reference for FIT field encoding / the fallback only; **not** the path we're building.

## Conventions

- Python 3.11+, `src/` layout, Pydantic models, minimal deps.
- Strict library/CLI boundary (above) — if you find Garmin logic creeping into the CLI, that's a bug.
- Keep it small: this is a focused tool, not a Garmin SDK. Don't over-engineer (it's a nice-to-have that replaces a manual weekly step).

## Where things stand (handoff)

- **Done:** library survey (the four linked uploader repos all target the wrong *activity* endpoint — rejected; `python-garminconnect` chosen). Spec written and revised to be generic/OSS-ready with the two-layer split. Git repo initialised (branch `main`, MIT LICENSE). Personal files moved to gitignored `source_data/` and the original commit that contained them was discarded — history is clean. Tracked files: `.gitignore`, `LICENSE`, `garmin-workout-push-spec.md`, `CLAUDE.md`.
- **No remote** configured yet.
- **Next step:** start building per the spec — likely `model` + `loader` + `builder` with unit tests first (pure, no network), then `client`, then `cli`, then `examples/` + `README`.
- **Open question to resolve before/while building:** sport scope for v1 — running only (with cycling/swimming as a designed-in extension point), or build all three sports now? Spec currently assumes running-first.
