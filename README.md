# milton-mcp

An [MCP](https://modelcontextprotocol.io) server for [Milton](https://withmilton.ai)'s analyst agents. Add it
to Claude Code, Claude Desktop, Cursor or your own agent, and the agent can ask Milton for a technical,
fundamental or macro read, a risk-checked trade idea, or the full desk on a ticker.

The server is a thin layer over Milton's [public API](https://withmilton.ai/docs/api/v1). The agents run
on Milton's servers; this package only sends your requests and formats the results. You need a Milton
account and an API token.

## Install

With [uv](https://docs.astral.sh/uv/) (no separate install step; `uvx` fetches and runs it):

```sh
uvx milton-mcp --version
```

Or with pip: `pip install milton-mcp`.

## Get an API token

Sign in at [withmilton.ai](https://withmilton.ai), open **Integrations → API tokens** and create one. It starts
with `mlt_`. Treat it like a password: it can start runs that bill to your balance.

## Claude.ai and ChatGPT

Milton hosts this server at `https://withmilton.ai/api/mcp`. In Claude.ai (**Settings → Connectors →
Add custom connector**) or ChatGPT (**add a custom MCP server**), enter that URL; no API token is
needed. You sign in to Milton, then choose the model and effort the connection uses. Every run from the
app uses them; to change them, disconnect the app in Milton (**Integrations → Connected apps**) and connect
it again.

## Configure your client

### Claude Code

```sh
claude mcp add milton -e MILTON_API_KEY=mlt_your_token -- uvx milton-mcp
```

### Claude Desktop, Cursor and other JSON-configured clients

Claude Desktop: `claude_desktop_config.json`. Cursor: `~/.cursor/mcp.json` or `.cursor/mcp.json`.

```json
{
  "mcpServers": {
    "milton": {
      "command": "uvx",
      "args": ["milton-mcp"],
      "env": { "MILTON_API_KEY": "mlt_your_token" }
    }
  }
}
```

### Your own agent

Any MCP client works. With the OpenAI Agents SDK, for example:

```python
from agents import Agent, Runner
from agents.mcp import MCPServerStdio

async with MCPServerStdio(
    params={"command": "uvx", "args": ["milton-mcp"], "env": {"MILTON_API_KEY": "mlt_your_token"}},
    client_session_timeout_seconds=70,
) as milton:
    agent = Agent(name="Analyst", instructions="...", mcp_servers=[milton])
    result = await Runner.run(agent, "Give me a swing-trade technical read on NVDA using gpt-6.1-sol.")
```

A tool call can wait up to 50 seconds for a run to finish, so give your client a request timeout of at
least 70 seconds.

## Settings

| Variable | Meaning |
|---|---|
| `MILTON_API_KEY` | Your API token (`mlt_…`). Required in stdio mode. |
| `MILTON_DEFAULT_MODEL` | Optional. The model runs use when a call doesn't name one; `model` then becomes optional in the tool schemas. |
| `MILTON_DEFAULT_EFFORT` | Optional. The reasoning effort runs use when a call doesn't name one. |
| `MILTON_BASE_URL` | Optional. Defaults to `https://withmilton.ai`. Links in results point here. |
| `MILTON_API_URL` | Optional. Where API calls go, if not `MILTON_BASE_URL` (for example a hosted deployment reaching the api inside its own network). |
| `MILTON_RESOURCE_METADATA_URL` | Optional, HTTP mode only. The URL of the endpoint's OAuth protected-resource metadata. When set, a 401 carries `WWW-Authenticate: Bearer resource_metadata="…", scope="agents"`, which is how OAuth clients such as Claude.ai and ChatGPT connectors find Milton's sign-in. Milton's hosted server sets it; a self-hosted server serving API tokens doesn't need it. |
| `MILTON_FORWARD_CLIENT_IP` | Optional, HTTP mode only. `true` passes each request's `CF-Connecting-IP` header on to Milton, so Milton's per-IP rate limits apply to your callers rather than to your server. Turn it on only if every request reaches the server through Cloudflare. Otherwise a caller could set the header and pick the IP those limits apply to. |

## Tools

| Tool | What it does |
|---|---|
| `milton_technical_analysis` | Multi-timeframe technical read of one US stock or ETF: directional bias and conviction, support and resistance, volatility posture. Inputs: `ticker`, `horizon`. |
| `milton_fundamental_analysis` | Fundamental read from filings, financials and news: bias, valuation, business quality, drivers, risks. Input: `ticker`. |
| `milton_macro_analysis` | Market-wide macro read: risk-on or risk-off regime, bias, timing, scheduled event risks, breadth. No ticker. |
| `milton_quant_analysis` | One risk-checked trade (options or shares) for a ticker and horizon, sized against a hypothetical $100,000 portfolio. It can conclude no trade is worth taking. |
| `milton_desk` | The full desk: macro, fundamental and technical reads, then a trade designed on them and reviewed by Milton's risk analyst. Takes several minutes. |
| `milton_get_run` | Gets a run by `run_id`: its status and, once it completes, its result. Uses no tokens. |

Every agent tool also takes `model` (any model Milton offers) and an optional `effort` (defaults to
`high`, or the model's highest level). `horizon` is `intraday`, `swing`, `position` or `long_term`.

### What comes back

A short digest the model can read (stance, conviction, summary, key levels, risks, how fresh the data
is, cost), the full result as structured content, and links to the run in Milton and in the API.

A run that hasn't finished after 50 seconds comes back as a `run_id` instead; `milton_get_run` waits up to
50 seconds per call for it. A desk run always returns its `run_id` at once.

### Repeated calls

MCP clients sometimes re-send a call when a connection drops. An identical call (same tool and inputs)
within 10 minutes returns the same run and isn't billed again, whichever server process handles it. Two
identical calls 10 to 20 minutes apart may also share a run; after that, a call starts a new one. A call
with any different input starts a new run. If the earlier identical run failed, asking again starts a new
run rather than returning the failure; failed runs aren't billed.

## Cost

Runs bill the tokens they use at the chosen model's rates ([pricing](https://withmilton.ai/api/v1/pricing))
against your Milton balance; a desk run bills every analyst it runs. Failed runs aren't billed. Pick a
smaller model or a lower effort for cheaper, faster runs.

## Running it on your own server

`--http` serves MCP over Streamable HTTP (stateless, JSON responses), so agents on other machines can
reach it:

```sh
milton-mcp --http --host 0.0.0.0 --port 8000      # endpoint: http://<host>:8000/mcp
```

In HTTP mode the server holds no API token. Every request must carry the caller's token as
`Authorization: Bearer mlt_…`, which is passed on to Milton. A request without one gets a 401, and so
does a call whose token Milton rejects (expired, revoked or disconnected), so OAuth clients refresh or
sign in again. Put it behind TLS if it's reachable beyond your own network. `GET /healthz` answers 200 without a token, for
load-balancer health checks.

### Telemetry

With an OpenTelemetry SDK configured (for example, run under `opentelemetry-instrument`), the server
counts calls as `milton.mcp.calls` (labels `method`, `tool`, `outcome`) and passes the trace context on
to Milton. Without one it records nothing.

## Development

```sh
uv sync --group dev
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

The tools' input schemas, the result schema and the fallback model list are generated from Milton's
published API description:

```sh
uv run python scripts/generate_schemas.py            # from https://withmilton.ai
uv run python scripts/generate_schemas.py --check    # fails if src/milton_mcp/schemas.json is stale
```

Releases publish to PyPI when a `vX.Y.Z` tag matching `pyproject.toml`'s version is pushed.

## Disclosures

Milton is not a registered investment adviser, broker-dealer or financial planner. Its outputs are
AI-generated general information, not personalized investment advice or a recommendation to buy or sell
any security. Each result carries Milton's full disclosures.

## License

MIT
