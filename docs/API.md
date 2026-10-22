# Home-SmartLink cloud API (reverse-engineered)

Status: **draft, built from observed traffic only.** Every statement below cites the
capture it comes from (`captures/<name>.har`, extracted to `captures/extracted/<name>.json`
by `scripts/har_extract.py`). Anything not observed is explicitly marked **not observed**.

- App: `com.texas2france.smartlink` 2.5.0 (build 805), .NET for Android (Mono AOT).
- Captured on 2026-10-22, Android 14 emulator, mitmproxy 12.3.

## 1. Transport

| Item | Value | Source |
|---|---|---|
| Base URL | `https://jcqzjjt6q5.execute-api.eu-west-3.amazonaws.com/Prod/` (AWS API Gateway, eu-west-3) | all captures; also hard-coded in `SmartLink.Core.dll` |
| Content type | `application/json; charset=utf-8` for bodies | all |
| Auth header | `x-session: <token>` | 01, 02, 04-16 |
| Response header `info` | names the server-side handler, e.g. `authentication.login`, `home.get`, `gateway.notify` | all |
| User agent | default Dalvik UA, nothing app-specific | all |
| Realtime channel | **none**: no websocket/MQTT socket opened by the app | 12 (5 min idle, socket table checked) |
| App polling | **none**: the app fetches on start and on screen open only; pull-to-refresh does nothing | 12, 03 |
| Rate limiting | **not observed** (no 429, no rate-limit headers) | all |

The app also embeds a development base URL `http://10.0.2.2:3000/` and an emulator check
(`Build.FINGERPRINT` contains `/emu64`, etc.). On an unmodified emulator, login fails
silently; the captures were made after renaming the emulator device (`emu64a` → `oriole`).
This does not affect the integration.

## 2. Authentication

### `POST api/1/signin` (capture 01)

```json
// request
{"email": "<email>", "password": "<password>", "agent": "Droid", "version": 103}
// response 200
{"token": "<24 hex chars>",
 "invitation": {"_id": "<ID>", "email": "<email>", "homeid": "<HOME_ID>", "role": 2,
                "name": "<name>", "_created_at": "...", "_updated_at": "..."}}
```

- `token`: **opaque 24-hex string** (MongoDB ObjectId format), **not a JWT**. No expiry
  information is returned (no `expires_in`, no claims).
- `invitation.homeid`: the home this account can access. `role: 2` meaning **not observed**
  (likely owner vs guest).
- `agent` / `version`: app identifiers sent verbatim (`"Droid"`, `103`).
- **No refresh token.** No refresh endpoint observed.

### `GET api/1/auth?version=103` (captures 01, 02)

Session check, called on every app start with the stored token.

```json
{"invitations": [{"_id": "<ID>", "email": "<email>", "homeid": "<HOME_ID>", "role": 2, ...}]}
```

On cold start (02) the app reuses the stored token: `auth` → `homes/{id}`, no new `signin`.

## 3. Data model

### Home: `GET api/1/homes/{homeId}` (captures 01, 02)

```text
home
├── _id, client, _created_at, _updated_at
├── GatewayEnabled: bool, hasGateway: bool
├── location {latitude, longitude, locality, postalCode}     (personal, masked)
├── meshCryptogram: str                                       (mesh secret, masked)
├── vacationReturnDate: str
└── rooms[]
    ├── roomNumber: int (0..n-1), name: str, area: int (m²)
    ├── ecopilotEnabled: bool, openWindowsDetectionEnabled: bool
    ├── accessories[] {header: <device id>, category: 5, softwareVersion: "39", creationDate}
    ├── heaterSettings {currentMode, manualValue, economyValue, standardValue, limitationSetPoint}
    └── events[]  (weekly program) {eventID, reccurency, mode, startHour, startMinute, endHour, endMinute}
```

- One thermostat per room in this home; `category: 5` = thermostat (from the device list in 16).
- The **box (gateway) is not in `rooms`**. It is described by `GET api/1/device/{homeId}`.
- **No measured room temperature anywhere** in the observed responses. The home screen
  and the room screen display the **active set point**, not a measurement (see §7).

### Box: `GET api/1/device/{homeId}` (capture 16)

```json
{"homeId": "<HOME_ID>", "hasGateway": true, "version": "1.15", "identifier": "<ID>",
 "installation": "2025-02-01T08:36:14.033Z", "lastConnection": "2026-10-22T16:57:17.245Z"}
```

`lastConnection` is the only liveness signal observed.

### Diagnosis: `POST api/1/diagnosys` + `GET api/1/diagnosys/{id}` (captures 01, 02, 22)

The app sends `{"homeId": ...}` → `{"status": "OK", "id": "<ID>"}`, then polls
`GET diagnosys/{id}` → `{"_id", "acknowledge": true, "_created_at", "_updated_at"}`.

- **On every app start** it polls once, about 3 s later (01, 02, 22).
- From **My devices → stethoscope** (22), it sends the **same POST**, then polls every
  15 s for about 2 min.

In 22 the response never contained more than `acknowledge`, and the app reported every
thermostat as "not responding". Yet the thermostats had answered (see `deviceStatus`
below). What a complete `diagnosys/{id}` response looks like, and what
`acknowledge: false` means, were **not observed**.

### Thermostat status and measured temperature: `GET api/1/deviceStatus/{homeId}` (probe, 2026-10-22)

The app never calls this endpoint in the captures. Its path comes from `SmartLink.Core.dll`.
It was probed **read-only, twice**, with the app's session token
(`captures/probe/`, kept out of git).

```json
// 200, response header info: diagnosys.get_old
{"_created_at": "2026-10-22T17:33:07.961Z", "homeId": "<HOME_ID>",
 "status": ["R0D0M3S0C38A42J0W0M0Y0", "R1D1M3S0C39A42J0W0M0Y0", "R2D0M4S0C40A40J0W0M0Y0"]}
```

- It returns the result of the **last diagnosis**: `_created_at` matches the diagnosis
  launched in 22. Three minutes later, without a new diagnosis, it returned the same snapshot.
  **Fresh values therefore need a `POST diagnosys`.**
- **Latency**: on 2026-10-22 18:33:37Z a diagnosis requested by the client was readable at
  18:34:58Z, about 80 s later. The status `_created_at` is (close to) the **request** time,
  not the completion time; completion showed up as a second change of the diagnosis
  `_updated_at` (`GET diagnosys/{id}`). A status is fresh when
  `_created_at` ≥ the request time. Polling `GET diagnosys/{id}` is not required: the status
  of a diagnosis whose id was never read also arrived.
- Status string, one per room. Fields are a letter followed by digits:

  | Field | Example | Meaning | Confidence |
  |---|---|---|---|
  | `R` | `R0` | `roomNumber` | certain (matches rooms) |
  | `D` | `D0`, `D1` | unknown (0 or 1 observed) | — |
  | `M` | `M3`, `M4` | `currentMode` | certain (matches `heaterSettings`) |
  | `S` | `S0` | unknown | — |
  | `C` | `C38` | set point × 2 (38 → 19.0 °C) | certain (matches `manualValue`/`standardValue`) |
  | `A` | `A42` | **measured ambient temperature × 2** (42 → 21.0 °C) | high: plausible values; the APK sample `TA41` suggests "température ambiante" |
  | `J` `W` `M` `Y` | `J0`... | probably consumption per day/week/month/year (all 0) | low |

- The `tests` regexes sent with `device/notify` (§5.2) describe the same string format.
  The server likely compares them with the next status to decide whether the command was
  applied.
- The second `M` (in `...W0M0Y0`) must be parsed by position, not by letter.

## 4. Heater modes

`heaterSettings.currentMode` per room, as written by the app in `PUT homes/` (captures 05-11):

| UI button | `currentMode` | `description` in notify | HA mapping (proposal) |
|---|---|---|---|
| Stop (power icon) | 1 | `mode Stop` | `HVACMode.OFF` |
| Antifreeze (snowflake) | 2 | `mode Antifreeze` | preset `away` (hors-gel) |
| Manual "M" | 3 | `mode Manual` | `HVACMode.HEAT`, target = `manualValue` |
| Program (clock) | 4 | `mode Prog` | `HVACMode.AUTO` |
| (0) | **not observed** | | `mode_do_nothing` exists in the APK |

Set points (°C, step 0.5 observed):

- `manualValue`: target in Manual mode.
- `economyValue` / `standardValue`: eco / comfort temperatures (15.5 / 19.5 here).
- The **moon** and **sun** buttons do **not** change the mode. They copy `economyValue` or
  `standardValue` into `manualValue` and stay in Manual (09, 10).
- **Range on the app dial: 13.5 to 30 °C, step 0.5** (19: the dial stops at both ends).
  30 equals `limitationSetPoint`. The heater may accept values outside this range, but the
  app never sends them.
- In Program mode, the room screen shows the current program slot (eco/comfort) and its
  temperature (07).

## 5. Writing: changing a mode or a set point

Every command observed (04-11) is **two requests**:

1. `POST api/1/device/notify`: the command sent to the box:

   ```json
   {"homeId": "<HOME_ID>",
    "action": "<base64, 64 bytes>",
    "description": "cockpit room 0 => mode Manual, manuelSP:19)",
    "tests": "R0D[0-9]M3S[0-9]C(26|38)A[0-9]{1,3}J... R1D... R2D..."}
   // response {"status": "OK"}, ~0.7 s
   ```

2. `PUT api/1/homes/`: the **whole home document** (same shape as `GET homes/{id}`,
   without `_created_at`/`_updated_at`), with the room's `heaterSettings` updated.
   Response `{"status": "OK"}`.

**Opening a room screen** sometimes re-sends both requests with the unchanged state: first
open after login (04, 21), and reopening a room after a state change (17). It did not happen on
other opens. The PUT body is then identical to the previous GET.

The app also logs every notify payload to logcat (`DOTNET: sending MQTT...` followed by the
JSON). Despite the label, the transport is the HTTPS `device/notify` call above.

### 5.1 Frames (source: decompiled app, 2026-10-22)

The app's .NET assemblies still contain IL. Decompiling `SmartLink.Core`, `SmartKit` and
`SmartLink.Droid` with ILSpy gave the exact encoders (`SmartKit.PayloadBuilder`,
`SmartLink.Core.Model.DTO.RoomDescriptor`, `HomeExtension`). The earlier
reverse-engineered rules were consistent with them. **All 43 captured room frames and `tests`
strings are reproduced byte for byte** (`tests/client/test_frame.py`).

**Room frame (64 bytes).** Bytes 0-7 are a little-endian 64-bit word:

| Bits | Field |
|---|---|
| 0-7 | `1` (frame type) |
| 12 | open-window detection (`openWindowsDetectionEnabled`) |
| 14-16 | device mode: 0 Stop, 1 Antifreeze, 2 Economy, 3 Standard, 4 Program, 7 Ecopilot |
| 21-26 | eco set point × 2 |
| 27-32 | comfort set point × 2 |
| 33-39 | days until `vacationReturnDate` (0 if none or past, max 227) |
| 40-47 | room number |

The device mode and set points come from the room (`RoomDescriptor`):

| `currentMode` | Device mode | eco × 2 | comfort × 2 |
|---|---|---|---|
| Stop | 0 | 26 | 28 |
| Antifreeze | 1 | 26 | 28 |
| Manual (set point 13.0) | 2 | 26 | `standardValue` × 2 |
| Manual (other set point) | 3 | 26 | `manualValue` × 2 |
| Program, `ecopilotEnabled` false | 4 | `economyValue` × 2 | `standardValue` × 2 |
| Program, `ecopilotEnabled` true | 7 | `economyValue` × 2 | `standardValue` × 2 |

Rooms whose `economyValue` is 65 drive a boiler relay. For them, the set points are 63/63 and
the modes become Stop → 2, Antifreeze → 1, Manual → 3, Program → 4.

Bytes 8-43 hold one 4-byte little-endian word per program event, in document order:

| Bits | Field |
|---|---|
| 0-2 | event `mode` (1 Standard, 2 Boost, 3 Fan) |
| 3-6 | `eventID` |
| 7 | `1` |
| 8-14 | `reccurency` (bit 0 = Monday ... bit 6 = Sunday) |
| 15 | `1` |
| 16-23 | start, in 10-minute slots (truncated) |
| 24-31 | end, in 10-minute slots |

Byte 44 is the room number again; the rest is zero.

**Home frame (512 bytes).** 8 slots of 64 bytes, room *n* at offset `n × 64`. Unused slots
start with `0xFF`.

**When each frame is used** (`device/notify`, then `PUT homes/` in both cases):

| App screen | Field | Content |
|---|---|---|
| Room screen and room editor (mode, set point, eco/comfort, programming preference, open window) | `action` | room frame; `description` = `cockpit room <n> => mode <Mode>, manuelSP:<v>)` |
| Program editor (slot hours, days, mode) and "whole home" commands | `payload` | home frame; `description` null, or a label for whole-home modes |

### 5.2 `tests` field

`HomeExtension.BuildTest`: one regex per **thermostat** (a room with two thermostats gets two
identical lines), rooms in document order, rooms without devices skipped, joined by spaces:
`R<room>D[0-9]M<device mode>S[0-9]C<sp>A[0-9]{1,3}J[0-9]{1,3}W[0-9]{1,3}M[0-9]{1,3}Y[0-9]{1,3}`.
Here `<sp>` is `([0-9]{2})` for device modes 0 and 1, and `(<eco × 2>|<comfort × 2>)` otherwise,
using the values in the table above. Whether the server checks it was not observed.

### 5.3 Weekly program

From `ProgramRange`, `Room` and `EcoPilotRoomExtension`:

- A room in Program mode heats at **`standardValue` while one of its slots is active,
  `economyValue` otherwise** (`Room.CurrentProgrammTemperature`).
- A slot is active when the current weekday is in its `reccurency` mask and
  `start <= now <= end`, comparing minutes, in the phone's local time.
- Which slots count depends on `ecopilotEnabled`, the "Programming preference" of the room
  editor:
  - **Advanced** (false): `events[0:6]`, the six slots of the calendar screen, each with its
    own days;
  - **Simplified** (true): `events[6:9]`, i.e. Morning (`eventID` 7), Day (9) and Evening (8),
    each with its own days. Day always spans from the end of Morning to the start of Evening.
- In Stop and Antifreeze, the app displays a set point of 7 °C.
- Editor rules:
  - eco between 13 and 19 °C, comfort between 13 and 30 °C, eco ≤ comfort − 0.5;
  - an Advanced slot must end after it starts, and a Fan slot lasts at most 2 h;
  - Simplified: Morning and Evening must not be reversed, and Morning must end before Evening
    starts.
- Switching the programming preference only flips `ecopilotEnabled`; no slot is reset.

## 6. Errors observed

**None.** Every request in every capture returned `200`. Not observed yet: wrong password,
expired or invalid token, box offline, malformed command, rate limiting.

## 7. Uncertainties and missing captures

### Uncertain or unknown

1. **Measured room temperature**: available through `GET deviceStatus/{homeId}` (field `A`),
   but only as fresh as the last `POST diagnosys`. Not known:
   - the meaning of `D` and `S`;
   - whether `J`/`W`/`M`/`Y` really are consumption counters;
   - how a non-responding thermostat appears in the list (missing entry? special values?);
   - whether frequent diagnoses have a cost (mesh traffic, thermostat battery if any,
     server rate limit).
2. **Token lifetime**: opaque token, no expiry information, no refresh endpoint observed.
   We don't know when it expires or what an expired-token response looks like.
3. **Frames**: fully specified by the decompiled app (§5.1).
4. **Whether both requests are needed**: does `notify` alone drive the heater? Does `PUT homes`
   alone? The app always sends both.
5. **Concurrency**: `PUT homes/` replaces the whole document, so a write from Home Assistant
   could overwrite a concurrent change from the app (last write wins).
6. **`tests`** semantics, and whether the server validates it.
7. **`diagnosys`**: the meaning of `acknowledge: false` (box offline?).
8. Mode `0` ("do nothing"), set point bounds and step, `role`, `vacationReturnDate`,
   `ecopilotEnabled` and open-window detection: out of scope or not observed.

### Captures still needed

Done on 2026-10-22: A (another room → capture 17), B (Program at another time → 18),
C (set-point range → 19). Every room was verified back to its initial state (20).

| # | Action | Resolves |
|---|---|---|
| D | **Wrong password** login | error format (§6) |
| E | **Logout**, then use the old token (app restart) | revocation, expired-token response (§7.2) |
| F | App start **with the box unplugged** (if acceptable) | box-offline signal: `diagnosys`, `lastConnection` |
| G | Diagnosis on your **phone** (My devices → stethoscope), where it shows temperatures | complete `diagnosys/{id}` response |
| H | Toggle ecopilot on one room, then Program (only if Program writes misbehave) | Program byte 1 rule; capture 23 (Salon in Program) already done |

## 8. Capture method notes

- Android's HTTP stack silently **falls back to a direct connection** when the proxy is down,
  then keeps reusing that pooled connection. Keep mitmproxy running for the whole session,
  or force-stop the app after any proxy restart (this is how captures 17 and 18 were first
  lost).
- `captures/17-20` were cut from one continuous capture by timestamp.
