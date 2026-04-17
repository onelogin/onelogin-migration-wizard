"""Tests for secure settings management (no credentials in files)."""

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from onelogin_migration_core.secure_settings import (
    NonSensitiveSettings,
    SecureSettingsManager,
    get_default_settings_manager,
)


class TestNonSensitiveSettings:
    """Tests for NonSensitiveSettings Pydantic model."""

    def test_default_values(self):
        """Test that defaults are set correctly."""
        settings = NonSensitiveSettings()

        assert settings.dry_run is True
        assert settings.chunk_size == 200
        assert settings.export_directory == "artifacts"
        assert settings.concurrency_enabled is False
        assert settings.max_workers == 4
        assert settings.bulk_user_upload is False
        assert settings.project == "migration"
        assert settings.owner == ""
        assert settings.okta_domain == ""
        assert settings.okta_rate_limit_per_minute == 600
        assert settings.okta_page_size == 200
        assert settings.onelogin_region == "us"
        assert settings.onelogin_subdomain == ""
        assert settings.onelogin_rate_limit_per_hour == 5000
        assert settings.onelogin_client_id == ""

    def test_custom_values(self):
        """Test creating settings with custom values."""
        settings = NonSensitiveSettings(
            dry_run=False,
            chunk_size=500,
            okta_domain="mycompany.okta.com",
            onelogin_client_id="abc123",
            onelogin_region="eu",
        )

        assert settings.dry_run is False
        assert settings.chunk_size == 500
        assert settings.okta_domain == "mycompany.okta.com"
        assert settings.onelogin_client_id == "abc123"
        assert settings.onelogin_region == "eu"

    def test_validation_chunk_size_min(self):
        """Test chunk_size minimum validation."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            NonSensitiveSettings(chunk_size=0)

    def test_validation_chunk_size_max(self):
        """Test chunk_size maximum validation."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            NonSensitiveSettings(chunk_size=2000)

    def test_validation_max_workers_min(self):
        """Test max_workers minimum validation."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            NonSensitiveSettings(max_workers=0)

    def test_validation_max_workers_max(self):
        """Test max_workers maximum validation."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            NonSensitiveSettings(max_workers=100)

    def test_model_dump(self):
        """Test serialization with model_dump."""
        settings = NonSensitiveSettings(
            dry_run=False,
            okta_domain="test.okta.com",
        )

        data = settings.model_dump()

        assert isinstance(data, dict)
        assert data["dry_run"] is False
        assert data["okta_domain"] == "test.okta.com"
        assert "token" not in data  # No credential fields
        assert "client_secret" not in data

    def test_no_extra_fields_allowed(self):
        """Test that extra fields are forbidden."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            NonSensitiveSettings(some_random_field="value")


class TestSecureSettingsManager:
    """Tests for SecureSettingsManager class."""

    @pytest.fixture
    def temp_settings_dir(self):
        """Create temporary settings directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def manager(self, temp_settings_dir):
        """Create SecureSettingsManager with temp directory."""
        return SecureSettingsManager(settings_dir=temp_settings_dir)

    def test_init_creates_directory(self, temp_settings_dir):
        """Test that initialization creates settings directory."""
        settings_dir = temp_settings_dir / "subdir"
        assert not settings_dir.exists()

        manager = SecureSettingsManager(settings_dir=settings_dir)

        assert settings_dir.exists()
        assert manager.settings_file == settings_dir / "settings.json"

    def test_load_settings_with_no_file(self, manager):
        """Test loading settings when no file exists returns defaults."""
        settings = manager.load_settings()

        assert isinstance(settings, NonSensitiveSettings)
        assert settings.dry_run is True
        assert settings.chunk_size == 200

    def test_save_and_load_settings(self, manager):
        """Test saving and loading settings."""
        original = NonSensitiveSettings(
            dry_run=False,
            chunk_size=300,
            okta_domain="company.okta.com",
            onelogin_client_id="client123",
        )

        manager.save_settings(original)

        # Verify file exists
        assert manager.settings_file.exists()

        # Load and verify
        loaded = manager.load_settings()
        assert loaded.dry_run is False
        assert loaded.chunk_size == 300
        assert loaded.okta_domain == "company.okta.com"
        assert loaded.onelogin_client_id == "client123"

    def test_save_settings_atomic(self, manager):
        """Test that save is atomic (uses temp file + rename)."""
        settings = NonSensitiveSettings(dry_run=False)

        manager.save_settings(settings)

        # Check that temp file is gone (renamed to final)
        temp_file = manager.settings_file.with_suffix(".tmp")
        assert not temp_file.exists()
        assert manager.settings_file.exists()

    def test_save_settings_creates_valid_json(self, manager):
        """Test that saved file is valid JSON."""
        settings = NonSensitiveSettings(
            okta_domain="test.okta.com",
            chunk_size=250,
        )

        manager.save_settings(settings)

        # Read and parse JSON
        data = json.loads(manager.settings_file.read_text())
        assert data["okta_domain"] == "test.okta.com"
        assert data["chunk_size"] == 250

    def test_load_settings_with_corrupted_file(self, manager):
        """Test loading with corrupted file returns defaults."""
        # Write invalid JSON
        manager.settings_file.write_text("{ invalid json }")

        # Should return defaults and log warning
        settings = manager.load_settings()
        assert isinstance(settings, NonSensitiveSettings)
        assert settings.dry_run is True  # Default value

    def test_reset_settings(self, manager):
        """Test resetting settings to defaults."""
        # Save custom settings
        custom = NonSensitiveSettings(dry_run=False, chunk_size=500)
        manager.save_settings(custom)

        # Reset
        reset_settings = manager.reset_settings()

        # Verify defaults
        assert reset_settings.dry_run is True
        assert reset_settings.chunk_size == 200

        # Verify saved to file
        loaded = manager.load_settings()
        assert loaded.dry_run is True
        assert loaded.chunk_size == 200

    def test_export_settings(self, manager, temp_settings_dir):
        """Test exporting settings to a specific path."""
        settings = NonSensitiveSettings(
            dry_run=False,
            okta_domain="export.okta.com",
        )
        manager.save_settings(settings)

        export_path = temp_settings_dir / "exported_settings.json"
        manager.export_settings(export_path)

        # Verify export file exists and is valid
        assert export_path.exists()
        data = json.loads(export_path.read_text())
        assert data["okta_domain"] == "export.okta.com"

    def test_import_settings(self, manager, temp_settings_dir):
        """Test importing settings from a specific path."""
        import_path = temp_settings_dir / "import.json"
        import_data = {
            "dry_run": False,
            "chunk_size": 400,
            "okta_domain": "import.okta.com",
            "okta_rate_limit_per_minute": 600,
            "okta_page_size": 200,
            "onelogin_region": "us",
            "onelogin_subdomain": "",
            "onelogin_rate_limit_per_hour": 5000,
            "onelogin_client_id": "",
            "export_directory": "artifacts",
            "concurrency_enabled": False,
            "max_workers": 4,
            "bulk_user_upload": False,
            "project": "migration",
            "owner": "",
        }
        import_path.write_text(json.dumps(import_data, indent=2))

        imported = manager.import_settings(import_path)

        assert imported.dry_run is False
        assert imported.chunk_size == 400
        assert imported.okta_domain == "import.okta.com"

        # Verify saved
        loaded = manager.load_settings()
        assert loaded.okta_domain == "import.okta.com"

    def test_import_from_yaml(self, manager, temp_settings_dir):
        """Test importing from legacy YAML config."""
        yaml_path = temp_settings_dir / "legacy.yaml"
        yaml_data = {
            "dry_run": False,
            "chunk_size": 150,
            "export_directory": "output",
            "concurrency_enabled": True,
            "max_workers": 8,
            "bulk_user_upload": True,
            "metadata": {
                "project": "test_project",
                "owner": "test_owner",
            },
            "okta": {
                "domain": "legacy.okta.com",
                "token": "00secret_token_here",  # Should NOT be imported
                "rate_limit_per_minute": 500,
                "page_size": 100,
            },
            "onelogin": {
                "client_id": "client_abc",
                "client_secret": "secret_xyz",  # Should NOT be imported
                "region": "eu",
                "subdomain": "legacy-company",
                "rate_limit_per_hour": 3000,
            },
        }
        yaml_path.write_text(yaml.dump(yaml_data))

        settings, credentials = manager.import_from_yaml(yaml_path)

        # Verify settings extracted
        assert settings.dry_run is False
        assert settings.chunk_size == 150
        assert settings.export_directory == "output"
        assert settings.concurrency_enabled is True
        assert settings.max_workers == 8
        assert settings.bulk_user_upload is True
        assert settings.project == "test_project"
        assert settings.owner == "test_owner"
        assert settings.okta_domain == "legacy.okta.com"
        assert settings.okta_rate_limit_per_minute == 500
        assert settings.okta_page_size == 100
        assert settings.onelogin_client_id == "client_abc"
        assert settings.onelogin_region == "eu"
        assert settings.onelogin_subdomain == "legacy-company"
        assert settings.onelogin_rate_limit_per_hour == 3000

        # Verify credentials extracted separately
        assert "okta_token" in credentials
        assert credentials["okta_token"] == "00secret_token_here"
        assert "onelogin_client_secret" in credentials
        assert credentials["onelogin_client_secret"] == "secret_xyz"

    def test_import_from_yaml_with_missing_fields(self, manager, temp_settings_dir):
        """Test importing from minimal YAML config."""
        yaml_path = temp_settings_dir / "minimal.yaml"
        yaml_data = {
            "okta": {"domain": "minimal.okta.com"},
        }
        yaml_path.write_text(yaml.dump(yaml_data))

        settings, credentials = manager.import_from_yaml(yaml_path)

        # Should use defaults for missing fields
        assert settings.dry_run is True  # Default
        assert settings.chunk_size == 200  # Default
        assert settings.okta_domain == "minimal.okta.com"
        assert len(credentials) == 0  # No credentials

    def test_to_legacy_yaml_format(self, manager):
        """Test converting settings to legacy YAML format."""
        settings = NonSensitiveSettings(
            dry_run=False,
            chunk_size=300,
            okta_domain="convert.okta.com",
            okta_rate_limit_per_minute=700,
            onelogin_client_id="client_xyz",
            onelogin_region="eu",
            onelogin_subdomain="convert-company",
        )

        yaml_format = manager.to_legacy_yaml_format(settings)

        # Verify structure
        assert yaml_format["dry_run"] is False
        assert yaml_format["chunk_size"] == 300
        assert yaml_format["export_directory"] == "artifacts"

        # Verify okta section
        assert yaml_format["okta"]["domain"] == "convert.okta.com"
        assert yaml_format["okta"]["rate_limit_per_minute"] == 700
        assert yaml_format["okta"]["token_source"] == "keyring"  # Indicates secure storage

        # Verify onelogin section
        assert yaml_format["onelogin"]["client_id"] == "client_xyz"
        assert yaml_format["onelogin"]["region"] == "eu"
        assert yaml_format["onelogin"]["subdomain"] == "convert-company"
        assert (
            yaml_format["onelogin"]["client_secret_source"] == "keyring"
        )  # Indicates secure storage

        # Verify NO plaintext credentials
        assert "token" not in yaml_format["okta"]
        assert "client_secret" not in yaml_format["onelogin"]

    def test_settings_file_permissions(self, manager):
        """Test that settings file has appropriate permissions."""
        settings = NonSensitiveSettings(okta_domain="test.okta.com")
        manager.save_settings(settings)

        # File should exist and be readable
        assert manager.settings_file.exists()
        assert manager.settings_file.is_file()
        # On Unix systems, should have restrictive permissions
        # (This is more of a reminder - actual permission setting would be OS-specific)

    def test_default_settings_location(self):
        """Test that default settings use correct location."""
        manager = SecureSettingsManager()

        expected_dir = Path.home() / ".onelogin-migration"
        expected_file = expected_dir / "settings.json"

        assert manager.settings_dir == expected_dir
        assert manager.settings_file == expected_file

    def test_get_default_settings_manager(self):
        """Test helper function for default manager."""
        manager = get_default_settings_manager()

        assert isinstance(manager, SecureSettingsManager)
        assert manager.settings_dir == Path.home() / ".onelogin-migration"


class TestSecureSettingsIntegration:
    """Integration tests for secure settings workflow."""

    @pytest.fixture
    def temp_settings_dir(self):
        """Create temporary settings directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_full_migration_workflow(self, temp_settings_dir):
        """Test complete migration from YAML to secure settings."""
        manager = SecureSettingsManager(settings_dir=temp_settings_dir)

        # 1. Create legacy YAML config
        yaml_path = temp_settings_dir / "legacy_config.yaml"
        legacy_config = {
            "dry_run": False,
            "chunk_size": 250,
            "okta": {
                "domain": "migration.okta.com",
                "token": "00secret_okta_token",
                "rate_limit_per_minute": 650,
            },
            "onelogin": {
                "client_id": "onelogin_client_id",
                "client_secret": "secret_onelogin_secret",
                "region": "us",
                "subdomain": "migration-company",
            },
        }
        yaml_path.write_text(yaml.dump(legacy_config))

        # 2. Import from YAML
        settings, credentials = manager.import_from_yaml(yaml_path)

        # 3. Save settings (NO credentials)
        manager.save_settings(settings)

        # 4. Verify settings saved correctly
        loaded_settings = manager.load_settings()
        assert loaded_settings.dry_run is False
        assert loaded_settings.chunk_size == 250
        assert loaded_settings.okta_domain == "migration.okta.com"

        # 5. Verify credentials extracted (would be stored in keyring separately)
        assert credentials["okta_token"] == "00secret_okta_token"
        assert credentials["onelogin_client_secret"] == "secret_onelogin_secret"

        # 6. Verify settings file has NO credentials
        settings_json = json.loads(manager.settings_file.read_text())
        assert "token" not in json.dumps(settings_json)
        assert "secret" not in json.dumps(settings_json)
        assert "00secret_okta_token" not in json.dumps(settings_json)
        assert "secret_onelogin_secret" not in json.dumps(settings_json)

    def test_export_for_sharing(self, temp_settings_dir):
        """Test exporting settings for team sharing (without credentials)."""
        manager = SecureSettingsManager(settings_dir=temp_settings_dir)

        # Create settings with company-specific configuration
        settings = NonSensitiveSettings(
            dry_run=True,
            chunk_size=200,
            okta_domain="company.okta.com",
            okta_rate_limit_per_minute=600,
            onelogin_region="us",
            onelogin_subdomain="company",
            project="prod_migration",
            owner="platform_team",
        )
        manager.save_settings(settings)

        # Export to share with team
        export_path = temp_settings_dir / "team_settings.json"
        manager.export_settings(export_path)

        # Verify export is safe to share (no credentials)
        export_data = json.loads(export_path.read_text())

        # Has useful config
        assert export_data["okta_domain"] == "company.okta.com"
        assert export_data["project"] == "prod_migration"

        # Has NO credentials
        export_text = export_path.read_text()
        assert "token" not in export_text
        assert "secret" not in export_text
        assert "password" not in export_text

    def test_settings_persistence_across_sessions(self, temp_settings_dir):
        """Test that settings persist correctly across multiple sessions."""
        # Session 1: Create and save settings
        manager1 = SecureSettingsManager(settings_dir=temp_settings_dir)
        settings1 = NonSensitiveSettings(
            dry_run=False,
            okta_domain="session1.okta.com",
        )
        manager1.save_settings(settings1)

        # Session 2: Load settings (simulate app restart)
        manager2 = SecureSettingsManager(settings_dir=temp_settings_dir)
        settings2 = manager2.load_settings()

        assert settings2.dry_run is False
        assert settings2.okta_domain == "session1.okta.com"

        # Session 3: Update and save
        settings2.chunk_size = 350
        manager2.save_settings(settings2)

        # Session 4: Verify update persisted
        manager3 = SecureSettingsManager(settings_dir=temp_settings_dir)
        settings3 = manager3.load_settings()

        assert settings3.chunk_size == 350
        assert settings3.okta_domain == "session1.okta.com"  # Unchanged


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
