"""Data update coordinator for Home-SmartLink."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from homesmartlink import (
    AuthenticationError,
    DeviceStatus,
    Gateway,
    HeaterMode,
    Home,
    HomeSmartLinkClient,
    HomeSmartLinkError,
    RateLimitError,
)

from .const import (
    CONF_DIAGNOSIS_INTERVAL,
    CONF_SCAN_INTERVAL,
    DEFAULT_DIAGNOSIS_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DIAGNOSIS_GRACE,
    DIAGNOSIS_TIMEOUT,
    DOMAIN,
    MAX_BACKOFF,
)

if TYPE_CHECKING:
    from . import HomeSmartLinkConfigEntry

_LOGGER = logging.getLogger(__name__)

type _Fetch[T] = Callable[[str], Awaitable[T]]


@dataclass(frozen=True, slots=True)
class HomeSmartLinkState:
    """Everything the entities need, refreshed on each poll."""

    home: Home
    gateway: Gateway | None
    status: DeviceStatus | None


class HomeSmartLinkCoordinator(DataUpdateCoordinator[HomeSmartLinkState]):
    """Poll one home and send commands to it."""

    config_entry: HomeSmartLinkConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HomeSmartLinkConfigEntry,
        client: HomeSmartLinkClient,
        home_id: str,
    ) -> None:
        self._base_interval = timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=self._base_interval,
        )
        self.client = client
        self.home_id = home_id
        self.box_device_id: str | None = None
        diagnosis_minutes = entry.options.get(CONF_DIAGNOSIS_INTERVAL, DEFAULT_DIAGNOSIS_INTERVAL)
        self._diagnosis_interval = diagnosis_minutes * 60
        self._last_diagnosis: float | None = None
        self._diagnosis_id: str | None = None
        self._diagnosis_requested_at: datetime | None = None
        self._failures = 0
        # Box reachability from diagnosis acknowledgements (None until known).
        self.box_online: bool | None = None

    @property
    def diagnosis_enabled(self) -> bool:
        return bool(self._diagnosis_interval)

    @property
    def status_max_age(self) -> timedelta | None:
        """Age after which a thermostat status is considered stale."""
        if not self._diagnosis_interval:
            return None
        return timedelta(seconds=2 * self._diagnosis_interval) + DIAGNOSIS_GRACE

    @property
    def last_diagnosis_requested_at(self) -> datetime | None:
        return self._diagnosis_requested_at

    async def _async_update_data(self) -> HomeSmartLinkState:
        try:
            home = await self.client.get_home(self.home_id)
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed("Home-SmartLink rejected the credentials") from err
        except RateLimitError as err:
            self._back_off(err.retry_after)
            raise UpdateFailed("Home-SmartLink is rate limiting requests") from err
        except HomeSmartLinkError as err:
            self._back_off()
            raise UpdateFailed(f"Cannot update Home-SmartLink: {err}") from err

        previous: HomeSmartLinkState | None = self.data
        gateway = await self._optional(
            self.client.get_gateway, previous.gateway if previous else None
        )
        status = await self._optional(
            self.client.get_device_status, previous.status if previous else None
        )
        await self._check_diagnosis()
        await self._maybe_request_diagnosis()

        if self._failures:
            self._failures = 0
            self.update_interval = self._base_interval
        return HomeSmartLinkState(home=home, gateway=gateway, status=status)

    async def _optional[T](self, fetch: _Fetch[T], fallback: T | None) -> T | None:
        """Secondary reads: keep the last known value instead of failing the poll."""
        try:
            return await fetch(self.home_id)
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed("Home-SmartLink rejected the credentials") from err
        except HomeSmartLinkError as err:
            _LOGGER.debug("Keeping previous value, %s failed: %s", fetch.__name__, err)
            return fallback

    async def _maybe_request_diagnosis(self) -> None:
        """Ask the box to refresh thermostat statuses (measured temperatures)."""
        if not self._diagnosis_interval:
            return
        now = time.monotonic()
        if (
            self._last_diagnosis is not None
            and now - self._last_diagnosis < self._diagnosis_interval
        ):
            return
        self._last_diagnosis = now
        try:
            self._diagnosis_id = await self.client.request_diagnosis(self.home_id)
            self._diagnosis_requested_at = dt_util.utcnow()
        except HomeSmartLinkError as err:
            _LOGGER.debug("Diagnosis request failed: %s", err)

    async def _check_diagnosis(self) -> None:
        """Follow the pending diagnosis: an acknowledgement means the box is online."""
        if self._diagnosis_id is None or self._diagnosis_requested_at is None:
            return
        try:
            diagnosis = await self.client.get_diagnosis(self._diagnosis_id)
        except HomeSmartLinkError as err:
            _LOGGER.debug("Diagnosis check failed: %s", err)
            return
        if diagnosis.acknowledged:
            self.box_online = True
            self._diagnosis_id = None
        elif dt_util.utcnow() - self._diagnosis_requested_at > DIAGNOSIS_TIMEOUT:
            self.box_online = False
            self._diagnosis_id = None

    def _back_off(self, retry_after: float | None = None) -> None:
        self._failures += 1
        delay = self._base_interval * 2**self._failures
        if retry_after:
            delay = max(delay, timedelta(seconds=retry_after))
        self.update_interval = min(delay, MAX_BACKOFF)

    async def async_set_room_state(
        self, room_number: int, mode: HeaterMode, manual_value: float | None = None
    ) -> None:
        """Send a command, show it immediately, then confirm with a refresh."""
        await self._apply(
            await self.client.set_room_state(
                self.home_id, room_number, mode, manual_value, today=dt_util.now().date()
            )
        )

    async def async_update_room(self, room_number: int, edit: Callable[[Home], Home]) -> None:
        """Room settings edit (eco/comfort, programming preference), like the room editor."""
        await self._apply(
            await self.client.update_room(
                self.home_id, room_number, edit, today=dt_util.now().date()
            )
        )

    async def async_update_program(self, edit: Callable[[Home], Home]) -> None:
        """Weekly program edit, like the app's program editor."""
        await self.async_update_home(edit)

    async def async_update_home(
        self, edit: Callable[[Home], Home], description: str | None = None
    ) -> None:
        """Home-wide edit (program, vacation, whole-home mode): whole-home frame."""
        await self._apply(
            await self.client.update_home(
                self.home_id, edit, description=description, today=dt_util.now().date()
            )
        )

    async def _apply(self, home: Home) -> None:
        if self.data is not None:
            self.async_set_updated_data(replace(self.data, home=home))
        await self.async_request_refresh()
