"""Base entities for Home-SmartLink."""

from __future__ import annotations

from collections.abc import Awaitable

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homesmartlink import HomeSmartLinkError, Room, RoomStatus, UnsupportedCommandError

from .const import DOMAIN, MANUFACTURER
from .coordinator import HomeSmartLinkCoordinator

THERMOSTAT_CATEGORY = 5


def box_device_info(coordinator: HomeSmartLinkCoordinator) -> DeviceInfo:
    """The Home-SmartLink box, keyed by home id (always known, unlike its serial)."""
    gateway = coordinator.data.gateway if coordinator.data else None
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.home_id)},
        manufacturer=MANUFACTURER,
        model="Box Home-SmartLink",
        name="Box Home-SmartLink",
        sw_version=gateway.version if gateway else None,
    )


class HomeSmartLinkEntity(CoordinatorEntity[HomeSmartLinkCoordinator]):
    """Entity attached to the box."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HomeSmartLinkCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.home_id}_{key}"
        self._attr_device_info = box_device_info(coordinator)


class HomeSmartLinkRoomEntity(CoordinatorEntity[HomeSmartLinkCoordinator]):
    """Entity attached to the thermostat of one room."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HomeSmartLinkCoordinator, room: Room, key: str) -> None:
        super().__init__(coordinator)
        self.room_number = room.number
        home_id = coordinator.home_id
        self._attr_unique_id = f"{home_id}_room{room.number}_{key}"

        thermostat = next((a for a in room.accessories if a.category == THERMOSTAT_CATEGORY), None)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, thermostat.id if thermostat else f"{home_id}_room{room.number}")},
            manufacturer=MANUFACTURER,
            model="Thermostat Home-SmartLink",
            # HA prefixes entity ids and names with the area: avoid repeating the room.
            name="Thermostat",
            sw_version=thermostat.software_version if thermostat else None,
            suggested_area=room.name,
        )
        if coordinator.box_device_id:
            self._attr_device_info["via_device_id"] = coordinator.box_device_id

    @property
    def room(self) -> Room | None:
        try:
            return self.coordinator.data.home.room(self.room_number)
        except KeyError:
            return None

    @property
    def room_status(self) -> RoomStatus | None:
        status = self.coordinator.data.status
        return status.rooms.get(self.room_number) if status else None

    @property
    def available(self) -> bool:
        return super().available and self.room is not None


async def call_cloud(command: Awaitable[None]) -> None:
    """Run a write and turn library errors into Home Assistant errors."""
    try:
        await command
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
