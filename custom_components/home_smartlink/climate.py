"""Climate entities: one per Home-SmartLink thermostat."""

from __future__ import annotations

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
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from homesmartlink import HeaterMode, HomeSmartLinkError, Room, UnsupportedCommandError
from homesmartlink.const import MAX_SET_POINT, MIN_SET_POINT, SET_POINT_STEP

from . import HomeSmartLinkConfigEntry
from .const import DOMAIN
from .coordinator import HomeSmartLinkCoordinator
from .entity import HomeSmartLinkRoomEntity

PARALLEL_UPDATES = 1

_HVAC_MODES = {
    HeaterMode.STOP: HVACMode.OFF,
    HeaterMode.ANTIFREEZE: HVACMode.HEAT,
    HeaterMode.MANUAL: HVACMode.HEAT,
    HeaterMode.PROGRAM: HVACMode.AUTO,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeSmartLinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        HomeSmartLinkClimate(coordinator, room) for room in coordinator.data.home.rooms
    )


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
        room = self.room
        if room is None or self._mode is not HeaterMode.MANUAL:
            return None
        return room.heater_settings.manual_value

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

    async def _send(self, mode: HeaterMode, manual_value: float | None = None) -> None:
        try:
            await self.coordinator.async_set_room_state(self.room_number, mode, manual_value)
        except UnsupportedCommandError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_command",
                translation_placeholders={"error": str(err)},
            ) from err
        except HomeSmartLinkError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

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
