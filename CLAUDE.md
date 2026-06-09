# garmin-workout-push

> **Status: built (v0.1.0), passing tests.** The library + CLI are implemented under `src/garmin_workout_push/` per the spec. [`garmin-workout-push-spec.md`](./garmin-workout-push-spec.md) remains the design source of truth; this file is the quick orientation + handoff. Not yet device-tested against a live Garmin account (see Verification below).

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

## Repo layout (built)

`src/garmin_workout_push/{model,loader,builder,client,cli,exceptions}.py` · `examples/{tempo-16k,3x3k}.yaml` · `tests/` (loader/builder run offline, client + CLI mocked — 48 tests) · `pyproject.toml` (console scripts `garmin-workout-push` + `gwpush` alias) · `README.md`.

**Build/test notes (sandbox):** the dependency installs into a Python 3.12 venv at `.venv/` (gitignored); the default sandbox python is 3.14, which lacks `curl_cffi` wheels. Run tests with `.venv/bin/python -m pytest`. The venv was bootstrapped with `get-pip.py` because `ensurepip` is missing.

**One schema decision worth knowing:** `garminconnect.workout.ConditionType.DISTANCE = 1` is *wrong* for the live workout-service (and unused by the library's own helpers). The builder defines authoritative end-condition ids itself: `1=lap.button`, `2=time`, `3=distance`, `7=iterations` (time/iterations confirmed by the library's working `create_*` helpers). See `builder.py` docstring.

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

- **Done:** full implementation (model/loader/builder/client/cli/exceptions), two example workouts, 48 passing tests, README with schema docs, `pyproject.toml` with both console scripts. Sport scope resolved: **all three sports wired** (running/cycling/swimming) since the builder machinery is shared and `garminconnect` provides all three typed classes — running is still the proven/tested path.
- **Not committed yet** — working tree only; no commit made (waiting on user). **No remote** configured.
- **Open follow-up (unchanged from spec §13):** move/remove the personal plan docs + FIT artifacts before publishing (they're already gitignored under `source_data/`).
- **The one thing left that code can't do:** device-side verification — push a real workout to a live account and confirm targets display on the watch. The CLI does API-side verification automatically; the device check is manual.
