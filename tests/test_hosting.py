from __future__ import annotations

import httpx2
import pytest
from mcp import Client
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from milton_mcp.__main__ import http_app
from milton_mcp.client import MiltonClient
from milton_mcp.config import Settings
from milton_mcp.server import MiltonTools, build_server
from tests.fakes import API_KEY, BASE_URL, FakeMilton
from tests.test_http_mode import TECHNICAL, run_over_http

pytestmark = pytest.mark.anyio

INTERNAL = "http://api.internal.test:8080"


async def test_health_check_needs_no_token(fake: FakeMilton):
    app = http_app(Settings(base_url=BASE_URL), client=MiltonClient(BASE_URL, transport=fake.transport()))
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as http:
        resp = await http.get("/healthz")
    assert resp.status_code == 200
    assert not fake.requests


async def test_without_an_api_url_calls_go_to_the_base_url():
    other = "https://milton.example"
    fake = FakeMilton(api_url=other)
    settings = Settings(base_url=other, api_key=API_KEY)
    client = MiltonClient.from_settings(settings, transport=fake.transport())
    async with Client(build_server(MiltonTools(settings, client, http_mode=False)), cache=None) as mcp:
        result = await mcp.call_tool("milton_technical_analysis", TECHNICAL)

    assert result.is_error is False
    assert not fake.misdirected
    (post,) = fake.run_posts()
    assert str(post.url).startswith(other + "/api/v1/agents/technical/runs")


async def test_calls_go_to_the_api_url_and_links_use_the_public_origin(make_server, fake: FakeMilton):
    fake.api_url = INTERNAL
    settings = Settings(base_url=BASE_URL, api_url=INTERNAL, api_key=API_KEY)
    async with Client(make_server(settings), cache=None) as client:
        result = await client.call_tool("milton_technical_analysis", TECHNICAL)

    (post,) = fake.run_posts()
    assert str(post.url).startswith(INTERNAL + "/api/v1/agents/technical/runs")
    run_id = result.structured_content["run"]["id"]
    assert f"View in Milton: {BASE_URL}/runs/{run_id}" in result.content[0].text
    assert INTERNAL not in result.content[0].text


FORWARDING = Settings(base_url=BASE_URL, forward_client_ip=True)


async def test_forwards_the_callers_cloudflare_ip_when_enabled(fake: FakeMilton):
    await run_over_http(fake, API_KEY, FORWARDING, headers={"CF-Connecting-IP": "203.0.113.7"})
    (post,) = fake.run_posts()
    assert post.headers["cf-connecting-ip"] == "203.0.113.7"


async def test_does_not_forward_a_client_ip_by_default(fake: FakeMilton):
    await run_over_http(fake, API_KEY, headers={"CF-Connecting-IP": "203.0.113.7"})
    (post,) = fake.run_posts()
    assert "cf-connecting-ip" not in post.headers


async def test_sends_no_client_ip_when_the_caller_had_none(fake: FakeMilton):
    await run_over_http(fake, API_KEY, FORWARDING)
    (post,) = fake.run_posts()
    assert "cf-connecting-ip" not in post.headers


async def test_propagates_the_trace_to_milton(fake: FakeMilton):
    tracer = TracerProvider().get_tracer("test")
    client = MiltonClient(BASE_URL, transport=fake.transport())
    with tracer.start_as_current_span("tools/call") as span:
        await client.start_run("macro", {"model": "x"}, token=API_KEY, idempotency_key="k", wait=True)
    (post,) = fake.run_posts()
    trace_id = format(span.get_span_context().trace_id, "032x")
    assert post.headers["traceparent"].split("-")[1] == trace_id
    assert trace.get_current_span() is trace.INVALID_SPAN
