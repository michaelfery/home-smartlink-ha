"""Fixtures for the Home-SmartLink integration tests."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_smartlink.const import CONF_HOME_ID, DOMAIN
from homesmartlink import Gateway, Home, Invitation
from homesmartlink.status import parse_device_status

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "api"
HOME_ID = "home-1"
EMAIL = "user@example.invalid"
PASSWORD = "not-a-real-password"


def load_api(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_home() -> Home:
    return Home.from_dict({**load_api("home.json"), "_id": HOME_ID})


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load integrations from custom_components/."""


@pytest.fixture
def mock_flow_client() -> Generator[MagicMock]:
    """HomeSmartLinkClient as seen by the config flow."""
    with patch(
        "custom_components.home_smartlink.config_flow.HomeSmartLinkClient", autospec=True
    ) as client_cls:
        client = client_cls.return_value
        client.login.return_value = [Invitation(id="inv-1", home_id=HOME_ID, role=2)]
        client.get_invitations.return_value = []
        yield client


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    with patch(
        "custom_components.home_smartlink.async_setup_entry", return_value=True
    ) as setup_entry:
        yield setup_entry


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """HomeSmartLinkClient used by the config entry, serving the captured fixtures."""
    with patch("custom_components.home_smartlink.HomeSmartLinkClient", autospec=True) as cls:
        client = cls.return_value
        client.get_home.return_value = fixture_home()
        client.get_gateway.return_value = Gateway.from_dict(load_api("gateway.json"))
        client.get_device_status.return_value = parse_device_status(load_api("device_status.json"))
        client.request_diagnosis.return_value = "diag-1"

        async def set_room_state(
            home_id: str, room: int, mode: Any, manual: Any = None, **_: Any
        ) -> Home:
            home = client.get_home.return_value
            settings = home.room(room).heater_settings
            new = type(settings)(
                mode,
                settings.manual_value if manual is None else manual,
                settings.economy_value,
                settings.standard_value,
                settings.limitation_set_point,
            )
            updated = home.with_room_settings(room, new)
            # The cloud now serves the written document.
            client.get_home.return_value = updated
            return updated

        async def apply_edit(home_id: str, *args: Any, **_: Any) -> Home:
            edit = args[-1]
            updated = edit(client.get_home.return_value)
            client.get_home.return_value = updated
            return updated

        client.update_room.side_effect = apply_edit
        client.update_program.side_effect = apply_edit
        client.update_home.side_effect = apply_edit
        client.set_room_state.side_effect = set_room_state
        yield client


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=HOME_ID,
        title=f"Home-SmartLink ({EMAIL})",
        data={CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD, CONF_HOME_ID: HOME_ID},
    )


@pytest.fixture(autouse=True)
async def paris_morning(hass: HomeAssistant, freezer: Any) -> None:
    """Thursday 22 Oct 2026, 07:00 in Paris: the bathroom program slot is active."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to("2026-10-22T05:00:00+00:00")


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> MockConfigEntry:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
