from __future__ import annotations

from milton_mcp.idempotency import WINDOW_SECONDS, IdempotencyKeys, canonical_arguments, resolve_effort
from tests.fakes import MODELS

ARGS = {"ticker": "NVDA", "horizon": "swing", "model": "claude-opus-5-5", "effort": "high"}


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_key_is_mcp_prefixed_sha256():
    key = IdempotencyKeys(Clock(0)).key_for("caller", "milton_technical_analysis", ARGS)
    assert key.startswith("mcp:")
    assert len(key) == 4 + 64


def test_same_call_in_the_window_gets_the_same_key():
    keys = IdempotencyKeys(Clock(100))
    assert keys.key_for("c", "t", ARGS) == keys.key_for("c", "t", dict(ARGS))


def test_a_call_resent_across_the_window_boundary_keeps_its_key():
    clock = Clock(WINDOW_SECONDS - 5)
    keys = IdempotencyKeys(clock)
    first = keys.key_for("c", "t", ARGS)
    clock.now = WINDOW_SECONDS + 5
    assert keys.key_for("c", "t", ARGS) == first


def test_a_fresh_process_hashes_the_same_key_within_a_window():
    assert IdempotencyKeys(Clock(10)).key_for("c", "t", ARGS) == IdempotencyKeys(Clock(500)).key_for("c", "t", ARGS)


def test_after_the_window_a_call_gets_a_new_key():
    clock = Clock(0)
    keys = IdempotencyKeys(clock)
    first = keys.key_for("c", "t", ARGS)
    clock.now = WINDOW_SECONDS + 1
    assert keys.key_for("c", "t", ARGS) != first


def test_remembered_keys_are_per_caller():
    clock = Clock(WINDOW_SECONDS - 5)
    keys = IdempotencyKeys(clock)
    a_first = keys.key_for("a", "t", ARGS)
    clock.now = WINDOW_SECONDS + 5
    assert keys.key_for("b", "t", ARGS) != a_first
    assert keys.key_for("a", "t", ARGS) == a_first


def test_tool_and_arguments_change_the_key():
    keys = IdempotencyKeys(Clock(0))
    base = keys.key_for("c", "t", ARGS)
    assert keys.key_for("c", "other", ARGS) != base
    assert keys.key_for("c", "t", dict(ARGS, horizon="position")) != base


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
