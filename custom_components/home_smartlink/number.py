"""Number entities: eco and comfort temperatures of Program mode."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from homesmartlink import HeaterSettings, Home, Room
from homesmartlink.program import COMFORT_RANGE, ECO_RANGE, with_program_temperatures

from . import HomeSmartLinkConfigEntry
from .coordinator import HomeSmartLinkCoordinator
from .entity import HomeSmartLinkRoomEntity, call_cloud

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class ProgramTemperatureDescription(NumberEntityDescription):
    value: Callable[[HeaterSettings], float]
    edit: Callable[[Home, int, float], Home]


DESCRIPTIONS = (
    ProgramTemperatureDescription(
        key="eco_temperature",
        translation_key="eco_temperature",
        native_min_value=ECO_RANGE[0],
        native_max_value=ECO_RANGE[1],
        value=lambda settings: settings.economy_value,
        edit=lambda home, room, value: with_program_temperatures(home, room, economy=value),
    ),
    ProgramTemperatureDescription(
        key="comfort_temperature",
        translation_key="comfort_temperature",
        native_min_value=COMFORT_RANGE[0],
        native_max_value=COMFORT_RANGE[1],
        value=lambda settings: settings.standard_value,
        edit=lambda home, room, value: with_program_temperatures(home, room, standard=value),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeSmartLinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ProgramTemperatureNumber(coordinator, room, description)
        for room in coordinator.data.home.rooms
        for description in DESCRIPTIONS
    )


class ProgramTemperatureNumber(HomeSmartLinkRoomEntity, NumberEntity):
    """Temperature used by Program mode outside (eco) or inside (comfort) slots."""

    entity_description: ProgramTemperatureDescription
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        coordinator: HomeSmartLinkCoordinator,
        room: Room,
        description: ProgramTemperatureDescription,
    ) -> None:
        super().__init__(coordinator, room, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        room = self.room
        return self.entity_description.value(room.heater_settings) if room else None

    async def async_set_native_value(self, value: float) -> None:
        number, edit = self.room_number, self.entity_description.edit
        await call_cloud(
            self.coordinator.async_update_room(number, lambda home: edit(home, number, value))
        )
