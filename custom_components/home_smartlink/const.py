"""Constants for the Home-SmartLink integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "home_smartlink"

CONF_HOME_ID: Final = "home_id"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_DIAGNOSIS_INTERVAL: Final = "diagnosis_interval"

# Seconds between cloud polls (reads only).
DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 30

# Minutes between diagnoses, which make the box query every thermostat and
# refresh the measured temperatures; 0 disables them.
DEFAULT_DIAGNOSIS_INTERVAL: Final = 15
MIN_DIAGNOSIS_INTERVAL: Final = 5
MAX_DIAGNOSIS_INTERVAL: Final = 120

MAX_BACKOFF: Final = timedelta(minutes=10)
