"""The Home-SmartLink integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from homesmartlink import HomeSmartLinkClient

from .const import CONF_HOME_ID
from .coordinator import HomeSmartLinkCoordinator

PLATFORMS: list[Platform] = []

type HomeSmartLinkConfigEntry = ConfigEntry[HomeSmartLinkCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HomeSmartLinkConfigEntry) -> bool:
    """Set up Home-SmartLink from a config entry."""
    client = HomeSmartLinkClient(
        async_get_clientsession(hass), entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )
    coordinator = HomeSmartLinkCoordinator(hass, entry, client, entry.data[CONF_HOME_ID])
    # Signs in lazily; auth failures start a reauth flow, other errors retry later.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HomeSmartLinkConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
