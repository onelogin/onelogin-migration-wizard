"""Tests for V3→V4 vault migration.

Tests:
- Successful migration from V3 to V4
- Backup creation
- Data integrity after migration
- Error handling (wrong password, already V4, etc.)
"""

import json
import tempfile
from pathlib import Path

from onelogin_migration_core.credentials import (
    Argon2VaultV3,
    AutoSaveCredentialManager,
)


class TestVaultMigration:
    """Test V3 to V4 vault migration."""

    def _create_v3_vault(self, storage_dir: str, password: str, credentials: dict) -> Path:
        """Helper to create a V3 format vault for testing."""
        vault_path = Path(storage_dir) / "vault.enc"
        counter_file = Path(storage_dir) / ".vault_counter"

        # Create vault instance
        vault = Argon2VaultV3(counter_file=counter_file)

        # Create vault data
        vault_data = {}
        for service, creds in credentials.items():
            vault_data[service] = {}
            for key, value in creds.items():
                vault_data[service][key] = {
                    "value": value,
                    "created": "2024-01-01T00:00:00",
                }

        # Encrypt with V3 format (use internal _decrypt_v3 backwards)
        # Actually, we need to manually create V3 format
        vault_json = json.dumps(vault_data)

        # Manually create V3 format encrypted data
        import base64
        import secrets
        from argon2.low_level import Type, hash_secret_raw
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        # Generate V3 format encryption
        salt = secrets.token_bytes(32)
        nonce = secrets.token_bytes(12)

        # Derive key
        key = hash_secret_raw(
            secret=password.encode("utf-8"),
            salt=salt,
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
            hash_len=32,
            type=Type.ID,
        )

        # Encrypt
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, vault_json.encode("utf-8"), None)

        # Create V3 format structure
        encrypted_v3 = {
            "version": "3",
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "counter": 1,  # V3 has counter outside
        }

        # Write to file
        with open(vault_path, "w") as f:
            json.dump(encrypted_v3, f, indent=2)

        # Also write counter file
        counter_file.write_text("1")

        return vault_path

    def test_migrate_v3_to_v4_basic(self):
        """Test basic migration from V3 to V4."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create V3 vault
            credentials = {
                "service1": {"key1": "value1", "key2": "value2"},
                "service2": {"key3": "value3"},
            }

            vault_path = self._create_v3_vault(tmpdir, "test_password", credentials)

            # Verify it's V3
            with open(vault_path) as f:
                data = json.load(f)
            assert data["version"] == "3"

            # Create manager and migrate
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="test_password",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            stats = manager.migrate_vault_v3_to_v4("test_password")

            # Verify migration stats
            assert stats["credentials_count"] == 3
            assert stats["old_format"] == "V3"
            assert stats["new_format"] == "V4"
            assert "timestamp" in stats
            assert "backup_path" in stats

            # Verify vault is now V4
            with open(vault_path) as f:
                data = json.load(f)
            assert data["version"] == "4"

            # Verify data integrity - all credentials should still be accessible
            cred1 = manager.get_credential("service1", "key1")
            cred2 = manager.get_credential("service1", "key2")
            cred3 = manager.get_credential("service2", "key3")

            assert cred1.reveal() == "value1"
            assert cred2.reveal() == "value2"
            assert cred3.reveal() == "value3"

    def test_migration_creates_backup(self):
        """Test that migration creates a backup file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials = {"service1": {"key1": "value1"}}
            vault_path = self._create_v3_vault(tmpdir, "test_password", credentials)

            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="test_password",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            stats = manager.migrate_vault_v3_to_v4("test_password", create_backup=True)

            # Verify backup was created
            assert "backup_path" in stats
            backup_path = Path(stats["backup_path"])
            assert backup_path.exists()
            assert "vault.enc.v3.backup" in backup_path.name

            # Verify backup is V3 format
            with open(backup_path) as f:
                backup_data = json.load(f)
            assert backup_data["version"] == "3"

    def test_migration_without_backup(self):
        """Test migration without creating backup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials = {"service1": {"key1": "value1"}}
            self._create_v3_vault(tmpdir, "test_password", credentials)

            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="test_password",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            stats = manager.migrate_vault_v3_to_v4("test_password", create_backup=False)

            # Verify no backup in stats
            assert "backup_path" not in stats

            # Verify no backup files created
            backup_files = list(Path(tmpdir).glob("vault.enc.v3.backup.*"))
            assert len(backup_files) == 0

    def test_migration_already_v4_raises_error(self):
        """Test that migrating an already V4 vault raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create V4 vault (default for new vaults)
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="test_password",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            # Save some data (creates V4 vault)
            manager.auto_save_credential("service1", "key1", "value1")

            # Try to migrate - should fail
            try:
                manager.migrate_vault_v3_to_v4("test_password")
                assert False, "Should have raised ValueError"
            except ValueError as e:
                assert "already in format V4" in str(e)

    def test_migration_wrong_password_raises_error(self):
        """Test that migration with wrong password fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials = {"service1": {"key1": "value1"}}
            self._create_v3_vault(tmpdir, "correct_password", credentials)

            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="correct_password",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            # Try to migrate with wrong password
            try:
                manager.migrate_vault_v3_to_v4("wrong_password")
                assert False, "Should have raised ValueError"
            except ValueError as e:
                assert "Failed to decrypt" in str(e)

    def test_migration_preserves_all_credentials(self):
        """Test that migration preserves all credentials."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create vault with many credentials
            credentials = {
                f"service{i}": {
                    f"key{j}": f"value{i}_{j}"
                    for j in range(3)
                }
                for i in range(5)
            }

            self._create_v3_vault(tmpdir, "test_password", credentials)

            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="test_password",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            stats = manager.migrate_vault_v3_to_v4("test_password")

            # Should have migrated all 15 credentials (5 services × 3 keys)
            assert stats["credentials_count"] == 15

            # Verify all credentials are accessible
            for i in range(5):
                for j in range(3):
                    cred = manager.get_credential(f"service{i}", f"key{j}")
                    assert cred is not None
                    assert cred.reveal() == f"value{i}_{j}"

    def test_migration_non_vault_backend_raises_error(self):
        """Test that migration on non-vault backend raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AutoSaveCredentialManager(
                storage_backend="keyring",  # Not vault
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            try:
                manager.migrate_vault_v3_to_v4("test_password")
                assert False, "Should have raised ValueError"
            except ValueError as e:
                assert "only supported for vault backend" in str(e)

    def test_migration_nonexistent_vault_raises_error(self):
        """Test that migrating nonexistent vault raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="test_password",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            # No vault file exists yet
            try:
                manager.migrate_vault_v3_to_v4("test_password")
                assert False, "Should have raised ValueError"
            except ValueError as e:
                assert "does not exist" in str(e)

    def test_migration_logs_audit_event(self):
        """Test that migration logs an audit event."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            credentials = {"service1": {"key1": "value1"}}
            self._create_v3_vault(tmpdir, "test_password", credentials)

            # Create manager with audit logging
            from onelogin_migration_core.credentials import TamperEvidentAuditLogger

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="test_password",
                enable_tamper_evidence=True,
            )

            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="test_password",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )
            manager.audit_logger = logger

            # Perform migration
            manager.migrate_vault_v3_to_v4("test_password")

            # Verify audit event was logged
            events = []
            with open(audit_file) as f:
                for line in f:
                    entry = json.loads(line)
                    if "event" in entry:
                        events.append(entry["event"])
                    else:
                        events.append(entry)

            # Should have vault_migration event
            migration_events = [e for e in events if e.get("event_type") == "vault_migration"]
            assert len(migration_events) == 1

            event = migration_events[0]
            assert event["old_format"] == "V3"
            assert event["new_format"] == "V4"
            assert event["credentials_count"] == 1
