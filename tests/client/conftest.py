"""Shared fixtures for the homesmartlink client tests.

The cloud is replaced by a local aiohttp server (FakeCloud) so that requests,
timeouts and connection errors go through the real HTTP stack.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from homesmartlink import HomeSmartLinkClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EMAIL = "user@example.invalid"
PASSWORD = "not-a-real-password"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@dataclass
class Reply:
    status: int = 200
    payload: Any = None
    body: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0


@dataclass
class Recorded:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    json: Any


class FakeCloud:
    """Queue of canned replies per (method, path); the last reply repeats."""

    def __init__(self) -> None:
        self._replies: dict[tuple[str, str], deque[Reply]] = defaultdict(deque)
        self.requests: list[Recorded] = []

    def add(self, method: str, path: str, **kwargs: Any) -> None:
        self._replies[(method, "/Prod/" + path)].append(Reply(**kwargs))

    def calls(self, method: str, path: str) -> list[Recorded]:
        return [r for r in self.requests if r.method == method and r.path == "/Prod/" + path]

    async def handle(self, request: web.Request) -> web.StreamResponse:
        body = await request.text()
        self.requests.append(
            Recorded(
                method=request.method,
                path=request.path,
                query=dict(request.query),
                headers=dict(request.headers),
                json=json.loads(body) if body else None,
            )
        )
        queue = self._replies.get((request.method, request.path))
        if not queue:
            return web.Response(status=599, text="no canned reply")
        reply = queue.popleft() if len(queue) > 1 else queue[0]
        if reply.delay:
            await asyncio.sleep(reply.delay)
        if reply.body is not None:
            return web.Response(status=reply.status, text=reply.body, headers=reply.headers)
        return web.json_response(reply.payload, status=reply.status, headers=reply.headers)


@pytest.fixture
def home_payload() -> dict[str, Any]:
    payload: dict[str, Any] = load_fixture("api/home.json")
    return payload


@pytest.fixture
def home_id(home_payload: dict[str, Any]) -> str:
    return str(home_payload["_id"])


@pytest.fixture
async def cloud() -> AsyncIterator[tuple[FakeCloud, str]]:
    fake = FakeCloud()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", fake.handle)
    server = TestServer(app)
    await server.start_server()
    try:
        yield fake, str(server.make_url("/Prod/"))
    finally:
        await server.close()


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as http:
        yield http


@pytest.fixture
def fake(cloud: tuple[FakeCloud, str]) -> FakeCloud:
    return cloud[0]


@pytest.fixture
def client(cloud: tuple[FakeCloud, str], session: aiohttp.ClientSession) -> HomeSmartLinkClient:
    return HomeSmartLinkClient(session, EMAIL, PASSWORD, base_url=cloud[1], timeout=0.5)
