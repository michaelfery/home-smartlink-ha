"""Date entity: vacation return date."""

from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from homesmartlink.settings import vacation_active, vacation_description, with_vacation

from . import HomeSmartLinkConfigEntry
from .coordinator import HomeSmartLinkCoordinator
from .entity import HomeSmartLinkEntity, call_cloud

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeSmartLinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([VacationReturnDate(entry.runtime_data)])


class VacationReturnDate(HomeSmartLinkEntity, DateEntity):
    """Return date of vacation mode; setting a date starts vacation mode."""

    _attr_translation_key = "vacation_return"

    def __init__(self, coordinator: HomeSmartLinkCoordinator) -> None:
        super().__init__(coordinator, "vacation_return")

    @property
    def native_value(self) -> date | None:
        home = self.coordinator.data.home
        if not vacation_active(home, dt_util.now().date()):
            return None
        return home.vacation_return_date

    async def async_set_value(self, value: date) -> None:
        today = dt_util.now().date()
        await call_cloud(
            self.coordinator.async_update_home(
                lambda home: with_vacation(home, value, today), vacation_description(value)
            )
        )
