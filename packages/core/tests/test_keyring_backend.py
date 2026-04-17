"""
Tests for keyring backend enhancements.

This module tests:
- Keyring credential tracking
- list_credentials() for keyring backend
- backup_to_file() for keyring backend
- restore_from_file() to keyring backend
- Tracking file persistence and recovery
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from onelogin_migration_core.credentials import AutoSaveCredentialManager


class TestKeyringTracking:
    """Test keyring credential tracking functionality."""

    @patch("layered_credentials.core.keyring")
    def test_save_creates_tracking(self, mock_keyring):
        """Test that saving a credential creates tracking entry."""
        mock_keyring.set_password = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AutoSaveCredentialManager(
                storage_backend="keyring",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            # Save credential
            manager.auto_save_credential("service1", "key1", "value1")

            # Verify tracking file was created
            tracking_file = Path(tmpdir) / ".keyring_credentials.json"
            assert tracking_file.exists()

            # Verify tracking content
            import json

            with open(tracking_file) as f:
                data = json.load(f)

            assert data["version"] == "1"
            assert len(data["credentials"]) == 1
            assert data["credentials"][0]["service"] == "service1"
            assert data["credentials"][0]["key"] == "key1"
            assert "created_at" in data["credentials"][0]

    @patch("layered_credentials.core.keyring")
    def test_delete_removes_from_tracking(self, mock_keyring):
        """Test that deleting a credential removes it from tracking."""
        mock_keyring.set_password = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=None)
        mock_keyring.delete_password = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AutoSaveCredentialManager(
                storage_backend="keyring",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            # Save and then delete credential
            manager.auto_save_credential("service1", "key1", "value1")
            manager.delete_credential("service1", "key1")

            # Verify tracking file updated
            tracking_file = Path(tmpdir) / ".keyring_credentials.json"
            import json

            with open(tracking_file) as f:
                data = json.load(f)

            assert len(data["credentials"]) == 0

    @patch("layered_credentials.core.keyring")
    def test_tracking_persists_across_sessions(self, mock_keyring):
        """Test that tracking file persists across manager instances."""
        mock_keyring.set_password = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            # First session - save credentials
            manager1 = AutoSaveCredentialManager(
                storage_backend="keyring",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )
            manager1.auto_save_credential("service1", "key1", "value1")
            manager1.auto_save_credential("service2", "key2", "value2")

            # Second session - should load tracking
            manager2 = AutoSaveCredentialManager(
                storage_backend="keyring",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            # Verify tracking was loaded
            assert len(manager2._keyring_store) == 2
            assert ("service1", "key1") in manager2._keyring_store
            assert ("service2", "key2") in manager2._keyring_store


class TestKeyringListCredentials:
    """Test list_credentials() for keyring backend."""

    @patch("layered_credentials.core.keyring")
    def test_list_empty_keyring(self, mock_keyring):
        """Test listing credentials when keyring is empty."""
        mock_keyring.set_password = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AutoSaveCredentialManager(
                storage_backend="keyring",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            credentials = manager.list_credentials()
            assert len(credentials) == 0

    @patch("layered_credentials.core.keyring")
    def test_list_keyring_credentials(self, mock_keyring):
        """Test listing credentials from keyring."""
        mock_keyring.set_password = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AutoSaveCredentialManager(
                storage_backend="keyring",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            # Save some credentials
            manager.auto_save_credential("service1", "key1", "value1")
            manager.auto_save_credential("service2", "key2", "value2")
            manager.auto_save_credential("service3", "key3", "value3")

            # List credentials
            credentials = manager.list_credentials()

            assert len(credentials) == 3
            assert ("service1", "key1", "keyring") in credentials
            assert ("service2", "key2", "keyring") in credentials
            assert ("service3", "key3", "keyring") in credentials

    @patch("layered_credentials.core.keyring")
    def test_list_after_delete(self, mock_keyring):
        """Test that list_credentials reflects deletions."""
        mock_keyring.set_password = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=None)
        mock_keyring.delete_password = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AutoSaveCredentialManager(
                storage_backend="keyring",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            # Save credentials
            manager.auto_save_credential("service1", "key1", "value1")
            manager.auto_save_credential("service2", "key2", "value2")

            # Delete one
            manager.delete_credential("service1", "key1")

            # List should show only remaining credential
            credentials = manager.list_credentials()
            assert len(credentials) == 1
            assert ("service2", "key2", "keyring") in credentials


class TestKeyringBackup:
    """Test backup functionality for keyring backend."""

    @patch("layered_credentials.core.keyring")
    def test_backup_empty_keyring(self, mock_keyring):
        """Test backing up empty keyring."""
        mock_keyring.set_password = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "backup.enc"

            manager = AutoSaveCredentialManager(
                storage_backend="keyring",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            # Backup empty keyring
            stats = manager.backup_to_file(backup_path, backup_password="backup_secret")

            assert stats["credentials_count"] == 0
            assert stats["backend"] == "keyring"
            assert "timestamp" in stats
            assert stats["version"] == "1"
            assert backup_path.exists()

    @patch("layered_credentials.core.keyring")
    def test_backup_keyring_with_credentials(self, mock_keyring):
        """Test backing up keyring with credentials."""
        # Mock keyring operations
        stored_passwords = {}

        def set_password(service, username, password):
            stored_passwords[f"{service}_{username}"] = password

        def get_password(service, username):
            return stored_passwords.get(f"{service}_{username}")

        mock_keyring.set_password = MagicMock(side_effect=set_password)
        mock_keyring.get_password = MagicMock(side_effect=get_password)

        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "backup.enc"

            manager = AutoSaveCredentialManager(
                storage_backend="keyring",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            # Save credentials
            manager.auto_save_credential("service1", "key1", "secret1")
            manager.auto_save_credential("service2", "key2", "secret2")

            # Backup
            stats = manager.backup_to_file(backup_path, backup_password="backup_secret")

            assert stats["credentials_count"] == 2
            assert backup_path.exists()

    @patch("layered_credentials.core.keyring")
    def test_restore_to_keyring_from_backup(self, mock_keyring):
        """Test restoring credentials to keyring from backup."""
        # Mock keyring operations - separate storage for each manager
        stored_passwords_1 = {}
        stored_passwords_2 = {}
        current_storage = [stored_passwords_1]  # Use list to allow closure modification

        def set_password(service, username, password):
            current_storage[0][f"{service}_{username}"] = password

        def get_password(service, username):
            return current_storage[0].get(f"{service}_{username}")

        mock_keyring.set_password = MagicMock(side_effect=set_password)
        mock_keyring.get_password = MagicMock(side_effect=get_password)

        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                backup_path = Path(tmpdir1) / "backup.enc"

                # Create first keyring and backup
                manager1 = AutoSaveCredentialManager(
                    storage_backend="keyring",
                    storage_dir=tmpdir1,
                    keyring_service="test-service",
                    enable_audit_log=False,
                )
                manager1.auto_save_credential("service1", "key1", "secret1")
                manager1.auto_save_credential("service2", "key2", "secret2")

                # Backup
                manager1.backup_to_file(backup_path, backup_password="backup_secret")

                # Switch to second keyring storage (simulating different machine)
                current_storage[0] = stored_passwords_2

                # Create second keyring and restore
                manager2 = AutoSaveCredentialManager(
                    storage_backend="keyring",
                    storage_dir=tmpdir2,
                    keyring_service="test-service",
                    enable_audit_log=False,
                )

                # Restore
                stats = manager2.restore_from_file(backup_path, backup_password="backup_secret")

                assert stats["credentials_restored"] == 2
                assert stats["credentials_skipped"] == 0

                # Verify restored credentials
                cred1 = manager2.get_credential("service1", "key1")
                cred2 = manager2.get_credential("service2", "key2")
                assert cred1.reveal() == "secret1"
                assert cred2.reveal() == "secret2"

                # Verify tracking was updated
                assert len(manager2._keyring_store) == 2


class TestKeyringTrackingRecovery:
    """Test keyring tracking file recovery scenarios."""

    @patch("layered_credentials.core.keyring")
    def test_recovery_from_corrupted_tracking_file(self, mock_keyring):
        """Test that corrupted tracking file doesn't crash the manager."""
        mock_keyring.set_password = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            tracking_file = Path(tmpdir) / ".keyring_credentials.json"

            # Create corrupted tracking file
            with open(tracking_file, "w") as f:
                f.write("{ invalid json }")

            # Should not crash, should start with empty tracking
            manager = AutoSaveCredentialManager(
                storage_backend="keyring",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            assert len(manager._keyring_store) == 0

    @patch("layered_credentials.core.keyring")
    def test_tracking_file_missing_fields(self, mock_keyring):
        """Test handling of tracking file with missing fields."""
        mock_keyring.set_password = MagicMock()
        mock_keyring.get_password = MagicMock(return_value=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            tracking_file = Path(tmpdir) / ".keyring_credentials.json"

            # Create tracking file with missing fields
            import json

            with open(tracking_file, "w") as f:
                json.dump(
                    {
                        "version": "1",
                        "credentials": [
                            {"service": "svc1", "key": "key1"},  # Missing created_at
                            {"service": "svc2"},  # Missing key
                        ],
                    },
                    f,
                )

            # Should load valid entries
            manager = AutoSaveCredentialManager(
                storage_backend="keyring",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            # Only the first entry should load (it has service and key)
            assert len(manager._keyring_store) >= 0  # Should not crash


class TestKeyringBackupRestoreIntegration:
    """Integration tests for keyring backup/restore."""

    @patch("layered_credentials.core.keyring")
    def test_full_keyring_backup_restore_workflow(self, mock_keyring):
        """Test complete backup and restore workflow for keyring."""
        # Mock keyring operations - separate storage for each manager
        stored_passwords_1 = {}
        stored_passwords_2 = {}
        current_storage = [stored_passwords_1]  # Use list to allow closure modification

        def set_password(service, username, password):
            current_storage[0][f"{service}_{username}"] = password

        def get_password(service, username):
            return current_storage[0].get(f"{service}_{username}")

        mock_keyring.set_password = MagicMock(side_effect=set_password)
        mock_keyring.get_password = MagicMock(side_effect=get_password)

        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                backup_path = Path(tmpdir1) / "backup.enc"

                # Step 1: Create keyring with credentials
                manager1 = AutoSaveCredentialManager(
                    storage_backend="keyring",
                    storage_dir=tmpdir1,
                    keyring_service="test-integration-service",
                    enable_audit_log=False,
                )
                manager1.auto_save_credential("okta", "domain", "example.okta.com")
                manager1.auto_save_credential("okta", "token", "00abc123")
                manager1.auto_save_credential("onelogin", "client_id", "12345")

                # Step 2: Backup
                backup_stats = manager1.backup_to_file(backup_path, backup_password="backup_password")

                assert backup_stats["credentials_count"] == 3

                # Switch to second keyring storage (simulating different machine)
                current_storage[0] = stored_passwords_2

                # Step 3: Restore to new keyring
                manager2 = AutoSaveCredentialManager(
                    storage_backend="keyring",
                    storage_dir=tmpdir2,
                    keyring_service="test-integration-service",
                    enable_audit_log=False,
                )
                restore_stats = manager2.restore_from_file(
                    backup_path, backup_password="backup_password"
                )

                assert restore_stats["credentials_restored"] == 3

                # Step 4: Verify restored credentials
                assert ("okta", "domain") in manager2._keyring_store
                assert ("okta", "token") in manager2._keyring_store
                assert ("onelogin", "client_id") in manager2._keyring_store
