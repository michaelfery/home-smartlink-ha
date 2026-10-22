"""Tests for the Home-SmartLink options flow (intervals and program editor)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, section
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_smartlink.const import CONF_DIAGNOSIS_INTERVAL, CONF_SCAN_INTERVAL
from homesmartlink import Home
from homesmartlink.program import days_from_mask

BATHROOM, CUISINE = 2, 0


def suggested(result: Any) -> dict[str, Any]:
    """Suggested values of a form, sections included."""

    def walk(schema: Any) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, value in schema.schema.items():
            if isinstance(value, section):
                values[str(key)] = walk(value.schema)
            else:
                values[str(key)] = (key.description or {}).get("suggested_value")
        return values

    return walk(result["data_schema"])


def written(mock: MagicMock) -> Home:
    home: Home = mock.get_home.return_value
    return home


async def start(hass: HomeAssistant, entry: MockConfigEntry, step: str) -> Any:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["program", "intervals"]
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


async def open_room(hass: HomeAssistant, entry: MockConfigEntry, room: int) -> Any:
    result = await start(hass, entry, "program")
    assert result["step_id"] == "program"
    return await hass.config_entries.options.async_configure(result["flow_id"], {"room": str(room)})


# -- intervals -------------------------------------------------------------------


async def test_intervals_defaults_and_reload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    result = await start(hass, init_integration, "intervals")
    assert suggested(result) == {CONF_SCAN_INTERVAL: 60, CONF_DIAGNOSIS_INTERVAL: 15}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 120, CONF_DIAGNOSIS_INTERVAL: 30}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options == {CONF_SCAN_INTERVAL: 120, CONF_DIAGNOSIS_INTERVAL: 30}
    assert init_integration.runtime_data.update_interval == timedelta(seconds=120)


async def test_diagnosis_interval_validation(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    result = await start(hass, init_integration, "intervals")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60, CONF_DIAGNOSIS_INTERVAL: 2}
    )
    assert result["errors"] == {CONF_DIAGNOSIS_INTERVAL: "diagnosis_interval_too_short"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60, CONF_DIAGNOSIS_INTERVAL: 0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options[CONF_DIAGNOSIS_INTERVAL] == 0


# -- program editor --------------------------------------------------------------

ROOM_UNCHANGED = {
    "programming_preference": "advanced",
    "eco_temperature": 15.5,
    "comfort_temperature": 20.0,
}


async def test_advanced_program_editor(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    result = await open_room(hass, init_integration, BATHROOM)
    assert result["step_id"] == "room"
    assert result["description_placeholders"]["room"] == "Salle de bain du bas"
    assert suggested(result) == ROOM_UNCHANGED

    result = await hass.config_entries.options.async_configure(result["flow_id"], ROOM_UNCHANGED)
    assert result["step_id"] == "advanced"
    mock_client.update_room.assert_not_awaited()
    current = suggested(result)
    assert current["slot1"] == {
        "start": "06:30:00",
        "end": "08:00:00",
        "days": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
    }
    assert current["slot2"]["days"] == []

    user_input = {f"slot{n}": {k: v for k, v in current[f"slot{n}"].items()} for n in range(1, 7)}
    user_input["slot2"] = {"start": "17:00:00", "end": "21:30:00", "days": ["monday", "friday"]}
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "program_saved"
    mock_client.update_program.assert_awaited_once()
    events = {e.event_id: e for e in written(mock_client).room(BATHROOM).events}
    assert (events[2].start_hour, events[2].end_hour, events[2].end_minute) == (17, 21, 30)
    assert days_from_mask(events[2].recurrence) == {0, 4}
    assert days_from_mask(events[1].recurrence) == set(range(7))
    assert init_integration.options == {}  # program edits never touch options


async def test_room_settings_are_written_first(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    result = await open_room(hass, init_integration, BATHROOM)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**ROOM_UNCHANGED, "eco_temperature": 16.0}
    )
    assert result["step_id"] == "advanced"
    mock_client.update_room.assert_awaited_once()
    assert written(mock_client).room(BATHROOM).heater_settings.economy_value == 16.0


async def test_switching_to_simplified_opens_simplified_editor(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    result = await open_room(hass, init_integration, BATHROOM)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**ROOM_UNCHANGED, "programming_preference": "simplified"}
    )
    assert result["step_id"] == "simplified"
    assert written(mock_client).room(BATHROOM).ecopilot_enabled is True


async def test_simplified_program_editor(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    result = await open_room(hass, init_integration, CUISINE)
    room = suggested(result)
    assert room["programming_preference"] == "simplified"
    result = await hass.config_entries.options.async_configure(result["flow_id"], room)
    assert result["step_id"] == "simplified"
    current = suggested(result)
    assert current["morning"] == {"start": "06:00:00", "end": "08:00:00", "days": []}
    assert current["day"] == {"days": []}

    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    user_input = {
        "morning": {**current["morning"], "days": weekdays},
        "day": {"days": []},
        "evening": {**current["evening"], "end": "22:30:00", "days": weekdays},
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
    assert result["reason"] == "program_saved"
    events = {e.event_id: e for e in written(mock_client).room(CUISINE).events}
    assert days_from_mask(events[7].recurrence) == {0, 1, 2, 3, 4}
    assert days_from_mask(events[8].recurrence) == {0, 1, 2, 3, 4}
    assert (events[8].end_hour, events[8].end_minute) == (22, 30)


async def test_invalid_slot_shows_error_and_writes_nothing(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    result = await open_room(hass, init_integration, BATHROOM)
    result = await hass.config_entries.options.async_configure(result["flow_id"], ROOM_UNCHANGED)
    current = suggested(result)
    user_input = {f"slot{n}": current[f"slot{n}"] for n in range(1, 7)}
    user_input["slot2"] = {"start": "21:00:00", "end": "17:00:00", "days": ["monday"]}
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_program"}
    assert "after it starts" in result["description_placeholders"]["error"]
    # The edit is rejected before anything is sent: the home is unchanged.
    slot2 = next(e for e in written(mock_client).room(BATHROOM).events if e.event_id == 2)
    assert (slot2.start_hour, slot2.start_minute, slot2.recurrence) == (16, 30, 0)


async def test_unchanged_program(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    result = await open_room(hass, init_integration, BATHROOM)
    result = await hass.config_entries.options.async_configure(result["flow_id"], ROOM_UNCHANGED)
    current = suggested(result)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {f"slot{n}": current[f"slot{n}"] for n in range(1, 7)}
    )
    assert result["reason"] == "program_unchanged"
    mock_client.update_program.assert_not_awaited()


async def test_program_editor_needs_loaded_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await start(hass, config_entry, "program")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"
