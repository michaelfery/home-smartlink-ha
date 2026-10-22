# Home-SmartLink for Home Assistant

Custom integration for **Carrera Home-SmartLink** pilot-wire thermostats (fil pilote
adapters for electric heaters), through the Home-SmartLink cloud used by the mobile app.

```text
thermostats ──(BLE mesh)── Home-SmartLink box ──(Wi-Fi)── Home-SmartLink cloud ── Home Assistant
```

> [!WARNING]
> **Unofficial.** Not affiliated with or endorsed by Carrera or Texas de France. The cloud
> API is undocumented. It was reverse-engineered from the Android app (see
> [docs/API.md](docs/API.md)) and may change without notice.

This repository contains two parts:

- [`custom_components/home_smartlink`](custom_components/home_smartlink): the Home Assistant
  integration (installable with HACS);
- [`homesmartlink`](homesmartlink): an async Python client for the cloud API, with no Home
  Assistant dependency, published on PyPI.

## Features

For each room with a thermostat:

| Entity | Content |
|---|---|
| `climate.<room>_thermostat` | Mode, presets, target temperature, measured temperature, weekly program (attributes) |
| `sensor.<room>_thermostat_temperature` | Measured temperature |
| `number.<room>_thermostat_eco_temperature_program` | Eco temperature of Program mode (13–19 °C) |
| `number.<room>_thermostat_comfort_temperature_program` | Comfort temperature of Program mode (13–30 °C) |
| `select.<room>_thermostat_programming_preference` | Program type: `advanced` or `simplified` |

For the box (diagnostic entities): last connection to the cloud, and time of the last
thermostat status update.

### Modes

| Home Assistant | Home-SmartLink app |
|---|---|
| `heat` | Manual (**M**) at the target temperature |
| `auto` | Program (clock), the weekly program set in the app |
| `off` | Stop (power button) |
| preset `comfort` | Manual at the room's comfort temperature (sun button) |
| preset `eco` | Manual at the room's eco temperature (moon button) |
| preset `away` | Antifreeze (snowflake) |

Target temperature: 13.5 to 30 °C, in 0.5 °C steps (the app's range). Setting a temperature
switches the room to Manual, like the app's dial.

### Program mode (`auto`)

The heater uses the room's **comfort temperature while a program slot is active**, and its
**eco temperature otherwise**. In `auto`, the climate entity shows that effective target. Its
attributes give `program_state` (`comfort`/`eco`), `active_slot` and the whole `program`.

Two kinds of program exist, chosen with the *Programming preference* select:

- **Advanced**: six slots, each with its hours and weekdays (the app's calendar screen).
  Edit them with the `home_smartlink.set_program_slot` action:

  ```yaml
  action: home_smartlink.set_program_slot
  target:
    entity_id: climate.bathroom_thermostat
  data:
    slot: 2
    start: "17:00"
    end: "21:30"
    days: [monday, tuesday, wednesday, thursday, friday]  # [] disables the slot
  ```

- **Simplified**: Morning, Day and Evening ranges, each active on chosen weekdays. Day always
  spans from the end of Morning to the start of Evening. Edit them with
  `home_smartlink.set_simplified_program`; omitted fields keep their value:

  ```yaml
  action: home_smartlink.set_simplified_program
  target:
    entity_id: climate.kitchen_thermostat
  data:
    morning_start: "06:00"
    morning_end: "08:00"
    evening_start: "17:00"
    evening_end: "22:00"
    morning_days: [monday, tuesday, wednesday, thursday, friday]
    evening_days: [monday, tuesday, wednesday, thursday, friday, saturday, sunday]
  ```

Times must be multiples of 10 minutes (the thermostats store 10-minute steps). The app's
rules apply: a slot ends after it starts; Morning ends before Evening starts; eco is at least
0.5 °C below comfort.

## Requirements

- Home Assistant **2026.10** or later.
- A Home-SmartLink box connected to the cloud, and the e-mail and password of the mobile app.

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/michaelfery/home-smartlink-ha`,
   category **Integration**.
2. Install **Home-SmartLink**, then restart Home Assistant.

### Manual

Copy `custom_components/home_smartlink` into the `custom_components` folder of your Home
Assistant configuration, then restart Home Assistant.

## Configuration

**Settings → Devices & services → Add integration → Home-SmartLink**, then sign in with the
app's e-mail and password. If the account has access to several homes, choose one; add the
integration again for each other home.

Options (**Configure** on the integration):

| Option | Default | Range | Effect |
|---|---|---|---|
| Polling interval | 60 s | 30–3600 s | How often modes and set points are read from the cloud |
| Diagnosis interval | 15 min | 0 (off), 5–120 min | How often the box is asked to poll the thermostats, which refreshes measured temperatures |

If the password changes, Home Assistant asks you to sign in again (re-authentication).

## How data is refreshed

- **Modes and set points** are read from the cloud at every poll. Commands are shown
  immediately, then confirmed by a refresh.
- **Measured temperatures** are only reported by the thermostats during a *diagnosis*.
  The app runs one each time it opens. The integration runs one at start-up and then at the
  diagnosis interval. Results arrive about 1–2 minutes after the request, so a measured
  temperature can be up to the diagnosis interval (+2 min) old. The
  *Thermostat status update* sensor shows when it was collected.
- When the cloud cannot be reached, polling backs off (doubling, up to 10 minutes) and
  returns to normal at the first success.

## Known limitations

- **Cloud only.** No local control: the box and thermostats are only reachable through
  the vendor cloud.
- **No refresh token.** The API has none, so the integration stores your app password in
  the Home Assistant configuration and signs in again when the session expires.
- **Measured temperatures are not live** (see above).
- **Whole-document writes.** Each command saves the whole home document (that is what the
  app does). A change made in the app at the same moment can be overwritten.
- **The `auto` target is computed** from the program and Home Assistant's time zone, the
  same way the app does. It assumes Home Assistant and the home are in the same time zone.
  Antifreeze shows 7 °C, the value the app displays.
- **Not supported:** vacation mode, geofencing, open-window detection, temperature
  limitation, slot modes Boost/Fan beyond setting them, consumption counters. Use the app
  for these.
- The command frames come from the decompiled app ([docs/API.md](docs/API.md) §5). Program
  edits were checked live against the cloud document, not on the thermostats themselves.
- Error responses of the cloud (wrong password, expired session, box offline) were never
  observed. They are handled generically.

## Privacy and security

- Credentials are stored in the Home Assistant config entry (like any cloud integration).
  They are only sent to the Home-SmartLink cloud.
- Neither the password nor the session token is ever logged.
- Raw traffic captures used to study the API are never committed. Test fixtures are
  anonymized, and a test fails if one contains personal data.

## Python library

```python
import aiohttp
from homesmartlink import HeaterMode, HomeSmartLinkClient

async with aiohttp.ClientSession() as session:
    client = HomeSmartLinkClient(session, "email", "password")
    home_id = (await client.login())[0].home_id
    home = await client.get_home(home_id)
    status = await client.get_device_status(home_id)  # measured temperatures
    await client.set_room_state(home_id, room_number=0, mode=HeaterMode.MANUAL, manual_value=19.5)
```

## Development

Requires [uv](https://docs.astral.sh/uv/). Home Assistant 2026.10 needs Python 3.14.

```bash
uv sync --all-groups
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest                              # client tests
uv run pytest -o addopts= tests/components # integration tests (Home Assistant plugin)
```

Fixtures in `tests/fixtures/` are generated from local captures (kept out of git) with
`scripts/build_fixtures.py`, which anonymizes them and refuses to write if anything leaks.
`scripts/har_extract.py` turns captures into readable, anonymized JSON for analysis.

### Release

1. Bump the version in `pyproject.toml`, `homesmartlink/__init__.py` and
   `custom_components/home_smartlink/manifest.json` (version and requirement).
2. Tag `vX.Y.Z` and push the tag. The release workflow checks the versions and publishes
   `homesmartlink` to PyPI (Trusted Publishing).
3. Create a GitHub release for HACS.

## License

[MIT](LICENSE)
