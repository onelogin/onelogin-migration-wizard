"""Integration tests for YAML credential extraction (Phase 2)."""

import tempfile
from pathlib import Path

import pytest
import yaml

from onelogin_migration_core.config_parser import CredentialExtractor
from onelogin_migration_core.credentials import AutoSaveCredentialManager


class TestCredentialExtractor:
    """Tests for CredentialExtractor class."""

    @pytest.fixture
    def sample_config_with_credentials(self):
        """Create a sample config with credentials."""
        return {
            "okta": {
                "subdomain": "mycompany",
                "token": "00abc123secrettoken",
                "rate_limit_per_minute": 600,
            },
            "onelogin": {
                "client_id": "client_abc123",
                "client_secret": "secret_xyz789",
                "subdomain": "mycompany-ol",
                "rate_limit_per_hour": 5000,
            },
            "migration": {"batch_size": 100, "dry_run": False},
        }

    @pytest.fixture
    def temp_config_file(self, sample_config_with_credentials):
        """Create a temporary config file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(sample_config_with_credentials, f)
            config_path = Path(f.name)
        yield config_path
        if config_path.exists():
            config_path.unlink()
        # Clean up backup files
        for backup in config_path.parent.glob(f"{config_path.stem}_backup_*.yaml"):
            backup.unlink()

    @pytest.fixture
    def credential_manager(self):
        """Create a credential manager with memory backend."""
        return AutoSaveCredentialManager(storage_backend="memory", enable_audit_log=False)

    def test_detect_credentials(self, sample_config_with_credentials):
        """Test detecting credentials in config."""
        extractor = CredentialExtractor()
        credentials = extractor.detect_credentials(sample_config_with_credentials)

        # Should detect token, client_secret
        assert len(credentials) >= 2
        services = {cred[0] for cred in credentials}
        keys = {cred[1] for cred in credentials}

        assert "token" in keys
        assert "client_secret" in keys

    def test_extract_and_secure(self, temp_config_file, credential_manager):
        """Test extracting credentials and securing them."""
        extractor = CredentialExtractor()

        sanitized_config, extracted_creds, backup_path = extractor.extract_and_secure(
            temp_config_file, credential_manager
        )

        # Check sanitized config
        assert "okta" in sanitized_config
        assert "onelogin" in sanitized_config

        # Token should be replaced with source reference
        assert (
            "token_source" in sanitized_config["okta"]
            or sanitized_config["okta"]["token"] != "00abc123secrettoken"
        )

        # Check extracted credentials
        assert len(extracted_creds) >= 2

        # Check backup was created
        assert backup_path.exists()
        assert "backup" in backup_path.name

    def test_sanitize_config(self, sample_config_with_credentials, credential_manager):
        """Test sanitizing config."""
        extractor = CredentialExtractor()

        # First detect credentials
        credentials = extractor.detect_credentials(sample_config_with_credentials)

        # Sanitize config (needs backend parameter)
        sanitized = extractor._sanitize_config(
            sample_config_with_credentials, credentials, "keyring"
        )

        # Original config should still have credentials
        assert sample_config_with_credentials["okta"]["token"] == "00abc123secrettoken"

        # Sanitized should not have plaintext credential
        assert "token" not in sanitized.get("okta", {})
        # Should have source reference instead
        assert sanitized.get("okta", {}).get("token_source") == "keyring"

    def test_create_backup(self, temp_config_file):
        """Test creating backup."""
        extractor = CredentialExtractor()

        backup_path = extractor._create_backup(temp_config_file)

        assert backup_path.exists()
        assert backup_path != temp_config_file
        assert "backup" in backup_path.name

        # Backup should have same content as original
        original_content = temp_config_file.read_text()
        backup_content = backup_path.read_text()
        assert original_content == backup_content

        # Clean up
        backup_path.unlink()

    def test_restore_credentials(
        self, temp_config_file, credential_manager, sample_config_with_credentials
    ):
        """Test restoring credentials from storage."""
        extractor = CredentialExtractor()

        # First extract and secure
        sanitized_config, extracted_creds, backup_path = extractor.extract_and_secure(
            temp_config_file, credential_manager
        )

        # Now restore (takes config_path, not config dict)
        restored_config = extractor.restore_credentials(temp_config_file, credential_manager)

        # Restored config should have credentials back
        assert "okta" in restored_config
        okta_token = restored_config["okta"].get("token")
        assert okta_token is not None
        # Should have the original value
        assert okta_token == sample_config_with_credentials["okta"]["token"]

    def test_validate_sanitized_config(self, temp_config_file, credential_manager):
        """Test validating sanitized config."""
        extractor = CredentialExtractor()

        # First create a sanitized config
        sanitized_config, extracted_creds, backup_path = extractor.extract_and_secure(
            temp_config_file, credential_manager
        )

        # Validate the sanitized config
        is_valid, remaining = extractor.validate_sanitized_config(temp_config_file)

        # The *_source fields will be detected as credentials (false positives)
        # Filter out _source fields from validation
        real_credentials = [r for r in remaining if not r.endswith("_source")]

        # Should have no real credentials remaining
        assert len(real_credentials) == 0, f"Real credentials remain: {real_credentials}"

    def test_get_credential_mapping(self, sample_config_with_credentials):
        """Test getting credential mapping."""
        extractor = CredentialExtractor()

        # get_credential_mapping takes config, not credentials list
        mapping = extractor.get_credential_mapping(sample_config_with_credentials)

        assert isinstance(mapping, dict)
        # Should have entries like "okta_token" -> ("okta", "token")
        assert len(mapping) > 0
        # Check specific mapping
        assert "okta_token" in mapping
        assert mapping["okta_token"] == ("okta", "token")

    def test_migrate_config(self, temp_config_file, credential_manager):
        """Test full migration workflow."""
        extractor = CredentialExtractor()

        # Create destination path
        dest_path = temp_config_file.parent / "migrated_config.yaml"

        # Perform migration (returns backup_path and extracted_names, not dict)
        backup_path, extracted_names = extractor.migrate_config(
            temp_config_file, dest_path, credential_manager
        )

        assert backup_path.exists()
        assert "backup" in backup_path.name
        assert len(extracted_names) >= 2
        assert dest_path.exists()

        # Clean up
        dest_path.unlink()
        backup_path.unlink()

    def test_extract_nested_credentials(self):
        """Test extracting credentials from nested config."""
        extractor = CredentialExtractor()

        config = {
            "level1": {
                "level2": {"level3": {"secret_key": "nested_secret", "api_token": "nested_token"}}
            },
            "other": {"normal_field": "value"},
        }

        credentials = extractor.detect_credentials(config)

        # Should detect nested credentials
        assert len(credentials) >= 2
        keys = {cred[1] for cred in credentials}
        assert "secret_key" in keys
        assert "api_token" in keys

    def test_extract_with_empty_config(self, credential_manager):
        """Test extracting from empty config."""
        extractor = CredentialExtractor()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"test": "value"}, f)  # Need non-empty config
            config_path = Path(f.name)

        try:
            # extract_and_secure returns early if no credentials detected
            sanitized_config, extracted_creds, backup_path = extractor.extract_and_secure(
                config_path, credential_manager
            )

            # No credentials, so returns original config and same path
            assert sanitized_config == {"test": "value"}
            assert len(extracted_creds) == 0
            # backup_path will be same as config_path if no credentials
            assert backup_path == config_path
        finally:
            config_path.unlink()

    def test_extract_preserves_structure(self, temp_config_file, credential_manager):
        """Test that extraction preserves config structure."""
        extractor = CredentialExtractor()

        # Load original
        original_config = yaml.safe_load(temp_config_file.read_text())

        # Extract
        sanitized_config, extracted_creds, backup_path = extractor.extract_and_secure(
            temp_config_file, credential_manager
        )

        # Structure should be preserved
        assert set(sanitized_config.keys()) == set(original_config.keys())
        assert "migration" in sanitized_config
        assert sanitized_config["migration"] == original_config["migration"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
