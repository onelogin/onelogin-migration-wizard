"""Tests for WizardState provider-agnostic migration."""

from __future__ import annotations

import pytest


class TestWizardStateToMigrationSettings:
    def test_domain_field_used_directly(self) -> None:
        from onelogin_migration_gui import WizardState

        state = WizardState()
        state.source_provider = "Okta"
        state.source_settings = {
            "domain": "mycompany.okta.com",
            "token": "tok123",
            "rate_limit_per_minute": "600",
        }
        state.target_settings = {
            "client_id": "cid",
            "client_secret": "csec",
            "region": "us",
            "subdomain": "myco",
        }

        settings = state.to_migration_settings()
        assert settings.source.domain == "mycompany.okta.com"
        assert settings.source.provider_slug == "okta"

    def test_legacy_subdomain_synthesizes_domain(self) -> None:
        from onelogin_migration_gui import WizardState

        state = WizardState()
        state.source_provider = "Okta"
        state.source_settings = {
            "subdomain": "mycompany",
            "token": "tok123",
            "rate_limit_per_minute": "600",
        }
        state.target_settings = {
            "client_id": "cid",
            "client_secret": "csec",
            "region": "us",
            "subdomain": "myco",
        }

        settings = state.to_migration_settings()
        assert settings.source.domain == "mycompany.okta.com"

    def test_missing_domain_and_subdomain_raises(self) -> None:
        from onelogin_migration_gui import WizardState

        state = WizardState()
        state.source_provider = "Okta"
        state.source_settings = {"token": "tok123"}
        state.target_settings = {
            "client_id": "cid",
            "client_secret": "csec",
            "region": "us",
            "subdomain": "myco",
        }

        with pytest.raises(ValueError, match="domain is required"):
            state.to_migration_settings()


class TestWizardStateFromDict:
    def test_from_dict_subdomain_upgrade(self) -> None:
        from onelogin_migration_gui import WizardState

        saved = {
            "source": {
                "provider": "Okta",
                "settings": {"subdomain": "mycompany", "token": "tok"},
            },
            "target": {
                "provider": "OneLogin",
                "settings": {},
            },
        }
        state = WizardState.from_dict(saved)
        assert state.source_settings.get("domain") == "mycompany.okta.com"
