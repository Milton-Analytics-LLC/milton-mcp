from __future__ import annotations

import httpx2
import pytest
from mcp import Client
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from milton_mcp.client import MiltonClient
from milton_mcp.config import Settings
from milton_mcp.server import MiltonTools, build_server
from milton_mcp.telemetry import CallMetrics
from tests.fakes import API_KEY, BASE_URL, FakeMilton

pytestmark = pytest.mark.anyio

TECHNICAL = {"ticker": "NVDA", "horizon": "swing", "model": "claude-opus-5-5"}


@pytest.fixture
def reader() -> InMemoryMetricReader:
    return InMemoryMetricReader()


@pytest.fixture
def server(fake: FakeMilton, reader: InMemoryMetricReader):
    metrics = CallMetrics(MeterProvider(metric_readers=[reader]))
    client = MiltonClient(BASE_URL, transport=fake.transport())
    return build_server(
        MiltonTools(Settings(base_url=BASE_URL, api_key=API_KEY), client, http_mode=False, metrics=metrics)
    )


def calls(reader: InMemoryMetricReader, method: str | None = None) -> dict[tuple[str, str, str], int]:
    out: dict[tuple[str, str, str], int] = {}
    data = reader.get_metrics_data()
    for rm in data.resource_metrics if data else []:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                assert metric.name == "milton.mcp.calls"
                for point in metric.data.data_points:
                    a = point.attributes
                    if method is None or a["method"] == method:
                        out[(a["method"], a["tool"], a["outcome"])] = point.value
    return out


async def test_counts_lists_and_completed_runs(server, reader):
    async with Client(server, cache=None) as client:
        await client.list_tools()
        await client.call_tool("milton_technical_analysis", TECHNICAL)
    assert calls(reader) == {
        ("tools/list", "none", "ok"): 1,
        ("tools/call", "milton_technical_analysis", "ok"): 1,
    }


async def test_a_run_still_working_is_pending(server, reader, fake: FakeMilton):
    fake.new_run_status = "working"
    async with Client(server, cache=None) as client:
        await client.call_tool("milton_desk", TECHNICAL)
    assert calls(reader, "tools/call") == {("tools/call", "milton_desk", "pending"): 1}


async def test_a_failed_run(server, reader, fake: FakeMilton):
    env = {
        "schema_version": "2",
        "agent": "technical",
        "run": {
            "id": "0b6d1c58-2f0e-5d0a-9e51-6f4a7b3c2d10",
            "status": "failed",
            "model": "m",
            "effort": "high",
            "created_at": "2026-11-04T14:02:00Z",
            "cost_cents": 0,
        },
        "status_detail": "failed:timeout",
        "disclosures": "d",
    }
    fake.add_run(env)
    async with Client(server, cache=None) as client:
        await client.call_tool("milton_get_run", {"run_id": env["run"]["id"]})
    assert calls(reader, "tools/call") == {("tools/call", "milton_get_run", "run_failed"): 1}


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (401, "auth"),
        (402, "payment"),
        (429, "rate_limited"),
        (422, "invalid_input"),
        (404, "not_found"),
        (503, "upstream_error"),
    ],
)
async def test_api_errors(server, reader, fake: FakeMilton, status, outcome):
    fake.error = (status, {"code": "x"}, {})
    async with Client(server, cache=None) as client:
        await client.call_tool("milton_technical_analysis", TECHNICAL)
    assert calls(reader, "tools/call") == {("tools/call", "milton_technical_analysis", outcome): 1}


async def test_unreachable(server, reader, fake: FakeMilton):
    def refuse(request):
        raise httpx2.ConnectError("refused", request=request)

    fake.handle = refuse
    async with Client(server, cache=None) as client:
        await client.call_tool("milton_macro_analysis", {"model": "x"})
    assert calls(reader, "tools/call") == {("tools/call", "milton_macro_analysis", "unreachable"): 1}


async def test_an_unknown_tool_name_is_clamped(server, reader):
    async with Client(server, cache=None) as client:
        await client.call_tool("anything_a_client_sends", {})
    assert calls(reader, "tools/call") == {("tools/call", "other", "invalid_input"): 1}


def test_records_nothing_without_a_configured_sdk():
    CallMetrics().record("tools/call", "milton_desk", "ok")
