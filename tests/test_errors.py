from __future__ import annotations

import pytest
from mcp import Client

from milton_mcp.client import ApiError
from milton_mcp.errors import api_error_sentence
from tests.fakes import BASE_URL, FakeMilton

CASES = [
    (401, {}, None, "Create one at https://milton.test/settings/api-tokens and set it as MILTON_API_KEY"),
    (402, {"code": "insufficient_balance"}, None, "Add credits at https://milton.test/billing/balance"),
    (
        402,
        {"code": "monthly_limit_reached", "cap_cents": 3000, "resets_at": "2026-12-01T00:00:00Z"},
        None,
        "agent-run limit ($30 of model cost). It resets on December 1, 2026.",
    ),
    (
        429,
        {"code": "too_many_runs_in_flight", "max_runs_in_flight": 5},
        30,
        "You already have 5 runs in progress. Try again in about 30 seconds",
    ),
    (429, {"error": "rate limit exceeded"}, 1, "Try again in 1 second."),
    (
        422,
        {"code": "invalid_model", "valid_models": ["claude-opus-5-5", "gpt-6.1-sol"]},
        None,
        "Use one of: claude-opus-5-5, gpt-6.1-sol.",
    ),
    (
        422,
        {"code": "invalid_effort", "model": "claude-haiku-4-5", "valid_efforts": ["low", "medium"]},
        None,
        "claude-haiku-4-5 doesn't offer that effort; its levels are: low, medium.",
    ),
    (422, {"code": "invalid_ticker", "candidates": ["NVDA", "NVDL"]}, None, "Did you mean: NVDA, NVDL?"),
    (422, {"code": "invalid_ticker", "candidates": []}, None, "Check the symbol."),
    (
        422,
        {"code": "invalid_horizon", "valid_horizons": ["intraday", "swing"]},
        None,
        "horizon must be one of: intraday, swing.",
    ),
    (422, {"code": "missing_field", "field": "ticker"}, None, "Missing required input: ticker."),
    (422, {"code": "unknown_field", "field": "portfolio_id"}, None, "Unknown input: portfolio_id."),
    (422, {"code": "idempotency_key_reused"}, None, "Try again in a few minutes."),
    (503, {"code": "enqueue_failed"}, None, "Repeat the same call; it won't start a second run."),
    (500, {"error": "boom"}, None, "server error (500)"),
    (422, {"code": "invalid_field", "error": "cash must be a number"}, None, "(422): cash must be a number."),
]


@pytest.mark.parametrize(("status", "body", "retry_after", "expected"), CASES)
def test_sentences(status, body, retry_after, expected):
    sentence = api_error_sentence(ApiError(status, body, retry_after), base_url=BASE_URL, http_mode=False)
    assert expected in sentence


def test_401_in_http_mode_names_the_bearer_token():
    sentence = api_error_sentence(ApiError(401, {}), base_url=BASE_URL, http_mode=True)
    assert "Authorization bearer token" in sentence


def test_404_names_the_run():
    sentence = api_error_sentence(ApiError(404, {}), base_url=BASE_URL, http_mode=False, run_id="abc")
    assert sentence == "There's no run with id abc in your Milton account."


@pytest.mark.anyio
async def test_api_error_becomes_an_is_error_result(make_server, fake: FakeMilton):
    fake.error = (429, {"code": "too_many_runs_in_flight", "max_runs_in_flight": 5}, {"Retry-After": "30"})
    async with Client(make_server(), cache=None) as client:
        result = await client.call_tool(
            "milton_technical_analysis", {"ticker": "NVDA", "horizon": "swing", "model": "x"}
        )
    assert result.is_error is True
    assert "Try again in about 30 seconds" in result.content[0].text


@pytest.mark.anyio
async def test_unreachable_milton(make_server, fake: FakeMilton):
    def refuse(request):
        import httpx2

        raise httpx2.ConnectError("refused", request=request)

    fake.handle = refuse
    async with Client(make_server(), cache=None) as client:
        result = await client.call_tool("milton_macro_analysis", {"model": "x"})
    assert result.is_error is True
    assert "Couldn't reach Milton at https://milton.test (ConnectError)" in result.content[0].text
