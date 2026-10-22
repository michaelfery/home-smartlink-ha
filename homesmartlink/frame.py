"""Encoding of `device/notify` commands (docs/API.md §5).

Every rule here was derived from captured frames; anything outside what was
observed raises UnsupportedCommandError instead of guessing.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable

from .const import (
    FROST_FRAME_SET_POINT,
    MAX_PROGRAM_EVENTS,
    MAX_SET_POINT,
    MIN_SET_POINT,
    SET_POINT_STEP,
)
from .exceptions import UnsupportedCommandError
from .models import HeaterMode, ProgramEvent, Room

FRAME_LENGTH = 64

_MODE_NAMES = {
    HeaterMode.STOP: "Stop",
    HeaterMode.ANTIFREEZE: "Antifreeze",
    HeaterMode.MANUAL: "Manual",
    HeaterMode.PROGRAM: "Prog",
}

_TESTS_SUFFIX = "A[0-9]{1,3}J[0-9]{1,3}W[0-9]{1,3}M[0-9]{1,3}Y[0-9]{1,3}"
# First alternative of C(..|..) in Manual mode; only ever observed as 26.
_TESTS_MANUAL_LOW = 26


def validate_set_point(value: float, limit: float = MAX_SET_POINT) -> float:
    """Check a set point against the range and step the app allows."""
    upper = min(MAX_SET_POINT, limit)
    if not MIN_SET_POINT <= value <= upper:
        raise UnsupportedCommandError(f"Set point {value} outside {MIN_SET_POINT}-{upper}")
    if (value / SET_POINT_STEP) % 1:
        raise UnsupportedCommandError(f"Set point {value} is not a multiple of {SET_POINT_STEP}")
    return value


def _mode(room: Room) -> HeaterMode:
    mode = room.heater_settings.current_mode
    if not isinstance(mode, HeaterMode):
        raise UnsupportedCommandError(f"Unknown heater mode {mode}")
    return mode


def _encode_set_point(value: float) -> bytes:
    return (((round(value * 2)) << 3) | 0b011).to_bytes(2, "little")


def _encode_event(event: ProgramEvent) -> bytes:
    fields = (event.event_id, event.recurrence, event.mode)
    if not (0 <= event.event_id < 16 and 0 <= event.recurrence < 128 and 0 <= event.mode < 8):
        raise UnsupportedCommandError(f"Program event fields out of range: {fields}")
    start = event.start_hour * 6 + event.start_minute // 10
    end = event.end_hour * 6 + event.end_minute // 10
    if not (0 <= start <= 144 and 0 <= end <= 144):
        raise UnsupportedCommandError(f"Program event time out of range: {fields}")
    return bytes([0x80 | event.event_id << 3 | event.mode, 0x80 | event.recurrence, start, end])


def encode_action(room: Room) -> bytes:
    """Build the 64-byte frame that puts `room` in its `heater_settings` state."""
    settings = room.heater_settings
    mode = _mode(room)
    if len(room.events) > MAX_PROGRAM_EVENTS:
        raise UnsupportedCommandError(f"Rooms with {len(room.events)} program events")
    if not 0 <= room.number < 256:
        raise UnsupportedCommandError(f"Room number {room.number}")

    if mode in (HeaterMode.STOP, HeaterMode.ANTIFREEZE):
        set_point = FROST_FRAME_SET_POINT
        state = 0x10 if mode is HeaterMode.STOP else 0x50
        flags = 0x40
    elif mode is HeaterMode.MANUAL:
        set_point = validate_set_point(settings.manual_value, settings.limitation_set_point)
        state, flags = 0xD0, 0x40
    else:  # PROGRAM
        set_point = validate_set_point(settings.standard_value, settings.limitation_set_point)
        state = 0xD0 if room.ecopilot_enabled else 0x10
        flags = 0xE1

    frame = bytearray([0x01, state, flags])
    frame += _encode_set_point(set_point)
    frame += bytes([room.number, 0, 0])
    for event in room.events:
        frame += _encode_event(event)
    frame.append(room.number)
    return bytes(frame.ljust(FRAME_LENGTH, b"\x00"))


def encode_action_b64(room: Room) -> str:
    return base64.b64encode(encode_action(room)).decode("ascii")


def describe(room: Room) -> str:
    """Human-readable `description`, formatted like the app's."""
    settings = room.heater_settings
    return (
        f"cockpit room {room.number} => mode {_MODE_NAMES[_mode(room)]}, "
        f"manuelSP:{settings.manual_value:g})"
    )


def _room_tests(room: Room) -> str:
    settings = room.heater_settings
    mode = _mode(room)
    if mode is HeaterMode.STOP:
        device_mode, set_points = 0, "([0-9]{2})"
    elif mode is HeaterMode.ANTIFREEZE:
        device_mode, set_points = 1, "([0-9]{2})"
    elif mode is HeaterMode.MANUAL:
        device_mode = 3
        set_points = f"({_TESTS_MANUAL_LOW}|{round(settings.manual_value * 2)})"
    else:
        device_mode = 7 if room.ecopilot_enabled else 4
        set_points = f"({round(settings.economy_value * 2)}|{round(settings.standard_value * 2)})"
    return f"R{room.number}D[0-9]M{device_mode}S[0-9]C{set_points}{_TESTS_SUFFIX}"


def build_tests(rooms: Iterable[Room]) -> str:
    """Expected status patterns of every room, as sent by the app with each command."""
    return " ".join(_room_tests(room) for room in rooms)
