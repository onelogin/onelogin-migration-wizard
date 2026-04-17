"""Tests for multi-provider abstraction layer."""

from __future__ import annotations

import pytest
from onelogin_migration_core.clients import (
    OktaSourceClient,
    SourceClient,
    build_source_client,
    _PROVIDER_REGISTRY,
)
from onelogin_migration_core.config import MigrationSettings, SourceApiSettings


def _minimal_settings(**source_overrides) -> MigrationSettings:
    source = {"provider": "okta", "domain": "test.okta.com", "token": "tok"}
    source.update(source_overrides)
    return MigrationSettings.from_dict(
        {"source": source, "onelogin": {"client_id": "id", "client_secret": "s"}}
    )


class TestSourceClientProtocol:
    def test_okta_client_satisfies_protocol(self) -> None:
        settings = SourceApiSettings(domain="x.okta.com", token="t", provider="okta")
        client = OktaSourceClient(settings)
        assert isinstance(client, SourceClient)

    def test_provider_registry_contains_okta(self) -> None:
        assert "okta" in _PROVIDER_REGISTRY
        assert _PROVIDER_REGISTRY["okta"] is OktaSourceClient


class TestBuildSourceClient:
    def test_builds_okta_client(self) -> None:
        settings = _minimal_settings()
        client = build_source_client(settings)
        assert isinstance(client, OktaSourceClient)

    def test_raises_for_unsupported_provider(self) -> None:
        settings = _minimal_settings(provider="azure_ad")
        with pytest.raises(ValueError, match="Unsupported source provider"):
            build_source_client(settings)


class TestSourceApiSettings:
    def test_provider_slug_normalizes(self) -> None:
        s = SourceApiSettings(domain="x", token="t", provider="  Okta  ")
        assert s.provider_slug == "okta"

    def test_provider_display_name(self) -> None:
        s = SourceApiSettings(domain="x", token="t", provider="azure_ad")
        assert s.provider_display_name == "Azure Ad"

    def test_source_label_strips_okta_domain(self) -> None:
        s = SourceApiSettings(domain="mycompany.okta.com", token="t", provider="okta")
        assert s.source_label == "mycompany"

    def test_source_label_generic_domain(self) -> None:
        s = SourceApiSettings(domain="login.microsoftonline.com", token="t", provider="azure_ad")
        assert s.source_label == "login"

    def test_source_label_with_https(self) -> None:
        s = SourceApiSettings(domain="https://mycompany.okta.com", token="t", provider="okta")
        assert s.source_label == "mycompany"

    def test_validate_okta_valid(self) -> None:
        s = SourceApiSettings(domain="mycompany.okta.com", token="tok123", provider="okta")
        s.validate()  # should not raise

    def test_validate_empty_domain_raises(self) -> None:
        s = SourceApiSettings(domain="", token="tok", provider="okta")
        with pytest.raises(ValueError, match="domain"):
            s.validate()

    def test_validate_empty_token_raises(self) -> None:
        s = SourceApiSettings(domain="x.okta.com", token="", provider="okta")
        with pytest.raises(ValueError, match="token"):
            s.validate()


from onelogin_migration_core.config import OktaApiSettings


class TestOktaApiSettingsAlias:
    def test_okta_api_settings_is_source_api_settings(self) -> None:
        assert OktaApiSettings is SourceApiSettings

    def test_okta_api_settings_defaults_provider_to_okta(self) -> None:
        s = OktaApiSettings(domain="x.okta.com", token="t")
        assert s.provider_slug == "okta"

    def test_provider_none_normalized_to_okta(self) -> None:
        s = SourceApiSettings(domain="x.okta.com", token="t", provider=None)
        assert s.provider == "okta"
        assert s.provider_slug == "okta"


class TestFromDictSourceKey:
    def test_from_dict_with_source_key(self) -> None:
        s = MigrationSettings.from_dict({
            "source": {"provider": "okta", "domain": "x.okta.com", "token": "t"},
            "onelogin": {"client_id": "id", "client_secret": "s"},
        })
        assert s.source.provider_slug == "okta"
        assert s.source.domain == "x.okta.com"

    def test_from_dict_with_legacy_okta_key(self) -> None:
        s = MigrationSettings.from_dict({
            "okta": {"domain": "x.okta.com", "token": "t"},
            "onelogin": {"client_id": "id", "client_secret": "s"},
        })
        assert s.source.provider_slug == "okta"
        assert s.source.domain == "x.okta.com"

    def test_from_dict_source_takes_precedence_over_okta(self) -> None:
        s = MigrationSettings.from_dict({
            "source": {"provider": "okta", "domain": "new.okta.com", "token": "t"},
            "okta": {"domain": "old.okta.com", "token": "old"},
            "onelogin": {"client_id": "id", "client_secret": "s"},
        })
        assert s.source.domain == "new.okta.com"

    def test_from_dict_missing_both_keys_raises(self) -> None:
        with pytest.raises(ValueError, match="source.*okta"):
            MigrationSettings.from_dict({
                "onelogin": {"client_id": "id", "client_secret": "s"},
            })

    def test_backward_compat_okta_property(self) -> None:
        s = MigrationSettings.from_dict({
            "source": {"provider": "okta", "domain": "x.okta.com", "token": "t"},
            "onelogin": {"client_id": "id", "client_secret": "s"},
        })
        assert s.okta is s.source


class TestMigrationManagerSourceClient:
    def _make_manager(self, **overrides):
        from unittest.mock import MagicMock
        settings = _minimal_settings(**overrides)

        class DummySource:
            def __init__(self):
                self.settings = settings.source
                self.session = MagicMock()
                self.export_payload = {"users": [{"id": "1"}], "groups": [], "memberships": [], "applications": []}
            def export_all(self, categories=None):
                return self.export_payload
            def list_users(self): return []
            def list_groups(self): return []
            def list_group_memberships(self, groups=None): return []
            def list_applications(self): return []
            def list_policies(self): return []
            def test_connection(self): return True, "ok"

        class DummyOneLogin:
            dry_run = False

        return DummySource(), DummyOneLogin(), settings

    def test_accepts_source_client_kwarg(self) -> None:
        from onelogin_migration_core.manager import MigrationManager
        source, onelogin, settings = self._make_manager()
        mgr = MigrationManager(settings, source_client=source, onelogin_client=onelogin)
        assert mgr.source is source
        assert mgr.okta is source

    def test_export_from_source_delegates(self) -> None:
        from onelogin_migration_core.manager import MigrationManager
        source, onelogin, settings = self._make_manager()
        mgr = MigrationManager(settings, source_client=source, onelogin_client=onelogin)
        result = mgr.export_from_source()
        assert result["users"] == [{"id": "1"}]

    def test_export_from_okta_backward_compat(self) -> None:
        from onelogin_migration_core.manager import MigrationManager
        source, onelogin, settings = self._make_manager()
        mgr = MigrationManager(settings, source_client=source, onelogin_client=onelogin)
        result = mgr.export_from_okta()
        assert result == mgr.export_from_source()


from unittest.mock import patch, MagicMock


class TestOktaTestConnection:
    def test_test_connection_success(self) -> None:
        settings = SourceApiSettings(domain="myco.okta.com", token="tok", provider="okta")
        client = OktaSourceClient(settings)
        mock_resp = MagicMock()
        mock_resp.ok = True
        with patch.object(client.session, "get", return_value=mock_resp) as mock_get:
            success, msg = client.test_connection()
            assert success is True
            assert "Successfully" in msg
            mock_get.assert_called_once()
            call_url = mock_get.call_args[0][0]
            assert "/api/v1/users" in call_url

    def test_test_connection_401(self) -> None:
        settings = SourceApiSettings(domain="myco.okta.com", token="bad", provider="okta")
        client = OktaSourceClient(settings)
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 401
        with patch.object(client.session, "get", return_value=mock_resp):
            success, msg = client.test_connection()
            assert success is False
            assert "invalid" in msg.lower()

    def test_test_connection_timeout(self) -> None:
        import requests as req
        settings = SourceApiSettings(domain="myco.okta.com", token="tok", provider="okta")
        client = OktaSourceClient(settings)
        with patch.object(client.session, "get", side_effect=req.Timeout("timed out")):
            success, msg = client.test_connection()
            assert success is False
            assert "timed out" in msg.lower() or "timeout" in msg.lower()
