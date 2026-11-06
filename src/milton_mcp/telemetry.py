"""OpenTelemetry metrics for the tool calls. A no-op unless an OpenTelemetry SDK is configured
(the hosted image runs under opentelemetry-instrument; a local install records nothing)."""

from __future__ import annotations

from opentelemetry import metrics
from opentelemetry.metrics import MeterProvider

from milton_mcp.tools import AGENT_TOOLS_BY_NAME, GET_RUN

# Labels are a closed set, so a client-controlled tool name can't grow the metric's cardinality.
KNOWN_TOOLS = frozenset({*AGENT_TOOLS_BY_NAME, GET_RUN})
OUTCOMES = frozenset(
    {
        "ok",
        "pending",
        "run_failed",
        "invalid_input",
        "auth",
        "payment",
        "rate_limited",
        "not_found",
        "upstream_error",
        "unreachable",
    }
)
NO_TOOL = "none"
OTHER = "other"


class CallMetrics:
    def __init__(self, meter_provider: MeterProvider | None = None) -> None:
        meter = (meter_provider or metrics.get_meter_provider()).get_meter("milton-mcp")
        self._calls = meter.create_counter(
            "milton.mcp.calls", unit="{call}", description="MCP requests, by method, tool and outcome."
        )

    def record(self, method: str, tool: str, outcome: str) -> None:
        if tool != NO_TOOL and tool not in KNOWN_TOOLS:
            tool = OTHER
        if outcome not in OUTCOMES:
            outcome = "upstream_error"
        self._calls.add(1, {"method": method, "tool": tool, "outcome": outcome})


def outcome_for_status(status: int) -> str:
    """The outcome label for an error response from Milton's api."""
    if status == 401:
        return "auth"
    if status == 402:
        return "payment"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if status in (400, 409, 422):
        return "invalid_input"
    return "upstream_error"
