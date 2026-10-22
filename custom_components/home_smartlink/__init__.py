"""The Home-SmartLink integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from homesmartlink import (
    AuthenticationError,
    CannotConnectError,
    HomeSmartLinkClient,
    HomeSmartLinkError,
)

from .const import CONF_HOME_ID

PLATFORMS: list[Platform] = []


@dataclass
class HomeSmartLinkData:
    """Runtime data of a config entry."""

    client: HomeSmartLinkClient
    home_id: str


type HomeSmartLinkConfigEntry = ConfigEntry[HomeSmartLinkData]


async def async_setup_entry(hass: HomeAssistant, entry: HomeSmartLinkConfigEntry) -> bool:
    """Set up Home-SmartLink from a config entry."""
    client = HomeSmartLinkClient(
        async_get_clientsession(hass), entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )
    try:
        await client.login()
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed("Credentials rejected by Home-SmartLink") from err
    except (CannotConnectError, HomeSmartLinkError) as err:
        raise ConfigEntryNotReady(f"Cannot reach Home-SmartLink: {err}") from err

    entry.runtime_data = HomeSmartLinkData(client=client, home_id=entry.data[CONF_HOME_ID])
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HomeSmartLinkConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
