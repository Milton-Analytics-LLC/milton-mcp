from __future__ import annotations

from milton_mcp.config import DEFAULT_BASE_URL, settings_from_env


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
