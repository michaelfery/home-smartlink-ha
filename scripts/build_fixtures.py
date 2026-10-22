#!/usr/bin/env python3
"""Build anonymized test fixtures from raw captures.

Usage:
    python -I scripts/build_fixtures.py captures/ -o tests/fixtures/

Writes, under the output directory:

* ``api/*.json``: one anonymized response per endpoint;
* ``frames.json``: every captured ``device/notify`` call with the home state it
  produced, used to check the frame encoder byte for byte.

Uses the same Anonymizer as ``har_extract.py`` and refuses to write anything if
a raw identifier or secret would end up in a fixture.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from har_extract import DEFAULT_HOST, EMAIL_RE, HEX24_RE, Anonymizer

ROOM_KEYS = ("roomNumber", "name", "ecopilotEnabled", "heaterSettings", "events")


def load_entries(path: Path) -> list[dict[str, Any]]:
    entries = json.loads(path.read_text(encoding="utf-8"))["log"]["entries"]
    return [e for e in entries if DEFAULT_HOST in e["request"]["url"]]


def body(entry: dict[str, Any], side: str) -> Any:
    if side == "request":
        return json.loads(entry["request"]["postData"]["text"])
    return json.loads(entry["response"]["content"]["text"])


def find(entries: list[dict[str, Any]], method: str, fragment: str) -> dict[str, Any]:
    for e in entries:
        if e["request"]["method"] == method and fragment in e["request"]["url"]:
            return e
    raise LookupError(f"{method} {fragment} not captured")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("captures", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()

    anon = Anonymizer()
    out: dict[str, Any] = {}

    login = load_entries(args.captures / "01_login.har")
    out["api/signin.json"] = body(find(login, "POST", "/api/1/signin"), "response")
    out["api/auth.json"] = body(find(login, "GET", "/api/1/auth"), "response")
    out["api/home.json"] = body(find(login, "GET", "/api/1/homes/"), "response")
    out["api/diagnosys_request.json"] = body(find(login, "POST", "/api/1/diagnosys"), "response")
    out["api/diagnosys_get.json"] = body(find(login, "GET", "/api/1/diagnosys/"), "response")
    browse = load_entries(args.captures / "16_menu_browse.har")
    out["api/gateway.json"] = body(find(browse, "GET", "/api/1/device/"), "response")
    probe = args.captures / "probe" / "deviceStatus_homeId.raw.json"
    out["api/device_status.json"] = json.loads(probe.read_text(encoding="utf-8"))
    out["api/status_ok.json"] = {"status": "OK"}

    frames = []
    for har in sorted(args.captures.glob("*.har")):
        entries = load_entries(har)
        for i, e in enumerate(entries):
            if not e["request"]["url"].endswith("/api/1/device/notify"):
                continue
            later_puts = [x for x in entries[i + 1 :] if x["request"]["method"] == "PUT"]
            if not later_puts:
                continue
            notify = body(e, "request")
            home = body(later_puts[0], "request")
            frames.append(
                {
                    "capture": har.stem,
                    "home_id": home["_id"],
                    "rooms": [{k: r[k] for k in ROOM_KEYS} for r in home["rooms"]],
                    **notify,
                }
            )
    out["frames.json"] = frames

    rendered = {
        name: json.dumps(anon.json(data), indent=2, ensure_ascii=False) + "\n"
        for name, data in out.items()
    }

    leaks = [
        name
        for name, text in rendered.items()
        if EMAIL_RE.search(text)
        or HEX24_RE.search(text)
        or any(secret in text for secret in anon.raw_secrets)
    ]
    if leaks:
        print("LEAK CHECK FAILED, nothing written:", *leaks, sep="\n  ", file=sys.stderr)
        return 1

    for name, text in rendered.items():
        path = args.output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(f"{len(rendered)} fixtures written, {len(frames)} frames, leak check OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
