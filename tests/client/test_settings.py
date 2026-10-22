"""Vacation mode, whole-home modes and open-window detection edits."""

from __future__ import annotations

from datetime import date

import pytest

from homesmartlink import HeaterMode, Home, UnsupportedCommandError
from homesmartlink.frame import encode_room
from homesmartlink.settings import (
    home_mode_description,
    vacation_active,
    vacation_description,
    with_home_mode,
    with_open_window_detection,
    with_vacation,
)

from .conftest import load_fixture

TODAY = date(2026, 10, 22)


@pytest.fixture
def home() -> Home:
    return Home.from_dict(load_fixture("api/home.json"))


def test_no_vacation_in_capture(home: Home) -> None:
    assert home.vacation_return_date is None
    assert not vacation_active(home, TODAY)


def test_start_and_stop_vacation(home: Home) -> None:
    away = with_vacation(home, date(2026, 10, 30), TODAY)
    assert away.raw["vacationReturnDate"] == "2026-10-30T00:00:00.000Z"
    assert away.vacation_return_date == date(2026, 10, 30)
    assert vacation_active(away, TODAY)
    assert away.raw["_id"] == home.raw["_id"]
    # Every room frame carries the days left.
    word = int.from_bytes(
        encode_room(away.rooms[0], vacation_return=away.vacation_return_date, today=TODAY)[:8],
        "little",
    )
    assert (word >> 33) & 0x7F == 8

    back = with_vacation(away, None, TODAY)
    assert back.raw["vacationReturnDate"] == "0001-01-01T00:00:00.000Z"
    assert not vacation_active(back, TODAY)


@pytest.mark.parametrize("return_date", [TODAY, date(2026, 10, 1), date(2027, 7, 1)])
def test_vacation_rules(home: Home, return_date: date) -> None:
    with pytest.raises(UnsupportedCommandError):
        with_vacation(home, return_date, TODAY)


def test_vacation_description() -> None:
    assert vacation_description(date(2026, 10, 23)) == "mode vacance 10/23/2026 00:00:00"
    assert vacation_description(None) == "mode vacance 01/01/0001 00:00:00"


def test_whole_home_mode(home: Home) -> None:
    stopped = with_home_mode(home, HeaterMode.STOP)
    assert {r.heater_settings.current_mode for r in stopped.rooms} == {HeaterMode.STOP}
    assert [r.heater_settings.manual_value for r in stopped.rooms] == [
        r.heater_settings.manual_value for r in home.rooms
    ]
    assert home_mode_description(HeaterMode.PROGRAM) == "toute ma maison => Prog"


def test_open_window_detection(home: Home) -> None:
    updated = with_open_window_detection(home, 1, False)
    assert updated.room(1).open_window_detection_enabled is False
    assert updated.room(0).open_window_detection_enabled is True
    word = int.from_bytes(encode_room(updated.room(1), today=TODAY)[:8], "little")
    assert (word >> 12) & 1 == 0
