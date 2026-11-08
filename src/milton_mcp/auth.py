"""HTTP-mode authentication: the 401 challenge, and turning a token Milton rejects into an HTTP 401."""

from __future__ import annotations

from contextvars import ContextVar

# Tokens a Claude.ai or ChatGPT connector got from Milton's OAuth server. A connection runs every
# call on the model and effort the user chose when connecting, so they aren't tool inputs.
CONNECTOR_TOKEN_PREFIX = "mlo_"
SCOPE = "agents"


def is_connector_token(token: str | None) -> bool:
    return bool(token) and token.startswith(CONNECTOR_TOKEN_PREFIX)


def challenge(resource_metadata_url: str | None, *, rejected: bool = False) -> bytes:
    """The WWW-Authenticate value: with a protected-resource metadata URL, clients can discover
    Milton's OAuth server from it (RFC 9728) and ask for the agents scope. A token Milton rejected
    is marked invalid_token; a request with no token carries no error code (RFC 6750 §3.1)."""
    params = ['error="invalid_token"'] if rejected else []
    if resource_metadata_url:
        params += [f'resource_metadata="{resource_metadata_url}"', f'scope="{SCOPE}"']
    return ("Bearer " + ", ".join(params)).strip().encode()


# Set per HTTP request by the bearer guard; a tool call appends to it when Milton rejects the
# request's token, and the guard then answers 401 so the client refreshes or signs in again.
_token_rejected: ContextVar[list[bool] | None] = ContextVar("milton_mcp_token_rejected", default=None)


def note_token_rejected() -> None:
    flag = _token_rejected.get()
    if flag is not None:
        flag.append(True)
