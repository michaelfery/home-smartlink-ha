"""Weekly program rules, on the captured home."""

from __future__ import annotations

from datetime import datetime, time

import pytest

from homesmartlink import HeaterMode, Home, UnsupportedCommandError
from homesmartlink.models import HeaterSettings
from homesmartlink.program import (
    ProgramMode,
    SimplifiedRange,
    active_event,
    days_from_mask,
    mask_from_days,
    program_events,
    target_temperature,
    with_advanced_slot,
    with_program_temperatures,
    with_programming_preference,
    with_simplified_days,
    with_simplified_times,
)

from .conftest import load_fixture

THURSDAY = datetime(2026, 10, 22)
CUISINE, BATHROOM = 0, 2


@pytest.fixture
def home() -> Home:
    return Home.from_dict(load_fixture("api/home.json"))


def at(hour: int, minute: int) -> datetime:
    return THURSDAY.replace(hour=hour, minute=minute)


def test_day_masks() -> None:
    assert days_from_mask(127) == frozenset(range(7))
    assert days_from_mask(0b1000001) == {0, 6}  # Monday and Sunday
    assert mask_from_days([0, 6]) == 0b1000001
    with pytest.raises(UnsupportedCommandError):
        mask_from_days([7])


def test_slots_depend_on_programming_preference(home: Home) -> None:
    assert [e.event_id for e in program_events(home.room(BATHROOM))] == [1, 2, 3, 4, 5, 6]
    assert [e.event_id for e in program_events(home.room(CUISINE))] == [7, 9, 8]


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [(6, 29, 15.5), (6, 30, 20.0), (7, 0, 20.0), (8, 0, 20.0), (8, 1, 15.5), (21, 56, 15.5)],
)
def test_bathroom_advanced_program(home: Home, hour: int, minute: int, expected: float) -> None:
    """Slot 1 (6:30-8:00 every day) is the only active one."""
    assert target_temperature(home.room(BATHROOM), at(hour, minute)) == expected


@pytest.mark.parametrize("hour", [7, 12, 18])
def test_simplified_without_days_stays_eco(home: Home, hour: int) -> None:
    cuisine = home.room(CUISINE)
    program = cuisine.with_settings(HeaterSettings(HeaterMode.PROGRAM, 19.0, 15.5, 19.5, 30.0))
    assert active_event(program, at(hour, 0)) is None
    assert target_temperature(program, at(hour, 0)) == 15.5


def test_other_modes_targets(home: Home) -> None:
    cuisine = home.room(CUISINE)
    assert target_temperature(cuisine, at(12, 0)) == 19.0
    stop = cuisine.with_settings(HeaterSettings(HeaterMode.STOP, 19.0, 15.5, 19.5, 30.0))
    assert target_temperature(stop, at(12, 0)) == 7.0


def test_program_temperatures(home: Home) -> None:
    updated = with_program_temperatures(home, BATHROOM, economy=16.0)
    settings = updated.room(BATHROOM).heater_settings
    assert (settings.economy_value, settings.standard_value) == (16.0, 20.0)
    assert updated.raw["rooms"][BATHROOM]["heaterSettings"]["economyValue"] == 16.0


@pytest.mark.parametrize(
    ("economy", "standard"),
    [(12.5, None), (19.5, 25.0), (16.25, None), (None, 30.5), (18.0, 18.0)],
)
def test_program_temperature_rules(
    home: Home, economy: float | None, standard: float | None
) -> None:
    with pytest.raises(UnsupportedCommandError):
        with_program_temperatures(home, BATHROOM, economy=economy, standard=standard)


def test_programming_preference(home: Home) -> None:
    updated = with_programming_preference(home, BATHROOM, simplified=True)
    assert updated.room(BATHROOM).ecopilot_enabled is True
    assert updated.room(BATHROOM).events == home.room(BATHROOM).events


def test_advanced_slot(home: Home) -> None:
    updated = with_advanced_slot(home, BATHROOM, 2, time(17, 0), time(21, 30), [0, 4])
    event = next(e for e in updated.room(BATHROOM).events if e.event_id == 2)
    assert (event.start_hour, event.start_minute, event.end_hour, event.end_minute) == (
        17,
        0,
        21,
        30,
    )
    assert days_from_mask(event.recurrence) == {0, 4}
    assert event.mode == ProgramMode.STANDARD
    others = [e for e in updated.room(BATHROOM).events if e.event_id != 2]
    assert others == [e for e in home.room(BATHROOM).events if e.event_id != 2]


@pytest.mark.parametrize(
    ("slot", "start", "end", "mode"),
    [
        (7, time(6), time(8), None),  # simplified slot
        (2, time(8), time(8), None),  # empty
        (2, time(9), time(8), None),  # reversed
        (2, time(8, 5), time(9), None),  # not a 10-minute step
        (2, time(8), time(11), ProgramMode.FAN),  # fan longer than 2 h
    ],
)
def test_advanced_slot_rules(
    home: Home, slot: int, start: time, end: time, mode: ProgramMode | None
) -> None:
    with pytest.raises(UnsupportedCommandError):
        with_advanced_slot(home, BATHROOM, slot, start, end, [0], mode)


def test_simplified_times_fill_the_day_slot(home: Home) -> None:
    updated = with_simplified_times(
        home, CUISINE, (time(6, 30), time(8, 30)), (time(18, 0), time(22, 30))
    )
    events = {e.event_id: e for e in updated.room(CUISINE).events}
    assert (events[7].start_hour, events[7].start_minute) == (6, 30)
    assert (events[9].start_hour, events[9].start_minute) == (8, 30)
    assert (events[9].end_hour, events[9].end_minute) == (18, 0)
    assert (events[8].end_hour, events[8].end_minute) == (22, 30)


def test_simplified_times_rules(home: Home) -> None:
    with pytest.raises(UnsupportedCommandError):
        with_simplified_times(home, CUISINE, (time(6), time(19)), (time(18), time(22)))


def test_simplified_days(home: Home) -> None:
    updated = with_simplified_days(
        home, CUISINE, {SimplifiedRange.MORNING: range(5), SimplifiedRange.EVENING: range(7)}
    )
    events = {e.event_id: e for e in updated.room(CUISINE).events}
    assert events[7].recurrence == 0b0011111
    assert events[8].recurrence == 127
    assert events[9].recurrence == 0
    cuisine = updated.room(CUISINE).with_settings(
        HeaterSettings(HeaterMode.PROGRAM, 19.0, 15.5, 19.5, 30.0)
    )
    assert target_temperature(cuisine, at(18, 0)) == 19.5  # Thursday evening
