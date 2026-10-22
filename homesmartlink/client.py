"""Async client for the Home-SmartLink cloud API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import date
from typing import Any

import aiohttp

from .const import APP_AGENT, APP_VERSION, BASE_URL, DEFAULT_TIMEOUT, SESSION_HEADER
from .exceptions import (
    AuthenticationError,
    CannotConnectError,
    CommandFailedError,
    HomeSmartLinkError,
    RateLimitError,
)
from .frame import b64, build_tests, describe, encode_home, encode_room, validate_set_point
from .models import (
    DeviceStatus,
    Diagnosis,
    Gateway,
    HeaterMode,
    HeaterSettings,
    Home,
    Invitation,
)
from .status import parse_device_status

_LOGGER = logging.getLogger(__name__)

_AUTH_FAILURE_STATUSES = frozenset({401, 403})


class HomeSmartLinkClient:
    """Client for one Home-SmartLink account.

    The API has no refresh token: when the session token is rejected, the client
    signs in again with the stored credentials (once per request).
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._base_url = base_url
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._token: str | None = None
        self._login_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    def __repr__(self) -> str:
        # Never expose credentials or the session token.
        return f"{type(self).__name__}(authenticated={self._token is not None})"

    # -- authentication ----------------------------------------------------------

    async def login(self) -> list[Invitation]:
        """Sign in and return the homes the account can access."""
        async with self._login_lock:
            return await self._login()

    async def _login(self) -> list[Invitation]:
        data = await self._request(
            "POST",
            "api/1/signin",
            json_body={
                "email": self._email,
                "password": self._password,
                "agent": APP_AGENT,
                "version": APP_VERSION,
            },
            authenticated=False,
        )
        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise AuthenticationError("Sign-in response did not contain a session token")
        self._token = token
        _LOGGER.debug("Signed in to Home-SmartLink")
        invitation = data.get("invitation")
        return [Invitation.from_dict(invitation)] if isinstance(invitation, dict) else []

    async def _renew_session(self, rejected_token: str | None) -> None:
        async with self._login_lock:
            # Another request may already have renewed the session.
            if self._token is None or self._token == rejected_token:
                self._token = None
                await self._login()

    # -- read --------------------------------------------------------------------

    async def get_invitations(self) -> list[Invitation]:
        data = await self._request("GET", "api/1/auth", params={"version": str(APP_VERSION)})
        return [Invitation.from_dict(i) for i in data.get("invitations", [])]

    async def get_home(self, home_id: str) -> Home:
        return Home.from_dict(await self._request("GET", f"api/1/homes/{home_id}"))

    async def get_gateway(self, home_id: str) -> Gateway:
        return Gateway.from_dict(await self._request("GET", f"api/1/device/{home_id}"))

    async def get_device_status(self, home_id: str) -> DeviceStatus:
        """Thermostat status (incl. ambient temperature) from the last diagnosis."""
        return parse_device_status(await self._request("GET", f"api/1/deviceStatus/{home_id}"))

    async def request_diagnosis(self, home_id: str) -> str:
        """Ask the box to poll every thermostat; returns the diagnosis id."""
        data = await self._request("POST", "api/1/diagnosys", json_body={"homeId": home_id})
        _check_ok(data, "diagnosys")
        return str(data["id"])

    async def get_diagnosis(self, diagnosis_id: str) -> Diagnosis:
        return Diagnosis.from_dict(await self._request("GET", f"api/1/diagnosys/{diagnosis_id}"))

    # -- write -------------------------------------------------------------------

    async def set_room_state(
        self,
        home_id: str,
        room_number: int,
        mode: HeaterMode,
        manual_value: float | None = None,
        *,
        today: date | None = None,
    ) -> Home:
        """Change the mode (and optionally the manual set point) of one room."""

        def edit(home: Home) -> Home:
            current = home.room(room_number).heater_settings
            new_manual = current.manual_value if manual_value is None else manual_value
            if manual_value is not None:
                validate_set_point(new_manual, current.limitation_set_point)
            settings = HeaterSettings(
                current_mode=mode,
                manual_value=new_manual,
                economy_value=current.economy_value,
                standard_value=current.standard_value,
                limitation_set_point=current.limitation_set_point,
            )
            return home.with_room_settings(room_number, settings)

        return await self.update_room(home_id, room_number, edit, today=today)

    async def update_program(
        self, home_id: str, edit: Callable[[Home], Home], *, today: date | None = None
    ) -> Home:
        """Weekly-program edit (whole-home frame, no description, like the app)."""
        return await self.update_home(home_id, edit, today=today)

    async def update_room(
        self,
        home_id: str,
        room_number: int,
        edit: Callable[[Home], Home],
        *,
        today: date | None = None,
    ) -> Home:
        """Apply a room-settings edit like the app's room screens.

        Re-reads the home, sends the room frame (`action`) to the box, then saves
        the whole home document. `edit` may raise UnsupportedCommandError, in
        which case nothing is sent. Returns the home as written.
        """
        async with self._write_lock:
            updated = edit(await self.get_home(home_id))
            day = today or date.today()
            room = updated.room(room_number)
            await self._notify(
                {
                    "action": b64(
                        encode_room(room, vacation_return=updated.vacation_return_date, today=day)
                    ),
                    "description": describe(room),
                    "homeId": home_id,
                    "tests": build_tests(updated, today=day),
                }
            )
            await self._save(updated)
            return updated

    async def update_home(
        self,
        home_id: str,
        edit: Callable[[Home], Home],
        *,
        description: str | None = None,
        today: date | None = None,
    ) -> Home:
        """Apply a home-wide edit like the app's program, settings and home screens.

        Same as update_room, but the box receives the whole-home frame
        (`payload`): weekly programs, vacation mode, whole-home modes.
        """
        async with self._write_lock:
            updated = edit(await self.get_home(home_id))
            day = today or date.today()
            await self._notify(
                {
                    "payload": b64(encode_home(updated, today=day)),
                    "description": description,
                    "homeId": home_id,
                    "tests": build_tests(updated, today=day),
                }
            )
            await self._save(updated)
            return updated

    async def _notify(self, body: dict[str, Any]) -> None:
        _check_ok(await self._request("POST", "api/1/device/notify", json_body=body), "notify")

    async def _save(self, home: Home) -> None:
        _check_ok(
            await self._request("PUT", "api/1/homes/", json_body=home.to_update_payload()),
            "home update",
        )

    # -- transport ---------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        authenticated: bool = True,
    ) -> Any:
        if authenticated and self._token is None:
            await self.login()

        for attempt in (1, 2):
            token = self._token
            headers = {SESSION_HEADER: token} if authenticated and token else {}
            try:
                async with self._session.request(
                    method,
                    self._base_url + path,
                    json=json_body,
                    params=params,
                    headers=headers,
                    timeout=self._timeout,
                ) as resp:
                    if resp.status in _AUTH_FAILURE_STATUSES:
                        if authenticated and attempt == 1:
                            _LOGGER.debug(
                                "Session rejected (HTTP %s), signing in again", resp.status
                            )
                            await self._renew_session(token)
                            continue
                        raise AuthenticationError(f"{method} {path}: HTTP {resp.status}")
                    _raise_for_status(resp, method, path, authenticated)
                    return await resp.json(content_type=None)
            except TimeoutError as err:
                raise CannotConnectError(f"{method} {path}: timeout") from err
            except aiohttp.ClientError as err:
                raise CannotConnectError(f"{method} {path}: {type(err).__name__}") from err
            except ValueError as err:
                raise HomeSmartLinkError(f"{method} {path}: invalid JSON") from err
        raise AuthenticationError(f"{method} {path}: session rejected after sign-in")


def _raise_for_status(
    resp: aiohttp.ClientResponse, method: str, path: str, authenticated: bool
) -> None:
    status = resp.status
    if status < 400:
        return
    if status == 429:
        retry_after: float | None
        try:
            retry_after = float(resp.headers.get("Retry-After", ""))
        except ValueError:
            retry_after = None
        raise RateLimitError(f"{method} {path}: rate limited", retry_after)
    if status >= 500:
        raise CannotConnectError(f"{method} {path}: HTTP {status}")
    if not authenticated:
        # Sign-in failures (wrong credentials were never captured: any 4xx).
        raise AuthenticationError(f"{method} {path}: HTTP {status}")
    raise HomeSmartLinkError(f"{method} {path}: HTTP {status}")


def _check_ok(data: Any, what: str) -> None:
    if not isinstance(data, dict) or data.get("status") != "OK":
        raise CommandFailedError(f"Unexpected {what} response")
