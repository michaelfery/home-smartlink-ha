"""Select entities: programming preference (Advanced or Simplified)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from homesmartlink import HeaterMode, Room
from homesmartlink.program import with_programming_preference
from homesmartlink.settings import home_mode_description, with_home_mode

from . import HomeSmartLinkConfigEntry
from .coordinator import HomeSmartLinkCoordinator
from .entity import HomeSmartLinkEntity, HomeSmartLinkRoomEntity, call_cloud

PARALLEL_UPDATES = 1

ADVANCED = "advanced"
SIMPLIFIED = "simplified"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeSmartLinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SelectEntity] = [HomeModeSelect(coordinator)]
    entities += [
        ProgrammingPreferenceSelect(coordinator, room) for room in coordinator.data.home.rooms
    ]
    async_add_entities(entities)


class ProgrammingPreferenceSelect(HomeSmartLinkRoomEntity, SelectEntity):
    """Which program drives the room in auto: six Advanced slots or Simplified ranges."""

    _attr_translation_key = "programming_preference"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = [ADVANCED, SIMPLIFIED]

    def __init__(self, coordinator: HomeSmartLinkCoordinator, room: Room) -> None:
        super().__init__(coordinator, room, "programming_preference")

    @property
    def current_option(self) -> str | None:
        room = self.room
        if room is None:
            return None
        return SIMPLIFIED if room.ecopilot_enabled else ADVANCED

    async def async_select_option(self, option: str) -> None:
        number, simplified = self.room_number, option == SIMPLIFIED
        await call_cloud(
            self.coordinator.async_update_room(
                number, lambda home: with_programming_preference(home, number, simplified)
            )
        )


HOME_MODES = {
    "off": HeaterMode.STOP,
    "antifreeze": HeaterMode.ANTIFREEZE,
    "manual": HeaterMode.MANUAL,
    "program": HeaterMode.PROGRAM,
}


class HomeModeSelect(HomeSmartLinkEntity, SelectEntity):
    """Put every room in the same mode (the app's whole-home buttons)."""

    _attr_translation_key = "home_mode"
    _attr_options = list(HOME_MODES)

    def __init__(self, coordinator: HomeSmartLinkCoordinator) -> None:
        super().__init__(coordinator, "home_mode")

    @property
    def current_option(self) -> str | None:
        """The shared mode, or unknown when rooms differ."""
        modes = {room.heater_settings.current_mode for room in self.coordinator.data.home.rooms}
        if len(modes) != 1:
            return None
        mode = modes.pop()
        return next((option for option, m in HOME_MODES.items() if m == mode), None)

    async def async_select_option(self, option: str) -> None:
        mode = HOME_MODES[option]
        await call_cloud(
            self.coordinator.async_update_home(
                lambda home: with_home_mode(home, mode), home_mode_description(mode)
            )
        )
