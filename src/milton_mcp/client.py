"""A small async client for the slice of Milton's REST API the tools use."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx2

from milton_mcp import __version__

# How long a call waits on Milton for a run to finish before returning a run handle. Under the
# 60-second default request timeout of common MCP clients, which JSON responses can't extend.
WAIT_SECONDS = 50
_HTTP_TIMEOUT = httpx2.Timeout(WAIT_SECONDS + 20, connect=10)


class ApiError(Exception):
    """A non-2xx response from Milton, with its coded body when it has one."""

    def __init__(self, status: int, body: dict[str, Any], retry_after: int | None = None) -> None:
        self.status = status
        self.body = body
        self.code = str(body.get("code") or "")
        self.message = str(body.get("error") or "")
        self.retry_after = retry_after
        super().__init__(f"{status} {self.code or self.message}")


@dataclass(frozen=True)
class RunResponse:
    envelope: dict[str, Any]
    replayed: bool = False


class MiltonClient:
    def __init__(self, base_url: str, *, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self._http = httpx2.AsyncClient(
            base_url=base_url,
            timeout=_HTTP_TIMEOUT,
            transport=transport,
            headers={"User-Agent": f"milton-mcp/{__version__}"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def start_run(
        self, agent: str, body: dict[str, Any], *, token: str, idempotency_key: str, wait: bool
    ) -> RunResponse:
        params = {"wait": str(WAIT_SECONDS)} if wait else None
        resp = await self._http.post(
            f"/api/v1/agents/{agent}/runs",
            json=body,
            params=params,
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": idempotency_key},
        )
        envelope = _json_or_raise(resp)
        return RunResponse(envelope, replayed=resp.headers.get("Idempotent-Replayed") == "true")

    async def get_run(self, run_id: str, *, token: str) -> dict[str, Any]:
        resp = await self._http.get(
            f"/api/v1/runs/{run_id}",
            params={"wait": str(WAIT_SECONDS)},
            headers={"Authorization": f"Bearer {token}"},
        )
        return _json_or_raise(resp)

    async def pricing(self) -> dict[str, Any]:
        resp = await self._http.get("/api/v1/pricing", timeout=10)
        return _json_or_raise(resp)


def _json_or_raise(resp: httpx2.Response) -> dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    if resp.status_code >= 400:
        raise ApiError(resp.status_code, body, _retry_after(resp))
    return body


def _retry_after(resp: httpx2.Response) -> int | None:
    try:
        return int(resp.headers.get("Retry-After", ""))
    except ValueError:
        return None
