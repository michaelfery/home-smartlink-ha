"""Tests for the Home-SmartLink config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.home_smartlink.const import CONF_HOME_ID, DOMAIN
from homesmartlink import (
    AuthenticationError,
    CannotConnectError,
    HomeSmartLinkError,
    Invitation,
)

from .conftest import EMAIL, HOME_ID, PASSWORD

USER_INPUT = {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD}


async def test_user_flow_single_home(
    hass: HomeAssistant, mock_flow_client: MagicMock, mock_setup_entry: AsyncMock
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Home-SmartLink ({EMAIL})"
    assert result["data"] == {**USER_INPUT, CONF_HOME_ID: HOME_ID}
    assert result["result"].unique_id == HOME_ID
    assert len(mock_setup_entry.mock_calls) == 1


async def test_user_flow_several_homes(
    hass: HomeAssistant, mock_flow_client: MagicMock, mock_setup_entry: AsyncMock
) -> None:
    mock_flow_client.login.return_value = [
        Invitation(id="inv-1", home_id=HOME_ID, role=2),
        Invitation(id="inv-2", home_id="home-2", role=1),
    ]
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "home"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOME_ID: "home-2"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOME_ID] == "home-2"


async def test_falls_back_to_invitation_list(
    hass: HomeAssistant, mock_flow_client: MagicMock, mock_setup_entry: AsyncMock
) -> None:
    mock_flow_client.login.return_value = []
    mock_flow_client.get_invitations.return_value = [
        Invitation(id="inv-1", home_id=HOME_ID, role=2)
    ]
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (AuthenticationError("bad"), "invalid_auth"),
        (CannotConnectError("down"), "cannot_connect"),
        (HomeSmartLinkError("weird"), "unknown"),
    ],
)
async def test_user_flow_errors_then_recover(
    hass: HomeAssistant,
    mock_flow_client: MagicMock,
    mock_setup_entry: AsyncMock,
    side_effect: Exception,
    error: str,
) -> None:
    mock_flow_client.login.side_effect = side_effect
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_flow_client.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_account_without_home(
    hass: HomeAssistant, mock_flow_client: MagicMock, mock_setup_entry: AsyncMock
) -> None:
    mock_flow_client.login.return_value = []
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "no_home"}


async def test_already_configured(
    hass: HomeAssistant, mock_flow_client: MagicMock, mock_setup_entry: AsyncMock
) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=HOME_ID, data={}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_password(
    hass: HomeAssistant, mock_flow_client: MagicMock, mock_setup_entry: AsyncMock
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=HOME_ID,
        data={**USER_INPUT, CONF_PASSWORD: "old", CONF_HOME_ID: HOME_ID},
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["email"] == EMAIL

    mock_flow_client.login.side_effect = AuthenticationError("still bad")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_flow_client.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-password"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"
    assert entry.data[CONF_EMAIL] == EMAIL


async def test_reauth_with_other_account(
    hass: HomeAssistant, mock_flow_client: MagicMock, mock_setup_entry: AsyncMock
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=HOME_ID, data={**USER_INPUT, CONF_HOME_ID: HOME_ID}
    )
    entry.add_to_hass(hass)
    mock_flow_client.login.return_value = [Invitation(id="x", home_id="other-home", role=2)]
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
