"""milton-mcp: run the Milton MCP server over stdio (default) or Streamable HTTP."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

import anyio

from milton_mcp import __version__
from milton_mcp.client import MiltonClient
from milton_mcp.config import Settings, settings_from_env
from milton_mcp.server import MiltonTools, build_server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="milton-mcp",
        description="MCP server for Milton's analyst agents. stdio by default; --http serves Streamable HTTP.",
    )
    parser.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (default 8000)")
    parser.add_argument("--path", default="/mcp", help="HTTP endpoint path (default /mcp)")
    parser.add_argument("--version", action="version", version=f"milton-mcp {__version__}")
    args = parser.parse_args(argv)

    # stdout carries the protocol in stdio mode, so logs go to stderr.
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    settings = settings_from_env()

    if args.http:
        serve_http(settings, host=args.host, port=args.port, path=args.path)
        return
    if not settings.api_key:
        sys.exit(
            "milton-mcp: set MILTON_API_KEY to a Milton API token (mlt_…); create one at "
            f"{settings.base_url}/settings/api-tokens"
        )
    anyio.run(serve_stdio, settings)


async def serve_stdio(settings: Settings) -> None:
    from mcp.server.stdio import stdio_server

    client = MiltonClient(settings.base_url)
    try:
        server = build_server(MiltonTools(settings, client, http_mode=False))
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await client.aclose()


def http_app(settings: Settings, *, host: str = "127.0.0.1", path: str = "/mcp", client: MiltonClient | None = None):
    """The Streamable HTTP app: stateless, JSON responses, a bearer token required on every request."""
    client = client or MiltonClient(settings.base_url)
    server = build_server(MiltonTools(settings, client, http_mode=True))
    app = server.streamable_http_app(streamable_http_path=path, json_response=True, stateless_http=True, host=host)
    return RequireBearer(app, path)


def serve_http(settings: Settings, *, host: str, port: int, path: str) -> None:
    import uvicorn

    uvicorn.run(http_app(settings, host=host, path=path), host=host, port=port)


class RequireBearer:
    """Answers a request to the MCP endpoint without a bearer token with 401, before MCP sees it.
    The server holds no key; the token is passed on to Milton, which checks it."""

    def __init__(self, app: Any, path: str) -> None:
        self.app = app
        self.path = path.rstrip("/") or "/"

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["path"].rstrip("/") == self.path.rstrip("/") and not _has_bearer(scope):
            body = json.dumps({"error": "a Milton API token is required as the Authorization bearer"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b"Bearer"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def _has_bearer(scope: dict[str, Any]) -> bool:
    for name, value in scope.get("headers", []):
        if name.lower() == b"authorization":
            scheme, _, token = value.decode("latin-1").partition(" ")
            return scheme.lower() == "bearer" and bool(token.strip())
    return False


if __name__ == "__main__":
    main()
