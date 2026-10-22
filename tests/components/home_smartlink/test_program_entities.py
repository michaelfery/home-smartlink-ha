"""Program mode: effective target, program attributes, number/select entities, services."""

from __future__ import annotations

from datetime import time
from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.components.number import (
    ATTR_VALUE,
    SERVICE_SET_VALUE,
)
from homeassistant.components.number import (
    DOMAIN as NUMBER_DOMAIN,
)
from homeassistant.components.select import (
    ATTR_OPTION,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.home_smartlink.const import DOMAIN
from homesmartlink import Home
from homesmartlink.program import days_from_mask

CUISINE = "climate.cuisine_thermostat"
BATHROOM = "climate.salle_de_bain_du_bas_thermostat"


def written_home(mock: MagicMock) -> Home:
    """The home the last edit produced (the fake cloud serves it back)."""
    home: Home = mock.get_home.return_value
    return home


async def test_advanced_program_attributes(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    state = hass.states.get(BATHROOM)
    assert state is not None
    attributes = state.attributes
    assert attributes["programming_preference"] == "advanced"
    assert attributes["program_state"] == "comfort"
    assert attributes["active_slot"] == 1
    assert attributes["program"]["1"] == {
        "start": "06:30",
        "end": "08:00",
        "days": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
    }
    assert attributes["program"]["2"]["days"] == []
    assert (attributes["eco_temperature"], attributes["comfort_temperature"]) == (15.5, 20.0)


async def test_simplified_program_attributes(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    state = hass.states.get(CUISINE)
    assert state is not None
    assert state.attributes["programming_preference"] == "simplified"
    assert set(state.attributes["program"]) == {"morning", "day", "evening"}
    assert state.attributes["program"]["evening"]["start"] == "17:00"
    assert "program_state" not in state.attributes  # Cuisine is in manual


async def test_auto_target_follows_the_clock(
    hass: HomeAssistant, init_integration: MockConfigEntry, freezer: Any
) -> None:
    freezer.move_to("2026-10-22T19:56:00+00:00")  # 21:56 in Paris, outside every slot
    async_fire_time_changed(hass)
    await init_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(BATHROOM)
    assert state is not None
    assert state.attributes[ATTR_TEMPERATURE] == 15.5
    assert state.attributes["program_state"] == "eco"
    assert state.attributes["active_slot"] is None


async def test_program_temperature_numbers(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    eco = "number.salle_de_bain_du_bas_thermostat_eco_temperature_program"
    comfort = "number.salle_de_bain_du_bas_thermostat_comfort_temperature_program"
    assert hass.states.get(eco).state == "15.5"  # type: ignore[union-attr]
    assert hass.states.get(comfort).state == "20.0"  # type: ignore[union-attr]

    await hass.services.async_call(
        NUMBER_DOMAIN, SERVICE_SET_VALUE, {ATTR_ENTITY_ID: eco, ATTR_VALUE: 16.0}, blocking=True
    )
    mock_client.update_room.assert_awaited_once()
    assert mock_client.update_room.await_args.args[1] == 2
    assert written_home(mock_client).room(2).heater_settings.economy_value == 16.0
    assert hass.states.get(eco).state == "16.0"  # type: ignore[union-attr]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: comfort, ATTR_VALUE: 16.0},
            blocking=True,
        )


async def test_programming_preference_select(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    entity_id = "select.salle_de_bain_du_bas_thermostat_programming_preference"
    state = hass.states.get(entity_id)
    assert state is not None and state.state == "advanced"
    assert state.attributes["options"] == ["advanced", "simplified"]

    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: "simplified"},
        blocking=True,
    )
    assert written_home(mock_client).room(2).ecopilot_enabled is True
    assert hass.states.get(entity_id).state == "simplified"  # type: ignore[union-attr]


async def test_set_program_slot_service(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    await hass.services.async_call(
        DOMAIN,
        "set_program_slot",
        {
            ATTR_ENTITY_ID: BATHROOM,
            "slot": 2,
            "start": "17:00",
            "end": "21:30",
            "days": ["monday", "friday"],
        },
        blocking=True,
    )
    mock_client.update_home.assert_awaited_once()
    slot = next(e for e in written_home(mock_client).room(2).events if e.event_id == 2)
    assert (slot.start_hour, slot.end_hour, slot.end_minute) == (17, 21, 30)
    assert days_from_mask(slot.recurrence) == {0, 4}


@pytest.mark.parametrize(
    "data",
    [
        {"slot": 2, "start": "09:00", "end": "08:00", "days": ["monday"]},
        {"slot": 2, "start": "08:05", "end": "09:00", "days": ["monday"]},
    ],
)
async def test_set_program_slot_rules(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: MagicMock,
    data: dict[str, Any],
) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_program_slot", {ATTR_ENTITY_ID: BATHROOM, **data}, blocking=True
        )


async def test_set_simplified_program_service(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    await hass.services.async_call(
        DOMAIN,
        "set_simplified_program",
        {
            ATTR_ENTITY_ID: CUISINE,
            "morning_end": "08:30",
            "morning_days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
        },
        blocking=True,
    )
    events = {e.event_id: e for e in written_home(mock_client).room(0).events}
    assert (events[7].start_hour, events[7].end_hour, events[7].end_minute) == (6, 8, 30)
    assert time(events[9].start_hour, events[9].start_minute) == time(8, 30)
    assert days_from_mask(events[7].recurrence) == {0, 1, 2, 3, 4}
    assert events[8].recurrence == 0  # untouched
