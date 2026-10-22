"""Fixtures for the Home-SmartLink integration tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homesmartlink import Invitation

HOME_ID = "home-1"
EMAIL = "user@example.invalid"
PASSWORD = "not-a-real-password"


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
