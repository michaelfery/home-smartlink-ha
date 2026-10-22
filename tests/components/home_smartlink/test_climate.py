"""Tests for the Home-SmartLink climate and sensor entities."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_NONE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_smartlink.const import DOMAIN
from homesmartlink import CannotConnectError, HeaterMode, UnsupportedCommandError

from .conftest import HOME_ID

CUISINE = "climate.cuisine_thermostat"
SALON = "climate.salon_thermostat"
BATHROOM = "climate.salle_de_bain_du_bas_thermostat"


async def test_states_from_captured_home(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    cuisine = hass.states.get(CUISINE)
    assert cuisine is not None
    assert cuisine.state == HVACMode.HEAT
    assert cuisine.attributes[ATTR_TEMPERATURE] == 19.0
    assert cuisine.attributes[ATTR_CURRENT_TEMPERATURE] == 21.0
    assert cuisine.attributes[ATTR_PRESET_MODE] == PRESET_NONE
    assert cuisine.attributes["min_temp"] == 13.5
    assert cuisine.attributes["max_temp"] == 30.0
    assert cuisine.attributes["target_temp_step"] == 0.5

    salon = hass.states.get(SALON)
    assert salon is not None
    assert salon.attributes[ATTR_PRESET_MODE] == PRESET_COMFORT

    bathroom = hass.states.get(BATHROOM)
    assert bathroom is not None
    assert bathroom.state == HVACMode.AUTO
    assert bathroom.attributes[ATTR_TEMPERATURE] is None
    assert bathroom.attributes[ATTR_CURRENT_TEMPERATURE] == 20.0


async def test_sensors(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    temperature = hass.states.get("sensor.cuisine_thermostat_temperature")
    assert temperature is not None and temperature.state == "21.0"
    assert temperature.attributes["unit_of_measurement"] == "°C"
    last_connection = hass.states.get("sensor.box_home_smartlink_last_connection")
    assert last_connection is not None and last_connection.state.startswith("2026-10-22T")
    updated = hass.states.get("sensor.box_home_smartlink_thermostat_status_update")
    assert updated is not None and updated.state.startswith("2026-10-22T")


async def test_temperature_unknown_without_status(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.get_device_status.side_effect = CannotConnectError("down")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.cuisine_thermostat_temperature")
    assert state is not None and state.state == STATE_UNKNOWN
    climate = hass.states.get(CUISINE)
    assert climate is not None and climate.attributes[ATTR_CURRENT_TEMPERATURE] is None


async def test_thermostats_hang_off_the_box(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    registry = dr.async_get(hass)
    box = registry.async_get_device_by_identifier((DOMAIN, HOME_ID), init_integration.entry_id)
    assert box is not None and box.sw_version == "1.15"
    thermostats = [
        d
        for d in dr.async_entries_for_config_entry(registry, init_integration.entry_id)
        if d.id != box.id
    ]
    assert [d.name for d in thermostats] == ["Thermostat"] * 3
    assert sorted(d.suggested_area or "" for d in thermostats) == [
        "Cuisine",
        "Salle de bain du bas",
        "Salon",
    ]
    assert all(d.via_device_id == box.id for d in thermostats)
    assert all(d.sw_version == "39" for d in thermostats)


@pytest.mark.parametrize(
    ("service", "data", "expected"),
    [
        (SERVICE_SET_TEMPERATURE, {ATTR_TEMPERATURE: 21.5}, (HeaterMode.MANUAL, 21.5)),
        (SERVICE_SET_HVAC_MODE, {ATTR_HVAC_MODE: HVACMode.OFF}, (HeaterMode.STOP, None)),
        (SERVICE_SET_HVAC_MODE, {ATTR_HVAC_MODE: HVACMode.AUTO}, (HeaterMode.PROGRAM, None)),
        (SERVICE_SET_HVAC_MODE, {ATTR_HVAC_MODE: HVACMode.HEAT}, (HeaterMode.MANUAL, None)),
        (SERVICE_SET_PRESET_MODE, {ATTR_PRESET_MODE: PRESET_ECO}, (HeaterMode.MANUAL, 15.5)),
        (SERVICE_SET_PRESET_MODE, {ATTR_PRESET_MODE: PRESET_COMFORT}, (HeaterMode.MANUAL, 19.5)),
        (SERVICE_SET_PRESET_MODE, {ATTR_PRESET_MODE: PRESET_AWAY}, (HeaterMode.ANTIFREEZE, None)),
        (SERVICE_SET_PRESET_MODE, {ATTR_PRESET_MODE: PRESET_NONE}, (HeaterMode.MANUAL, None)),
        (SERVICE_TURN_OFF, {}, (HeaterMode.STOP, None)),
        (SERVICE_TURN_ON, {}, (HeaterMode.MANUAL, None)),
    ],
)
async def test_services_send_the_right_command(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: MagicMock,
    service: str,
    data: dict[str, Any],
    expected: tuple[HeaterMode, float | None],
) -> None:
    await hass.services.async_call(
        CLIMATE_DOMAIN, service, {ATTR_ENTITY_ID: CUISINE, **data}, blocking=True
    )
    mock_client.set_room_state.assert_awaited_once_with(HOME_ID, 0, *expected)


async def test_command_is_reflected_immediately(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: CUISINE, ATTR_PRESET_MODE: PRESET_AWAY},
        blocking=True,
    )
    state = hass.states.get(CUISINE)
    assert state is not None
    assert state.attributes[ATTR_PRESET_MODE] == PRESET_AWAY
    assert state.attributes[ATTR_TEMPERATURE] is None


@pytest.mark.parametrize(
    ("error", "raised"),
    [
        (UnsupportedCommandError("nope"), ServiceValidationError),
        (CannotConnectError("down"), HomeAssistantError),
    ],
)
async def test_command_errors(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: MagicMock,
    error: Exception,
    raised: type[Exception],
) -> None:
    mock_client.set_room_state.side_effect = error
    with pytest.raises(raised):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: CUISINE, ATTR_TEMPERATURE: 21.5},
            blocking=True,
        )
