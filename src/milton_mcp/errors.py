"""Milton API errors as tool results: an isError result with a sentence the model can act on."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mcp_types import CallToolResult, TextContent

from milton_mcp.client import ApiError


def error_result(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)


def api_error_result(err: ApiError, *, base_url: str, http_mode: bool, run_id: str | None = None) -> CallToolResult:
    return error_result(api_error_sentence(err, base_url=base_url, http_mode=http_mode, run_id=run_id))


def api_error_sentence(err: ApiError, *, base_url: str, http_mode: bool, run_id: str | None = None) -> str:
    body: dict[str, Any] = err.body
    code = err.code
    retry = err.retry_after

    if err.status == 401:
        where = "the Authorization bearer token" if http_mode else "MILTON_API_KEY"
        return (
            f"Milton rejected the API key (missing, expired or revoked). Create one at "
            f"{base_url}/settings/api-tokens and set it as {where}."
        )
    if code == "insufficient_balance":
        return f"Your Milton balance is used up, so no run can start. Add credits at {base_url}/billing/balance."
    if code == "monthly_limit_reached":
        cap = body.get("cap_cents")
        limit = f" (${cap / 100:.0f} of model cost)" if isinstance(cap, (int, float)) else ""
        return f"You've reached this month's agent-run limit{limit}. It resets on {_date(body.get('resets_at'))}."
    if code == "too_many_runs_in_flight":
        most = body.get("max_runs_in_flight", "the maximum number of")
        wait = f"about {retry} seconds" if retry else "a moment"
        return (
            f"You already have {most} runs in progress. Try again in {wait}, "
            "or wait for one to finish with milton_get_run."
        )
    if err.status == 429:
        return f"Too many requests to Milton. Try again in {retry or 1} second{'s' if (retry or 1) != 1 else ''}."
    if code == "invalid_model":
        return "Milton doesn't offer that model. Use one of: " + ", ".join(body.get("valid_models") or []) + "."
    if code == "invalid_effort":
        levels = ", ".join(body.get("valid_efforts") or [])
        return f"{body.get('model', 'That model')} doesn't offer that effort; its levels are: {levels}."
    if code == "invalid_ticker":
        candidates = body.get("candidates") or []
        hint = f" Did you mean: {', '.join(candidates)}?" if candidates else " Check the symbol."
        return f"Milton doesn't recognize that ticker (US stocks and ETFs only).{hint}"
    if code == "invalid_horizon":
        return "horizon must be one of: " + ", ".join(body.get("valid_horizons") or []) + "."
    if code == "missing_field":
        return f"Missing required input: {body.get('field', '')}."
    if code == "unknown_field":
        return f"Unknown input: {body.get('field', '')}."
    if code == "idempotency_key_reused":
        return "Milton matched this call to an earlier one with different inputs. Try again in a few minutes."
    if code == "enqueue_failed":
        return "Milton couldn't queue the run. Repeat the same call; it won't start a second run."
    if err.status == 404:
        if run_id:
            return f"There's no run with id {run_id} in your Milton account."
        return "Milton doesn't have this endpoint. The server may need a newer milton-mcp."
    if err.status >= 500:
        return (
            f"Milton had a server error ({err.status}). Try again shortly; "
            "repeating the same call won't start a second run."
        )
    detail = err.message or code or "no detail"
    return f"Milton rejected the request ({err.status}): {detail}."


def _date(value: Any) -> str:
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return "the first of next month"
    return f"{when:%B} {when.day}, {when.year}"
