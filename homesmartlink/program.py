"""Weekly program rules (port of the app's ProgramRange, Room and EcoPilot code).

A room in Program mode heats at its comfort temperature (`standardValue`) while
one of its program slots is active, and at its eco temperature otherwise.
Which slots count depends on the room's programming preference:

* Advanced (`ecopilotEnabled` false): the six slots 1-6, each with its days;
* Simplified (`ecopilotEnabled` true): Morning (event 7), Day (9) and
  Evening (8); Day always spans from the end of Morning to the start of Evening.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, time
from enum import IntEnum, StrEnum
from typing import Any

from .exceptions import UnsupportedCommandError
from .models import HeaterMode, Home, ProgramEvent, Room

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
ADVANCED_SLOTS = range(1, 7)

# Set point the app shows for Stop and Antifreeze.
FROST_PROTECTION_TEMPERATURE = 7.0

ECO_RANGE = (13.0, 19.0)
COMFORT_RANGE = (13.0, 30.0)
MIN_ECO_COMFORT_GAP = 0.5
MAX_FAN_MINUTES = 120


class ProgramMode(IntEnum):
    """`mode` of a program slot."""

    STANDARD = 1
    BOOST = 2
    FAN = 3


class SimplifiedRange(StrEnum):
    MORNING = "morning"
    DAY = "day"
    EVENING = "evening"


SIMPLIFIED_EVENT_IDS = {
    SimplifiedRange.MORNING: 7,
    SimplifiedRange.DAY: 9,
    SimplifiedRange.EVENING: 8,
}


def days_from_mask(mask: int) -> frozenset[int]:
    """Weekday indexes (0 = Monday) of a `reccurency` mask."""
    return frozenset(day for day in range(7) if mask & (1 << day))


def mask_from_days(days: Iterable[int]) -> int:
    mask = 0
    for day in days:
        if not 0 <= day <= 6:
            raise UnsupportedCommandError(f"Invalid weekday {day}")
        mask |= 1 << day
    return mask


def _minutes(hour: int, minute: int) -> int:
    return hour * 60 + minute


def program_events(room: Room) -> tuple[ProgramEvent, ...]:
    """The slots that drive the room in Program mode (positions, like the app)."""
    return room.events[6:9] if room.ecopilot_enabled else room.events[:6]


def is_event_active(event: ProgramEvent, now: datetime) -> bool:
    """Same test as the app: right weekday, start <= now <= end (minutes)."""
    if now.weekday() not in days_from_mask(event.recurrence):
        return False
    current = _minutes(now.hour, now.minute)
    return (
        _minutes(event.start_hour, event.start_minute)
        <= current
        <= _minutes(event.end_hour, event.end_minute)
    )


def active_event(room: Room, now: datetime) -> ProgramEvent | None:
    return next((e for e in program_events(room) if is_event_active(e, now)), None)


def target_temperature(room: Room, now: datetime) -> float | None:
    """The set point the app displays for the room at `now` (local time)."""
    settings = room.heater_settings
    mode = settings.current_mode
    if mode in (HeaterMode.STOP, HeaterMode.ANTIFREEZE):
        return FROST_PROTECTION_TEMPERATURE
    if mode is HeaterMode.MANUAL:
        return settings.manual_value
    if mode is HeaterMode.PROGRAM:
        if active_event(room, now) is not None:
            return settings.standard_value
        return settings.economy_value
    return None


# -- edits ---------------------------------------------------------------------


def _check_half_degree(value: float, bounds: tuple[float, float], what: str) -> None:
    low, high = bounds
    if not low <= value <= high or (value * 2) % 1:
        raise UnsupportedCommandError(f"{what} must be {low}-{high} °C by 0.5 steps")


def _check_time(value: time, what: str) -> int:
    if value.minute % 10 or value.second or value.microsecond:
        raise UnsupportedCommandError(f"{what} must be a multiple of 10 minutes")
    return _minutes(value.hour, value.minute)


def _set_event(room: dict[str, Any], event_id: int, **fields: int) -> None:
    for event in room["events"]:
        if int(event["eventID"]) == event_id:
            event.update(fields)
            return
    raise UnsupportedCommandError(f"Room has no program slot {event_id}")


def _times(start: time, end: time) -> dict[str, int]:
    return {
        "startHour": start.hour,
        "startMinute": start.minute,
        "endHour": end.hour,
        "endMinute": end.minute,
    }


def with_program_temperatures(
    home: Home, room_number: int, economy: float | None = None, standard: float | None = None
) -> Home:
    """Eco and comfort temperatures of Program mode (room editor rules)."""
    settings = home.room(room_number).heater_settings
    eco = settings.economy_value if economy is None else economy
    comfort = settings.standard_value if standard is None else standard
    _check_half_degree(eco, ECO_RANGE, "Eco temperature")
    _check_half_degree(comfort, COMFORT_RANGE, "Comfort temperature")
    if eco > comfort - MIN_ECO_COMFORT_GAP:
        raise UnsupportedCommandError("Eco temperature must be at least 0.5 °C below comfort")

    def update(room: dict[str, Any]) -> None:
        room["heaterSettings"] = {
            **room["heaterSettings"],
            "economyValue": eco,
            "standardValue": comfort,
        }

    return home.with_room_raw(room_number, update)


def with_programming_preference(home: Home, room_number: int, simplified: bool) -> Home:
    """Switch between Simplified (ecopilot) and Advanced programs."""

    def update(room: dict[str, Any]) -> None:
        room["ecopilotEnabled"] = simplified

    return home.with_room_raw(room_number, update)


def with_advanced_slot(
    home: Home,
    room_number: int,
    slot: int,
    start: time,
    end: time,
    days: Iterable[int],
    mode: ProgramMode | None = None,
) -> Home:
    """Edit one of the six Advanced slots (program editor rules)."""
    if slot not in ADVANCED_SLOTS:
        raise UnsupportedCommandError(f"Advanced slots are 1-6, not {slot}")
    start_min, end_min = _check_time(start, "Start"), _check_time(end, "End")
    if end_min <= start_min:
        raise UnsupportedCommandError("A slot must end after it starts")
    current = next((e for e in home.room(room_number).events if e.event_id == slot), None)
    if current is None:
        raise UnsupportedCommandError(f"Room has no program slot {slot}")
    new_mode = ProgramMode(current.mode) if mode is None else mode
    if new_mode is ProgramMode.FAN and end_min - start_min > MAX_FAN_MINUTES:
        raise UnsupportedCommandError("Fan slots last at most 2 hours")
    fields = {**_times(start, end), "reccurency": mask_from_days(days), "mode": int(new_mode)}
    return home.with_room_raw(room_number, lambda room: _set_event(room, slot, **fields))


def with_simplified_times(
    home: Home,
    room_number: int,
    morning: tuple[time, time],
    evening: tuple[time, time],
) -> Home:
    """Morning and Evening hours; Day fills the gap between them."""
    morning_start, morning_end = (_check_time(t, "Morning") for t in morning)
    evening_start, evening_end = (_check_time(t, "Evening") for t in evening)
    if morning_start > morning_end or evening_start > evening_end:
        raise UnsupportedCommandError("A range must end after it starts")
    if morning_end > evening_start:
        raise UnsupportedCommandError("Morning must end before Evening starts")

    def update(room: dict[str, Any]) -> None:
        ids = SIMPLIFIED_EVENT_IDS
        _set_event(room, ids[SimplifiedRange.MORNING], **_times(*morning))
        _set_event(room, ids[SimplifiedRange.EVENING], **_times(*evening))
        _set_event(room, ids[SimplifiedRange.DAY], **_times(morning[1], evening[0]))

    return home.with_room_raw(room_number, update)


def with_simplified_days(
    home: Home, room_number: int, days: dict[SimplifiedRange, Iterable[int]]
) -> Home:
    """Weekdays on which each Simplified range heats at comfort temperature."""
    masks = {SIMPLIFIED_EVENT_IDS[r]: mask_from_days(d) for r, d in days.items()}

    def update(room: dict[str, Any]) -> None:
        for event_id, mask in masks.items():
            _set_event(room, event_id, reccurency=mask)

    return home.with_room_raw(room_number, update)
