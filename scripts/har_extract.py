#!/usr/bin/env python3
"""Extract and anonymize Home-SmartLink API traffic from HAR captures.

Usage:
    python -I scripts/har_extract.py captures/ -o captures/extracted/

For every ``*.har`` file in the input directory, keeps only requests to the
Home-SmartLink cloud host and writes ``<capture>.json`` plus a ``summary.md``
endpoint table. Every secret, identifier and personal value is replaced
*before* anything is written:

* identifiers become stable pseudonyms (``<ID_1>``, ``<DEVICE_2>``...) shared
  across all captures, so relations (home -> rooms -> devices) stay readable;
* credentials, tokens and keys become ``<MASKED_*>`` placeholders;
* emails, JWTs and 24-hex ids are also scrubbed inside free text, URLs and
  query strings.

As a final safety net the script remembers every raw value it replaced and
fails if any of them still appears in the output files.

Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

DEFAULT_HOST = "execute-api.eu-west-3.amazonaws.com"

# Headers that carry no information about the API contract.
DROPPED_HEADERS = {
    "accept-encoding",
    "connection",
    "content-length",
    "host",
    "date",
    "via",
    "x-amz-cf-id",
    "x-amz-cf-pop",
    "x-cache",
}
SECRET_HEADER_RE = re.compile(
    r"^(authorization|cookie|set-cookie|x-session|x-api-key|x-amz-.*id|x-.*token.*|x-.*key.*)$",
    re.I,
)

# JSON keys whose values are secrets: replaced by a fixed placeholder.
SECRET_KEY_RE = re.compile(r"(token|password|passwd|secret|cryptogram|session)", re.I)
# JSON keys whose values identify the user, a device or a place: pseudonymized.
PSEUDO_KEYS: dict[str, str] = {
    "_id": "ID",
    "id": "ID",
    "homeid": "ID",
    "homeId": "ID",
    "prmId": "ID",
    "identifier": "ID",
    "client": "CLIENT",
    "header": "DEVICE",
    "serial": "DEVICE",
    "mac": "DEVICE",
    "ssid": "SSID",
}
PERSONAL_KEY_RE = re.compile(
    r"^(e?mail|login|username|account|user_?id|firstName|lastName|phone|address|street|"
    r"zipCode|postalCode|locality|city|latitude|longitude|lat|lon|lng)$",
    re.I,
)
# Keys that are personal only inside some parents (e.g. the name of an invited person).
PERSONAL_NAME_PARENTS = {"invitation", "invitations"}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
HEX24_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{24}(?![0-9a-fA-F])")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class Anonymizer:
    """Replace sensitive values, keeping a registry of what was replaced."""

    def __init__(self) -> None:
        self._pseudonyms: dict[tuple[str, str], str] = {}
        self._counters: dict[str, int] = defaultdict(int)
        self.raw_secrets: set[str] = set()

    def pseudonym(self, kind: str, value: str) -> str:
        key = (kind, value)
        if key not in self._pseudonyms:
            self._counters[kind] += 1
            self._pseudonyms[key] = f"<{kind}_{self._counters[kind]}>"
        self._remember(value)
        return self._pseudonyms[key]

    def mask(self, kind: str, value: Any) -> str:
        if isinstance(value, str):
            self._remember(value)
        return f"<MASKED_{kind}>"

    def _remember(self, value: str) -> None:
        # Very short values ("0", "fr") would make the leak check meaningless.
        if len(value) >= 6:
            self.raw_secrets.add(value)

    def text(self, value: str) -> str:
        """Scrub free text: emails, JWTs, UUIDs and 24-hex ids."""
        value = EMAIL_RE.sub(lambda m: self.pseudonym("EMAIL", m.group()), value)
        value = JWT_RE.sub(lambda m: self.mask("JWT", m.group()), value)
        value = UUID_RE.sub(lambda m: self.pseudonym("ID", m.group().lower()), value)
        return HEX24_RE.sub(lambda m: self.pseudonym("ID", m.group().lower()), value)

    def json(self, node: Any, parent: str = "") -> Any:
        if isinstance(node, dict):
            return {k: self._field(k, v, parent) for k, v in node.items()}
        if isinstance(node, list):
            return [self.json(item, parent) for item in node]
        if isinstance(node, str):
            return self.text(node)
        return node

    def _field(self, key: str, value: Any, parent: str) -> Any:
        if value is None or isinstance(value, bool):
            return value
        if SECRET_KEY_RE.search(key):
            return self.mask(key.upper(), value)
        if key in PSEUDO_KEYS and isinstance(value, (str, int)):
            raw = str(value)
            return self.pseudonym(PSEUDO_KEYS[key], raw.lower() if HEX24_RE.fullmatch(raw) else raw)
        if PERSONAL_KEY_RE.match(key) or (key == "name" and parent in PERSONAL_NAME_PARENTS):
            if isinstance(value, (dict, list)):
                return self.json(value, key)
            return self.mask(key.upper(), str(value))
        return self.json(value, key)


def jwt_summary(token: str) -> dict[str, Any] | None:
    """Keep only the shape of a JWT: header alg, claim names, iat/exp."""
    try:
        header, claims = (
            json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            for part in token.split(".")[:2]
        )
    except ValueError:
        return None
    return {
        "alg": header.get("alg"),
        "claims": sorted(claims),
        "iat": claims.get("iat"),
        "exp": claims.get("exp"),
    }


def describe_token(value: str) -> dict[str, Any]:
    """Non-reversible description of an auth token."""
    if JWT_RE.fullmatch(value):
        return {"type": "jwt", **(jwt_summary(value) or {})}
    kind = "hex" if re.fullmatch(r"[0-9a-fA-F]+", value) else "opaque"
    return {"type": kind, "length": len(value)}


def parse_body(text: str | None, anon: Anonymizer) -> Any:
    if not text:
        return None
    try:
        return anon.json(json.loads(text))
    except ValueError:
        return {"_non_json": anon.text(text)[:2000]}


def extract_entry(entry: dict[str, Any], anon: Anonymizer) -> dict[str, Any]:
    req, res = entry["request"], entry["response"]
    url = urlsplit(req["url"])
    headers: dict[str, str] = {}
    tokens: dict[str, Any] = {}
    for h in req["headers"]:
        name = h["name"].lower()
        if name in DROPPED_HEADERS:
            continue
        if SECRET_HEADER_RE.match(name):
            tokens[name] = describe_token(h["value"])
            headers[name] = anon.mask(name.upper(), h["value"])
        else:
            headers[name] = anon.text(h["value"])

    response_body = parse_body(res["content"].get("text"), anon)
    # Describe tokens returned by the API before they are masked away.
    try:
        raw_response = json.loads(res["content"].get("text") or "null")
    except ValueError:
        raw_response = None
    if isinstance(raw_response, dict):
        for key, value in raw_response.items():
            if SECRET_KEY_RE.search(key) and isinstance(value, str):
                tokens[f"response.{key}"] = describe_token(value)

    return {
        "started": entry["startedDateTime"],
        "elapsed_ms": round(entry.get("time", 0)),
        "method": req["method"],
        "path_template": HEX24_RE.sub("{id}", url.path),
        "path": anon.text(url.path),
        "query": {k: anon.text(v) for k, v in parse_qsl(url.query, keep_blank_values=True)},
        "request_headers": headers,
        "request_body": parse_body((req.get("postData") or {}).get("text"), anon),
        "status": res["status"],
        "response_headers": {
            h["name"].lower(): anon.text(h["value"])
            for h in res["headers"]
            if h["name"].lower() not in DROPPED_HEADERS and not SECRET_HEADER_RE.match(h["name"])
        },
        "response_body": response_body,
        "tokens": tokens,
    }


def write_summary(rows: dict[tuple[str, str], dict[str, set[str]]], out: Path) -> None:
    lines = [
        "# Endpoint summary",
        "",
        "Generated by `scripts/har_extract.py`. One row per (method, path template).",
        "",
        "| Method | Path | Captures | Statuses |",
        "|---|---|---|---|",
    ]
    for (method, path), info in sorted(rows.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        lines.append(
            f"| {method} | `{path}` | {', '.join(sorted(info['captures']))} "
            f"| {', '.join(sorted(info['statuses']))} |"
        )
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def leak_check(out: Path, raw_secrets: set[str]) -> list[str]:
    leaks = []
    for path in out.glob("*"):
        content = path.read_text(encoding="utf-8")
        for secret in raw_secrets:
            if secret in content:
                leaks.append(f"{path.name}: leaked value of length {len(secret)}")
    return leaks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("captures", type=Path, help="directory containing *.har files")
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--host", default=DEFAULT_HOST, help="API host suffix to keep")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    anon = Anonymizer()
    rows: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(
        lambda: {"captures": set(), "statuses": set()}
    )

    for har_path in sorted(args.captures.glob("*.har")):
        har = json.loads(har_path.read_text(encoding="utf-8"))
        entries = [
            extract_entry(e, anon)
            for e in har["log"]["entries"]
            if urlsplit(e["request"]["url"]).netloc.endswith(args.host)
        ]
        (args.output / f"{har_path.stem}.json").write_text(
            json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        for e in entries:
            row = rows[(e["method"], e["path_template"])]
            row["captures"].add(har_path.stem)
            row["statuses"].add(str(e["status"]))
        print(f"{har_path.name}: {len(entries)} API requests")

    write_summary(rows, args.output)

    leaks = leak_check(args.output, anon.raw_secrets)
    if leaks:
        print("LEAK CHECK FAILED:", *leaks, sep="\n  ", file=sys.stderr)
        return 1
    print(f"leak check OK ({len(anon.raw_secrets)} raw values verified absent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
