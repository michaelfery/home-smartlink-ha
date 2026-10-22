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
  **Fresh values therefore need a `POST diagnosys`.** How long the thermostats take to
  answer: under about 6 s here (diagnosis requested at 17:33:02, status at 17:33:07).
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

### 5.1 `action` frame (64 bytes, deterministic)

The same state always gives the same bytes (04 = 08 = 11). The frame is **not encrypted**.

```text
offset  0      : 0x01                    constant in all 33 samples (frame type?)
offset  1..4   : uint32 LE "state word"  (see below)
offset  5      : roomNumber              (0 → 00, 1 → 01; capture 17)
offset  6..7   : 00 00
offset  8..    : one 4-byte group per program event of that room
next byte      : roomNumber again        (byte 44 with 9 events; 00 for room 0, 01 for room 1)
rest           : zero padding to 64 bytes
```

**Validation:** an encoder built from these rules reproduces **38/38 captured frames
byte for byte** (3 rooms, 4 modes, Program with ecopilot on and off, set points 13.5 to 30,
recurring and one-off events; captures 04-11, 17-19, 21-23).

**State word** (bytes 1-4 as a little-endian uint32), observed values for room 0:

| Capture | State | Bytes 1-4 | uint32 LE |
|---|---|---|---|
| 08 | Manual 19 | `d0 40 33 01` | `0x013340d0` |
| 10 | Manual 19.5 | `d0 40 3b 01` | `0x013b40d0` |
| 09 | Manual 15.5 | `d0 40 fb 00` | `0x00fb40d0` |
| 05 | Stop | `10 40 e3 00` | `0x00e34010` |
| 06 | Antifreeze | `50 40 e3 00` | `0x00e34050` |
| 07 | Program | `d0 e1 3b 01` | `0x013be1d0` |

- **Bits 16-31 = set point**: `((T * 2) << 3) | 0b011`. Checked on 20 values from 13.5
  to 30 (capture 19). Stop and Antifreeze carry 227 (= 14 °C) whatever `manualValue` is.
  Program carries **`standardValue`**: in 07 and 18 the Cuisine had `manualValue` 19 and
  `standardValue` 19.5, and the frame encoded 19.5. Room 2 (21) encoded 20 = its
  `standardValue`.
- **Byte 1**: `0x10` Stop, `0x50` Antifreeze, `0xd0` Manual. In Program:
  - `0xd0` for room 0 and room 1, both with `ecopilotEnabled` true (07, 18, 23);
  - `0x10` for room 2, with `ecopilotEnabled` false (21).

  Rule used: **Program → `0xd0` if `ecopilotEnabled` else `0x10`**. The three rooms were in
  the same program time slot and the same mode, so ecopilot is the only differing room
  attribute. Consistent with 3 rooms, but not proven on a room where only ecopilot is
  toggled.
- **Byte 2**: `0x40`, except `0xe1` in Program. It is the same at 18:50 and 19:14 local time
  (07, 18), so it is a constant of the mode, not the time of day.

**Program event groups** (bytes 8+, matched one-to-one with `rooms[0].events`, capture 02/08):

```text
byte 0 = 0x80 | (eventID << 3) | mode
byte 1 = 0x80 | reccurency          (7-bit mask, presumably weekdays: 0 → 0x80, 127 → 0xff; capture 21)
byte 2 = start time in 10-minute slots  (5:30 → 33 = 0x21)
byte 3 = end time in 10-minute slots    (22:00 → 132 = 0x84)
```

### 5.2 `tests` field

A space-separated regex per room, `R<room>D[0-9]M<mode>S[0-9]C(<a>|<b>)A..J..W..M..Y..`,
where `M` = `currentMode` and `C` = set point × 2 (38 = 19 °C, 40 = 20 °C). It appears to
describe the device status string expected after the command (the APK also contains the
sample `R7D1M3S4TC44TA41`). **Whether the server requires or checks it was not observed.**
The first alternative in `C(..)` (26 for room 0, 31 for room 2) is not understood.

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
3. **`action` frame**: the rules reproduce all 34 samples, but some fields are not
   understood:
   - the meaning of byte 0;
   - Program-mode byte 1 (the `ecopilotEnabled` hypothesis).

   Not tested: rooms with a number of events other than 9.
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
