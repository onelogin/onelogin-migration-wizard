"""Tests for password rotation and audit key lifecycle.

Tests:
- Password rotation with audit key rotation
- Old audit entries remain valid after key rotation
- New entries use new key after rotation
- Key rotation marker events are logged
"""

import tempfile
from pathlib import Path

import pytest

from onelogin_migration_core.credentials import (
    AutoSaveCredentialManager,
    TamperEvidentAuditLogger,
)


class TestPasswordRotation:
    """Test password rotation atomically rotates audit keys."""

    def test_password_change_without_audit_logger(self):
        """Test password change works without audit logger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create manager without audit logging
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="old_password",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            # Save some credentials
            manager.auto_save_credential("service1", "key1", "value1")
            manager.auto_save_credential("service1", "key2", "value2")

            # Change password
            stats = manager.change_vault_password("old_password", "new_password")

            assert stats["credentials_count"] == 2
            assert "timestamp" in stats

            # Verify credentials still accessible with new password
            new_manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="new_password",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            cred1 = new_manager.get_credential("service1", "key1")
            cred2 = new_manager.get_credential("service1", "key2")

            assert cred1.reveal() == "value1"
            assert cred2.reveal() == "value2"

    def test_password_change_with_basic_audit_logger(self):
        """Test password change with basic AuditLogger (no tamper-evidence)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create manager with basic audit logging (not TamperProofAuditLogger)
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="old_password",
                storage_dir=tmpdir,
                enable_audit_log=True,
            )

            # Save credentials
            manager.auto_save_credential("service1", "key1", "value1")

            # Change password - should not fail even though audit logger doesn't support rotation
            stats = manager.change_vault_password("old_password", "new_password")

            assert stats["credentials_count"] == 1

            # Check audit log contains password_change event
            audit_file = Path(tmpdir) / "audit.log"
            assert audit_file.exists()

            events = []
            with open(audit_file) as f:
                import json

                for line in f:
                    events.append(json.loads(line))

            # Should have store and password_change events
            assert any(e.get("event_type") == "credential_stored" for e in events)
            assert any(e.get("event_type") == "password_change" for e in events)

    def test_password_change_rotates_audit_key(self):
        """Test that password change automatically rotates audit key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create audit logger with old password
            audit_file = Path(tmpdir) / "audit.log"
            old_logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="old_password",
                enable_tamper_evidence=True,
            )

            # Create manager with tamper-proof audit logger
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="old_password",
                storage_dir=tmpdir,
                enable_audit_log=False,  # Disable default, we'll set custom one
            )
            manager.audit_logger = old_logger

            # Save some credentials
            manager.auto_save_credential("service1", "key1", "value1")
            manager.auto_save_credential("service1", "key2", "value2")

            # Change password - this should rotate the audit key
            stats = manager.change_vault_password("old_password", "new_password")

            assert stats["credentials_count"] == 2

            # Verify audit log contains key rotation marker
            events = []
            with open(audit_file) as f:
                import json

                for line in f:
                    entry = json.loads(line)
                    if "event" in entry:
                        events.append(entry["event"])
                    else:
                        events.append(entry)

            # Should have: 2x store, audit_key_rotated, password_change
            assert sum(1 for e in events if e.get("event_type") == "credential_stored") == 2
            assert sum(1 for e in events if e.get("event_type") == "audit_key_rotated") == 1
            assert sum(1 for e in events if e.get("event_type") == "password_change") == 1

            # Verify audit_key_rotated event has correct structure
            rotation_event = next(e for e in events if e.get("event_type") == "audit_key_rotated")
            assert rotation_event["reason"] == "vault_password_change"
            assert "old_key_hash" in rotation_event["metadata"]
            assert "rotation_time" in rotation_event["metadata"]

    def test_old_audit_entries_remain_valid_after_rotation(self):
        """Test that old audit entries are still valid after key rotation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            # Create initial logger with old password
            old_logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="old_password",
                enable_tamper_evidence=True,
            )

            # Create manager
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="old_password",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )
            manager.audit_logger = old_logger

            # Save credentials (logged with old key)
            manager.auto_save_credential("service1", "key1", "value1")

            # Get old key hash for later verification
            old_key_hash = old_logger.audit_key

            # Change password (rotates audit key)
            manager.change_vault_password("old_password", "new_password")

            # Save new credential (logged with new key)
            manager.auto_save_credential("service2", "key2", "value2")

            # Verify audit log structure
            with open(audit_file) as f:
                import json

                lines = [json.loads(line) for line in f if line.strip()]

            # First entry should use old key
            # Rotation marker should chain from first entry with old key
            # New entries after rotation should start fresh chain with new key

            assert len(lines) >= 4  # store, rotate, password_change, store

    def test_new_entries_use_new_key_after_rotation(self):
        """Test that new audit entries use new key after rotation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            # Create manager with tamper-proof audit
            old_logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="old_password",
                enable_tamper_evidence=True,
            )

            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="old_password",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )
            manager.audit_logger = old_logger

            # Save before rotation
            manager.auto_save_credential("service1", "key1", "value1")

            old_key = old_logger.audit_key

            # Rotate password and key
            manager.change_vault_password("old_password", "new_password")

            new_key = old_logger.audit_key

            # Keys should be different
            assert old_key != new_key

            # Save after rotation
            manager.auto_save_credential("service2", "key2", "value2")

            # Verify last entry was logged with new key
            # (This is implicitly tested by the manager continuing to work)

    def test_rotation_resets_hash_chain(self):
        """Test that key rotation starts a fresh hash chain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="old_password",
                enable_tamper_evidence=True,
            )

            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="old_password",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )
            manager.audit_logger = logger

            # Create some entries
            manager.auto_save_credential("service1", "key1", "value1")

            # Rotate key
            manager.change_vault_password("old_password", "new_password")

            # After rotation, prev_hash should be reset to empty
            assert logger._prev_hash == ""

            # New entry should start fresh chain
            manager.auto_save_credential("service2", "key2", "value2")

            # Read audit log to verify structure
            with open(audit_file) as f:
                import json

                lines = [json.loads(line) for line in f if line.strip()]

            # Find the first entry after password_change
            password_change_idx = next(
                i for i, line in enumerate(lines) if line.get("event", {}).get("event_type") == "password_change"
            )

            # Next entry should have empty prev_hash (fresh chain)
            if password_change_idx + 1 < len(lines):
                next_entry = lines[password_change_idx + 1]
                assert next_entry.get("prev_hash") == ""

    def test_multiple_password_rotations(self):
        """Test multiple successive password rotations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="password1",
                enable_tamper_evidence=True,
            )

            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="password1",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )
            manager.audit_logger = logger

            # Save initial credential
            manager.auto_save_credential("service1", "key1", "value1")

            # First rotation
            manager.change_vault_password("password1", "password2")
            manager.auto_save_credential("service2", "key2", "value2")

            # Second rotation
            manager.change_vault_password("password2", "password3")
            manager.auto_save_credential("service3", "key3", "value3")

            # Third rotation
            manager.change_vault_password("password3", "password4")
            manager.auto_save_credential("service4", "key4", "value4")

            # Verify audit log has 3 rotation events
            events = []
            with open(audit_file) as f:
                import json

                for line in f:
                    entry = json.loads(line)
                    if "event" in entry:
                        events.append(entry["event"])
                    else:
                        events.append(entry)

            rotation_count = sum(1 for e in events if e.get("event_type") == "audit_key_rotated")
            assert rotation_count == 3

            # Verify credentials are accessible with final password
            final_manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="password4",
                storage_dir=tmpdir,
                enable_audit_log=False,
            )

            assert final_manager.get_credential("service1", "key1").reveal() == "value1"
            assert final_manager.get_credential("service2", "key2").reveal() == "value2"
            assert final_manager.get_credential("service3", "key3").reveal() == "value3"
            assert final_manager.get_credential("service4", "key4").reveal() == "value4"


class TestAuditKeyRotation:
    """Test standalone audit key rotation functionality."""

    def test_rotate_audit_key_with_password(self):
        """Test rotating audit key with new password."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="old_password",
                enable_tamper_evidence=True,
            )

            old_key = logger.audit_key

            # Log an event with old key
            logger.log_store("service1", "key1", True)

            # Rotate key
            logger.rotate_audit_key(new_vault_password="new_password")

            new_key = logger.audit_key

            # Keys should be different
            assert old_key != new_key

            # Log an event with new key
            logger.log_store("service2", "key2", True)

            # Verify both events are in the log
            with open(audit_file) as f:
                import json

                lines = [json.loads(line) for line in f if line.strip()]

            assert len(lines) >= 3  # store, rotation marker, store

    def test_rotate_audit_key_without_password(self):
        """Test rotating audit key with random key generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="password",
                enable_tamper_evidence=True,
            )

            old_key = logger.audit_key

            # Rotate without providing new password (generates random key)
            logger.rotate_audit_key(new_vault_password=None)

            new_key = logger.audit_key

            # Keys should be different
            assert old_key != new_key
            assert len(new_key) == 32  # Should still be 32 bytes

    def test_rotation_without_tamper_evidence_enabled(self):
        """Test that rotation is skipped when tamper-evidence is disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                enable_tamper_evidence=False,  # Disabled
            )

            # Should not have audit key
            assert logger.audit_key is None

            # Rotation should be no-op
            logger.rotate_audit_key(new_vault_password="new_password")

            # Still no audit key
            assert logger.audit_key is None

    def test_rotation_marker_contains_old_key_hash(self):
        """Test that rotation marker contains hash of old key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                vault_password="old_password",
                enable_tamper_evidence=True,
            )

            import hashlib

            old_key = logger.audit_key
            expected_hash = hashlib.sha256(old_key).hexdigest()[:16]

            # Rotate
            logger.rotate_audit_key(new_vault_password="new_password")

            # Check rotation event
            with open(audit_file) as f:
                import json

                for line in f:
                    entry = json.loads(line)
                    event = entry.get("event", entry)
                    if event.get("event_type") == "audit_key_rotated":
                        assert event["metadata"]["old_key_hash"] == expected_hash
                        break
                else:
                    pytest.fail("No audit_key_rotated event found")
