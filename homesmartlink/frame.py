"""Encoding of `device/notify` commands (docs/API.md §5).

Mirrors the official app (SmartKit.PayloadBuilder, SmartLink RoomDescriptor and
HomeExtension): a 64-byte frame per room, sent alone as `action` for room
settings, or as part of a 512-byte whole-home `payload` for program edits.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import IntEnum

from .const import MAX_PROGRAM_EVENTS, MAX_SET_POINT, MIN_SET_POINT, SET_POINT_STEP
from .exceptions import UnsupportedCommandError
from .models import HeaterMode, Home, ProgramEvent, Room

ROOM_FRAME_LENGTH = 64
MAX_ROOMS = 8
HOME_FRAME_LENGTH = ROOM_FRAME_LENGTH * MAX_ROOMS
ROOM_NUMBER_OFFSET = 44
MAX_VACATION_DAYS = 227

# A room whose eco temperature is 65 °C drives a boiler relay, not a heater.
FURNACE_ECONOMY_VALUE = 65.0

_MODE_NAMES = {
    HeaterMode.STOP: "Stop",
    HeaterMode.ANTIFREEZE: "Antifreeze",
    HeaterMode.MANUAL: "Manual",
    HeaterMode.PROGRAM: "Prog",
}
_TESTS_SUFFIX = "A[0-9]{1,3}J[0-9]{1,3}W[0-9]{1,3}M[0-9]{1,3}Y[0-9]{1,3}"


class DeviceMode(IntEnum):
    """Mode code understood by the thermostats (also `M` in status strings)."""

    STOP = 0
    ANTIFREEZE = 1
    ECONOMY = 2
    STANDARD = 3
    PROGRAM = 4
    ECOPILOT = 7


@dataclass(frozen=True, slots=True)
class RoomDescriptor:
    """What the app derives from a room before encoding it."""

    room_number: int
    device_mode: DeviceMode
    economy_sp: int  # half degrees
    standard_sp: int  # half degrees
    vacation_days: int
    open_window_detection: bool


def validate_set_point(value: float, limit: float = MAX_SET_POINT) -> float:
    """Check a manual set point against the range and step of the app dial."""
    upper = min(MAX_SET_POINT, limit)
    if not MIN_SET_POINT <= value <= upper:
        raise UnsupportedCommandError(f"Set point {value} outside {MIN_SET_POINT}-{upper}")
    if (value / SET_POINT_STEP) % 1:
        raise UnsupportedCommandError(f"Set point {value} is not a multiple of {SET_POINT_STEP}")
    return value


def is_furnace(room: Room) -> bool:
    return abs(room.heater_settings.economy_value - FURNACE_ECONOMY_VALUE) < 1.0


def _mode(room: Room) -> HeaterMode:
    mode = room.heater_settings.current_mode
    if not isinstance(mode, HeaterMode):
        raise UnsupportedCommandError(f"Unknown heater mode {mode}")
    return mode


def vacation_days(return_date: date | None, today: date) -> int:
    """Days left before the vacation return date, as the app counts them."""
    if return_date is None:
        return 0
    days = (return_date - today).days
    return max(0, min(days, MAX_VACATION_DAYS)) if days >= 1 else 0


def describe_room(room: Room, *, vacation_return: date | None, today: date) -> RoomDescriptor:
    """Port of the app's RoomDescriptor constructor."""
    settings = room.heater_settings
    mode = _mode(room)
    if is_furnace(room):
        device_mode = {
            HeaterMode.STOP: DeviceMode.ECONOMY,
            HeaterMode.ANTIFREEZE: DeviceMode.ANTIFREEZE,
            HeaterMode.MANUAL: DeviceMode.STANDARD,
            HeaterMode.PROGRAM: DeviceMode.PROGRAM,
        }[mode]
        economy_sp = standard_sp = 63
    elif mode is HeaterMode.STOP:
        device_mode, economy_sp, standard_sp = DeviceMode.STOP, 26, 28
    elif mode is HeaterMode.ANTIFREEZE:
        device_mode, economy_sp, standard_sp = DeviceMode.ANTIFREEZE, 26, 28
    elif mode is HeaterMode.MANUAL:
        economy_sp = 26
        if abs(settings.manual_value - 13.0) < 0.1:
            device_mode, standard_sp = DeviceMode.ECONOMY, int(settings.standard_value * 2)
        else:
            device_mode, standard_sp = DeviceMode.STANDARD, int(settings.manual_value * 2)
    else:
        device_mode = DeviceMode.ECOPILOT if room.ecopilot_enabled else DeviceMode.PROGRAM
        economy_sp = int(settings.economy_value * 2)
        standard_sp = int(settings.standard_value * 2)
    return RoomDescriptor(
        room_number=room.number,
        device_mode=device_mode,
        economy_sp=economy_sp,
        standard_sp=standard_sp,
        vacation_days=vacation_days(vacation_return, today),
        open_window_detection=room.open_window_detection_enabled,
    )


def _bits(fields: Iterable[tuple[int, int, int]], length: int) -> bytes:
    """Pack (value, size, offset) bit fields into a little-endian word."""
    word = 0
    for value, size, offset in fields:
        if not 0 <= value < (1 << size):
            raise UnsupportedCommandError(f"Value {value} does not fit in {size} bits")
        word |= value << offset
    return word.to_bytes(length, "little")


def _encode_header(d: RoomDescriptor) -> bytes:
    return _bits(
        (
            (1, 8, 0),
            (int(d.open_window_detection), 1, 12),
            (int(d.device_mode), 3, 14),
            (d.economy_sp, 6, 21),
            (d.standard_sp, 6, 27),
            (d.vacation_days, 7, 33),
            (d.room_number, 8, 40),
        ),
        8,
    )


def _encode_event(event: ProgramEvent) -> bytes:
    start = (event.start_hour * 60 + event.start_minute) // 10
    end = (event.end_hour * 60 + event.end_minute) // 10
    return _bits(
        (
            (event.mode, 3, 0),
            (event.event_id, 4, 3),
            (1, 1, 7),
            (event.recurrence, 7, 8),
            (1, 1, 15),
            (start, 8, 16),
            (end, 8, 24),
        ),
        4,
    )


def encode_room(room: Room, *, vacation_return: date | None = None, today: date) -> bytes:
    """The 64-byte configuration frame of one room."""
    if len(room.events) > MAX_PROGRAM_EVENTS:
        raise UnsupportedCommandError(f"Rooms with {len(room.events)} program events")
    if not 0 <= room.number < MAX_ROOMS:
        raise UnsupportedCommandError(f"Room number {room.number}")
    if _mode(room) is HeaterMode.MANUAL and not is_furnace(room):
        validate_set_point(room.heater_settings.manual_value)
    frame = bytearray(ROOM_FRAME_LENGTH)
    frame[0:8] = _encode_header(describe_room(room, vacation_return=vacation_return, today=today))
    for index, event in enumerate(room.events):
        frame[8 + 4 * index : 12 + 4 * index] = _encode_event(event)
    frame[ROOM_NUMBER_OFFSET] = room.number
    return bytes(frame)


def encode_home(home: Home, *, today: date) -> bytes:
    """The 512-byte whole-home frame: 8 room slots, unused ones start with 0xFF."""
    frame = bytearray(HOME_FRAME_LENGTH)
    for slot in range(MAX_ROOMS):
        frame[slot * ROOM_FRAME_LENGTH] = 0xFF
    for room in home.rooms:
        start = room.number * ROOM_FRAME_LENGTH
        frame[start : start + ROOM_FRAME_LENGTH] = encode_room(
            room, vacation_return=home.vacation_return_date, today=today
        )
    return bytes(frame)


def b64(frame: bytes) -> str:
    return base64.b64encode(frame).decode("ascii")


def describe(room: Room) -> str:
    """Human-readable `description` of a room command, formatted like the app's."""
    settings = room.heater_settings
    return (
        f"cockpit room {room.number} => mode {_MODE_NAMES[_mode(room)]}, "
        f"manuelSP:{settings.manual_value:g})"
    )


def build_tests(home: Home, *, today: date) -> str:
    """Expected status patterns: one per thermostat, as the app sends them."""
    parts = []
    for room in home.rooms:
        if not room.accessories:
            continue
        d = describe_room(room, vacation_return=home.vacation_return_date, today=today)
        if d.device_mode in (DeviceMode.STOP, DeviceMode.ANTIFREEZE):
            set_points = "C([0-9]{2})"
        else:
            set_points = f"C({d.economy_sp}|{d.standard_sp})"
        line = f"R{d.room_number}D[0-9]M{int(d.device_mode)}S[0-9]{set_points}{_TESTS_SUFFIX}"
        parts.extend([line] * len(room.accessories))
    return " ".join(parts)
