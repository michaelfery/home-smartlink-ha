"""Frame encoder and `tests` builder, checked against every captured command."""

from __future__ import annotations

import base64
from typing import Any

import pytest

from homesmartlink import HeaterMode, Room, UnsupportedCommandError
from homesmartlink.frame import build_tests, describe, encode_action, validate_set_point
from homesmartlink.models import HeaterSettings

from .conftest import load_fixture

FRAMES: list[dict[str, Any]] = load_fixture("frames.json")


def _rooms(frame: dict[str, Any]) -> list[Room]:
    return [Room.from_dict(r) for r in frame["rooms"]]


def _target_room(frame: dict[str, Any]) -> Room:
    number = int(frame["description"].split("room ")[1].split(" ")[0])
    return next(r for r in _rooms(frame) if r.number == number)


def test_fixture_covers_every_mode() -> None:
    modes = {_target_room(f).heater_settings.current_mode for f in FRAMES}
    assert modes == set(HeaterMode)
    assert len(FRAMES) >= 38


@pytest.mark.parametrize("frame", FRAMES, ids=lambda f: f"{f['capture']}:{f['description']}")
def test_encode_action_matches_capture(frame: dict[str, Any]) -> None:
    assert encode_action(_target_room(frame)) == base64.b64decode(frame["action"])


@pytest.mark.parametrize("frame", FRAMES, ids=lambda f: f"{f['capture']}:{f['description']}")
def test_build_tests_matches_capture(frame: dict[str, Any]) -> None:
    assert build_tests(_rooms(frame)) == frame["tests"]


@pytest.mark.parametrize("frame", FRAMES, ids=lambda f: f"{f['capture']}:{f['description']}")
def test_describe_matches_capture(frame: dict[str, Any]) -> None:
    assert describe(_target_room(frame)) == frame["description"]


def _manual_room(value: float, limit: float = 30.0) -> Room:
    room = _target_room(FRAMES[0])
    settings = HeaterSettings(HeaterMode.MANUAL, value, 15.5, 19.5, limit)
    return room.with_settings(settings)


@pytest.mark.parametrize("value", [13.0, 30.5, 19.3, 21.25])
def test_rejects_set_points_the_app_cannot_send(value: float) -> None:
    with pytest.raises(UnsupportedCommandError):
        encode_action(_manual_room(value))


def test_rejects_set_point_above_room_limitation() -> None:
    with pytest.raises(UnsupportedCommandError):
        validate_set_point(25.0, limit=24.0)


def test_rejects_unknown_mode() -> None:
    room = _manual_room(19.0)
    with pytest.raises(UnsupportedCommandError):
        encode_action(room.with_settings(HeaterSettings(0, 19.0, 15.5, 19.5, 30.0)))


def test_rejects_programs_longer_than_observed() -> None:
    room = _manual_room(19.0)
    longer = Room(
        number=room.number,
        name=room.name,
        area=room.area,
        ecopilot_enabled=room.ecopilot_enabled,
        open_window_detection_enabled=room.open_window_detection_enabled,
        accessories=room.accessories,
        heater_settings=room.heater_settings,
        events=room.events + room.events[:1],
    )
    with pytest.raises(UnsupportedCommandError):
        encode_action(longer)
