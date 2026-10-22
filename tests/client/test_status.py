"""Status string parsing."""

from __future__ import annotations

from homesmartlink import HeaterMode
from homesmartlink.status import parse_device_status, parse_room_status

from .conftest import load_fixture


def test_parse_room_status() -> None:
    status = parse_room_status("R1D1M3S0C39A42J0W0M0Y0")
    assert status is not None
    assert status.room_number == 1
    assert status.heater_mode is HeaterMode.MANUAL
    assert status.set_point == 19.5
    assert status.ambient_temperature == 21.0
    assert status.unknown_d == 1
    assert status.counters == (0, 0, 0, 0)


def test_program_with_ecopilot_device_mode() -> None:
    status = parse_room_status("R0D0M7S0C39A40J0W0M0Y0")
    assert status is not None
    assert status.device_mode == 7
    assert status.heater_mode is HeaterMode.PROGRAM


def test_unknown_format_is_ignored() -> None:
    assert parse_room_status("R0-garbage") is None
    assert parse_room_status("R0D0M9S0C38A42J0W0M0Y0") is not None  # unknown mode kept
    assert parse_room_status("R0D0M9S0C38A42J0W0M0Y0").heater_mode is None  # type: ignore[union-attr]


def test_parse_device_status_fixture() -> None:
    status = parse_device_status(load_fixture("api/device_status.json"))
    assert status.created_at is not None
    assert sorted(status.rooms) == [0, 1, 2]
    assert status.rooms[0].ambient_temperature == 21.0
    assert status.rooms[2].heater_mode is HeaterMode.PROGRAM


def test_parse_device_status_without_status() -> None:
    assert parse_device_status({}).rooms == {}
