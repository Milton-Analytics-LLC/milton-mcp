from __future__ import annotations

import json

import pytest
from mcp import Client

from milton_mcp.config import Settings
from milton_mcp.tools import load_bundle
from tests.fakes import API_KEY, BASE_URL, MODELS

pytestmark = pytest.mark.anyio

EXPECTED = {
    "milton_technical_analysis",
    "milton_fundamental_analysis",
    "milton_macro_analysis",
    "milton_quant_analysis",
    "milton_desk",
    "milton_get_run",
}


async def list_tools(server):
    async with Client(server, cache=None) as client:
        return await client.list_tools()


async def test_lists_exposed_agents_and_get_run(make_server):
    result = await list_tools(make_server())
    assert {t.name for t in result.tools} == EXPECTED
    for tool in result.tools:
        assert tool.title
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert len(tool.name) <= 64
        assert tool.output_schema == load_bundle()["envelope_schema"]


async def test_tools_list_is_cacheable_per_caller(make_server):
    result = await list_tools(make_server())
    assert result.cache_scope == "private"
    assert result.ttl_ms == 3_600_000


async def test_no_portfolio_inputs_and_no_top_level_combinators(make_server):
    result = await list_tools(make_server())
    for tool in result.tools:
        schema = tool.input_schema
        assert schema["type"] == "object"
        assert not {"oneOf", "anyOf", "allOf", "dependentRequired"} & set(schema)
        assert "portfolio_id" not in json.dumps(schema)
        assert "positions" not in schema.get("properties", {})


async def test_agent_tools_take_typed_inputs_plus_model_and_effort(make_server):
    tools = {t.name: t for t in (await list_tools(make_server())).tools}

    technical = tools["milton_technical_analysis"].input_schema
    assert set(technical["properties"]) == {"ticker", "horizon", "model", "effort"}
    assert technical["required"] == ["horizon", "model", "ticker"]
    assert technical["properties"]["horizon"]["enum"] == ["intraday", "swing", "position", "long_term"]
    assert technical["properties"]["model"]["enum"] == sorted(MODELS)
    assert technical["properties"]["effort"]["enum"] == ["low", "medium", "high", "xhigh", "max"]
    assert "claude-haiku-4-5: low, medium" in technical["properties"]["effort"]["description"]
    assert technical["additionalProperties"] is False

    assert set(tools["milton_macro_analysis"].input_schema["properties"]) == {"model", "effort"}
    assert set(tools["milton_desk"].input_schema["properties"]) == {"ticker", "horizon", "model", "effort"}


async def test_descriptions_say_what_returns_and_billing(make_server):
    tools = {t.name: t for t in (await list_tools(make_server())).tools}
    for name in EXPECTED - {"milton_get_run"}:
        description = tools[name].description
        assert "Use it for" in description
        assert "bill to your Milton balance" in description
        assert f"{BASE_URL}/api/v1/pricing" in description
    assert "run_id at once" in tools["milton_desk"].description
    assert "milton_get_run instead" in tools["milton_technical_analysis"].description
    assert "Uses no tokens" in tools["milton_get_run"].description


async def test_default_model_makes_model_optional(make_server):
    settings = Settings(base_url=BASE_URL, api_key=API_KEY, default_model="gpt-6.1-sol", default_effort="low")
    tools = {t.name: t for t in (await list_tools(make_server(settings))).tools}
    schema = tools["milton_quant_analysis"].input_schema
    assert "model" not in schema["required"]
    assert schema["properties"]["model"]["default"] == "gpt-6.1-sol"
    assert schema["properties"]["effort"]["default"] == "low"


async def test_falls_back_to_bundled_models_without_pricing(make_server, fake):
    fake.pricing_status = 503
    tools = {t.name: t for t in (await list_tools(make_server())).tools}
    enum = tools["milton_technical_analysis"].input_schema["properties"]["model"]["enum"]
    assert enum == sorted(load_bundle()["models"])
