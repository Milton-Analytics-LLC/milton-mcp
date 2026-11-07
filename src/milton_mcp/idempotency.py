"""Idempotency keys for run-starting tool calls.

MCP clients send no Idempotency-Key and re-send a call when a stream breaks, so the server derives
one: "mcp:" + sha256 of the tool, its canonical arguments and a 10-minute window. Milton maps the
key to a run per user (the run id is derived from the user and the key), so a repeat under the same
key returns the same run and is billed once.

A failed run isn't billed and is no use to a caller asking again, so when an identical call gets
a failed run back, the server starts a new one under retry_key(failed run).

A re-send just after the window rolls over hashes to a new key, so each call also sends the previous
window's key as Idempotency-Previous-Key, and Milton returns a run started under it for the same
request. Nothing is remembered here, so this holds across restarts and replicas: an identical call
within 10 minutes returns the same run, and one within 20 minutes may.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True)
class RunKeys:
    current: str
    previous: str


class IdempotencyKeys:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock

    def keys_for(self, tool: str, arguments: Mapping[str, Any]) -> RunKeys:
        """This window's key for the call, and the previous window's."""
        canonical = json.dumps({"tool": tool, "arguments": arguments}, sort_keys=True, separators=(",", ":"))
        window = int(self._clock() // WINDOW_SECONDS)
        return RunKeys(current=_key(canonical, window), previous=_key(canonical, window - 1))


def _key(canonical: str, window: int) -> str:
    return "mcp:" + hashlib.sha256(f"{canonical}|{window}".encode()).hexdigest()


def retry_key(failed_run_id: str) -> str:
    """The key for a fresh attempt after a failed run. It depends only on that run, so a re-sent
    retry finds the same new run instead of starting another."""
    return "mcp:retry:" + hashlib.sha256(failed_run_id.encode()).hexdigest()
