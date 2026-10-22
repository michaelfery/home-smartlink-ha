"""Climate entities: one per Home-SmartLink thermostat."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import time
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from homesmartlink import HeaterMode, Home, ProgramEvent, Room
from homesmartlink.const import MAX_SET_POINT, MIN_SET_POINT, SET_POINT_STEP
from homesmartlink.program import (
    WEEKDAYS,
    ProgramMode,
    SimplifiedRange,
    active_event,
    days_from_mask,
    program_events,
    target_temperature,
    with_advanced_slot,
    with_simplified_days,
    with_simplified_times,
)

from . import HomeSmartLinkConfigEntry
from .coordinator import HomeSmartLinkCoordinator
from .entity import HomeSmartLinkRoomEntity, call_cloud

PARALLEL_UPDATES = 1

_HVAC_MODES = {
    HeaterMode.STOP: HVACMode.OFF,
    HeaterMode.ANTIFREEZE: HVACMode.HEAT,
    HeaterMode.MANUAL: HVACMode.HEAT,
    HeaterMode.PROGRAM: HVACMode.AUTO,
}
_SIMPLIFIED_NAMES = {7: SimplifiedRange.MORNING, 9: SimplifiedRange.DAY, 8: SimplifiedRange.EVENING}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeSmartLinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        HomeSmartLinkClimate(coordinator, room) for room in coordinator.data.home.rooms
    )


def _hhmm(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def _describe_slot(event: ProgramEvent) -> dict[str, Any]:
    return {
        "start": _hhmm(event.start_hour, event.start_minute),
        "end": _hhmm(event.end_hour, event.end_minute),
        "days": [WEEKDAYS[d] for d in sorted(days_from_mask(event.recurrence))],
    }


class HomeSmartLinkClimate(HomeSmartLinkRoomEntity, ClimateEntity):
    """A pilot-wire heater driven by its Home-SmartLink thermostat."""

    _attr_name = None
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.AUTO, HVACMode.OFF]
    _attr_preset_modes = [PRESET_NONE, PRESET_COMFORT, PRESET_ECO, PRESET_AWAY]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = SET_POINT_STEP
    _attr_min_temp = MIN_SET_POINT

    def __init__(self, coordinator: HomeSmartLinkCoordinator, room: Room) -> None:
        super().__init__(coordinator, room, "climate")

    @property
    def _mode(self) -> HeaterMode | None:
        room = self.room
        mode = room.heater_settings.current_mode if room else None
        return mode if isinstance(mode, HeaterMode) else None

    @property
    def hvac_mode(self) -> HVACMode | None:
        mode = self._mode
        return _HVAC_MODES[mode] if mode else None

    @property
    def preset_mode(self) -> str | None:
        room, mode = self.room, self._mode
        if room is None or mode is None:
            return None
        if mode is HeaterMode.ANTIFREEZE:
            return PRESET_AWAY
        if mode is not HeaterMode.MANUAL:
            return None
        settings = room.heater_settings
        if settings.manual_value == settings.standard_value:
            return PRESET_COMFORT
        if settings.manual_value == settings.economy_value:
            return PRESET_ECO
        return PRESET_NONE

    @property
    def target_temperature(self) -> float | None:
        """What the thermostat aims at now; in auto, comfort or eco per the program."""
        room = self.room
        if room is None or self._mode in (None, HeaterMode.STOP):
            return None
        return target_temperature(room, dt_util.now())

    @property
    def current_temperature(self) -> float | None:
        status = self.room_status
        return status.ambient_temperature if status else None

    @property
    def max_temp(self) -> float:
        room = self.room
        if room is None:
            return MAX_SET_POINT
        return min(MAX_SET_POINT, room.heater_settings.limitation_set_point)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        room = self.room
        if room is None:
            return None
        settings = room.heater_settings
        active = active_event(room, dt_util.now())
        attributes: dict[str, Any] = {
            "programming_preference": "simplified" if room.ecopilot_enabled else "advanced",
            "eco_temperature": settings.economy_value,
            "comfort_temperature": settings.standard_value,
        }
        if room.ecopilot_enabled:
            attributes["program"] = {
                _SIMPLIFIED_NAMES[e.event_id].value: _describe_slot(e)
                for e in program_events(room)
                if e.event_id in _SIMPLIFIED_NAMES
            }
            attributes["active_slot"] = (
                _SIMPLIFIED_NAMES[active.event_id].value
                if active and active.event_id in _SIMPLIFIED_NAMES
                else None
            )
        else:
            attributes["program"] = {
                str(e.event_id): _describe_slot(e) for e in program_events(room)
            }
            attributes["active_slot"] = active.event_id if active else None
        if self._mode is HeaterMode.PROGRAM:
            attributes["program_state"] = "comfort" if active else "eco"
        return attributes

    async def _send(self, mode: HeaterMode, manual_value: float | None = None) -> None:
        await call_cloud(
            self.coordinator.async_set_room_state(self.room_number, mode, manual_value)
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode is HVACMode.OFF:
            await self._send(HeaterMode.STOP)
        elif hvac_mode is HVACMode.AUTO:
            await self._send(HeaterMode.PROGRAM)
        else:
            await self._send(HeaterMode.MANUAL)

    async def async_turn_on(self) -> None:
        await self._send(HeaterMode.MANUAL)

    async def async_turn_off(self) -> None:
        await self._send(HeaterMode.STOP)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        room = self.room
        if room is None:
            return
        settings = room.heater_settings
        if preset_mode == PRESET_AWAY:
            await self._send(HeaterMode.ANTIFREEZE)
        elif preset_mode == PRESET_COMFORT:
            await self._send(HeaterMode.MANUAL, settings.standard_value)
        elif preset_mode == PRESET_ECO:
            await self._send(HeaterMode.MANUAL, settings.economy_value)
        else:
            await self._send(HeaterMode.MANUAL)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if kwargs.get(ATTR_HVAC_MODE) is HVACMode.OFF:
            await self._send(HeaterMode.STOP)
            return
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
                await self.async_set_hvac_mode(hvac_mode)
            return
        # Like the app dial: a set point always means Manual mode.
        await self._send(HeaterMode.MANUAL, float(temperature))

    # -- entity services (services.py) -------------------------------------------

    async def async_set_program_slot(
        self,
        slot: int,
        start: time,
        end: time,
        days: list[str],
        mode: str | None = None,
    ) -> None:
        """Edit one of the six slots of an Advanced program."""
        number = self.room_number
        weekdays = [WEEKDAYS.index(d) for d in days]
        program_mode = ProgramMode[mode.upper()] if mode else None
        await call_cloud(
            self.coordinator.async_update_program(
                lambda home: with_advanced_slot(
                    home, number, slot, start, end, weekdays, program_mode
                )
            )
        )

    async def async_set_simplified_program(self, **fields: Any) -> None:
        """Edit the Morning/Evening hours and the days of a Simplified program."""
        room = self.room
        if room is None:
            return
        number = self.room_number
        events = {e.event_id: e for e in room.events}

        def bound(name: str, event_id: int, end: bool) -> time:
            if (value := fields.get(name)) is not None:
                return value  # type: ignore[no-any-return]
            event = events[event_id]
            if end:
                return time(event.end_hour, event.end_minute)
            return time(event.start_hour, event.start_minute)

        morning = (bound("morning_start", 7, False), bound("morning_end", 7, True))
        evening = (bound("evening_start", 8, False), bound("evening_end", 8, True))
        days = {
            r: [WEEKDAYS.index(d) for d in fields[f"{r.value}_days"]]
            for r in SimplifiedRange
            if f"{r.value}_days" in fields
        }

        def edit(home: Home) -> Home:
            home = with_simplified_times(home, number, morning, evening)
            return with_simplified_days(home, number, days) if days else home

        await call_cloud(self.coordinator.async_update_program(edit))
