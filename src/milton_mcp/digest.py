"""Turn a run envelope into the tool result: a short text digest plus the envelope itself."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from mcp_types import CallToolResult, TextContent

from milton_mcp.client import WAIT_SECONDS

DISCLOSURE = (
    "AI-generated general information, not personalized investment advice; "
    "the full disclosures are in the structured result."
)

AGENT_TITLES = {
    "technical": "Technical analysis",
    "fundamental": "Fundamental analysis",
    "macro": "Macro analysis",
    "quant": "Trade design",
    "desk": "Desk",
}

FAILURE_REASONS = {
    "failed:timeout": "it ran past its time limit",
    "failed:expired": "it didn't finish in time",
    "failed:worker_lost": "the worker running it stopped",
    "failed:invalid_input": "Milton couldn't use the inputs",
    "failed:canary_hit": "a safety check withheld its output",
    "failed:agent_error": "the analyst hit an error",
    "failed:invalid_envelope": "the analyst's output couldn't be read",
}


def run_result(
    envelope: dict[str, Any],
    *,
    base_url: str,
    inputs: Mapping[str, Any] | None = None,
    replayed: bool = False,
    waited: bool = True,
) -> CallToolResult:
    run = envelope.get("run") or {}
    status = run.get("status", "")
    lines = [_heading(envelope, inputs)]

    if status == "completed":
        lines += _completed(envelope)
    elif status == "failed":
        detail = str(envelope.get("status_detail") or "")
        reason = FAILURE_REASONS.get(detail, detail or "no reason was recorded")
        lines.append(f"The run failed: {reason}. Failed runs aren't billed.")
    else:
        run_id = run.get("id", "")
        poll = (
            f'Call milton_get_run with run_id "{run_id}" for the result; each call waits up to {WAIT_SECONDS} seconds.'
        )
        desk = envelope.get("agent") == "desk"
        if waited:
            lines.append(f"Not finished after {WAIT_SECONDS} seconds ({status or 'working'}). {poll}")
            if desk:
                lines.append("A desk run usually takes several minutes.")
        else:
            lines.append(f"Started. {'A desk run usually takes several minutes. ' if desk else ''}{poll}")

    if replayed:
        lines.append(
            f"This is the run your identical request started at {_clock(run.get('created_at'))}; it isn't billed again."
        )
    lines += _links(envelope, base_url)
    lines.append(DISCLOSURE)

    return CallToolResult(
        content=[TextContent(type="text", text="\n".join(lines))],
        structured_content=envelope,
        is_error=status == "failed",
    )


def _heading(envelope: dict[str, Any], inputs: Mapping[str, Any] | None) -> str:
    agent = str(envelope.get("agent", ""))
    parts = [AGENT_TITLES.get(agent, agent or "Milton run")]
    for name in ("ticker", "horizon"):
        if inputs and inputs.get(name):
            parts.append(str(inputs[name]))
    return " · ".join(parts)


def _completed(envelope: dict[str, Any]) -> list[str]:
    run = envelope.get("run") or {}
    out: list[str] = []
    view = " · ".join(
        f"{label}: {envelope[key]}"
        for key, label in (("stance", "Stance"), ("conviction", "Conviction"))
        if envelope.get(key)
    )
    if view:
        out.append(view)
    if envelope.get("summary"):
        out += ["", str(envelope["summary"]), ""]

    levels = envelope.get("key_levels") or []
    if levels:
        out.append("Key levels:")
        for level in levels:
            timeframe = f" ({level['timeframe']})" if level.get("timeframe") else ""
            out.append(f"- {level.get('type', '')} {_price(level.get('price'))}: {level.get('label', '')}{timeframe}")
    risks = envelope.get("risks") or []
    if risks:
        out.append("Risks:")
        out += [f"- {risk}" for risk in risks]
    missing = (envelope.get("details") or {}).get("missing") or []
    if envelope.get("agent") == "desk" and missing:
        out.append("Reads that failed: " + ", ".join(missing) + ".")
    if envelope.get("data_as_of"):
        out.append(f"Data as of {envelope['data_as_of']}.")

    cost = f"${run.get('cost_cents', 0) / 100:.2f}"
    if run.get("cache_hit"):
        cost += " (served from a cached read)"
    out.append(f"Ran on {run.get('model', '')} at {run.get('effort', '')} effort; cost {cost}.")
    return out


def _links(envelope: dict[str, Any], base_url: str) -> list[str]:
    run_id = (envelope.get("run") or {}).get("id", "")
    out = [f"View in Milton: {base_url}/runs/{run_id}", f"API: {base_url}/api/v1/runs/{run_id}"]
    if envelope.get("report_url"):
        out.append(f"Full report (API): {base_url}{envelope['report_url']}")
    return out


def _price(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return str(value)
    return f"{value:,.2f}" if abs(value) >= 1 else f"{value:.4f}"


def _clock(created_at: Any) -> str:
    try:
        when = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return "earlier"
    return when.astimezone(timezone.utc).strftime("%H:%M UTC")
