"""Claude.ai and ChatGPT connectors: OAuth discovery from the 401, a 401 when Milton rejects the
token, and runs on the model and effort chosen when connecting."""

from __future__ import annotations

from typing import Any

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from milton_mcp.__main__ import http_app
from milton_mcp.client import MiltonClient
from milton_mcp.config import Settings
from tests.fakes import API_KEY, BASE_URL, CONNECTOR_KEY, FakeMilton

pytestmark = pytest.mark.anyio

METADATA_URL = f"{BASE_URL}/.well-known/oauth-protected-resource/api/mcp"
CHALLENGE = f'Bearer resource_metadata="{METADATA_URL}", scope="agents"'
HOSTED = Settings(base_url=BASE_URL, resource_metadata_url=METADATA_URL)


def make_app(fake: FakeMilton, settings: Settings = HOSTED):
    return http_app(settings, client=MiltonClient.from_settings(settings, transport=fake.transport()))


async def post_rpc(fake: FakeMilton, token: str | None, payload: dict[str, Any], settings: Settings = HOSTED):
    """One raw JSON-RPC POST to the stateless endpoint, as a connector sends it."""
    app = make_app(fake, settings)
    inner = app.app
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:8000", timeout=30)
    async with inner.router.lifespan_context(inner), http:
        return await http.post("/mcp", json=payload, headers=headers)


def technical_call(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "milton_technical_analysis", "arguments": arguments},
    }


async def test_the_401_challenge_points_at_the_protected_resource_metadata(fake: FakeMilton):
    resp = await post_rpc(fake, None, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == CHALLENGE
    assert not fake.requests


async def test_a_token_milton_rejects_is_an_http_401_with_the_challenge(fake: FakeMilton):
    fake.revoked.add(CONNECTOR_KEY)
    resp = await post_rpc(fake, CONNECTOR_KEY, technical_call({"ticker": "NVDA", "horizon": "swing"}))
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == CHALLENGE
    assert "rejected" in resp.json()["error"]
    assert fake.run_posts(), "the token was tried against Milton first"


async def test_an_accepted_token_gets_the_tool_result(fake: FakeMilton):
    resp = await post_rpc(fake, CONNECTOR_KEY, technical_call({"ticker": "NVDA", "horizon": "swing"}))
    assert resp.status_code == 200
    assert resp.json()["result"]["isError"] is False


async def test_other_api_errors_stay_tool_results(fake: FakeMilton):
    fake.error = (402, {"error": "insufficient balance", "code": "insufficient_balance"}, {})
    resp = await post_rpc(fake, CONNECTOR_KEY, technical_call({"ticker": "NVDA", "horizon": "swing"}))
    assert resp.status_code == 200
    assert resp.json()["result"]["isError"] is True


async def test_without_metadata_the_rejection_401_is_a_plain_challenge(fake: FakeMilton):
    fake.revoked.add(API_KEY)
    resp = await post_rpc(
        fake,
        API_KEY,
        technical_call({"ticker": "NVDA", "horizon": "swing", "model": "claude-opus-5-5"}),
        Settings(base_url=BASE_URL),
    )
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


async def connected(fake: FakeMilton, token: str, settings: Settings = HOSTED, arguments: dict[str, Any] | None = None):
    app = make_app(fake, settings)
    inner = app.app
    async with inner.router.lifespan_context(inner):
        http = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        async with http, Client(streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http)) as client:
            tools = await client.list_tools()
            result = await client.call_tool(
                "milton_technical_analysis", arguments or {"ticker": "NVDA", "horizon": "swing"}
            )
    return {t.name: t for t in tools.tools}, result


async def test_connector_tools_take_no_model_or_effort(fake: FakeMilton):
    tools, result = await connected(fake, CONNECTOR_KEY)
    for name, tool in tools.items():
        if name == "milton_get_run":
            continue
        assert "model" not in tool.input_schema["properties"], name
        assert "effort" not in tool.input_schema["properties"], name
        assert "model" not in tool.input_schema.get("required", []), name
        assert "chosen when Milton was connected" in (tool.description or ""), name
    assert result.is_error is False


async def test_api_token_tools_still_require_a_model(fake: FakeMilton):
    tools, _ = await connected(
        fake, API_KEY, arguments={"ticker": "NVDA", "horizon": "swing", "model": "claude-opus-5-5"}
    )
    schema = tools["milton_technical_analysis"].input_schema
    assert "model" in schema["required"]
    assert "effort" in schema["properties"]


async def test_a_connector_call_never_sends_model_or_effort(fake: FakeMilton):
    settings = Settings(
        base_url=BASE_URL, resource_metadata_url=METADATA_URL, default_model="gpt-6.1-sol", default_effort="low"
    )
    await connected(
        fake,
        CONNECTOR_KEY,
        settings,
        {"ticker": "NVDA", "horizon": "swing", "model": "claude-opus-5-5", "effort": "max"},
    )
    (post,) = fake.run_posts()
    body = FakeMilton.body(post)
    assert "model" not in body and "effort" not in body
    assert body["ticker"] == "NVDA"
