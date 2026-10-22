"""Entity services for editing weekly programs."""

from __future__ import annotations

import probatio
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service

from homesmartlink.program import ADVANCED_SLOTS, WEEKDAYS

from .const import DOMAIN

SERVICE_SET_PROGRAM_SLOT = "set_program_slot"
SERVICE_SET_SIMPLIFIED_PROGRAM = "set_simplified_program"

_DAYS = probatio.All(cv.ensure_list, [probatio.In(WEEKDAYS)])


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_PROGRAM_SLOT,
        entity_domain=CLIMATE_DOMAIN,
        schema={
            probatio.Required("slot"): probatio.All(
                probatio.Coerce(int), probatio.Range(min(ADVANCED_SLOTS), max(ADVANCED_SLOTS))
            ),
            probatio.Required("start"): cv.time,
            probatio.Required("end"): cv.time,
            probatio.Required("days"): _DAYS,
            probatio.Optional("mode"): probatio.In(["standard", "boost", "fan"]),
        },
        func="async_set_program_slot",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_SIMPLIFIED_PROGRAM,
        entity_domain=CLIMATE_DOMAIN,
        schema={
            probatio.Optional("morning_start"): cv.time,
            probatio.Optional("morning_end"): cv.time,
            probatio.Optional("evening_start"): cv.time,
            probatio.Optional("evening_end"): cv.time,
            probatio.Optional("morning_days"): _DAYS,
            probatio.Optional("day_days"): _DAYS,
            probatio.Optional("evening_days"): _DAYS,
        },
        func="async_set_simplified_program",
    )
