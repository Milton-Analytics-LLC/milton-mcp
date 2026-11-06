from __future__ import annotations

import json

import yaml

from scripts.generate_schemas import build
from tests.fakes import MODELS

SPEC = {
    "paths": {
        "/api/v1/agents/technical/runs": {
            "post": {
                "parameters": [
                    {"$ref": "#/components/parameters/IdempotencyKeyHeader"},
                    {"$ref": "#/components/parameters/AgentRunWait"},
                ]
            }
        },
        **{
            f"/api/v1/agents/{agent}/runs": {"post": {"parameters": [{"$ref": "#/components/parameters/AgentRunWait"}]}}
            for agent in ("fundamental", "macro", "quant")
        },
        "/api/v1/agents/desk/runs": {
            "post": {"parameters": [{"$ref": "#/components/parameters/IdempotencyKeyHeader"}]}
        },
    },
    "components": {
        "schemas": {
            **{
                f"{name}RunRequest": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "ticker": {"type": "string", "description": "US stock or ETF symbol."},
                        "model": {"type": "string"},
                        "effort": {"type": "string"},
                    },
                    "required": ["model", "ticker"],
                }
                for name in ("Technical", "Fundamental", "Macro", "Quant")
            },
            "DeskRunRequest": {
                "type": "object",
                "description": "Pass exactly one of portfolio_id or positions.",
                "oneOf": [{"required": ["portfolio_id"]}, {"required": ["ticker"]}],
                "properties": {
                    "ticker": {"type": "string"},
                    "portfolio_id": {"type": "string"},
                    "model": {"type": "string"},
                },
                "required": ["model", "ticker", "portfolio_id"],
            },
            "AgentRunEnvelope": {
                "type": "object",
                "properties": {
                    "stance": {"type": "string", "enum": ["bullish", "bearish"], "nullable": True},
                    "run": {
                        "type": "object",
                        "properties": {
                            "duration_ms": {"type": "integer", "format": "int64"},
                            "created_at": {"type": "string", "format": "date-time"},
                            "steps": {"type": "array", "items": {"$ref": "#/components/schemas/AgentRunStep"}},
                        },
                    },
                },
            },
            "AgentRunStep": {"type": "object", "properties": {"name": {"type": "string"}}},
        }
    },
}


def test_builds_tool_inputs_without_model_portfolio_or_combinators():
    out = build(yaml.safe_dump(SPEC), {"efforts": MODELS})
    desk = out["agents"]["desk"]
    assert desk["waits"] is False
    assert desk["input_schema"] == {
        "type": "object",
        "additionalProperties": False,
        "properties": {"ticker": {"type": "string"}},
        "required": ["ticker"],
    }
    assert out["agents"]["technical"]["waits"] is True
    assert set(out["agents"]["technical"]["input_schema"]["properties"]) == {"ticker"}
    assert out["models"] == MODELS


def test_envelope_becomes_json_schema():
    envelope = build(yaml.safe_dump(SPEC), {"efforts": MODELS})["envelope_schema"]
    assert envelope["properties"]["stance"] == {
        "anyOf": [{"type": "string", "enum": ["bullish", "bearish"]}, {"type": "null"}]
    }
    run = envelope["properties"]["run"]["properties"]
    assert run["duration_ms"] == {"type": "integer"}
    assert run["created_at"]["format"] == "date-time"
    assert run["steps"]["items"] == {"type": "object", "properties": {"name": {"type": "string"}}}
    assert "$ref" not in json.dumps(envelope)


def test_refuses_pricing_without_efforts():
    import pytest

    with pytest.raises(SystemExit):
        build(yaml.safe_dump(SPEC), {"rates": []})


def test_bundled_schemas_have_no_openapi_leftovers():
    from milton_mcp.tools import load_bundle

    text = json.dumps(load_bundle())
    for leftover in ('"nullable"', '"$ref"', '"int64"', "portfolio_id"):
        assert leftover not in text


def test_fetches_with_its_own_user_agent(monkeypatch):
    # withmilton.ai's Cloudflare rules answer urllib's default "Python-urllib/x.y" with a 403.
    import io
    import urllib.request

    from scripts import generate_schemas

    seen = {}

    def fake_urlopen(request, timeout):
        seen["user_agent"] = request.get_header("User-agent")
        return io.BytesIO(b"spec")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert generate_schemas._load("https://withmilton.ai/api/v1/openapi.yaml") == "spec"
    assert seen["user_agent"].startswith("milton-mcp-schema-generator")
