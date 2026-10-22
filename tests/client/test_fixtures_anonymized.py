"""Guard: committed fixtures must never contain raw personal data or secrets."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from .conftest import FIXTURES

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HEX24_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{24}(?![0-9a-fA-F])")
MUST_BE_MASKED = {
    "token",
    "password",
    "email",
    "meshCryptogram",
    "latitude",
    "longitude",
    "locality",
    "postalCode",
}
PSEUDONYM_RE = re.compile(r"^<[A-Z_]+(_\d+)?>$")

FILES = sorted(FIXTURES.rglob("*.json"))


def _walk(node: Any, key: str = "") -> list[tuple[str, Any]]:
    if isinstance(node, dict):
        return [item for k, v in node.items() for item in _walk(v, k)]
    if isinstance(node, list):
        return [item for v in node for item in _walk(v, key)]
    return [(key, node)]


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(FIXTURES)))
def test_fixture_is_anonymized(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert not EMAIL_RE.search(text)
    assert not HEX24_RE.search(text)
    for key, value in _walk(json.loads(text)):
        if key in MUST_BE_MASKED:
            assert isinstance(value, str) and PSEUDONYM_RE.match(value), key
        if key in {"_id", "homeid", "homeId", "header", "identifier", "client"}:
            assert isinstance(value, str) and PSEUDONYM_RE.match(value), key
