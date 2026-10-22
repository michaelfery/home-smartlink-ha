"""Frame encoder and `tests` builder, checked against every captured command."""

from __future__ import annotations

import base64
import re
from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from homesmartlink import HeaterMode, Home, Room, UnsupportedCommandError
from homesmartlink.frame import (
    DeviceMode,
    build_tests,
    describe,
    describe_room,
    encode_home,
    encode_room,
    vacation_days,
)
from homesmartlink.models import HeaterSettings

from .conftest import load_fixture

FRAMES: list[dict[str, Any]] = load_fixture("frames.json")
TODAY = date(2026, 10, 22)


def _home(frame: dict[str, Any]) -> Home:
    return Home.from_dict(
        {
            "_id": frame["home_id"],
            "rooms": frame["rooms"],
            "vacationReturnDate": frame["vacationReturnDate"],
        }
    )


def _target_room(frame: dict[str, Any]) -> Room:
    number = int(re.search(r"room (\d+)", frame["description"]).group(1))  # type: ignore[union-attr]
    return _home(frame).room(number)


def test_fixture_covers_every_mode() -> None:
    modes = {_target_room(f).heater_settings.current_mode for f in FRAMES}
    assert modes == set(HeaterMode)
    assert len(FRAMES) >= 38


@pytest.mark.parametrize("frame", FRAMES, ids=lambda f: f"{f['capture']}:{f['description']}")
def test_encode_room_matches_capture(frame: dict[str, Any]) -> None:
    assert encode_room(_target_room(frame), today=TODAY) == base64.b64decode(frame["action"])


@pytest.mark.parametrize("frame", FRAMES, ids=lambda f: f"{f['capture']}:{f['description']}")
def test_build_tests_matches_capture(frame: dict[str, Any]) -> None:
    assert build_tests(_home(frame), today=TODAY) == frame["tests"]


@pytest.mark.parametrize("frame", FRAMES, ids=lambda f: f"{f['capture']}:{f['description']}")
def test_describe_matches_capture(frame: dict[str, Any]) -> None:
    assert describe(_target_room(frame)) == frame["description"]


def test_home_frame_layout() -> None:
    home = _home(FRAMES[0])
    frame = encode_home(home, today=TODAY)
    assert len(frame) == 512
    for room in home.rooms:
        slot = frame[room.number * 64 : (room.number + 1) * 64]
        assert slot == encode_room(room, today=TODAY)
    used = {r.number for r in home.rooms}
    for slot_number in set(range(8)) - used:
        assert frame[slot_number * 64] == 0xFF
        assert not any(frame[slot_number * 64 + 1 : (slot_number + 1) * 64])


def _room(mode: HeaterMode, manual: float = 19.0, **changes: Any) -> Room:
    room = _target_room(FRAMES[0])
    settings = HeaterSettings(mode, manual, 15.5, 19.5, 30.0)
    return replace(room.with_settings(settings), **changes)


def test_header_fields() -> None:
    """Bit layout of the app's RoomConfig (docs/API.md §5.1)."""
    word = int.from_bytes(encode_room(_room(HeaterMode.PROGRAM), today=TODAY)[:8], "little")
    assert word & 0xFF == 1
    assert (word >> 12) & 1 == 1  # open-window detection
    assert (word >> 14) & 0b111 == DeviceMode.ECOPILOT
    assert (word >> 21) & 0x3F == 31  # eco 15.5
    assert (word >> 27) & 0x3F == 39  # comfort 19.5
    assert (word >> 33) & 0x7F == 0  # no vacation
    assert (word >> 40) & 0xFF == 0  # room number


def test_open_window_flag_and_advanced_program() -> None:
    room = _room(HeaterMode.PROGRAM, ecopilot_enabled=False, open_window_detection_enabled=False)
    word = int.from_bytes(encode_room(room, today=TODAY)[:8], "little")
    assert (word >> 12) & 1 == 0
    assert (word >> 14) & 0b111 == DeviceMode.PROGRAM


def test_vacation_days() -> None:
    assert vacation_days(None, TODAY) == 0
    assert vacation_days(date(2026, 10, 22), TODAY) == 0
    assert vacation_days(date(2026, 10, 25), TODAY) == 3
    assert vacation_days(date(2028, 1, 1), TODAY) == 227
    word = int.from_bytes(
        encode_room(_room(HeaterMode.MANUAL), vacation_return=date(2026, 10, 25), today=TODAY)[:8],
        "little",
    )
    assert (word >> 33) & 0x7F == 3


def test_manual_at_13_is_economy() -> None:
    descriptor = describe_room(_room(HeaterMode.MANUAL, 13.0), vacation_return=None, today=TODAY)
    assert descriptor.device_mode is DeviceMode.ECONOMY
    assert descriptor.standard_sp == 39


def test_furnace_room() -> None:
    room = _room(HeaterMode.MANUAL).with_settings(
        HeaterSettings(HeaterMode.MANUAL, 19.0, 65.0, 70.0, 30.0)
    )
    descriptor = describe_room(room, vacation_return=None, today=TODAY)
    assert (descriptor.economy_sp, descriptor.standard_sp) == (63, 63)
    assert descriptor.device_mode is DeviceMode.STANDARD


def test_tests_has_one_line_per_thermostat() -> None:
    home = _home(FRAMES[0])
    first = home.rooms[0]
    doubled = replace(home, rooms=(replace(first, accessories=first.accessories * 2),))
    assert len(build_tests(doubled, today=TODAY).split(" ")) == 2


@pytest.mark.parametrize("value", [13.0 - 0.5, 30.5, 19.3])
def test_rejects_set_points_the_app_cannot_send(value: float) -> None:
    with pytest.raises(UnsupportedCommandError):
        encode_room(_room(HeaterMode.MANUAL, value), today=TODAY)


def test_rejects_unknown_mode() -> None:
    with pytest.raises(UnsupportedCommandError):
        encode_room(
            _room(HeaterMode.MANUAL).with_settings(HeaterSettings(0, 19, 15.5, 19.5, 30)),
            today=TODAY,
        )


def test_rejects_programs_longer_than_the_frame() -> None:
    room = _room(HeaterMode.MANUAL)
    with pytest.raises(UnsupportedCommandError):
        encode_room(replace(room, events=room.events + room.events[:1]), today=TODAY)
