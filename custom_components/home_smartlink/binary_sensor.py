"""Binary sensors: Home-SmartLink box connectivity."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import HomeSmartLinkConfigEntry
from .const import GATEWAY_SILENCE
from .coordinator import HomeSmartLinkCoordinator
from .entity import HomeSmartLinkEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeSmartLinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([BoxConnectivity(entry.runtime_data)])


class BoxConnectivity(HomeSmartLinkEntity, BinarySensorEntity):
    """Whether the box answers: diagnosis acknowledgements, else its last cloud contact."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: HomeSmartLinkCoordinator) -> None:
        super().__init__(coordinator, "connectivity")

    @property
    def is_on(self) -> bool | None:
        coordinator = self.coordinator
        if coordinator.diagnosis_enabled and coordinator.box_online is not None:
            return coordinator.box_online
        gateway = coordinator.data.gateway
        if gateway is None or gateway.last_connection is None:
            return None
        return dt_util.utcnow() - gateway.last_connection < GATEWAY_SILENCE
