# Technical Spec — `garmin-workout-push`

**Status:** draft for review
**Date:** 2026-06-09
**One-liner:** Define structured workouts as simple files and push them to Garmin Connect, where they sync to any Garmin device that supports structured workouts.

---

## 1. What we're building

An open-source Python project in **two cleanly separated layers**:

1. **A library** (`garmin_workout_push`) that turns a generic, device-agnostic **workout definition** into a native Garmin Connect structured workout and pushes it to a user's account via the unofficial Connect API. Importable and usable on its own.
2. **A thin CLI** on top of it that takes **one workout file** and pushes it. The outer layer holds no workout-building logic — it parses arguments, gathers credentials, and calls the library.

Nothing in the core is tied to a specific watch model. Garmin Connect handles the device sync; any Garmin device that supports structured workouts (Forerunner, Fenix, Epix, Venu, Edge, etc.) receives it through the user's normal Connect ↔ device link.

### Why it exists
Getting a *structured* workout (with targets the device enforces) from a plan onto a Garmin device is high-friction: the web UI imports activities, not workouts; USB sideload needs a working cable; third-party routes are export-only or power/bike-only. The Connect *workout-service* API is the one route that accepts structured workouts with targets — this project wraps it behind a clean library and a one-command CLI.

---

## 2. Architecture — the library / CLI boundary

```
┌─────────────────────────────────────────────┐
│ CLI layer  (garmin_workout_push.cli)         │  thin, swappable
│  • parse args (one file path, flags)         │
│  • prompt for credentials / MFA              │
│  • call library, render result / errors      │
└───────────────┬─────────────────────────────┘
                │  imports, no Garmin logic of its own
┌───────────────▼─────────────────────────────┐
│ Library  (garmin_workout_push)               │  reusable core
│                                              │
│  loader     parse + validate a workout file  │
│             → WorkoutDefinition (model)       │
│  builder    WorkoutDefinition → typed Garmin  │
│             workout (RunningWorkout, …)        │
│  client     auth, push, schedule, verify      │
│             (wraps python-garminconnect)       │
└──────────────────────────────────────────────┘
```

**The contract:** anything the CLI can do, a third-party importer can do by calling the library directly — `from garmin_workout_push import load_workout, build_workout, GarminWorkoutClient`. The CLI is one of potentially many front-ends (a GUI, a web service, a scheduled job) and gets no special privileges.

**No I/O or interactivity in the core.** The library never prompts, never reads stdin, never prints. Credentials are *passed in* (e.g. an auth object or a callback for MFA); the library raises typed exceptions rather than exiting. All terminal interaction lives in the CLI layer.

---

## 3. Library design (public API)

Indicative surface — names to firm up in implementation, but the shape is the contract:

### 3.1 Models (`garmin_workout_push.model`)
- `WorkoutDefinition` — the parsed, validated, sport-agnostic representation: name, sport, optional schedule date, ordered list of `Step`.
- `Step` — `kind` (warmup / active / recovery / interval / cooldown / rest), a **duration** (one of: distance, time, or open/lap-press), and an optional **target** (see below).
- `Target` — one of: `pace` (range, entered as `mm:ss/km` or `/mi`), `heart_rate` (bpm or zone), `cadence`, `power`, or `open` (no target). Pace/speed conversions handled here.
- Repeats: a step group that repeats N times (so `3 × (3k @ pace + 1.5k easy)` is expressible without copy-paste).

These are validated value objects (Pydantic). They are the boundary between "user's file" and "Garmin's schema" — neither side leaks into the other.

### 3.2 Loader (`garmin_workout_push.loader`)
- `load_workout(path | dict) -> WorkoutDefinition` — parse YAML/JSON, validate, raise `WorkoutValidationError` with clear messages on bad input. Pure; no network.

### 3.3 Builder (`garmin_workout_push.builder`)
- `build_workout(WorkoutDefinition) -> <typed garminconnect workout>` — map the generic model to the library's typed models (`RunningWorkout` etc.), converting units (pace → m/s ×1000, etc.) and step kinds → Garmin intensities. Sport-extensible: running implemented first; cycling/swimming are a clear extension point (the underlying lib already provides `CyclingWorkout`/`SwimmingWorkout`).

### 3.4 Client (`garmin_workout_push.client`)
- `GarminWorkoutClient(auth)` — wraps `python-garminconnect`.
  - `.push(workout) -> workout_id`
  - `.schedule(workout_id, date)`
  - `.find(name) / .verify(workout_id) -> summary` for confirmation (see §8)
  - `.delete(workout_id)` for cleanup
- Auth is injected (credentials + optional MFA callback). The client owns no UI.

---

## 4. Input schema (generic, device-agnostic)

A small YAML or JSON file. Sport-aware, target-type-aware, with repeats. Example (the running session that motivated the project, now just one example among many):

```yaml
name: "Long run 16k — 2×3k tempo"
sport: running          # running | cycling | swimming (running first)
date: 2026-06-15        # optional; if present, --schedule puts it on the calendar
steps:
  - { kind: warmup,   distance_km: 4.0, target: open }
  - repeat: 2
    steps:
      - { kind: active,   distance_km: 3.0, target: { pace: ["4:55", "4:50"] }, name: "Tempo" }
      - { kind: recovery, distance_km: 1.5, target: open }
  - { kind: cooldown, distance_km: 4.5, target: open }
```

Supported, to make it broadly useful (not just one runner's plan):
- **Durations:** `distance_km` / `distance_m` / `distance_mi`, `time` (`mm:ss`), or `open` (lap-button press).
- **Targets:** `pace` range, `heart_rate` (bpm range or zone), `cadence`, `power`, or `open`.
- **Repeats:** nest steps under `repeat: N`.
- **Units:** metric or imperial pace/distance accepted; converted internally.

The schema is documented in the README so others can author files without reading code.

---

## 5. Tech stack & packages

- **Language:** Python 3.11+
- **Core dependency:** `python-garminconnect >= 0.3.5` with the workout extra — `pip install "garminconnect[workout]"` — providing typed workout models + `upload_running_workout()` / `schedule_workout()` against the *workout-service* endpoint. Pulls in `curl_cffi` and `pydantic`.
- **Input:** `pyyaml` (YAML support; JSON needs nothing).
- **CLI:** stdlib `argparse` + `getpass`. No heavy CLI framework.
- **Packaging:** `pyproject.toml`; two console-script entry points → `garmin-workout-push` (primary) and `gwpush` (short alias), both pointing at `garmin_workout_push.cli:main`.

Deliberately minimal: `garminconnect` + `pyyaml`. No credentials/config dependency (see §7).

> **FIT note:** this project does **not** create, encode, or transfer FIT files. Workouts are sent as JSON to the Connect workout-service endpoint; the device sync is Garmin's internal concern. FIT appears only in the appendix as abandoned prior art.

---

## 6. CLI layer

- **Invocation:** `garmin-workout-push WORKOUT_FILE [--schedule] [--dry-run] [--json]`
  - `WORKOUT_FILE` is mandatory and is the *only* thing that determines what is uploaded. One file in, one workout out — every time, explicitly. The CLI never scans, selects, or batches.
  - `--schedule` — also schedule to the file's `date`.
  - `--dry-run` — load + build + validate and print the resolved workout; no network, no auth.
  - `--json` — machine-readable output (workout id, status) for scripting.
- **Credentials:** prompted interactively each run (§7).
- **Exit codes:** 0 success; non-zero with a clear message on validation / auth / API failure. Library exceptions are caught here and rendered; they never escape as tracebacks in normal use.

---

## 7. Auth & credentials

Interactive each run, nothing persisted — the safe default for a shared open-source tool.

- Email + password prompted at runtime via `getpass` (password not echoed). No `.env`, no env vars by default, no credentials in source or logs.
- **MFA:** if challenged, an MFA callback prompts for the code in the terminal. The library accepts the callback; the prompt itself lives in the CLI.
- **Token persistence disabled by default:** the underlying library's token cache (`~/.garminconnect/`) is suppressed so every run re-authenticates and nothing sensitive is left at rest. (A future opt-in flag could enable caching for users who want it — off by default.)
- `.gitignore` already excludes `.env`, `.garminconnect/`, and `garmin_tokens.json` defensively.

---

## 8. Verification

Two layers, because an API 200 is not proof the device shows targets:

1. **API-side (automated):** after push, `find`/`verify` confirms the workout exists with the expected name, step count, durations, and targets. `--dry-run` covers build correctness without touching the network.
2. **Device-side (manual, user-run):** confirm it syncs to the watch/computer and that targets display on the policed steps. Only the user can do this on the device; documented in the README as the real acceptance test.

**Example test cases** (shipped under `examples/`): a distance-based tempo session (warmup / 2× tempo+recovery / cooldown) and a simple `3 × 3k @ pace` session — exercising repeats, pace targets, and open steps.

---

## 9. Non-goals

- **No plan parsing.** The tool does not read prose training plans or pick "this week's session." One explicit file in, one workout out.
- **No fetch-and-push / batching / selection logic.** Ever.
- **No activity upload.** That's a different endpoint and a solved problem elsewhere.
- **No FIT generation or transfer** in the core path.
- **No credential storage** by default.
- **Not a full Garmin Connect SDK** — scoped to building and pushing structured workouts.

---

## 10. Risks & caveats

- **Unofficial API:** can break when Garmin changes the backend. Mitigated by depending on a maintained library (`python-garminconnect`, 2.4k★, active) and keeping the surface small. README states this plainly.
- **ToS:** personal-account use; users accept the risk knowingly. Documented.
- **MFA friction:** with persistence off, login + MFA happen every run — accepted trade-off, with a future opt-in cache noted.
- **Library churn:** the typed-workout API is new (shipped Jun 2026); pin `>=0.3.5` and watch minor versions.

---

## 11. Repo layout (proposed)

```
garmin-workout-push/
├── src/garmin_workout_push/
│   ├── __init__.py        # public exports: load_workout, build_workout, GarminWorkoutClient
│   ├── model.py           # WorkoutDefinition, Step, Target, repeats
│   ├── loader.py          # load_workout()
│   ├── builder.py         # build_workout()  → typed garminconnect workout
│   ├── client.py          # GarminWorkoutClient (auth, push, schedule, verify)
│   └── cli.py             # argparse entry point (main)
├── examples/
│   ├── tempo-16k.yaml
│   └── 3x3k.yaml
├── tests/                 # loader/builder unit tests (no network); client mocked
├── README.md              # schema docs, usage, caveats
├── pyproject.toml
├── LICENSE                # MIT
└── .gitignore
```

---

## 12. Appendix — prior art / fallback (not part of the library)

Kept for context, outside the core:
- **`build_week2_fit.py` + USB sideload to `GARMIN/NewFiles/`** — a dependency-free FIT *workout* encoder from before this project; the offline route if the API dies, contingent on a working USB cable. Lives in the repo history / an `attic/` or `docs/` note, **not** in `src/`.
- The personal training-plan documents (`gold-coast-half-plan.md`, `running-calendar-2026-27.md`, the handoff) are **personal content, not part of the OSS package** — recommend moving them out of the repo (or into a private/ignored path) before publishing. See §13 follow-up.

---

## 13. Decisions log

- **Name:** `garmin-workout-push` (repo + package `garmin_workout_push` + CLI; `gwpush` alias). *(2026-06-09)*
- **Two layers:** reusable library + thin CLI; no Garmin/build logic in the CLI; no I/O in the core. *(2026-06-09)*
- **Device-agnostic:** no watch model in the core; any structured-workout-capable Garmin device via Connect sync. *(2026-06-09)*
- **FIT:** not used in the core path — JSON to the workout-service endpoint only. *(2026-06-09)*
- **Input:** explicit YAML/JSON file; no plan parsing. *(2026-06-09)*
- **Scope:** one file → one workout, explicit, every time. *(2026-06-09)*
- **Run mode:** one-shot CLI; no scheduling daemon. *(2026-06-09)*
- **Credentials:** interactive each run, nothing persisted by default. *(2026-06-09)*

### Open follow-up
- Move/remove the personal plan docs and the FIT artifacts from the publishable repo (needs your go-ahead — I won't delete your files without asking).
