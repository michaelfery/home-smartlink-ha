"""Tests for the Home-SmartLink options flow."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_smartlink.const import CONF_DIAGNOSIS_INTERVAL, CONF_SCAN_INTERVAL


async def test_options_defaults_and_reload(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"]
    assert schema is not None
    suggested = {str(k): k.description["suggested_value"] for k in schema.schema}
    assert suggested == {CONF_SCAN_INTERVAL: 60, CONF_DIAGNOSIS_INTERVAL: 15}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 120, CONF_DIAGNOSIS_INTERVAL: 30}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options == {CONF_SCAN_INTERVAL: 120, CONF_DIAGNOSIS_INTERVAL: 30}
    # The entry reloaded with the new interval.
    assert init_integration.runtime_data.update_interval == timedelta(seconds=120)


async def test_diagnosis_interval_validation(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60, CONF_DIAGNOSIS_INTERVAL: 2}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_DIAGNOSIS_INTERVAL: "diagnosis_interval_too_short"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60, CONF_DIAGNOSIS_INTERVAL: 0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options[CONF_DIAGNOSIS_INTERVAL] == 0
