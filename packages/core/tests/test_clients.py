"""Tests for the OneLogin client helpers."""

from __future__ import annotations

import json

import requests

from onelogin_migration_core.clients import OneLoginApiSettings, OneLoginClient


def _build_response(status: int, payload: dict[str, object]) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(payload).encode()
    response.url = "https://example.onelogin.com/api"
    return response


def test_custom_attribute_already_exists_detects_message() -> None:
    settings = OneLoginApiSettings(client_id="id", client_secret="secret", subdomain="tenant")
    client = OneLoginClient(settings)

    response = _build_response(400, {"message": "Shortname has already been taken"})

    assert client._custom_attribute_already_exists(response)  # type: ignore[attr-defined]


class DuplicateAttributeClient(OneLoginClient):
    def __init__(self, settings: OneLoginApiSettings) -> None:
        super().__init__(settings, dry_run=False)

    def _request(self, method: str, path: str, **kwargs: object) -> requests.Response:  # type: ignore[override]
        if method == "POST":
            response = _build_response(400, {"message": "Shortname has already been taken"})
            raise requests.HTTPError(response=response)
        if method == "GET":
            return _build_response(
                200,
                {"data": [{"shortname": "existing_attr", "name": "Existing Attr"}]},
            )
        raise AssertionError(f"Unexpected method {method}")


def test_create_custom_attribute_ignores_duplicate_error() -> None:
    settings = OneLoginApiSettings(client_id="id", client_secret="secret", subdomain="tenant")
    client = DuplicateAttributeClient(settings)
    client._custom_attribute_cache = set()  # type: ignore[attr-defined]
    client._custom_attribute_cache_loaded = True  # type: ignore[attr-defined]

    client._create_custom_attribute("existing_attr")  # type: ignore[attr-defined]

    assert "existing_attr" in client._custom_attribute_cache  # type: ignore[attr-defined]
