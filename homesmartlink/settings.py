"""Home and room settings edits (port of the app's settings and home screens)."""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

from .exceptions import UnsupportedCommandError
from .frame import MAX_VACATION_DAYS
from .models import HeaterMode, Home

# The app stores DateTime.MinValue when vacation mode is off.
NO_VACATION = "0001-01-01T00:00:00.000Z"
_MODE_NAMES = {
    HeaterMode.STOP: "Stop",
    HeaterMode.ANTIFREEZE: "Antifreeze",
    HeaterMode.MANUAL: "Manual",
    HeaterMode.PROGRAM: "Prog",
}


def vacation_active(home: Home, today: date) -> bool:
    """Same test as the app: the return date is after today."""
    return home.vacation_return_date is not None and home.vacation_return_date > today


def with_vacation(home: Home, return_date: date | None, today: date) -> Home:
    """Start vacation mode until `return_date`, or stop it with None.

    Thermostats stay in frost protection for the days left (at most 227).
    """
    if return_date is not None:
        days = (return_date - today).days
        if days < 1:
            raise UnsupportedCommandError("The return date must be after today")
        if days > MAX_VACATION_DAYS:
            raise UnsupportedCommandError(f"Vacations last at most {MAX_VACATION_DAYS} days")
    raw = copy.deepcopy(home.raw)
    # Midnight local time written with a literal Z, as the app's RFC3339 converter does.
    raw["vacationReturnDate"] = (
        f"{return_date.isoformat()}T00:00:00.000Z" if return_date else NO_VACATION
    )
    return Home.from_dict(raw)


def vacation_description(return_date: date | None) -> str:
    """`description` the app sends when toggling vacation mode."""
    shown = return_date or date(1, 1, 1)
    return f"mode vacance {shown:%m/%d/%Y} 00:00:00"


def with_home_mode(home: Home, mode: HeaterMode) -> Home:
    """Put every room in the same mode ("whole home" buttons of the app)."""
    for room in home.rooms:

        def update(raw: dict[str, Any]) -> None:
            raw["heaterSettings"] = {**raw["heaterSettings"], "currentMode": int(mode)}

        home = home.with_room_raw(room.number, update)
    return home


def home_mode_description(mode: HeaterMode) -> str:
    return f"toute ma maison => {_MODE_NAMES[mode]}"


def with_open_window_detection(home: Home, room_number: int, enabled: bool) -> Home:
    """Stop heating while a window is detected open (room editor switch)."""

    def update(raw: dict[str, Any]) -> None:
        raw["openWindowsDetectionEnabled"] = enabled

    return home.with_room_raw(room_number, update)
