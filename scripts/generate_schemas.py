"""Generate src/milton_mcp/schemas.json from Milton's published OpenAPI spec and pricing.

The tools' input schemas, the run envelope (each tool's outputSchema) and the fallback model list
all come from Milton's public API description, so the server never drifts from the API it calls:

    python scripts/generate_schemas.py                       # from https://withmilton.ai
    python scripts/generate_schemas.py --spec ../milton/go-services/cmd/api/openapi.yaml \\
        --pricing pricing.json                               # from a local checkout
    python scripts/generate_schemas.py --check               # exit 1 if the bundled copy is stale
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

import yaml

DEFAULT_BASE = "https://withmilton.ai"
OUT_PATH = Path(__file__).resolve().parents[1] / "src" / "milton_mcp" / "schemas.json"

# The agents this server exposes. risk and portfolio are left out for now; desk runs without
# portfolio_id (it sizes on a hypothetical portfolio).
AGENTS = ("technical", "fundamental", "macro", "quant", "desk")
DROPPED_FIELDS = {"portfolio_id"}
# Added by the server itself, with the offered models and effort levels as enums.
MODEL_FIELDS = {"model", "effort"}
# Top-level combinators some MCP hosts reject in a tool's input schema.
TOP_LEVEL_COMBINATORS = {"oneOf", "anyOf", "allOf", "dependentRequired"}
# OpenAPI-only formats; strict JSON Schema validators reject an unknown format.
OPENAPI_FORMATS = {"int32", "int64", "float", "double", "byte", "binary", "password"}


def _load(source: str) -> str:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=30) as resp:
            return resp.read().decode()
    return Path(source).read_text()


def _camel(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def _input_schema(spec: dict[str, Any], agent: str) -> dict[str, Any]:
    schema = copy.deepcopy(spec["components"]["schemas"][f"{_camel(agent)}RunRequest"])
    for key in TOP_LEVEL_COMBINATORS | {"description"}:
        schema.pop(key, None)
    props = schema.get("properties", {})
    for name in DROPPED_FIELDS | MODEL_FIELDS:
        props.pop(name, None)
    schema["properties"] = props
    schema["required"] = [r for r in schema.get("required", []) if r in props]
    schema["additionalProperties"] = False
    return schema


def _waits(spec: dict[str, Any], agent: str) -> bool:
    """Whether the start route takes ?wait (desk, the long-running agent, doesn't)."""
    params = spec["paths"][f"/api/v1/agents/{agent}/runs"]["post"].get("parameters", [])
    return any(p.get("$ref", "").endswith("/AgentRunWait") for p in params)


def _to_json_schema(node: Any, schemas: dict[str, Any]) -> Any:
    """OpenAPI 3.0 → JSON Schema 2020-12: inline component $refs, nullable → anyOf with null."""
    if isinstance(node, list):
        return [_to_json_schema(x, schemas) for x in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        return _to_json_schema(schemas[ref.removeprefix("#/components/schemas/")], schemas)
    out = {k: _to_json_schema(v, schemas) for k, v in node.items() if k != "nullable"}
    if out.get("format") in OPENAPI_FORMATS:
        del out["format"]
    if node.get("nullable") is True:
        # anyOf with single-type branches, not a type array: hosts that map tool schemas onto a
        # single-`type` dialect reject type arrays.
        description = out.pop("description", None)
        out = {"anyOf": [out, {"type": "null"}]}
        if description:
            out["description"] = description
    return out


def build(spec_text: str, pricing: dict[str, Any]) -> dict[str, Any]:
    spec = yaml.safe_load(spec_text)
    schemas = spec["components"]["schemas"]
    agents = {agent: {"input_schema": _input_schema(spec, agent), "waits": _waits(spec, agent)} for agent in AGENTS}
    envelope = _to_json_schema(schemas["AgentRunEnvelope"], schemas)
    efforts = pricing.get("efforts")
    if not efforts:
        raise SystemExit("pricing has no efforts: the API predates per-run model and effort")
    return {
        "agents": agents,
        "envelope_schema": envelope,
        "models": {model: list(levels) for model, levels in sorted(efforts.items())},
    }


def render(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spec", default=f"{DEFAULT_BASE}/api/v1/openapi.yaml", help="OpenAPI spec URL or path")
    parser.add_argument("--pricing", default=f"{DEFAULT_BASE}/api/v1/pricing", help="pricing JSON URL or path")
    parser.add_argument("--check", action="store_true", help="fail if the bundled schemas.json is stale")
    args = parser.parse_args(argv)

    text = render(build(_load(args.spec), json.loads(_load(args.pricing))))
    if args.check:
        if OUT_PATH.read_text() != text:
            print(f"{OUT_PATH} is stale; run scripts/generate_schemas.py", file=sys.stderr)
            return 1
        return 0
    OUT_PATH.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
