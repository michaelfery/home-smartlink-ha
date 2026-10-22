"""Constants of the Home-SmartLink cloud API (see docs/API.md)."""

from __future__ import annotations

from typing import Final

BASE_URL: Final = "https://jcqzjjt6q5.execute-api.eu-west-3.amazonaws.com/Prod/"

# Values the official Android app sends; the cloud may rely on them.
APP_AGENT: Final = "Droid"
APP_VERSION: Final = 103

SESSION_HEADER: Final = "x-session"
DEFAULT_TIMEOUT: Final = 20.0

# Set point range accepted by the official app dial (capture 19), in °C.
MIN_SET_POINT: Final = 13.5
MAX_SET_POINT: Final = 30.0
SET_POINT_STEP: Final = 0.5

# Set point carried by Stop and Antifreeze frames, whatever the room settings.
FROST_FRAME_SET_POINT: Final = 14.0

# Longest program the 64-byte frame was observed with.
MAX_PROGRAM_EVENTS: Final = 9
