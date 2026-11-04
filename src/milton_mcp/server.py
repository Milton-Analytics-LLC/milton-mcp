"""The MCP server: tools/list and tools/call over Milton's REST API."""

from __future__ import annotations

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
from milton_mcp.idempotency import IdempotencyKeys, caller_id, canonical_arguments
from milton_mcp.tools import AGENT_TOOLS_BY_NAME, GET_RUN, AgentTool, build_tools, load_bundle

logger = logging.getLogger(__name__)

# tools/list changes only when Milton adds a model or this package updates.
_LIST_CACHE = CacheHint(ttl_ms=60 * 60 * 1000, scope="private")


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
    ) -> None:
        self.settings = settings
        self.client = client
        self.http_mode = http_mode
        self.keys = keys or IdempotencyKeys()
        self.bundle = bundle or load_bundle()
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
        return ListToolsResult(tools=await self.tools())

    async def call_tool(self, ctx: ServerRequestContext[Any], params: CallToolRequestParams) -> CallToolResult:
        token = self._token(ctx)
        if not token:
            where = "an Authorization bearer token" if self.http_mode else "MILTON_API_KEY"
            return error_result(
                f"No Milton API key. Create one at {self.settings.base_url}/settings/api-tokens and send it as {where}."
            )
        arguments = dict(params.arguments or {})
        run_id = None
        try:
            if params.name == GET_RUN:
                run_id = str(arguments.get("run_id") or "").strip()
                return await self._get_run(run_id, token)
            spec = AGENT_TOOLS_BY_NAME.get(params.name)
            if spec is None:
                return error_result(f"Unknown tool: {params.name}.")
            return await self._start_run(spec, arguments, token)
        except ApiError as err:
            return api_error_result(err, base_url=self.settings.base_url, http_mode=self.http_mode, run_id=run_id)
        except httpx2.HTTPError as exc:
            return error_result(
                f"Couldn't reach Milton at {self.settings.base_url} ({type(exc).__name__}). Try again; "
                "repeating the same call won't start a second run."
            )

    async def _start_run(self, spec: AgentTool, arguments: dict[str, Any], token: str) -> CallToolResult:
        body = {name: value for name, value in arguments.items() if value is not None}
        if "model" not in body and self.settings.default_model:
            body["model"] = self.settings.default_model
        if "effort" not in body and self.settings.default_effort:
            body["effort"] = self.settings.default_effort

        canonical = canonical_arguments(body, await self.models())
        key = self.keys.key_for(caller_id(token), spec.name, canonical)
        waits = bool(self.bundle["agents"][spec.agent]["waits"])
        resp = await self.client.start_run(spec.agent, body, token=token, idempotency_key=key, wait=waits)
        return run_result(
            resp.envelope, base_url=self.settings.base_url, inputs=canonical, replayed=resp.replayed, waited=waits
        )

    async def _get_run(self, run_id: str, token: str) -> CallToolResult:
        try:
            uuid.UUID(run_id)
        except ValueError:
            return error_result("run_id must be the run_id a Milton tool returned (a UUID).")
        envelope = await self.client.get_run(run_id, token=token)
        return run_result(envelope, base_url=self.settings.base_url)

    def _token(self, ctx: ServerRequestContext[Any]) -> str | None:
        if not self.http_mode:
            return self.settings.api_key
        request = ctx.request
        header = request.headers.get("authorization", "") if request is not None else ""
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer":
            return None
        return token.strip() or None


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
