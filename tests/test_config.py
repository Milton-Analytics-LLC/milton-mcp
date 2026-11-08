from __future__ import annotations

import pytest

from milton_mcp.config import DEFAULT_BASE_URL, Settings, settings_from_env


def test_api_calls_go_to_the_public_origin_by_default():
    settings = settings_from_env({"MILTON_BASE_URL": "https://milton.test/"})
    assert settings.base_url == "https://milton.test"
    assert settings.api_url == "https://milton.test"


def test_hosted_deployments_call_the_api_inside_the_network():
    settings = settings_from_env(
        {"MILTON_BASE_URL": "https://withmilton.ai", "MILTON_API_URL": "http://api.milton.local:8080/"}
    )
    assert settings.base_url == "https://withmilton.ai"
    assert settings.api_url == "http://api.milton.local:8080"


def test_defaults():
    settings = settings_from_env({})
    assert settings.base_url == settings.api_url == DEFAULT_BASE_URL


def test_settings_built_directly_call_their_base_url():
    assert Settings(base_url="https://milton.test").api_url == "https://milton.test"
    assert (
        Settings(base_url="https://milton.test", api_url="http://api.internal:8080").api_url
        == "http://api.internal:8080"
    )


def test_client_ip_forwarding_is_off_by_default():
    assert settings_from_env({}).forward_client_ip is False
    assert Settings().forward_client_ip is False


@pytest.mark.parametrize(
    ("value", "expected"), [("true", True), ("1", True), ("TRUE", True), ("false", False), ("0", False), ("", False)]
)
def test_client_ip_forwarding_from_env(value: str, expected: bool):
    assert settings_from_env({"MILTON_FORWARD_CLIENT_IP": value}).forward_client_ip is expected


def test_resource_metadata_url_is_unset_by_default():
    assert settings_from_env({}).resource_metadata_url is None
    url = "https://withmilton.ai/.well-known/oauth-protected-resource/api/mcp"
    assert settings_from_env({"MILTON_RESOURCE_METADATA_URL": f" {url} "}).resource_metadata_url == url
