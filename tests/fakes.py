"""A fake of the slice of Milton's REST API the server calls."""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any

import httpx2

BASE_URL = "https://milton.test"
API_KEY = "mlt_" + "a" * 52
OTHER_KEY = "mlt_" + "b" * 52
RUN_NAMESPACE = uuid.UUID("a7c9e4d2-1f3b-4e8a-9c6d-2b5f8e1a0d47")

MODELS = {
    "claude-haiku-4-5": ["low", "medium"],
    "claude-opus-5-5": ["low", "medium", "high", "xhigh", "max"],
    "gpt-6.1-sol": ["low", "medium", "high", "xhigh"],
}

DISCLOSURES = "Milton is not a registered investment adviser."


def completed_envelope(run_id: str, agent: str = "technical", **overrides: Any) -> dict[str, Any]:
    env: dict[str, Any] = {
        "schema_version": "2",
        "agent": agent,
        "run": {
            "id": run_id,
            "status": "completed",
            "model": "claude-opus-5-5",
            "effort": "high",
            "created_at": "2026-11-04T14:02:00Z",
            "completed_at": "2026-11-04T14:03:01Z",
            "duration_ms": 61000,
            "cost_cents": 36,
            "usage": {"claude-opus-5-5": {"input_tokens": 40000, "output_tokens": 3000}},
        },
        "summary": "NVDA holds its uptrend above the 50-day average.",
        "stance": "bullish",
        "conviction": "moderate",
        "data_as_of": "2026-11-04T14:00:00Z",
        "key_levels": [
            {"price": 182.5, "type": "support", "label": "50-day average", "timeframe": "daily"},
            {"price": 205.0, "type": "resistance", "label": "prior high", "timeframe": None},
        ],
        "risks": ["Earnings on November 19."],
        "details": {"bias": "bullish"},
        "disclosures": DISCLOSURES,
    }
    env.update(overrides)
    return env


def working_envelope(run_id: str, agent: str = "technical", status: str = "working") -> dict[str, Any]:
    return {
        "schema_version": "2",
        "agent": agent,
        "run": {
            "id": run_id,
            "status": status,
            "model": "claude-opus-5-5",
            "effort": "high",
            "created_at": "2026-11-04T14:02:00Z",
            "cost_cents": 0,
        },
        "disclosures": DISCLOSURES,
    }


class FakeMilton:
    """Keys runs by (token, Idempotency-Key) the way Milton does, so replays return the same run."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.runs: dict[str, dict[str, Any]] = {}
        self.owners: dict[str, str] = {}
        self.created = 0
        self.new_run_status = "completed"
        self.error: tuple[int, dict[str, Any], dict[str, str]] | None = None
        self.pricing_status = 200

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/v1/pricing":
            if self.pricing_status != 200:
                return httpx2.Response(self.pricing_status, json={"error": "unavailable"})
            return httpx2.Response(200, json={"rates": [], "efforts": MODELS})

        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token not in (API_KEY, OTHER_KEY):
            return httpx2.Response(401, json={"error": "invalid or missing authentication token"})
        if self.error is not None:
            status, body, headers = self.error
            return httpx2.Response(status, json=body, headers=headers)

        if request.method == "POST" and path.startswith("/api/v1/agents/") and path.endswith("/runs"):
            agent = path.split("/")[4]
            key = request.headers["idempotency-key"]
            run_id = str(uuid.uuid5(RUN_NAMESPACE, f"{token}|{key}"))
            if run_id in self.runs:
                return httpx2.Response(200, json=self.runs[run_id], headers={"Idempotent-Replayed": "true"})
            self.created += 1
            if self.new_run_status == "completed":
                env = completed_envelope(run_id, agent)
            else:
                env = working_envelope(run_id, agent, self.new_run_status)
            self.runs[run_id] = env
            self.owners[run_id] = token
            return httpx2.Response(200 if self.new_run_status == "completed" else 202, json=env)

        if request.method == "GET" and path.startswith("/api/v1/runs/"):
            run_id = path.rsplit("/", 1)[-1]
            if self.owners.get(run_id) != token:
                return httpx2.Response(404, json={"error": "the requested resource could not be found"})
            return httpx2.Response(200, json=self.runs[run_id])

        return httpx2.Response(404, json={"error": "the requested resource could not be found"})

    def add_run(self, envelope: dict[str, Any], token: str = API_KEY) -> None:
        run_id = envelope["run"]["id"]
        self.runs[run_id] = copy.deepcopy(envelope)
        self.owners[run_id] = token

    def run_posts(self) -> list[httpx2.Request]:
        return [r for r in self.requests if r.method == "POST"]

    @staticmethod
    def body(request: httpx2.Request) -> dict[str, Any]:
        return json.loads(request.content)
