from __future__ import annotations

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from milton_mcp.__main__ import http_app
from milton_mcp.client import MiltonClient
from milton_mcp.config import Settings
from tests.fakes import API_KEY, BASE_URL, OTHER_KEY, FakeMilton

pytestmark = pytest.mark.anyio

TECHNICAL = {"ticker": "NVDA", "horizon": "swing", "model": "claude-opus-5-5"}


def make_app(fake: FakeMilton, settings: Settings | None = None):
    settings = settings or Settings(base_url=BASE_URL)
    return http_app(settings, client=MiltonClient(BASE_URL, transport=fake.transport()))


async def test_no_bearer_is_401_with_a_challenge(fake: FakeMilton):
    app = make_app(fake)
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as http:
        resp = await http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"
    assert not fake.requests


async def run_over_http(
    fake: FakeMilton, token: str, settings: Settings | None = None, headers: dict[str, str] | None = None
):
    app = make_app(fake, settings)
    inner = app.app
    async with inner.router.lifespan_context(inner):
        http = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
            headers={"Authorization": f"Bearer {token}", **(headers or {})},
            timeout=30,
        )
        async with http, Client(streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http)) as client:
            tools = await client.list_tools()
            result = await client.call_tool("milton_technical_analysis", TECHNICAL)
    return tools, result


async def test_forwards_each_callers_bearer_to_milton(fake: FakeMilton):
    tools, result = await run_over_http(fake, OTHER_KEY)
    assert "milton_desk" in {t.name for t in tools.tools}
    assert result.is_error is False
    (post,) = fake.run_posts()
    assert post.headers["authorization"] == f"Bearer {OTHER_KEY}"


async def test_never_uses_a_configured_key_in_http_mode(fake: FakeMilton):
    await run_over_http(fake, OTHER_KEY, Settings(base_url=BASE_URL, api_key=API_KEY))
    (post,) = fake.run_posts()
    assert post.headers["authorization"] == f"Bearer {OTHER_KEY}"
