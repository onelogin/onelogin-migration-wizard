"""
Tests for backup/restore and password rotation features.

This module tests:
- backup_to_file() functionality
- restore_from_file() functionality
- change_vault_password() functionality
- Error handling and edge cases
"""

import json
import tempfile
from pathlib import Path

import pytest

from onelogin_migration_core.credentials import AutoSaveCredentialManager


class TestBackupRestore:
    """Test backup and restore functionality."""

    def test_backup_empty_vault(self):
        """Test backing up an empty vault."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "backup.enc"

            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="vault_secret",
                storage_dir=tmpdir,
                enable_audit_log=False
            )

            # Backup empty vault
            stats = manager.backup_to_file(
                backup_path, backup_password="backup_secret", vault_password="vault_secret"
            )

            assert stats["credentials_count"] == 0
            assert stats["backend"] == "vault"
            assert "timestamp" in stats
            assert stats["version"] == "1"
            assert backup_path.exists()

    def test_backup_with_credentials(self):
        """Test backing up vault with credentials."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "backup.enc"

            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="vault_secret",
                storage_dir=tmpdir,
                enable_audit_log=False
            )

            # Add some credentials
            manager.auto_save_credential("service1", "key1", "secret1")
            manager.auto_save_credential("service2", "key2", "secret2")
            manager.auto_save_credential("service3", "key3", "secret3")

            # Backup
            stats = manager.backup_to_file(
                backup_path, backup_password="backup_secret", vault_password="vault_secret"
            )

            assert stats["credentials_count"] == 3
            assert backup_path.exists()

    def test_restore_from_backup(self):
        """Test restoring credentials from backup."""
        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                backup_path = Path(tmpdir1) / "backup.enc"

                # Create first vault with credentials
                manager1 = AutoSaveCredentialManager(
                    storage_backend="vault",
                    vault_password="vault_secret",
                    storage_dir=tmpdir1,
                    enable_audit_log=False
                )
                manager1.auto_save_credential("service1", "key1", "secret1")
                manager1.auto_save_credential("service2", "key2", "secret2")

                # Backup
                manager1.backup_to_file(
                    backup_path, backup_password="backup_secret", vault_password="vault_secret"
                )

                # Restore to new vault
                manager2 = AutoSaveCredentialManager(
                    storage_backend="vault",
                    vault_password="vault_secret",
                    storage_dir=tmpdir2,
                    enable_audit_log=False
                )
                stats = manager2.restore_from_file(
                    backup_path, backup_password="backup_secret", vault_password="vault_secret"
                )

                assert stats["credentials_restored"] == 2
                assert stats["credentials_skipped"] == 0

                # Verify restored credentials
                cred1 = manager2.get_credential("service1", "key1")
                cred2 = manager2.get_credential("service2", "key2")
                assert cred1.reveal() == "secret1"
                assert cred2.reveal() == "secret2"

    def test_restore_skips_existing_credentials(self):
        """Test that restore skips credentials that already exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "backup.enc"

            # Create vault with credentials
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="vault_secret",
                storage_dir=tmpdir,
                enable_audit_log=False
            )
            manager.auto_save_credential("service1", "key1", "original")
            manager.auto_save_credential("service2", "key2", "secret2")

            # Backup
            manager.backup_to_file(
                backup_path, backup_password="backup_secret", vault_password="vault_secret"
            )

            # Modify one credential
            manager.auto_save_credential("service1", "key1", "modified")

            # Restore (should skip both since they exist)
            stats = manager.restore_from_file(
                backup_path, backup_password="backup_secret", vault_password="vault_secret"
            )

            assert stats["credentials_restored"] == 0
            assert stats["credentials_skipped"] == 2

            # Verify modified credential wasn't overwritten
            cred1 = manager.get_credential("service1", "key1")
            assert cred1.reveal() == "modified"

    def test_backup_memory_backend_warns(self, caplog):
        """Test that backing up memory backend produces warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "backup.enc"

            manager = AutoSaveCredentialManager(
                storage_backend="memory",
                enable_audit_log=False
            )

            stats = manager.backup_to_file(
                backup_path, backup_password="backup_secret"
            )

            assert stats["credentials_count"] == 0
            assert "not persisted" in caplog.text


class TestPasswordRotation:
    """Test password rotation functionality."""

    def test_change_vault_password(self):
        """Test changing vault password."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create vault with old password
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="old_password",
                storage_dir=tmpdir,
                enable_audit_log=False
            )
            manager.auto_save_credential("service1", "key1", "secret1")
            manager.auto_save_credential("service2", "key2", "secret2")

            # Change password
            stats = manager.change_vault_password("old_password", "new_password")

            assert stats["credentials_count"] == 2
            assert "timestamp" in stats

            # Verify vault is re-encrypted with new password
            from onelogin_migration_core.credentials import Argon2VaultV3

            vault_path = Path(tmpdir) / "vault.enc"
            counter_file = Path(tmpdir) / ".vault_counter"
            with open(vault_path) as f:
                encrypted = json.load(f)

            vault = Argon2VaultV3(counter_file=counter_file)
            # Old password should fail
            with pytest.raises(ValueError):
                vault.decrypt(encrypted, "old_password")

            # New password should work
            plaintext = vault.decrypt(encrypted, "new_password")
            vault_data = json.loads(plaintext)
            assert len(vault_data) == 2  # 2 services

    def test_change_password_wrong_old_password(self):
        """Test that changing password fails with wrong old password."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create vault
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="correct_password",
                storage_dir=tmpdir,
                enable_audit_log=False
            )
            manager.auto_save_credential("service1", "key1", "secret1")

            # Try to change with wrong old password
            with pytest.raises(ValueError, match="Failed to decrypt with old password"):
                manager.change_vault_password("wrong_password", "new_password")

    def test_change_password_requires_vault_backend(self):
        """Test that password change requires vault backend."""
        manager = AutoSaveCredentialManager(
            storage_backend="memory",
            enable_audit_log=False
        )

        with pytest.raises(ValueError, match="only supported for vault backend"):
            manager.change_vault_password("old", "new")

    def test_change_password_nonexistent_vault(self):
        """Test that password change fails if vault doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="password",
                storage_dir=tmpdir,
                enable_audit_log=False
            )

            # Don't save any credentials (vault file won't exist)
            with pytest.raises(ValueError, match="does not exist"):
                manager.change_vault_password("old", "new")

    def test_change_password_preserves_credentials(self):
        """Test that password change preserves all credentials."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create vault with multiple credentials
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="old_password",
                storage_dir=tmpdir,
                enable_audit_log=False
            )
            credentials = {
                ("svc1", "key1"): "secret1",
                ("svc2", "key2"): "secret2",
                ("svc3", "key3"): "secret3",
            }

            for (service, key), secret in credentials.items():
                manager.auto_save_credential(service, key, secret)

            # Change password
            stats = manager.change_vault_password("old_password", "new_password")

            assert stats["credentials_count"] == 3

            # Verify all credentials are still accessible
            from onelogin_migration_core.credentials import Argon2VaultV3

            vault_path = Path(tmpdir) / "vault.enc"
            counter_file = Path(tmpdir) / ".vault_counter"
            with open(vault_path) as f:
                encrypted = json.load(f)

            vault = Argon2VaultV3(counter_file=counter_file)
            plaintext = vault.decrypt(encrypted, "new_password")
            vault_data = json.loads(plaintext)

            assert len(vault_data) == 3  # 3 services


class TestBackupRestoreIntegration:
    """Integration tests for backup/restore workflow."""

    def test_full_backup_restore_workflow(self):
        """Test complete backup and restore workflow."""
        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                backup_path = Path(tmpdir1) / "backup.enc"

                # Step 1: Create vault with credentials
                manager1 = AutoSaveCredentialManager(
                    storage_backend="vault",
                    vault_password="password1",
                    storage_dir=tmpdir1,
                    enable_audit_log=False
                )
                manager1.auto_save_credential("okta", "domain", "example.okta.com")
                manager1.auto_save_credential("okta", "token", "00abc123")
                manager1.auto_save_credential("onelogin", "client_id", "12345")

                # Step 2: Backup
                backup_stats = manager1.backup_to_file(
                    backup_path, backup_password="backup_password", vault_password="password1"
                )

                assert backup_stats["credentials_count"] == 3

                # Step 3: Restore to new vault
                manager2 = AutoSaveCredentialManager(
                    storage_backend="vault",
                    vault_password="password2",
                    storage_dir=tmpdir2,
                    enable_audit_log=False
                )
                restore_stats = manager2.restore_from_file(
                    backup_path, backup_password="backup_password", vault_password="password2"
                )

                assert restore_stats["credentials_restored"] == 3

                # Step 4: Verify restored credentials
                from onelogin_migration_core.credentials import Argon2VaultV3

                vault_path = Path(tmpdir2) / "vault.enc"
                counter_file = Path(tmpdir2) / ".vault_counter"
                with open(vault_path) as f:
                    encrypted = json.load(f)

                vault = Argon2VaultV3(counter_file=counter_file)
                plaintext = vault.decrypt(encrypted, "password2")
                vault_data = json.loads(plaintext)

                # vault_data is {service: {key: {...}}} format
                assert "okta" in vault_data
                assert "onelogin" in vault_data
                assert "domain" in vault_data["okta"]
                assert "token" in vault_data["okta"]
                assert "client_id" in vault_data["onelogin"]

    def test_backup_password_rotation_restore(self):
        """Test backup, password rotation, and restore workflow."""
        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                backup_path = Path(tmpdir1) / "backup.enc"

                # Create vault
                manager = AutoSaveCredentialManager(
                    storage_backend="vault",
                    vault_password="password1",
                    storage_dir=tmpdir1,
                    enable_audit_log=False
                )
                manager.auto_save_credential("service1", "key1", "secret1")

                # Backup with password1
                manager.backup_to_file(
                    backup_path, backup_password="backup_password", vault_password="password1"
                )

                # Change vault password
                manager.change_vault_password("password1", "password2")

                # Verify can still restore backup (backup is independent)
                manager2 = AutoSaveCredentialManager(
                    storage_backend="vault",
                    vault_password="password3",
                    storage_dir=tmpdir2,
                    enable_audit_log=False
                )
                stats = manager2.restore_from_file(
                    backup_path, backup_password="backup_password", vault_password="password3"
                )

                assert stats["credentials_restored"] == 1
