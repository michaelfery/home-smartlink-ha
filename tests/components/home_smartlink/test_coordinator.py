"""Tests for the Home-SmartLink coordinator and entry setup."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_smartlink.const import CONF_DIAGNOSIS_INTERVAL, DOMAIN
from custom_components.home_smartlink.coordinator import HomeSmartLinkCoordinator
from homesmartlink import (
    AuthenticationError,
    CannotConnectError,
    HeaterMode,
    RateLimitError,
)

from .conftest import HOME_ID


def coordinator_of(entry: MockConfigEntry) -> HomeSmartLinkCoordinator:
    coordinator: HomeSmartLinkCoordinator = entry.runtime_data
    return coordinator


async def test_setup_loads_home_gateway_and_status(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    assert init_integration.state is ConfigEntryState.LOADED
    data = coordinator_of(init_integration).data
    assert [r.name for r in data.home.rooms] == ["Cuisine", "Salon", "Salle de bain du bas"]
    assert data.gateway is not None and data.gateway.version == "1.15"
    assert data.status is not None and data.status.rooms[0].ambient_temperature == 21.0
    mock_client.get_home.assert_awaited_with(HOME_ID)
    mock_client.request_diagnosis.assert_awaited_once_with(HOME_ID)


async def test_unload(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(init_integration.entry_id)
    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_diagnosis_is_spaced_out(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    coordinator = coordinator_of(init_integration)
    clock = "custom_components.home_smartlink.coordinator.time.monotonic"
    start = coordinator._last_diagnosis
    assert start is not None

    with patch(clock, return_value=start + 14 * 60):
        await coordinator.async_refresh()
    assert mock_client.request_diagnosis.await_count == 1

    with patch(clock, return_value=start + 15 * 60):
        await coordinator.async_refresh()
    assert mock_client.request_diagnosis.await_count == 2


async def test_diagnosis_can_be_disabled(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=HOME_ID,
        data=config_entry.data,
        options={CONF_DIAGNOSIS_INTERVAL: 0},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mock_client.request_diagnosis.assert_not_awaited()


async def test_diagnosis_failure_does_not_fail_poll(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.request_diagnosis.side_effect = CannotConnectError("down")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.LOADED


async def test_secondary_reads_keep_previous_values(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    coordinator = coordinator_of(init_integration)
    previous = coordinator.data
    mock_client.get_gateway.side_effect = CannotConnectError("down")
    mock_client.get_device_status.side_effect = CannotConnectError("down")
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data.gateway == previous.gateway
    assert coordinator.data.status == previous.status


async def test_backoff_then_recovery(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    coordinator = coordinator_of(init_integration)
    mock_client.get_home.side_effect = CannotConnectError("down")
    await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert coordinator.update_interval == timedelta(seconds=120)
    await coordinator.async_refresh()
    assert coordinator.update_interval == timedelta(seconds=240)

    mock_client.get_home.side_effect = None
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.update_interval == timedelta(seconds=60)


async def test_backoff_is_capped_and_honors_retry_after(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    coordinator = coordinator_of(init_integration)
    mock_client.get_home.side_effect = RateLimitError("slow down", retry_after=500)
    await coordinator.async_refresh()
    assert coordinator.update_interval == timedelta(seconds=500)
    for _ in range(5):
        await coordinator.async_refresh()
    assert coordinator.update_interval == timedelta(minutes=10)


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    mock_client.get_home.side_effect = AuthenticationError("bad")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


@pytest.mark.parametrize("error", [CannotConnectError("down"), RateLimitError("slow")])
async def test_setup_retries_when_cloud_unavailable(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock, error: Exception
) -> None:
    mock_client.get_home.side_effect = error
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_command_is_shown_optimistically_then_refreshed(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_client: MagicMock
) -> None:
    coordinator = coordinator_of(init_integration)
    reads_before = mock_client.get_home.await_count
    with patch.object(coordinator, "async_request_refresh") as refresh:
        await coordinator.async_set_room_state(0, HeaterMode.MANUAL, 21.5)
    settings = coordinator.data.home.room(0).heater_settings
    assert settings.current_mode is HeaterMode.MANUAL
    assert settings.manual_value == 21.5
    mock_client.set_room_state.assert_awaited_once_with(
        HOME_ID, 0, HeaterMode.MANUAL, 21.5, today=date(2026, 10, 22)
    )
    refresh.assert_awaited_once()
    assert mock_client.get_home.await_count == reads_before
