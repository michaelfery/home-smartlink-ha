"""Async client for the Home-SmartLink (Carrera) heating cloud API."""

from .client import HomeSmartLinkClient
from .exceptions import (
    AuthenticationError,
    CannotConnectError,
    CommandFailedError,
    HomeSmartLinkError,
    RateLimitError,
    UnsupportedCommandError,
)
from .models import (
    Accessory,
    DeviceStatus,
    Diagnosis,
    Gateway,
    HeaterMode,
    HeaterSettings,
    Home,
    Invitation,
    ProgramEvent,
    Room,
    RoomStatus,
)

__all__ = [
    "Accessory",
    "AuthenticationError",
    "CannotConnectError",
    "CommandFailedError",
    "DeviceStatus",
    "Diagnosis",
    "Gateway",
    "HeaterMode",
    "HeaterSettings",
    "Home",
    "HomeSmartLinkClient",
    "HomeSmartLinkError",
    "Invitation",
    "ProgramEvent",
    "RateLimitError",
    "Room",
    "RoomStatus",
    "UnsupportedCommandError",
]
__version__ = "0.2.0"
