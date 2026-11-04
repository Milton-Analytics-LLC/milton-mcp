from __future__ import annotations

import pytest

from milton_mcp.client import MiltonClient
from milton_mcp.config import Settings
from milton_mcp.idempotency import IdempotencyKeys
from milton_mcp.server import MiltonTools, build_server
from tests.fakes import API_KEY, BASE_URL, FakeMilton


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fake() -> FakeMilton:
    return FakeMilton()


@pytest.fixture
def make_server(fake: FakeMilton):
    def make(settings: Settings | None = None, keys: IdempotencyKeys | None = None):
        settings = settings or Settings(base_url=BASE_URL, api_key=API_KEY)
        client = MiltonClient(settings.base_url, transport=fake.transport())
        return build_server(MiltonTools(settings, client, http_mode=False, keys=keys))

    return make
