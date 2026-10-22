"""HomeSmartLinkClient against a local fake of the cloud."""

from __future__ import annotations

import base64
from typing import Any

import aiohttp
import pytest

from homesmartlink import (
    AuthenticationError,
    CannotConnectError,
    CommandFailedError,
    HeaterMode,
    HomeSmartLinkClient,
    HomeSmartLinkError,
    RateLimitError,
    UnsupportedCommandError,
)

from .conftest import EMAIL, PASSWORD, FakeCloud, load_fixture

TOKEN = load_fixture("api/signin.json")["token"]


def add_signin(fake: FakeCloud) -> None:
    fake.add("POST", "api/1/signin", payload=load_fixture("api/signin.json"))


async def test_login_sends_app_identifiers(
    client: HomeSmartLinkClient, fake: FakeCloud, home_id: str
) -> None:
    add_signin(fake)
    invitations = await client.login()
    assert [i.home_id for i in invitations] == [home_id]
    assert fake.calls("POST", "api/1/signin")[0].json == {
        "email": EMAIL,
        "password": PASSWORD,
        "agent": "Droid",
        "version": 103,
    }


async def test_requests_sign_in_lazily_and_send_session(
    client: HomeSmartLinkClient, fake: FakeCloud, home_id: str, home_payload: Any
) -> None:
    add_signin(fake)
    fake.add("GET", f"api/1/homes/{home_id}", payload=home_payload)
    home = await client.get_home(home_id)
    assert [r.name for r in home.rooms] == ["Cuisine", "Salon", "Salle de bain du bas"]
    assert fake.calls("GET", f"api/1/homes/{home_id}")[0].headers["x-session"] == TOKEN


async def test_rejected_session_signs_in_again_once(
    client: HomeSmartLinkClient, fake: FakeCloud, home_id: str, home_payload: Any
) -> None:
    add_signin(fake)
    fake.add("GET", f"api/1/homes/{home_id}", status=401)
    fake.add("GET", f"api/1/homes/{home_id}", payload=home_payload)
    await client.get_home(home_id)
    assert len(fake.calls("POST", "api/1/signin")) == 2
    assert len(fake.calls("GET", f"api/1/homes/{home_id}")) == 2


async def test_session_rejected_twice_raises_auth_error(
    client: HomeSmartLinkClient, fake: FakeCloud, home_id: str
) -> None:
    add_signin(fake)
    fake.add("GET", f"api/1/homes/{home_id}", status=403)
    with pytest.raises(AuthenticationError):
        await client.get_home(home_id)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_bad_credentials(client: HomeSmartLinkClient, fake: FakeCloud, status: int) -> None:
    fake.add("POST", "api/1/signin", status=status, payload={"error": "x"})
    with pytest.raises(AuthenticationError):
        await client.login()


async def test_signin_without_token(client: HomeSmartLinkClient, fake: FakeCloud) -> None:
    fake.add("POST", "api/1/signin", payload={"error": "nope"})
    with pytest.raises(AuthenticationError):
        await client.login()


async def test_server_error(client: HomeSmartLinkClient, fake: FakeCloud, home_id: str) -> None:
    add_signin(fake)
    fake.add("GET", f"api/1/homes/{home_id}", status=502, payload={})
    with pytest.raises(CannotConnectError):
        await client.get_home(home_id)


async def test_timeout(client: HomeSmartLinkClient, fake: FakeCloud, home_id: str) -> None:
    add_signin(fake)
    fake.add("GET", f"api/1/homes/{home_id}", payload={}, delay=2)
    with pytest.raises(CannotConnectError):
        await client.get_home(home_id)


async def test_connection_refused(session: aiohttp.ClientSession) -> None:
    client = HomeSmartLinkClient(session, EMAIL, PASSWORD, base_url="http://127.0.0.1:9/Prod/")
    with pytest.raises(CannotConnectError):
        await client.login()


async def test_rate_limit(client: HomeSmartLinkClient, fake: FakeCloud, home_id: str) -> None:
    add_signin(fake)
    fake.add("GET", f"api/1/homes/{home_id}", status=429, payload={}, headers={"Retry-After": "30"})
    with pytest.raises(RateLimitError) as err:
        await client.get_home(home_id)
    assert err.value.retry_after == 30


async def test_invalid_json(client: HomeSmartLinkClient, fake: FakeCloud, home_id: str) -> None:
    add_signin(fake)
    fake.add("GET", f"api/1/homes/{home_id}", body="<html>")
    with pytest.raises(HomeSmartLinkError):
        await client.get_home(home_id)


async def test_read_endpoints(client: HomeSmartLinkClient, fake: FakeCloud, home_id: str) -> None:
    add_signin(fake)
    diagnosis = load_fixture("api/diagnosys_get.json")
    fake.add("GET", "api/1/auth", payload=load_fixture("api/auth.json"))
    fake.add("GET", f"api/1/device/{home_id}", payload=load_fixture("api/gateway.json"))
    fake.add("GET", f"api/1/deviceStatus/{home_id}", payload=load_fixture("api/device_status.json"))
    fake.add("POST", "api/1/diagnosys", payload=load_fixture("api/diagnosys_request.json"))
    fake.add("GET", f"api/1/diagnosys/{diagnosis['_id']}", payload=diagnosis)

    assert [i.home_id for i in await client.get_invitations()] == [home_id]
    assert fake.calls("GET", "api/1/auth")[0].query == {"version": "103"}
    gateway = await client.get_gateway(home_id)
    assert gateway.version == "1.15"
    assert gateway.last_connection is not None
    status = await client.get_device_status(home_id)
    assert status.rooms[1].ambient_temperature == 21.0
    diagnosis_id = await client.request_diagnosis(home_id)
    assert fake.calls("POST", "api/1/diagnosys")[0].json == {"homeId": home_id}
    assert (await client.get_diagnosis(diagnosis_id)).acknowledged is True


def _frame(capture: str) -> dict[str, Any]:
    return next(f for f in load_fixture("frames.json") if f["capture"] == capture)


def _add_write_routes(fake: FakeCloud, home_id: str, home_payload: Any, notify: str = "OK") -> None:
    add_signin(fake)
    fake.add("GET", f"api/1/homes/{home_id}", payload=home_payload)
    fake.add("POST", "api/1/device/notify", payload={"status": notify})
    fake.add("PUT", "api/1/homes/", payload={"status": "OK"})


async def test_set_room_state_mirrors_the_app(
    client: HomeSmartLinkClient, fake: FakeCloud, home_id: str, home_payload: Any
) -> None:
    """Cuisine Manual 19 -> 19.5 must produce exactly the frame of capture 10."""
    expected = _frame("10_preset_comfort")
    _add_write_routes(fake, home_id, home_payload)

    updated = await client.set_room_state(home_id, 0, HeaterMode.MANUAL, 19.5)

    notify = fake.calls("POST", "api/1/device/notify")[0].json
    assert base64.b64decode(notify["action"]) == base64.b64decode(expected["action"])
    assert notify["tests"] == expected["tests"]
    assert notify["description"] == expected["description"]
    assert notify["homeId"] == home_id

    put = fake.calls("PUT", "api/1/homes/")[0].json
    assert "_created_at" not in put and "_updated_at" not in put
    assert put["meshCryptogram"] == home_payload["meshCryptogram"]
    assert put["rooms"][0]["heaterSettings"]["manualValue"] == 19.5
    assert put["rooms"][0]["heaterSettings"]["currentMode"] == 3
    assert put["rooms"][1] == home_payload["rooms"][1]
    assert updated.room(0).heater_settings.manual_value == 19.5

    # The write sequence is the app's: fresh read, command, then document save.
    order = [(r.method, r.path.rsplit("/", 2)[-2]) for r in fake.requests[1:]]
    assert order == [("GET", "homes"), ("POST", "device"), ("PUT", "homes")]


async def test_set_room_state_validates_before_writing(
    client: HomeSmartLinkClient, fake: FakeCloud, home_id: str, home_payload: Any
) -> None:
    _add_write_routes(fake, home_id, home_payload)
    with pytest.raises(UnsupportedCommandError):
        await client.set_room_state(home_id, 0, HeaterMode.MANUAL, 31.0)
    assert not fake.calls("POST", "api/1/device/notify")


async def test_set_room_state_stops_when_notify_fails(
    client: HomeSmartLinkClient, fake: FakeCloud, home_id: str, home_payload: Any
) -> None:
    _add_write_routes(fake, home_id, home_payload, notify="KO")
    with pytest.raises(CommandFailedError):
        await client.set_room_state(home_id, 0, HeaterMode.STOP)
    assert not fake.calls("PUT", "api/1/homes/")


async def test_repr_hides_secrets(client: HomeSmartLinkClient, fake: FakeCloud) -> None:
    add_signin(fake)
    await client.login()
    text = repr(client)
    assert EMAIL not in text and PASSWORD not in text and TOKEN not in text


async def test_update_program_sends_the_whole_home_frame(
    client: HomeSmartLinkClient, fake: FakeCloud, home_id: str, home_payload: Any
) -> None:
    from datetime import date, time

    from homesmartlink.frame import encode_home
    from homesmartlink.program import with_advanced_slot

    _add_write_routes(fake, home_id, home_payload)
    updated = await client.update_program(
        home_id,
        lambda home: with_advanced_slot(home, 2, 2, time(17), time(21), [0]),
        today=date(2026, 10, 22),
    )
    notify = fake.calls("POST", "api/1/device/notify")[0].json
    assert set(notify) == {"payload", "description", "homeId", "tests"}
    assert notify["description"] is None
    payload = base64.b64decode(notify["payload"])
    assert len(payload) == 512
    assert payload == encode_home(updated, today=date(2026, 10, 22))
    put = fake.calls("PUT", "api/1/homes/")[0].json
    slot = next(e for e in put["rooms"][2]["events"] if e["eventID"] == 2)
    assert (slot["startHour"], slot["endHour"], slot["reccurency"]) == (17, 21, 1)


async def test_rejected_edit_sends_nothing(
    client: HomeSmartLinkClient, fake: FakeCloud, home_id: str, home_payload: Any
) -> None:
    from homesmartlink.program import with_program_temperatures

    _add_write_routes(fake, home_id, home_payload)
    with pytest.raises(UnsupportedCommandError):
        await client.update_room(
            home_id, 2, lambda home: with_program_temperatures(home, 2, economy=19.5)
        )
    assert not fake.calls("POST", "api/1/device/notify")
    assert not fake.calls("PUT", "api/1/homes/")


async def test_update_home_sends_description(
    client: HomeSmartLinkClient, fake: FakeCloud, home_id: str, home_payload: Any
) -> None:
    from datetime import date

    from homesmartlink.settings import vacation_description, with_vacation

    today, back = date(2026, 10, 22), date(2026, 10, 25)
    _add_write_routes(fake, home_id, home_payload)
    await client.update_home(
        home_id,
        lambda home: with_vacation(home, back, today),
        description=vacation_description(back),
        today=today,
    )
    notify = fake.calls("POST", "api/1/device/notify")[0].json
    assert notify["description"] == "mode vacance 10/25/2026 00:00:00"
    assert len(base64.b64decode(notify["payload"])) == 512
    assert fake.calls("PUT", "api/1/homes/")[0].json["vacationReturnDate"] == (
        "2026-10-25T00:00:00.000Z"
    )
