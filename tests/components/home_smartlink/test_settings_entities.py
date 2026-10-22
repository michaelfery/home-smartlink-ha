"""Vacation mode, vacation return date, whole-home mode and open-window detection."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
from homeassistant.components.date import DOMAIN as DATE_DOMAIN
from homeassistant.components.date import SERVICE_SET_VALUE
from homeassistant.components.select import (
    ATTR_OPTION,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_DATE,
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homesmartlink import HeaterMode, Home

VACATION = "switch.box_home_smartlink_vacation_mode"
RETURN = "date.box_home_smartlink_vacation_return"
HOME_MODE = "select.box_home_smartlink_home_mode"
WINDOW = "switch.salon_thermostat_open_window_detection"


def written(mock: MagicMock) -> Home:
    home: Home = mock.get_home.return_value
    return home


def description(mock: MagicMock) -> str | None:
    value: str | None = mock.update_home.await_args.kwargs["description"]
    return value


async def test_initial_states(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    assert hass.states.get(VACATION).state == STATE_OFF  # type: ignore[union-attr]
    assert hass.states.get(RETURN).state == STATE_UNKNOWN  # type: ignore[union-attr]
    # Rooms are in Manual and Program: no shared mode.
    assert hass.states.get(HOME_MODE).state == STATE_UNKNOWN  # type: ignore[union-attr]
    assert hass.states.get(WINDOW).state == STATE_ON  # type: ignore[union-attr]


async def test_vacation_switch(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: VACATION}, blocking=True
    )
    assert written(mock_client).vacation_return_date == date(2026, 10, 23)  # tomorrow
    assert description(mock_client) == "mode vacance 10/23/2026 00:00:00"
    assert hass.states.get(VACATION).state == STATE_ON  # type: ignore[union-attr]
    assert hass.states.get(RETURN).state == "2026-10-23"  # type: ignore[union-attr]

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: VACATION}, blocking=True
    )
    assert written(mock_client).vacation_return_date is None
    assert description(mock_client) == "mode vacance 01/01/0001 00:00:00"
    assert hass.states.get(VACATION).state == STATE_OFF  # type: ignore[union-attr]


async def test_vacation_return_date(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    await hass.services.async_call(
        DATE_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: RETURN, ATTR_DATE: "2026-11-02"},
        blocking=True,
    )
    assert written(mock_client).vacation_return_date == date(2026, 11, 2)
    assert hass.states.get(VACATION).state == STATE_ON  # type: ignore[union-attr]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DATE_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: RETURN, ATTR_DATE: "2026-10-22"},
            blocking=True,
        )


async def test_home_mode(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: HOME_MODE, ATTR_OPTION: "off"},
        blocking=True,
    )
    assert {r.heater_settings.current_mode for r in written(mock_client).rooms} == {HeaterMode.STOP}
    assert description(mock_client) == "toute ma maison => Stop"
    assert hass.states.get(HOME_MODE).state == "off"  # type: ignore[union-attr]
    assert hass.states.get("climate.salon_thermostat").state == "off"  # type: ignore[union-attr]


async def test_open_window_switch(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: WINDOW}, blocking=True
    )
    mock_client.update_room.assert_awaited_once()
    assert mock_client.update_room.await_args.args[1] == 1
    assert written(mock_client).room(1).open_window_detection_enabled is False
    assert hass.states.get(WINDOW).state == STATE_OFF  # type: ignore[union-attr]
