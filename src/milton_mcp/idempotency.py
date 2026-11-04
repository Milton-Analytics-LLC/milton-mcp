"""Idempotency keys for run-starting tool calls.

MCP clients send no Idempotency-Key and re-send a call when a stream breaks, so the server derives
one: "mcp:" + sha256 of the tool, its canonical arguments and a 10-minute window. Milton maps the
key to a run per user (the run id is derived from the user and the key), so an identical call
within the window returns the same run and is billed once.

A call whose window has just rolled over would hash to a new key, so the keys handed out in the
last 10 minutes are remembered and reused for the same caller and arguments.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

WINDOW_SECONDS = 600


def resolve_effort(model: str, effort: str | None, efforts: Mapping[str, Sequence[str]]) -> str:
    """The effort Milton will run at: the one given, else high, else the model's highest level."""
    if effort:
        return effort
    levels = list(efforts.get(model, ()))
    if not levels:
        return ""
    return "high" if "high" in levels else levels[-1]


def canonical_arguments(arguments: Mapping[str, Any], efforts: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, value in arguments.items():
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if name == "ticker":
                value = value.upper()
            elif name == "horizon":
                value = value.lower()
        out[name] = value
    model = str(out.get("model", ""))
    out["effort"] = resolve_effort(model, out.get("effort") or None, efforts)
    return out


class IdempotencyKeys:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._recent: dict[str, tuple[str, float]] = {}

    def key_for(self, caller: str, tool: str, arguments: Mapping[str, Any]) -> str:
        """The key for this call. caller identifies the credential (a hash, never the token)."""
        now = self._clock()
        canonical = json.dumps({"tool": tool, "arguments": arguments}, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(f"{caller}|{canonical}".encode()).hexdigest()

        self._recent = {fp: entry for fp, entry in self._recent.items() if now - entry[1] < WINDOW_SECONDS}
        if fingerprint in self._recent:
            return self._recent[fingerprint][0]

        window = int(now // WINDOW_SECONDS)
        key = "mcp:" + hashlib.sha256(f"{canonical}|{window}".encode()).hexdigest()
        self._recent[fingerprint] = (key, now)
        return key


def caller_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]
