"""Box connectivity, stale temperatures and diagnostics download."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.home_smartlink.const import CONF_DIAGNOSIS_INTERVAL, DOMAIN
from homesmartlink import DeviceStatus, Diagnosis

from .conftest import EMAIL, HOME_ID, PASSWORD

CONNECTIVITY = "binary_sensor.box_home_smartlink_connectivity"
CUISINE_TEMPERATURE = "sensor.cuisine_thermostat_temperature"


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_box_online_once_diagnosis_is_acknowledged(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    # The diagnosis requested at start-up is checked at the next poll.
    await refresh(hass, init_integration)
    mock_client.get_diagnosis.assert_awaited_with("diag-1")
    assert hass.states.get(CONNECTIVITY).state == STATE_ON  # type: ignore[union-attr]


async def test_box_offline_when_diagnosis_is_not_acknowledged(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_client: MagicMock,
    freezer: Any,
) -> None:
    mock_client.get_diagnosis.return_value = Diagnosis(
        id="diag-1", acknowledged=False, updated_at=None
    )
    await refresh(hass, init_integration)
    # Still waiting: the box keeps its previous (unknown) state, i.e. last connection.
    assert hass.states.get(CONNECTIVITY).state == STATE_ON  # type: ignore[union-attr]

    freezer.tick(240)
    await refresh(hass, init_integration)
    assert hass.states.get(CONNECTIVITY).state == STATE_OFF  # type: ignore[union-attr]


async def test_without_diagnoses_uses_last_connection(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock, freezer: Any
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=HOME_ID,
        data=config_entry.data,
        options={CONF_DIAGNOSIS_INTERVAL: 0},
    )
    entry.add_to_hass(hass)
    freezer.move_to("2026-10-22T17:30:00+00:00")  # 33 min after the last connection
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(CONNECTIVITY).state == STATE_ON  # type: ignore[union-attr]

    freezer.move_to("2026-10-22T19:30:00+00:00")  # 2 h 33 min of silence
    await refresh(hass, entry)
    assert hass.states.get(CONNECTIVITY).state == STATE_OFF  # type: ignore[union-attr]


async def test_stale_temperature_becomes_unavailable(
    hass: HomeAssistant, init_integration: MockConfigEntry, freezer: Any
) -> None:
    # The captured status dates from 17:33 UTC; diagnoses every 15 min -> 40 min max age.
    freezer.move_to("2026-10-22T18:00:00+00:00")
    await refresh(hass, init_integration)
    assert hass.states.get(CUISINE_TEMPERATURE).state == "21.0"  # type: ignore[union-attr]

    freezer.move_to("2026-10-22T18:30:00+00:00")
    await refresh(hass, init_integration)
    state = hass.states.get(CUISINE_TEMPERATURE)
    assert state is not None and state.state == STATE_UNAVAILABLE
    # The heater itself stays controllable.
    assert hass.states.get("climate.cuisine_thermostat").state != STATE_UNAVAILABLE  # type: ignore[union-attr]


async def test_room_missing_from_status_is_unavailable(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    status: DeviceStatus = mock_client.get_device_status.return_value
    mock_client.get_device_status.return_value = DeviceStatus(
        created_at=status.created_at,
        rooms={n: r for n, r in status.rooms.items() if n != 0},
    )
    await refresh(hass, init_integration)
    assert hass.states.get(CUISINE_TEMPERATURE).state == STATE_UNAVAILABLE  # type: ignore[union-attr]
    assert hass.states.get("sensor.salon_thermostat_temperature").state == "21.0"  # type: ignore[union-attr]


async def test_diagnostics_are_redacted(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
) -> None:
    result = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)
    text = json.dumps(result)
    for secret in (EMAIL, PASSWORD, HOME_ID):
        assert secret not in text
    assert result["home"]["meshCryptogram"] == "**REDACTED**"  # type: ignore[index]
    assert result["home"]["location"] == "**REDACTED**"  # type: ignore[index]
    rooms = result["home"]["rooms"]  # type: ignore[index]
    assert [r["name"] for r in rooms] == ["Cuisine", "Salon", "Salle de bain du bas"]  # type: ignore[index]
    assert result["status"]["rooms"][0].startswith("R0")  # type: ignore[index]
