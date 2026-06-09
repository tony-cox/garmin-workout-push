# garmin-workout-push

Define structured workouts as simple YAML/JSON files and push them to **Garmin
Connect**, where they sync to any Garmin device that supports structured
workouts (Forerunner, Fenix, Epix, Venu, Edge, …).

Getting a *structured* workout — one with targets the device actively enforces —
onto a watch is awkward: the Connect web UI imports activities, not workouts;
USB sideload needs a working cable; most third-party routes are export-only or
power/bike-only. The Connect **workout-service** API is the one route that
accepts structured workouts with targets. This project wraps it behind a small
library and a one-command CLI.

> [!WARNING]
> **This relies on an unofficial, reverse-engineered Garmin API and can break at
> any time, without warning.** There is no public API, no contract, and no
> endorsement from Garmin. Garmin can change the backend, tighten bot
> protection, or block access on any day, and when they do this tool may stop
> working — partially or completely — with no notice and no guaranteed fix.
> Logins in particular are fronted by Cloudflare and can fail intermittently
> (403/429) even when nothing is wrong with your file or credentials. Treat it
> as a convenience that may vanish, not a dependable integration. **Use at your
> own risk** — see [Caveats](#caveats) before relying on it.

```bash
pip install garmin-workout-push        # (or: pip install -e . from a clone)

garmin-workout-push examples/tempo-16k.yaml            # push it
garmin-workout-push examples/tempo-16k.yaml --schedule # push + put on the calendar
garmin-workout-push examples/tempo-16k.yaml --dry-run  # build + print, no network
```

The short alias `gwpush` is installed too.

---

## How it works

Two cleanly separated layers:

- **Library** (`garmin_workout_push`) — the reusable core:
  `loader` (parse + validate a file → `WorkoutDefinition`) →
  `builder` (model → typed Garmin workout) →
  `client` (auth, push, schedule, verify). No I/O, no prompts, no printing;
  credentials are injected and errors are raised as typed exceptions.
- **CLI** (`garmin_workout_push.cli`) — a thin front-end: it parses arguments,
  prompts for credentials/MFA, calls the library, and renders the result.
  Anything the CLI does is doable by importing the library directly.

```python
from garmin_workout_push import load_workout, build_workout, GarminWorkoutClient

definition = load_workout("examples/tempo-16k.yaml")
workout = build_workout(definition)

client = GarminWorkoutClient("me@example.com", "password", prompt_mfa=lambda: input("MFA: "))
workout_id = client.push(workout)
client.schedule(workout_id, definition.date)        # optional
print(client.verify(workout_id)["workoutName"])     # API-side confirmation
```

---

## Workout file schema

A workout is a small mapping with a `name`, a `sport`, an optional `date`, and a
list of `steps`.

```yaml
name: "Long run 16k — 2×3k tempo"
sport: running           # running | cycling | swimming
date: 2026-06-15         # optional; used by --schedule (YYYY-MM-DD)
steps:
  - { kind: warmup,   distance_km: 4.0, target: open }
  - repeat: 2
    steps:
      - { kind: active,   distance_km: 3.0, target: { pace: ["4:50", "4:55"] }, name: "Tempo" }
      - { kind: recovery, distance_km: 1.5, target: open }
  - { kind: cooldown, distance_km: 4.5, target: open }
```

### Step `kind`
`warmup` · `active` · `interval` · `recovery` · `cooldown` · `rest`.
(`active` and `interval` both map to Garmin's work step.)

### Duration — exactly one per step
| key | meaning |
|---|---|
| `distance_km`, `distance_m`, `distance_mi` | end after a distance |
| `time: "mm:ss"` (or `"h:mm:ss"`) | end after a time |
| `lap: true` | open step — ends on a lap-button press |

### Target — optional (defaults to `open` = no target)
| form | meaning |
|---|---|
| `target: open` *(or omit)* | no target |
| `target: { pace: ["4:50", "4:55"] }` | pace range; add `unit: mi` for per-mile (default `km`) |
| `target: { heart_rate: [140, 155] }` | heart-rate range in bpm |
| `target: { heart_rate: { zone: 3 } }` | heart-rate zone 1–5 |
| `target: { cadence: [170, 180] }` | cadence range (spm/rpm) |
| `target: { power: [200, 250] }` | power range in watts |
| `target: { power: { zone: 4 } }` | power zone 1–7 |

Pace bounds may be given in either order — they're sorted internally, so
`["4:50", "4:55"]` and `["4:55", "4:50"]` are equivalent. Distances and paces are accepted in metric or imperial and
normalised. Repeats nest a list of steps under `repeat: N` (one level deep).

JSON files work too — JSON is valid YAML.

---

## CLI

```
garmin-workout-push WORKOUT_FILE [--schedule] [--dry-run] [--json] [--email EMAIL] [--cn]
```

- `WORKOUT_FILE` — the one file that determines what is uploaded. One file in,
  one workout out, every time. The tool never scans, selects, or batches.
- `--schedule` — also schedule the workout on the file's `date`.
- `--dry-run` — load, build, and print the resolved workout; **no auth, no
  network**. The fastest way to check a file.
- `--json` — machine-readable output for scripting.
- `--email` — supply the account email (otherwise prompted).
- `--cn` — use the Garmin China backend (`garmin.cn`). Only for accounts
  registered on Garmin's separate mainland-China service (佳明); leave it off for
  normal global `garmin.com` accounts.

**Exit codes:** `0` ok · `2` validation error · `3` build error · `4` auth/API
error · `1` unexpected.

---

## Authentication

Interactive each run, nothing persisted — the safe default for a shared tool.

- Email + password are prompted at runtime (password via `getpass`, not echoed).
- **MFA:** if Garmin challenges, you're prompted for the code in the terminal.
- **No token cache by default:** the client logs in without a tokenstore, so
  each run re-authenticates and nothing sensitive is left on disk. (The library
  supports opt-in caching via `GarminWorkoutClient(..., persist_tokens=True)`;
  leave the `GARMINTOKENS` environment variable unset to keep persistence off.)

`.gitignore` defensively excludes `.env`, `.garminconnect/`, and
`garmin_tokens.json`.

---

## Verifying it worked

1. **API-side (automatic):** after a push the CLI fetches the workout back from
   Connect and reports the executable step count. `--dry-run` checks build
   correctness without the network.
2. **Device-side (manual — the real acceptance test):** sync your watch/computer
   and confirm the workout appears **and that targets display on the policed
   steps**. Only you can verify this on the device.

---

## Caveats

**Read these before depending on the tool for anything that matters.**

- **Unofficial, reverse-engineered API — it can break at any time.** There is no
  official Garmin workout API. This rides Garmin's private *workout-service*
  endpoints via [`python-garminconnect`](https://pypi.org/project/garminconnect/).
  Garmin owes no backwards compatibility and gives no deprecation notice: an
  endpoint, payload shape, or auth flow can change overnight and silently break
  pushes, scheduling, or login. It may also stop working **entirely** and stay
  that way. We pin `python-garminconnect>=0.3.5` and keep our surface small to
  limit blast radius, but **there is no guarantee any given push will work, and
  no promise of a timely fix.**
- **Login is fragile by design.** Garmin's SSO sits behind Cloudflare bot
  protection. The underlying library uses TLS-fingerprint impersonation
  (`curl_cffi`) to get through, and even then logins can fail intermittently
  with `403` (bot challenge) or `429` (rate limit) — often transient, sometimes
  not, and unrelated to your workout file. Retrying later usually helps; nothing
  in this tool can fix it if Garmin tightens the gate.
- **No warranty.** MIT, "as is" (see [LICENSE](./LICENSE)). This is a
  best-effort convenience, not a supported product or a dependable integration.
  Do not build anything safety- or schedule-critical on top of it without your
  own fallback.
- **Terms of service / account risk.** Automating against Connect with your
  personal credentials may run against Garmin's ToS, and aggressive use could in
  principle get an account rate-limited or flagged. For personal-account use;
  you accept that risk knowingly. Be gentle — one file, one push.
- **Always keep a manual fallback.** Because the API can disappear, don't let it
  become your only way to get a workout onto the watch. The Connect app/web and
  on-device workout creation still work when this doesn't.
- **MFA friction.** With token persistence off (the default), login + MFA happen
  every run — an accepted trade-off for not storing credentials.

If a push suddenly stops working, the most likely causes — in order — are a
Garmin-side change, a Cloudflare login block, or a `python-garminconnect`
version that needs updating. Check that project's issue tracker first; the break
is usually upstream, not in your file.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest          # loader + builder run offline; client and CLI are mocked
```

## License

MIT — see [LICENSE](./LICENSE).
