"""Push, schedule, and verify workouts against Garmin Connect.

Thin wrapper over ``python-garminconnect``. Credentials and an optional MFA
callback are injected; the client owns no UI — it never prompts or prints. It
raises ``PushError`` for workout-level failures and lets the underlying
library's authentication/transport exceptions propagate unchanged.

Token persistence is **off by default** (``persist_tokens=False``): the
``Garmin.login`` call is made without a tokenstore, so each run re-authenticates
and nothing is written to disk. (Note: if ``persist_tokens`` is False but the
``GARMINTOKENS`` environment variable is set, the underlying library may still
read it — the safe default for this tool is to leave that unset.)
"""

from __future__ import annotations

import datetime
from typing import Any, Callable

from .exceptions import PushError


class GarminWorkoutClient:
    """Authenticated gateway to the Connect workout-service.

    :param email: Garmin account email.
    :param password: Garmin account password.
    :param prompt_mfa: zero-arg callable returning an MFA code as a string,
        invoked only if Garmin challenges for one. If ``None`` and MFA is
        required, the underlying library raises an authentication error.
    :param is_cn: use Garmin's mainland-China backend (``garmin.cn``) instead of
        the global ``garmin.com``. Only for accounts registered on the Chinese
        service; leave False for normal global accounts.
    :param persist_tokens: opt in to the library's on-disk token cache.
    :param tokenstore: where to cache tokens when ``persist_tokens`` is True.
    :param api: a pre-built ``garminconnect.Garmin``-like object, primarily for
        testing. When provided, credentials are not used to construct one.
    """

    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        *,
        prompt_mfa: Callable[[], str] | None = None,
        is_cn: bool = False,
        persist_tokens: bool = False,
        tokenstore: str | None = None,
        api: Any | None = None,
    ) -> None:
        self._email = email
        self._password = password
        self._prompt_mfa = prompt_mfa
        self._is_cn = is_cn
        self._persist_tokens = persist_tokens
        self._tokenstore = tokenstore or "~/.garminconnect"
        self._api = api
        self._logged_in = False

    # ----------------------------------------------------------------- #
    #  Auth
    # ----------------------------------------------------------------- #

    def login(self) -> None:
        """Authenticate. Safe to call more than once (later calls are no-ops)."""
        if self._logged_in:
            return
        if self._api is None:
            from garminconnect import Garmin

            self._api = Garmin(
                email=self._email,
                password=self._password,
                prompt_mfa=self._prompt_mfa,
                is_cn=self._is_cn,
            )
        if self._persist_tokens:
            self._api.login(self._tokenstore)
        else:
            self._api.login()
        self._logged_in = True

    def _ensure_login(self) -> None:
        if not self._logged_in:
            self.login()

    # ----------------------------------------------------------------- #
    #  Workout operations
    # ----------------------------------------------------------------- #

    def push(self, workout: Any) -> int:
        """Upload a built workout and return its Garmin workout id.

        ``workout`` is a typed workout from :func:`build_workout` (anything with
        ``to_dict``) or a ready JSON-able dict.
        """
        self._ensure_login()
        payload = workout.to_dict() if hasattr(workout, "to_dict") else workout
        result = self._api.upload_workout(payload)
        workout_id = result.get("workoutId") if isinstance(result, dict) else None
        if workout_id is None:
            raise PushError(f"upload did not return a workoutId (got: {result!r})")
        return int(workout_id)

    def schedule(self, workout_id: int | str, date: datetime.date | str) -> dict[str, Any]:
        """Place an already-pushed workout on the Connect calendar for ``date``."""
        self._ensure_login()
        date_str = date.isoformat() if isinstance(date, datetime.date) else str(date)
        return self._api.schedule_workout(workout_id, date_str)

    def verify(self, workout_id: int | str) -> dict[str, Any]:
        """Fetch the stored workout so a caller can confirm it round-tripped."""
        self._ensure_login()
        return self._api.get_workout_by_id(workout_id)

    def find(self, name: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return stored workouts whose name matches ``name`` (case-insensitive)."""
        self._ensure_login()
        wanted = name.strip().casefold()
        workouts = self._api.get_workouts(0, limit) or []
        return [w for w in workouts if str(w.get("workoutName", "")).casefold() == wanted]

    def delete(self, workout_id: int | str) -> Any:
        """Delete a workout template from the Connect library."""
        self._ensure_login()
        return self._api.delete_workout(workout_id)
