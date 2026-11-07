"""The MCP server: tools/list and tools/call over Milton's REST API."""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

import httpx2
from mcp.server.caching import CacheHint
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp_types import CallToolRequestParams, CallToolResult, ListToolsResult, PaginatedRequestParams, Tool

from milton_mcp import __version__
from milton_mcp.client import ApiError, MiltonClient
from milton_mcp.config import Settings
from milton_mcp.digest import run_result
from milton_mcp.errors import api_error_result, error_result
from milton_mcp.idempotency import IdempotencyKeys, canonical_arguments, retry_key
from milton_mcp.telemetry import NO_TOOL, CallMetrics, outcome_for_status
from milton_mcp.tools import AGENT_TOOLS_BY_NAME, GET_RUN, AgentTool, build_tools, load_bundle

logger = logging.getLogger(__name__)

# tools/list changes only when Milton adds a model or this package updates.
_LIST_CACHE = CacheHint(ttl_ms=60 * 60 * 1000, scope="private")

# Each earlier identical call that failed adds one hop; the bound only stops a runaway loop.
_MAX_RETRIES_AFTER_FAILURE = 5


class MiltonTools:
    """Serves the tools. In stdio mode it calls Milton with the configured API key; in HTTP mode
    with the bearer token each request brings, so one server can serve many callers."""

    def __init__(
        self,
        settings: Settings,
        client: MiltonClient,
        *,
        http_mode: bool,
        keys: IdempotencyKeys | None = None,
        bundle: dict[str, Any] | None = None,
        metrics: CallMetrics | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.http_mode = http_mode
        self.keys = keys or IdempotencyKeys()
        self.metrics = metrics or CallMetrics()
        self.bundle = bundle or load_bundle()
        self._retry_heads: dict[tuple[bytes, str], str] = {}
        self._models: dict[str, list[str]] | None = None

    async def models(self) -> dict[str, list[str]]:
        """Each offered model's effort levels: live from Milton's pricing, else the bundled copy."""
        if self._models is None:
            try:
                efforts = (await self.client.pricing()).get("efforts")
            except (ApiError, httpx2.HTTPError) as exc:
                logger.warning("pricing unavailable, using the bundled model list: %s", type(exc).__name__)
                efforts = None
            if isinstance(efforts, dict) and efforts:
                self._models = {str(model): list(levels) for model, levels in efforts.items()}
            else:
                return dict(self.bundle["models"])
        return self._models

    async def tools(self) -> list[Tool]:
        return build_tools(self.bundle, await self.models(), self.settings)

    async def list_tools(
        self, ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        result = ListToolsResult(tools=await self.tools())
        self.metrics.record("tools/list", NO_TOOL, "ok")
        return result

    async def call_tool(self, ctx: ServerRequestContext[Any], params: CallToolRequestParams) -> CallToolResult:
        result, outcome = await self._call(ctx, params)
        self.metrics.record("tools/call", params.name, outcome)
        return result

    async def _call(self, ctx: ServerRequestContext[Any], params: CallToolRequestParams) -> tuple[CallToolResult, str]:
        token = self._token(ctx)
        if not token:
            where = "an Authorization bearer token" if self.http_mode else "MILTON_API_KEY"
            return error_result(
                f"No Milton API key. Create one at {self.settings.base_url}/settings/api-tokens and send it as {where}."
            ), "auth"
        forward = self._forward(ctx)
        arguments = dict(params.arguments or {})
        run_id = None
        try:
            if params.name == GET_RUN:
                run_id = str(arguments.get("run_id") or "").strip()
                try:
                    uuid.UUID(run_id)
                except ValueError:
                    return error_result("run_id must be the run_id a Milton tool returned (a UUID)."), "invalid_input"
                envelope = await self.client.get_run(run_id, token=token, forward=forward)
                return run_result(envelope, base_url=self.settings.base_url), _run_outcome(envelope)
            spec = AGENT_TOOLS_BY_NAME.get(params.name)
            if spec is None:
                return error_result(f"Unknown tool: {params.name}."), "invalid_input"
            return await self._start_run(spec, arguments, token, forward)
        except ApiError as err:
            result = api_error_result(err, base_url=self.settings.base_url, http_mode=self.http_mode, run_id=run_id)
            return result, outcome_for_status(err.status)
        except httpx2.HTTPError as exc:
            return error_result(
                f"Couldn't reach Milton at {self.settings.base_url} ({type(exc).__name__}). Try again; "
                "repeating the same call won't start a second run."
            ), "unreachable"

    async def _start_run(
        self, spec: AgentTool, arguments: dict[str, Any], token: str, forward: dict[str, str]
    ) -> tuple[CallToolResult, str]:
        body = {name: value for name, value in arguments.items() if value is not None}
        if "model" not in body and self.settings.default_model:
            body["model"] = self.settings.default_model
        if "effort" not in body and self.settings.default_effort:
            body["effort"] = self.settings.default_effort

        canonical = canonical_arguments(body, await self.models())
        keys = self.keys.keys_for(spec.name, canonical)
        token_hash = hashlib.sha256(token.encode()).digest()
        retry_parent = next(
            (
                self._retry_heads[identity]
                for identity in ((token_hash, keys.current), (token_hash, keys.previous))
                if identity in self._retry_heads
            ),
            None,
        )
        waits = bool(self.bundle["agents"][spec.agent]["waits"])
        resp = await self.client.start_run(
            spec.agent,
            body,
            token=token,
            idempotency_key=retry_key(retry_parent) if retry_parent else keys.current,
            previous_idempotency_key=keys.previous if retry_parent is None else None,
            wait=waits,
            forward=forward,
        )
        for _ in range(_MAX_RETRIES_AFTER_FAILURE):
            run = resp.envelope.get("run") or {}
            if not (resp.replayed and run.get("status") == "failed" and run.get("id")):
                break
            retry_parent = str(run["id"])
            resp = await self.client.start_run(
                spec.agent, body, token=token, idempotency_key=retry_key(retry_parent), wait=waits, forward=forward
            )
        run = resp.envelope.get("run") or {}
        if run.get("status") == "failed" and run.get("id"):
            retry_parent = str(run["id"])
        if retry_parent is not None:
            for key in (keys.current, keys.previous):
                self._retry_heads[(token_hash, key)] = retry_parent
        result = run_result(
            resp.envelope, base_url=self.settings.base_url, inputs=canonical, replayed=resp.replayed, waited=waits
        )
        return result, _run_outcome(resp.envelope)

    def _forward(self, ctx: ServerRequestContext[Any]) -> dict[str, str]:
        """Headers passed on to Milton: when enabled in HTTP mode, the caller's IP as Cloudflare
        reported it, so Milton's per-IP limits apply to the caller rather than to this server."""
        request = ctx.request if self.http_mode and self.settings.forward_client_ip else None
        client_ip = request.headers.get("cf-connecting-ip", "").strip() if request is not None else ""
        return {"CF-Connecting-IP": client_ip} if client_ip else {}

    def _token(self, ctx: ServerRequestContext[Any]) -> str | None:
        if not self.http_mode:
            return self.settings.api_key
        request = ctx.request
        header = request.headers.get("authorization", "") if request is not None else ""
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer":
            return None
        return token.strip() or None


def _run_outcome(envelope: dict[str, Any]) -> str:
    status = (envelope.get("run") or {}).get("status")
    if status == "completed":
        return "ok"
    if status == "failed":
        return "run_failed"
    return "pending"


def build_server(tools: MiltonTools) -> Server[Any]:
    return Server(
        "milton",
        version=__version__,
        title="Milton",
        description="Milton's analyst agents: technical, fundamental and macro reads, trade design and the full desk.",
        website_url="https://withmilton.ai",
        cache_hints={"tools/list": _LIST_CACHE, "server/discover": _LIST_CACHE},
        on_list_tools=tools.list_tools,
        on_call_tool=tools.call_tool,
    )
