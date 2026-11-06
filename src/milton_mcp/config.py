from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://withmilton.ai"


@dataclass(frozen=True)
class Settings:
    """Where Milton is and how to call it, from the environment.

    The API key is read only in stdio mode. In HTTP mode every request brings its own bearer token,
    so the server holds no key.
    """

    base_url: str = DEFAULT_BASE_URL
    api_key: str | None = None
    default_model: str | None = None
    default_effort: str | None = None


def settings_from_env(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env

    def get(name: str) -> str | None:
        value = (env.get(name) or "").strip()
        return value or None

    return Settings(
        base_url=(get("MILTON_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        api_key=get("MILTON_API_KEY"),
        default_model=get("MILTON_DEFAULT_MODEL"),
        default_effort=get("MILTON_DEFAULT_EFFORT"),
    )
