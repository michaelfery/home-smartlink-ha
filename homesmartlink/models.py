"""Typed views over the Home-SmartLink API payloads."""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from datetime import datetime
from enum import IntEnum
from typing import Any


class HeaterMode(IntEnum):
    """`heaterSettings.currentMode` values written by the app."""

    STOP = 1
    ANTIFREEZE = 2
    MANUAL = 3
    PROGRAM = 4


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class Invitation:
    """Access of the account to one home (`signin` / `auth` responses)."""

    id: str
    home_id: str
    role: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Invitation:
        return cls(id=str(data["_id"]), home_id=str(data["homeid"]), role=int(data["role"]))


@dataclass(frozen=True, slots=True)
class HeaterSettings:
    """Heating configuration of one room."""

    current_mode: HeaterMode | int
    manual_value: float
    economy_value: float
    standard_value: float
    limitation_set_point: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HeaterSettings:
        raw_mode = int(data["currentMode"])
        try:
            mode: HeaterMode | int = HeaterMode(raw_mode)
        except ValueError:
            mode = raw_mode
        return cls(
            current_mode=mode,
            manual_value=float(data["manualValue"]),
            economy_value=float(data["economyValue"]),
            standard_value=float(data["standardValue"]),
            limitation_set_point=float(data["limitationSetPoint"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "manualValue": self.manual_value,
            "economyValue": self.economy_value,
            "standardValue": self.standard_value,
            "currentMode": int(self.current_mode),
            "limitationSetPoint": self.limitation_set_point,
        }


@dataclass(frozen=True, slots=True)
class ProgramEvent:
    """One slot of the weekly program of a room."""

    event_id: int
    recurrence: int
    mode: int
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProgramEvent:
        return cls(
            event_id=int(data["eventID"]),
            recurrence=int(data["reccurency"]),
            mode=int(data["mode"]),
            start_hour=int(data["startHour"]),
            start_minute=int(data["startMinute"]),
            end_hour=int(data["endHour"]),
            end_minute=int(data["endMinute"]),
        )


@dataclass(frozen=True, slots=True)
class Accessory:
    """A device paired to a room (category 5 = thermostat)."""

    id: str
    category: int
    software_version: str | None
    created_at: datetime | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Accessory:
        version = data.get("softwareVersion")
        return cls(
            id=str(data["header"]),
            category=int(data["category"]),
            software_version=None if version is None else str(version),
            created_at=_parse_datetime(data.get("creationDate")),
        )


@dataclass(frozen=True, slots=True)
class Room:
    """A room and its heating configuration."""

    number: int
    name: str
    area: int | None
    ecopilot_enabled: bool
    open_window_detection_enabled: bool
    accessories: tuple[Accessory, ...]
    heater_settings: HeaterSettings
    events: tuple[ProgramEvent, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Room:
        area = data.get("area")
        return cls(
            number=int(data["roomNumber"]),
            name=str(data.get("name", "")),
            area=None if area is None else int(area),
            ecopilot_enabled=bool(data.get("ecopilotEnabled", False)),
            open_window_detection_enabled=bool(data.get("openWindowsDetectionEnabled", False)),
            accessories=tuple(Accessory.from_dict(a) for a in data.get("accessories", [])),
            heater_settings=HeaterSettings.from_dict(data["heaterSettings"]),
            events=tuple(ProgramEvent.from_dict(e) for e in data.get("events", [])),
        )

    def with_settings(self, settings: HeaterSettings) -> Room:
        return replace(self, heater_settings=settings)


@dataclass(frozen=True, slots=True)
class Home:
    """A home document (`GET homes/{id}`).

    The raw document is kept because writes must send the whole document back
    (`PUT homes/`), including fields this package does not model.
    """

    id: str
    has_gateway: bool
    rooms: tuple[Room, ...]
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Home:
        return cls(
            id=str(data["_id"]),
            has_gateway=bool(data.get("hasGateway", False)),
            rooms=tuple(Room.from_dict(r) for r in data.get("rooms", [])),
            raw=copy.deepcopy(data),
        )

    def room(self, number: int) -> Room:
        for room in self.rooms:
            if room.number == number:
                return room
        raise KeyError(f"No room {number} in home")

    def with_room_settings(self, number: int, settings: HeaterSettings) -> Home:
        """Return a copy of the home where one room has new heater settings."""
        raw = copy.deepcopy(self.raw)
        for room in raw.get("rooms", []):
            if int(room["roomNumber"]) == number:
                room["heaterSettings"] = {**room["heaterSettings"], **settings.to_dict()}
                break
        else:
            raise KeyError(f"No room {number} in home")
        return Home.from_dict(raw)

    def to_update_payload(self) -> dict[str, Any]:
        """Body of `PUT homes/`: the document without server-managed timestamps."""
        payload = copy.deepcopy(self.raw)
        payload.pop("_created_at", None)
        payload.pop("_updated_at", None)
        return payload


@dataclass(frozen=True, slots=True)
class Gateway:
    """The Home-SmartLink box (`GET device/{homeId}`)."""

    home_id: str
    identifier: str
    version: str | None
    installed_at: datetime | None
    last_connection: datetime | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Gateway:
        version = data.get("version")
        return cls(
            home_id=str(data["homeId"]),
            identifier=str(data["identifier"]),
            version=None if version is None else str(version),
            installed_at=_parse_datetime(data.get("installation")),
            last_connection=_parse_datetime(data.get("lastConnection")),
        )


@dataclass(frozen=True, slots=True)
class RoomStatus:
    """One status string reported by a thermostat during a diagnosis."""

    room_number: int
    device_mode: int
    set_point: float
    ambient_temperature: float
    raw: str
    unknown_d: int
    unknown_s: int
    counters: tuple[int, int, int, int]

    @property
    def heater_mode(self) -> HeaterMode | None:
        """Map the device mode code (0, 1, 3, 4, 7) to the app mode."""
        return DEVICE_MODE_TO_HEATER_MODE.get(self.device_mode)


# Device mode codes seen in status strings and `tests` (docs/API.md §5.2).
DEVICE_MODE_TO_HEATER_MODE: dict[int, HeaterMode] = {
    0: HeaterMode.STOP,
    1: HeaterMode.ANTIFREEZE,
    3: HeaterMode.MANUAL,
    4: HeaterMode.PROGRAM,
    7: HeaterMode.PROGRAM,
}


@dataclass(frozen=True, slots=True)
class DeviceStatus:
    """Result of the last diagnosis (`GET deviceStatus/{homeId}`)."""

    created_at: datetime | None
    rooms: dict[int, RoomStatus]


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """A diagnosis request (`GET diagnosys/{id}`)."""

    id: str
    acknowledged: bool
    updated_at: datetime | None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Diagnosis:
        return cls(
            id=str(data["_id"]),
            acknowledged=bool(data.get("acknowledge", False)),
            updated_at=_parse_datetime(data.get("_updated_at")),
        )
