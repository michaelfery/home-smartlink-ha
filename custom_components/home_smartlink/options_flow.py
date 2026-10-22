"""Options flow: polling intervals and weekly program editor."""

from __future__ import annotations

from collections.abc import Callable
from datetime import time
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.config_entries import ConfigEntryState, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TimeSelector,
)
from homeassistant.util import dt as dt_util

from homesmartlink import Home, HomeSmartLinkError, ProgramEvent, Room, UnsupportedCommandError
from homesmartlink.program import (
    ADVANCED_SLOTS,
    COMFORT_RANGE,
    ECO_RANGE,
    SIMPLIFIED_EVENT_IDS,
    WEEKDAYS,
    SimplifiedRange,
    days_from_mask,
    with_advanced_slot,
    with_program_temperatures,
    with_programming_preference,
    with_simplified_days,
    with_simplified_times,
)

from .const import (
    CONF_DIAGNOSIS_INTERVAL,
    CONF_SCAN_INTERVAL,
    DEFAULT_DIAGNOSIS_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    MAX_DIAGNOSIS_INTERVAL,
    MIN_DIAGNOSIS_INTERVAL,
    MIN_SCAN_INTERVAL,
)

if TYPE_CHECKING:
    from .coordinator import HomeSmartLinkCoordinator

ROOM = "room"
PREFERENCE = "programming_preference"
ECO = "eco_temperature"
COMFORT = "comfort_temperature"
START, END, DAYS = "start", "end", "days"
ADVANCED, SIMPLIFIED = "advanced", "simplified"

INTERVALS_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_SCAN_INTERVAL): NumberSelector(
            NumberSelectorConfig(
                min=MIN_SCAN_INTERVAL,
                max=3600,
                step=1,
                unit_of_measurement="s",
                mode=NumberSelectorMode.BOX,
            )
        ),
        probatio.Required(CONF_DIAGNOSIS_INTERVAL): NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=MAX_DIAGNOSIS_INTERVAL,
                step=1,
                unit_of_measurement="min",
                mode=NumberSelectorMode.BOX,
            )
        ),
    }
)

DAYS_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=list(WEEKDAYS),
        multiple=True,
        mode=SelectSelectorMode.LIST,
        translation_key="weekday",
    )
)


def _temperature(bounds: tuple[float, float]) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=bounds[0],
            max=bounds[1],
            step=0.5,
            unit_of_measurement="°C",
            mode=NumberSelectorMode.BOX,
        )
    )


ROOM_SETTINGS_SCHEMA = probatio.Schema(
    {
        probatio.Required(PREFERENCE): SelectSelector(
            SelectSelectorConfig(
                options=[ADVANCED, SIMPLIFIED],
                mode=SelectSelectorMode.LIST,
                translation_key="programming_preference",
            )
        ),
        probatio.Required(ECO): _temperature(ECO_RANGE),
        probatio.Required(COMFORT): _temperature(COMFORT_RANGE),
    }
)


def _range_schema(with_times: bool = True) -> section:
    fields: dict[Any, Any] = {}
    if with_times:
        fields[probatio.Required(START)] = TimeSelector()
        fields[probatio.Required(END)] = TimeSelector()
    fields[probatio.Optional(DAYS)] = DAYS_SELECTOR
    return section(probatio.Schema(fields), {"collapsed": False})


ADVANCED_SCHEMA = probatio.Schema(
    {probatio.Required(f"slot{n}"): _range_schema() for n in ADVANCED_SLOTS}
)
SIMPLIFIED_SCHEMA = probatio.Schema(
    {
        probatio.Required(SimplifiedRange.MORNING.value): _range_schema(),
        probatio.Required(SimplifiedRange.DAY.value): _range_schema(with_times=False),
        probatio.Required(SimplifiedRange.EVENING.value): _range_schema(),
    }
)


def _event_values(event: ProgramEvent) -> dict[str, Any]:
    return {
        START: time(event.start_hour, event.start_minute).isoformat(),
        END: time(event.end_hour, event.end_minute).isoformat(),
        DAYS: [WEEKDAYS[d] for d in sorted(days_from_mask(event.recurrence))],
    }


def _parse_time(value: str) -> time:
    parsed = dt_util.parse_time(value)
    if parsed is None:
        raise UnsupportedCommandError(f"Invalid time {value}")
    return parsed


def _weekdays(values: list[str]) -> list[int]:
    return [WEEKDAYS.index(v) for v in values]


class HomeSmartLinkOptionsFlow(OptionsFlowWithReload):
    """Polling intervals, and a program editor mirroring the app's screens."""

    _room_number: int

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["program", "intervals"])

    # -- intervals -----------------------------------------------------------------

    async def async_step_intervals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            diagnosis = int(user_input[CONF_DIAGNOSIS_INTERVAL])
            if 0 < diagnosis < MIN_DIAGNOSIS_INTERVAL:
                errors[CONF_DIAGNOSIS_INTERVAL] = "diagnosis_interval_too_short"
            else:
                return self.async_create_entry(
                    data={
                        **self.config_entry.options,
                        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                        CONF_DIAGNOSIS_INTERVAL: diagnosis,
                    }
                )
        current = {
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_DIAGNOSIS_INTERVAL: DEFAULT_DIAGNOSIS_INTERVAL,
            **self.config_entry.options,
            **(user_input or {}),
        }
        return self.async_show_form(
            step_id="intervals",
            data_schema=self.add_suggested_values_to_schema(INTERVALS_SCHEMA, current),
            errors=errors,
        )

    # -- program editor ----------------------------------------------------------

    @property
    def _coordinator(self) -> HomeSmartLinkCoordinator | None:
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return None
        coordinator: HomeSmartLinkCoordinator = self.config_entry.runtime_data
        return coordinator

    def _room(self) -> Room:
        coordinator = self._coordinator
        assert coordinator is not None
        return coordinator.data.home.room(self._room_number)

    async def _write(
        self, write: Callable[[], Any], errors: dict[str, str], placeholders: dict[str, str]
    ) -> bool:
        try:
            await write()
        except UnsupportedCommandError as err:
            errors["base"] = "invalid_program"
            placeholders["error"] = str(err)
            return False
        except HomeSmartLinkError:
            errors["base"] = "cannot_connect"
            return False
        return True

    async def async_step_program(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the room to edit."""
        coordinator = self._coordinator
        if coordinator is None:
            return self.async_abort(reason="not_loaded")
        if user_input is not None:
            self._room_number = int(user_input[ROOM])
            return await self.async_step_room()
        rooms = [
            SelectOptionDict(value=str(r.number), label=r.name) for r in coordinator.data.home.rooms
        ]
        return self.async_show_form(
            step_id="program",
            data_schema=probatio.Schema(
                {
                    probatio.Required(ROOM): SelectSelector(
                        SelectSelectorConfig(options=rooms, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
        )

    async def async_step_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Programming preference and Program-mode temperatures of the room."""
        coordinator = self._coordinator
        if coordinator is None:
            return self.async_abort(reason="not_loaded")
        room = self._room()
        settings = room.heater_settings
        current = {
            PREFERENCE: SIMPLIFIED if room.ecopilot_enabled else ADVANCED,
            ECO: settings.economy_value,
            COMFORT: settings.standard_value,
        }
        errors: dict[str, str] = {}
        placeholders = {"room": room.name, "error": ""}
        if user_input is not None:
            simplified = user_input[PREFERENCE] == SIMPLIFIED
            eco, comfort = float(user_input[ECO]), float(user_input[COMFORT])
            number = self._room_number
            changed = (simplified, eco, comfort) != (
                room.ecopilot_enabled,
                settings.economy_value,
                settings.standard_value,
            )

            def edit(home: Home) -> Home:
                home = with_program_temperatures(home, number, economy=eco, standard=comfort)
                return with_programming_preference(home, number, simplified)

            if not changed or await self._write(
                lambda: coordinator.async_update_room(number, edit), errors, placeholders
            ):
                return await (
                    self.async_step_simplified() if simplified else self.async_step_advanced()
                )

        return self.async_show_form(
            step_id="room",
            data_schema=self.add_suggested_values_to_schema(
                ROOM_SETTINGS_SCHEMA, user_input or current
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The six slots of an Advanced program."""
        coordinator = self._coordinator
        if coordinator is None:
            return self.async_abort(reason="not_loaded")
        room = self._room()
        events = {e.event_id: e for e in room.events}
        current = {f"slot{n}": _event_values(events[n]) for n in ADVANCED_SLOTS if n in events}
        errors: dict[str, str] = {}
        placeholders = {"room": room.name, "error": ""}
        if user_input is not None:
            number = self._room_number
            changed = {
                n: user_input[f"slot{n}"]
                for n in ADVANCED_SLOTS
                if _normalized(user_input[f"slot{n}"]) != _normalized(current.get(f"slot{n}", {}))
            }

            def edit(home: Home) -> Home:
                for n, slot in changed.items():
                    home = with_advanced_slot(
                        home,
                        number,
                        n,
                        _parse_time(slot[START]),
                        _parse_time(slot[END]),
                        _weekdays(slot.get(DAYS, [])),
                    )
                return home

            if not changed:
                return self.async_abort(reason="program_unchanged")
            if await self._write(
                lambda: coordinator.async_update_program(edit), errors, placeholders
            ):
                return self.async_abort(reason="program_saved")

        return self.async_show_form(
            step_id="advanced",
            data_schema=self.add_suggested_values_to_schema(ADVANCED_SCHEMA, user_input or current),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_simplified(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Morning, Day and Evening ranges of a Simplified program."""
        coordinator = self._coordinator
        if coordinator is None:
            return self.async_abort(reason="not_loaded")
        room = self._room()
        events = {e.event_id: e for e in room.events}
        current = {
            r.value: _event_values(events[SIMPLIFIED_EVENT_IDS[r]])
            for r in SimplifiedRange
            if SIMPLIFIED_EVENT_IDS[r] in events
        }
        current[SimplifiedRange.DAY.value] = {
            DAYS: current.get(SimplifiedRange.DAY.value, {}).get(DAYS, [])
        }
        errors: dict[str, str] = {}
        placeholders = {"room": room.name, "error": ""}
        if user_input is not None:
            number = self._room_number
            morning, day, evening = (user_input[r.value] for r in SimplifiedRange)
            if all(
                _normalized(user_input[r.value]) == _normalized(current.get(r.value, {}))
                for r in SimplifiedRange
            ):
                return self.async_abort(reason="program_unchanged")

            def edit(home: Home) -> Home:
                home = with_simplified_times(
                    home,
                    number,
                    (_parse_time(morning[START]), _parse_time(morning[END])),
                    (_parse_time(evening[START]), _parse_time(evening[END])),
                )
                return with_simplified_days(
                    home,
                    number,
                    {
                        SimplifiedRange.MORNING: _weekdays(morning.get(DAYS, [])),
                        SimplifiedRange.DAY: _weekdays(day.get(DAYS, [])),
                        SimplifiedRange.EVENING: _weekdays(evening.get(DAYS, [])),
                    },
                )

            if await self._write(
                lambda: coordinator.async_update_program(edit), errors, placeholders
            ):
                return self.async_abort(reason="program_saved")

        return self.async_show_form(
            step_id="simplified",
            data_schema=self.add_suggested_values_to_schema(
                SIMPLIFIED_SCHEMA, user_input or current
            ),
            errors=errors,
            description_placeholders=placeholders,
        )


def _normalized(values: dict[str, Any]) -> tuple[Any, ...]:
    """Compare form values regardless of seconds formatting and day order."""

    def hhmm(value: Any) -> str | None:
        return str(value)[:5] if value else None

    return (
        hhmm(values.get(START)),
        hhmm(values.get(END)),
        tuple(sorted(values.get(DAYS) or [], key=WEEKDAYS.index)),
    )
