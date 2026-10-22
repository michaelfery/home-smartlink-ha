"""Diagnostics download, with personal data and secrets redacted."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import HomeSmartLinkConfigEntry
from .const import CONF_HOME_ID

TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_HOME_ID,
    "_id",
    "homeId",
    "homeid",
    "client",
    "meshCryptogram",
    "location",
    "header",
    "identifier",
    "id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HomeSmartLinkConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    status = data.status
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
            "diagnosis_enabled": coordinator.diagnosis_enabled,
            "last_diagnosis_requested_at": coordinator.last_diagnosis_requested_at,
            "box_online": coordinator.box_online,
        },
        "home": async_redact_data(data.home.raw, TO_REDACT),
        "gateway": async_redact_data(asdict(data.gateway), TO_REDACT) if data.gateway else None,
        "status": {
            "created_at": status.created_at,
            "rooms": [room.raw for room in status.rooms.values()],
        }
        if status
        else None,
    }
