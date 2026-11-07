from __future__ import annotations

import jsonschema
import pytest
from mcp import Client

from milton_mcp.config import Settings
from milton_mcp.idempotency import WINDOW_SECONDS, IdempotencyKeys
from milton_mcp.tools import load_bundle
from tests.fakes import API_KEY, BASE_URL, FakeMilton, completed_envelope, working_envelope

pytestmark = pytest.mark.anyio

RUN_ID = "0b6d1c58-2f0e-5d0a-9e51-6f4a7b3c2d10"
TECHNICAL = {"ticker": "nvda", "horizon": "swing", "model": "claude-opus-5-5"}


async def call(server, name, arguments):
    async with Client(server, cache=None) as client:
        return await client.call_tool(name, arguments)


def text(result) -> str:
    return result.content[0].text


async def test_technical_completes_inline(make_server, fake: FakeMilton):
    result = await call(make_server(), "milton_technical_analysis", TECHNICAL)

    assert result.is_error is False
    body = text(result)
    assert body.startswith("Technical analysis · NVDA · swing")
    assert "Stance: bullish · Conviction: moderate" in body
    assert "NVDA holds its uptrend" in body
    assert "- support 182.50: 50-day average (daily)" in body
    assert "- resistance 205.00: prior high" in body
    assert "- Earnings on November 19." in body
    assert "cost $0.36" in body
    run_id = result.structured_content["run"]["id"]
    assert f"View in Milton: {BASE_URL}/runs/{run_id}" in body
    assert f"API: {BASE_URL}/api/v1/runs/{run_id}" in body
    assert "not personalized investment advice" in body
    jsonschema.validate(result.structured_content, load_bundle()["envelope_schema"])


async def test_start_request_waits_and_carries_key(make_server, fake: FakeMilton):
    await call(make_server(), "milton_technical_analysis", TECHNICAL)

    (post,) = fake.run_posts()
    assert post.url.path == "/api/v1/agents/technical/runs"
    assert post.url.params["wait"] == "50"
    assert post.headers["authorization"] == f"Bearer {API_KEY}"
    assert post.headers["idempotency-key"].startswith("mcp:")
    assert post.headers["user-agent"].startswith("milton-mcp/")
    assert fake.body(post) == TECHNICAL


async def test_desk_returns_a_handle_without_waiting(make_server, fake: FakeMilton):
    fake.new_run_status = "submitted"
    result = await call(make_server(), "milton_desk", TECHNICAL)

    (post,) = fake.run_posts()
    assert post.url.path == "/api/v1/agents/desk/runs"
    assert "wait" not in post.url.params
    assert result.is_error is False
    run_id = result.structured_content["run"]["id"]
    assert f'milton_get_run with run_id "{run_id}"' in text(result)
    assert "Started. A desk run usually takes several minutes" in text(result)
    assert "after 50 seconds" not in text(result)
    jsonschema.validate(result.structured_content, load_bundle()["envelope_schema"])


async def test_slow_run_returns_a_handle(make_server, fake: FakeMilton):
    fake.new_run_status = "working"
    result = await call(make_server(), "milton_technical_analysis", TECHNICAL)
    assert result.is_error is False
    assert "Not finished after 50 seconds (working)" in text(result)
    assert "several minutes" not in text(result)


async def test_get_run_returns_the_result_and_report_link(make_server, fake: FakeMilton):
    fake.add_run(
        completed_envelope(RUN_ID, "desk", report_url=f"/api/v1/runs/{RUN_ID}/report", details={"missing": ["macro"]})
    )
    result = await call(make_server(), "milton_get_run", {"run_id": RUN_ID})

    (get,) = [r for r in fake.requests if r.url.path.startswith("/api/v1/runs/")]
    assert get.url.params["wait"] == "50"
    assert result.is_error is False
    assert text(result).startswith("Desk")
    assert "Reads that failed: macro." in text(result)
    assert f"Full report (API): {BASE_URL}/api/v1/runs/{RUN_ID}/report" in text(result)


async def test_get_run_of_an_unfinished_desk_run(make_server, fake: FakeMilton):
    fake.add_run(working_envelope(RUN_ID, "desk"))
    result = await call(make_server(), "milton_get_run", {"run_id": RUN_ID})
    assert "Not finished after 50 seconds (working)" in text(result)
    assert "A desk run usually takes several minutes." in text(result)


async def test_get_run_of_someone_elses_or_unknown_run(make_server, fake: FakeMilton):
    result = await call(make_server(), "milton_get_run", {"run_id": RUN_ID})
    assert result.is_error is True
    assert f"There's no run with id {RUN_ID}" in text(result)


async def test_get_run_rejects_a_malformed_id_without_calling_milton(make_server, fake: FakeMilton):
    result = await call(make_server(), "milton_get_run", {"run_id": "../agents"})
    assert result.is_error is True
    assert "run_id must be" in text(result)
    assert not [r for r in fake.requests if r.url.path.startswith("/api/v1/runs")]


async def test_prices_print_to_cents_and_small_prices_keep_precision(make_server, fake: FakeMilton):
    env = completed_envelope(
        RUN_ID,
        key_levels=[
            {"price": 297.5761, "type": "support", "label": "200-day average"},
            {"price": 0.12345, "type": "support", "label": "penny"},
        ],
    )
    fake.add_run(env)
    body = text(await call(make_server(), "milton_get_run", {"run_id": RUN_ID}))
    assert "- support 297.58: 200-day average" in body
    assert "- support 0.1235: penny" in body


async def test_failed_run_is_an_error_with_the_reason(make_server, fake: FakeMilton):
    env = working_envelope(RUN_ID, status="failed")
    env["status_detail"] = "failed:timeout"
    fake.add_run(env)
    result = await call(make_server(), "milton_get_run", {"run_id": RUN_ID})
    assert result.is_error is True
    assert "it ran past its time limit" in text(result)
    assert "aren't billed" in text(result)
    assert result.structured_content["run"]["status"] == "failed"


async def test_identical_call_returns_the_same_run_billed_once(make_server, fake: FakeMilton):
    server = make_server()
    first = await call(server, "milton_technical_analysis", TECHNICAL)
    again = await call(server, "milton_technical_analysis", dict(TECHNICAL, ticker=" NVDA ", effort="high"))

    assert fake.created == 1
    keys = {r.headers["idempotency-key"] for r in fake.run_posts()}
    assert len(keys) == 1
    assert again.structured_content["run"]["id"] == first.structured_content["run"]["id"]
    assert "isn't billed again" in text(again)
    assert "isn't billed again" not in text(first)


async def test_different_inputs_start_a_new_run(make_server, fake: FakeMilton):
    server = make_server()
    await call(server, "milton_technical_analysis", TECHNICAL)
    await call(server, "milton_technical_analysis", dict(TECHNICAL, horizon="position"))
    assert fake.created == 2


async def test_a_resend_across_the_window_boundary_on_another_replica_returns_the_same_run(
    make_server, fake: FakeMilton
):
    replica_a = make_server(keys=IdempotencyKeys(lambda: WINDOW_SECONDS - 1))
    replica_b = make_server(keys=IdempotencyKeys(lambda: WINDOW_SECONDS + 1))
    first = await call(replica_a, "milton_technical_analysis", TECHNICAL)
    again = await call(replica_b, "milton_technical_analysis", TECHNICAL)

    assert fake.created == 1
    assert again.structured_content["run"]["id"] == first.structured_content["run"]["id"]
    assert "isn't billed again" in text(again)
    first_post, again_post = fake.run_posts()
    assert again_post.headers["idempotency-key"] != first_post.headers["idempotency-key"]
    assert again_post.headers["idempotency-previous-key"] == first_post.headers["idempotency-key"]


async def test_the_same_call_two_windows_later_starts_a_new_run(make_server, fake: FakeMilton):
    await call(make_server(keys=IdempotencyKeys(lambda: 0)), "milton_technical_analysis", TECHNICAL)
    await call(make_server(keys=IdempotencyKeys(lambda: 2 * WINDOW_SECONDS)), "milton_technical_analysis", TECHNICAL)
    assert fake.created == 2


async def test_default_model_and_effort_fill_the_request(make_server, fake: FakeMilton):
    settings = Settings(base_url=BASE_URL, api_key=API_KEY, default_model="gpt-6.1-sol", default_effort="low")
    await call(make_server(settings), "milton_macro_analysis", {})
    (post,) = fake.run_posts()
    assert fake.body(post) == {"model": "gpt-6.1-sol", "effort": "low"}


async def test_an_explicit_model_wins_over_the_default(make_server, fake: FakeMilton):
    settings = Settings(base_url=BASE_URL, api_key=API_KEY, default_model="gpt-6.1-sol")
    await call(make_server(settings), "milton_fundamental_analysis", {"ticker": "AAPL", "model": "claude-opus-5-5"})
    (post,) = fake.run_posts()
    assert fake.body(post) == {"ticker": "AAPL", "model": "claude-opus-5-5"}


async def test_unknown_tool(make_server):
    result = await call(make_server(), "milton_risk_analysis", {})
    assert result.is_error is True
