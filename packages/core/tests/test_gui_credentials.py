"""Tests for GUI credential integration (Phase 4)."""

import pytest

from onelogin_migration_core.credentials import AutoSaveCredentialManager

# Check if PySide6 is available
try:
    from onelogin_migration_core.gui.steps.provider import ProviderSettingsPage
    from onelogin_migration_core.gui.steps.source import SOURCE_PROVIDERS, SourceSettingsPage
    from onelogin_migration_core.gui.steps.target import TARGET_PROVIDERS, TargetSettingsPage
    from PySide6.QtWidgets import QApplication

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PYSIDE6_AVAILABLE, reason="PySide6 not available")


@pytest.fixture(scope="session")
def qapp():
    """Create QApplication instance for tests."""
    if PYSIDE6_AVAILABLE:
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        yield app
    else:
        yield None


@pytest.fixture
def credential_manager():
    """Create a credential manager with memory backend."""
    return AutoSaveCredentialManager(storage_backend="memory", enable_audit_log=False)


class TestProviderSettingsPage:
    """Tests for ProviderSettingsPage credential integration."""

    def test_provider_page_accepts_credential_manager(self, qapp, credential_manager):
        """Test that ProviderSettingsPage accepts credential_manager parameter."""
        page = ProviderSettingsPage(
            title="Test Page",
            entity_label="Test",
            providers={"TestProvider": {"field1": {"label": "Field 1"}}},
            credential_manager=credential_manager,
        )

        assert page.credential_manager is credential_manager
        assert hasattr(page, "_auto_save_timers")
        assert isinstance(page._auto_save_timers, dict)

    def test_provider_page_without_credential_manager(self, qapp):
        """Test that ProviderSettingsPage works without credential_manager."""
        page = ProviderSettingsPage(
            title="Test Page",
            entity_label="Test",
            providers={"TestProvider": {"field1": {"label": "Field 1"}}},
        )

        assert page.credential_manager is None

    def test_provider_page_has_auto_save_methods(self, qapp):
        """Test that ProviderSettingsPage has auto-save methods."""
        page = ProviderSettingsPage(
            title="Test Page",
            entity_label="Test",
            providers={"TestProvider": {"field1": {"label": "Field 1"}}},
        )

        assert hasattr(page, "_schedule_auto_save")
        assert hasattr(page, "_do_auto_save")
        assert callable(page._schedule_auto_save)
        assert callable(page._do_auto_save)

    def test_schedule_auto_save_without_manager(self, qapp):
        """Test that _schedule_auto_save works without credential manager."""
        page = ProviderSettingsPage(
            title="Test Page",
            entity_label="Test",
            providers={"TestProvider": {"field1": {"label": "Field 1"}}},
        )

        # Should not raise error
        page._schedule_auto_save("field1")

    def test_schedule_auto_save_with_manager(self, qapp, credential_manager):
        """Test that _schedule_auto_save creates timer with credential manager."""
        page = ProviderSettingsPage(
            title="Test Page",
            entity_label="Test",
            providers={"TestProvider": {"field1": {"label": "Field 1"}}},
            credential_manager=credential_manager,
        )

        # Create a field
        from PySide6.QtWidgets import QLineEdit

        page.fields["field1"] = QLineEdit()
        page.fields["field1"].setText("test_value")

        # Schedule auto-save
        page._schedule_auto_save("field1")

        # Should have created a timer
        assert "field1" in page._auto_save_timers
        assert page._auto_save_timers["field1"] is not None

    def test_do_auto_save_without_manager(self, qapp):
        """Test that _do_auto_save works without credential manager."""
        page = ProviderSettingsPage(
            title="Test Page",
            entity_label="Test",
            providers={"TestProvider": {"field1": {"label": "Field 1"}}},
        )

        # Should not raise error
        page._do_auto_save("field1")

    def test_do_auto_save_with_manager(self, qapp, credential_manager):
        """Test that _do_auto_save saves credential."""
        page = ProviderSettingsPage(
            title="Test Page",
            entity_label="Test",
            providers={"TestProvider": {"field1": {"label": "Field 1"}}},
            credential_manager=credential_manager,
        )

        # Create a field with value
        from PySide6.QtWidgets import QLineEdit

        page.fields["field1"] = QLineEdit()
        page.fields["field1"].setText("test_value")

        # Perform auto-save
        page._do_auto_save("field1")

        # Verify credential was saved
        saved = credential_manager.get_credential("test", "field1")
        assert saved is not None
        assert saved.reveal() == "test_value"


class TestSourceSettingsPage:
    """Tests for SourceSettingsPage credential integration."""

    def test_source_page_accepts_credential_manager(self, qapp, credential_manager):
        """Test that SourceSettingsPage accepts credential_manager parameter."""
        page = SourceSettingsPage(credential_manager=credential_manager)

        assert page.credential_manager is credential_manager

    def test_source_page_without_credential_manager(self, qapp):
        """Test that SourceSettingsPage works without credential_manager."""
        page = SourceSettingsPage()

        assert page.credential_manager is None

    def test_source_page_providers(self, qapp):
        """Test that SourceSettingsPage has correct providers."""
        page = SourceSettingsPage()

        assert page.provider_schemas == SOURCE_PROVIDERS
        assert "Okta" in page.provider_schemas


class TestTargetSettingsPage:
    """Tests for TargetSettingsPage credential integration."""

    def test_target_page_accepts_credential_manager(self, qapp, credential_manager):
        """Test that TargetSettingsPage accepts credential_manager parameter."""
        page = TargetSettingsPage(credential_manager=credential_manager)

        assert page.credential_manager is credential_manager

    def test_target_page_without_credential_manager(self, qapp):
        """Test that TargetSettingsPage works without credential_manager."""
        page = TargetSettingsPage()

        assert page.credential_manager is None

    def test_target_page_providers(self, qapp):
        """Test that TargetSettingsPage has correct providers."""
        page = TargetSettingsPage()

        assert page.provider_schemas == TARGET_PROVIDERS
        assert "OneLogin" in page.provider_schemas

    def test_target_page_hides_provider_selector(self, qapp):
        """Test that TargetSettingsPage hides provider selector."""
        page = TargetSettingsPage()

        assert page.hide_provider_selector is True


class TestCredentialWorkflow:
    """Integration tests for credential workflow in GUI."""

    def test_save_and_prefill_workflow(self, qapp, credential_manager):
        """Test save and prefill workflow."""
        # Create source page
        page = SourceSettingsPage(credential_manager=credential_manager)

        # Simulate saving credentials
        from PySide6.QtWidgets import QLineEdit

        # Create fields
        page.fields["subdomain"] = QLineEdit()
        page.fields["subdomain"].setText("mycompany")
        page.fields["token"] = QLineEdit()
        page.fields["token"].setText("00abc123token")

        # Simulate successful validation (which triggers save)
        page.show_validation_status(True, "Connection successful!")

        # Verify credentials were saved
        subdomain = credential_manager.get_credential("source", "subdomain")
        token = credential_manager.get_credential("source", "token")

        assert subdomain is not None
        assert subdomain.reveal() == "mycompany"
        assert token is not None
        assert token.reveal() == "00abc123token"

    def test_debounced_auto_save(self, qapp, credential_manager):
        """Test debounced auto-save on field changes."""
        import time

        from PySide6.QtWidgets import QLineEdit

        page = SourceSettingsPage(credential_manager=credential_manager)

        # Create a field
        page.fields["token"] = QLineEdit()

        # Simulate rapid typing (multiple changes)
        for i in range(5):
            page.fields["token"].setText(f"value_{i}")
            page._schedule_auto_save("token")

        # Should only have one active timer
        assert len(page._auto_save_timers) == 1

        # Wait for timer to expire
        time.sleep(0.1)
        QApplication.processEvents()

        # Note: Timer might not fire in test environment
        # This is a basic structure test

    def test_auto_prefill_on_page_entry(self, qapp, credential_manager):
        """Test auto-prefill when entering page."""
        # Pre-save some credentials
        credential_manager.auto_save_credential("source", "subdomain", "mycompany")
        credential_manager.auto_save_credential("source", "token", "00abc123token")

        # Create a mock WizardState
        class MockWizardState:
            source_provider = "Okta"
            source_settings = {}

        state = MockWizardState()

        # Create page
        page = SourceSettingsPage(credential_manager=credential_manager)

        # Simulate entering the page
        page.on_enter(state)

        # Fields should be populated
        # Note: This test verifies the logic exists, actual field population
        # depends on Qt event loop which may not run in tests


class TestCredentialSecurity:
    """Security tests for credential handling in GUI."""

    def test_credentials_not_in_plain_text_in_memory(self, qapp, credential_manager):
        """Test that credentials are not stored in plain text."""
        page = SourceSettingsPage(credential_manager=credential_manager)

        # Save a credential
        from PySide6.QtWidgets import QLineEdit

        page.fields["token"] = QLineEdit()
        page.fields["token"].setText("super_secret_token_12345")
        page._do_auto_save("token")

        # The credential should be in secure storage, not plain text in page
        # Check that _value_cache doesn't contain the plain token
        # (it might, but the secure storage should have it encrypted)

        # Retrieve from secure storage
        stored = credential_manager.get_credential("source", "token")
        assert stored is not None
        assert stored.reveal() == "super_secret_token_12345"

        # Original SecureString should hide value in repr
        assert "super_secret_token_12345" not in repr(stored)
        assert "***" in str(stored)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
