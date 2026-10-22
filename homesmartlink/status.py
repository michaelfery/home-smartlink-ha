"""Parsing of thermostat status strings (docs/API.md, deviceStatus)."""

from __future__ import annotations

import re
from typing import Any

from .models import DeviceStatus, RoomStatus, _parse_datetime

# Fields are positional: the letter M appears twice (mode, then a counter).
_STATUS_RE = re.compile(
    r"^R(?P<room>\d+)D(?P<d>\d+)M(?P<mode>\d+)S(?P<s>\d+)C(?P<c>\d+)A(?P<a>\d+)"
    r"J(?P<j>\d+)W(?P<w>\d+)M(?P<m>\d+)Y(?P<y>\d+)$"
)


def parse_room_status(value: str) -> RoomStatus | None:
    """Parse one status string, e.g. ``R0D0M3S0C38A42J0W0M0Y0``.

    Returns None for strings that do not follow the observed format.
    """
    match = _STATUS_RE.match(value.strip())
    if match is None:
        return None
    g = {k: int(v) for k, v in match.groupdict().items()}
    return RoomStatus(
        room_number=g["room"],
        device_mode=g["mode"],
        set_point=g["c"] / 2,
        ambient_temperature=g["a"] / 2,
        raw=value,
        unknown_d=g["d"],
        unknown_s=g["s"],
        counters=(g["j"], g["w"], g["m"], g["y"]),
    )


def parse_device_status(data: dict[str, Any]) -> DeviceStatus:
    """Parse a `GET deviceStatus/{homeId}` response, skipping unknown entries."""
    rooms: dict[int, RoomStatus] = {}
    for value in data.get("status") or []:
        if isinstance(value, str) and (status := parse_room_status(value)) is not None:
            rooms[status.room_number] = status
    return DeviceStatus(created_at=_parse_datetime(data.get("_created_at")), rooms=rooms)
