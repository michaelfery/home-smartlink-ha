"""Switches: vacation mode (box) and open-window detection (rooms)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from homesmartlink import Room
from homesmartlink.settings import (
    vacation_active,
    vacation_description,
    with_open_window_detection,
    with_vacation,
)

from . import HomeSmartLinkConfigEntry
from .coordinator import HomeSmartLinkCoordinator
from .entity import HomeSmartLinkEntity, HomeSmartLinkRoomEntity, call_cloud

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeSmartLinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [VacationSwitch(coordinator)]
    entities += [OpenWindowSwitch(coordinator, room) for room in coordinator.data.home.rooms]
    async_add_entities(entities)


class VacationSwitch(HomeSmartLinkEntity, SwitchEntity):
    """Frost protection in every room until the return date (app settings screen)."""

    _attr_translation_key = "vacation"

    def __init__(self, coordinator: HomeSmartLinkCoordinator) -> None:
        super().__init__(coordinator, "vacation")

    @property
    def is_on(self) -> bool:
        return vacation_active(self.coordinator.data.home, dt_util.now().date())

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Like the app: back tomorrow; adjust with the return date entity.
        today = dt_util.now().date()
        tomorrow = today.fromordinal(today.toordinal() + 1)
        await call_cloud(
            self.coordinator.async_update_home(
                lambda home: with_vacation(home, tomorrow, today),
                vacation_description(tomorrow),
            )
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        today = dt_util.now().date()
        await call_cloud(
            self.coordinator.async_update_home(
                lambda home: with_vacation(home, None, today), vacation_description(None)
            )
        )


class OpenWindowSwitch(HomeSmartLinkRoomEntity, SwitchEntity):
    """Stop heating while a window is detected open (app room editor)."""

    _attr_translation_key = "open_window_detection"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: HomeSmartLinkCoordinator, room: Room) -> None:
        super().__init__(coordinator, room, "open_window_detection")

    @property
    def is_on(self) -> bool | None:
        room = self.room
        return room.open_window_detection_enabled if room else None

    async def _set(self, enabled: bool) -> None:
        number = self.room_number
        await call_cloud(
            self.coordinator.async_update_room(
                number, lambda home: with_open_window_detection(home, number, enabled)
            )
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
