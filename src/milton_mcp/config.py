from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://withmilton.ai"


@dataclass(frozen=True)
class Settings:
    """Where Milton is and how to call it, from the environment.

    The API key is read only in stdio mode. In HTTP mode every request brings its own bearer token,
    so the server holds no key. base_url is the public origin, used for links; api_url is where API
    calls go, base_url unless a hosted deployment reaches the api inside its network.

    forward_client_ip passes the caller's CF-Connecting-IP on to Milton in HTTP mode. Turn it on only
    when every request reaches this server through Cloudflare, which sets that header; otherwise a
    caller could pick the IP Milton's per-IP limits apply to.
    """

    base_url: str = DEFAULT_BASE_URL
    api_url: str = ""
    api_key: str | None = None
    default_model: str | None = None
    default_effort: str | None = None
    forward_client_ip: bool = False

    def __post_init__(self) -> None:
        if not self.api_url:
            object.__setattr__(self, "api_url", self.base_url)


def settings_from_env(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env

    def get(name: str) -> str | None:
        value = (env.get(name) or "").strip()
        return value or None

    base_url = (get("MILTON_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    return Settings(
        base_url=base_url,
        api_url=(get("MILTON_API_URL") or base_url).rstrip("/"),
        api_key=get("MILTON_API_KEY"),
        default_model=get("MILTON_DEFAULT_MODEL"),
        default_effort=get("MILTON_DEFAULT_EFFORT"),
        forward_client_ip=(get("MILTON_FORWARD_CLIENT_IP") or "").lower() in ("1", "true", "yes"),
    )
