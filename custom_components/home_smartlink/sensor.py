"""Sensors: measured room temperatures and box diagnostics."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from homesmartlink import Room

from . import HomeSmartLinkConfigEntry
from .coordinator import HomeSmartLinkCoordinator
from .entity import HomeSmartLinkEntity, HomeSmartLinkRoomEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeSmartLinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        RoomTemperatureSensor(coordinator, room) for room in coordinator.data.home.rooms
    ]
    entities += [BoxLastConnectionSensor(coordinator), StatusUpdatedSensor(coordinator)]
    async_add_entities(entities)


class RoomTemperatureSensor(HomeSmartLinkRoomEntity, SensorEntity):
    """Temperature measured by the thermostat at the last diagnosis."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: HomeSmartLinkCoordinator, room: Room) -> None:
        super().__init__(coordinator, room, "temperature")

    @property
    def available(self) -> bool:
        """Unavailable when the thermostat did not report, or its report is stale."""
        if not super().available or self.room_status is None:
            return False
        status, max_age = self.coordinator.data.status, self.coordinator.status_max_age
        if max_age is None or status is None or status.created_at is None:
            return True
        return dt_util.utcnow() - status.created_at <= max_age

    @property
    def native_value(self) -> float | None:
        status = self.room_status
        return status.ambient_temperature if status else None


class BoxLastConnectionSensor(HomeSmartLinkEntity, SensorEntity):
    """Last time the box contacted the cloud."""

    _attr_translation_key = "last_connection"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: HomeSmartLinkCoordinator) -> None:
        super().__init__(coordinator, "last_connection")

    @property
    def native_value(self) -> datetime | None:
        gateway = self.coordinator.data.gateway
        return gateway.last_connection if gateway else None


class StatusUpdatedSensor(HomeSmartLinkEntity, SensorEntity):
    """When the thermostat statuses (measured temperatures) were last collected."""

    _attr_translation_key = "status_updated"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: HomeSmartLinkCoordinator) -> None:
        super().__init__(coordinator, "status_updated")

    @property
    def native_value(self) -> datetime | None:
        status = self.coordinator.data.status
        return status.created_at if status else None
