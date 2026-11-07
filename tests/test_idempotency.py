from __future__ import annotations

from milton_mcp.idempotency import WINDOW_SECONDS, IdempotencyKeys, canonical_arguments, resolve_effort
from tests.fakes import MODELS

ARGS = {"ticker": "NVDA", "horizon": "swing", "model": "claude-opus-5-5", "effort": "high"}


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def keys_at(now: float, tool: str = "t", arguments=ARGS):
    return IdempotencyKeys(Clock(now)).keys_for(tool, arguments)


def test_keys_are_mcp_prefixed_sha256():
    keys = keys_at(0, "milton_technical_analysis")
    for key in (keys.current, keys.previous):
        assert key.startswith("mcp:")
        assert len(key) == 4 + 64
    assert keys.current != keys.previous


def test_any_process_derives_the_same_keys_within_a_window():
    assert keys_at(10) == keys_at(WINDOW_SECONDS - 1)
    assert keys_at(10) == keys_at(10, arguments=dict(ARGS))


def test_the_previous_key_is_the_last_windows_key():
    assert keys_at(WINDOW_SECONDS + 1).previous == keys_at(WINDOW_SECONDS - 1).current


def test_two_windows_later_neither_key_matches():
    first = keys_at(WINDOW_SECONDS - 1).current
    later = keys_at(2 * WINDOW_SECONDS + 1)
    assert first not in (later.current, later.previous)


def test_tool_and_arguments_change_the_keys():
    base = keys_at(0)
    assert keys_at(0, "other") != base
    assert keys_at(0, arguments=dict(ARGS, horizon="position")) != base


def test_canonical_arguments_normalize_like_milton():
    canonical = canonical_arguments({"ticker": " nvda ", "horizon": "Swing", "model": "claude-opus-5-5"}, MODELS)
    assert canonical == {"ticker": "NVDA", "horizon": "swing", "model": "claude-opus-5-5", "effort": "high"}
    assert canonical_arguments({"model": "gpt-6.1-sol", "effort": None, "ticker": None}, MODELS) == {
        "model": "gpt-6.1-sol",
        "effort": "high",
    }


def test_resolve_effort():
    assert resolve_effort("claude-haiku-4-5", None, MODELS) == "medium"
    assert resolve_effort("claude-opus-5-5", None, MODELS) == "high"
    assert resolve_effort("claude-opus-5-5", "max", MODELS) == "max"
    assert resolve_effort("unknown-model", None, MODELS) == ""
