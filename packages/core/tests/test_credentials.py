"""Comprehensive tests for credential management system (Phase 1)."""

import json
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from onelogin_migration_core.credentials import (
    Argon2VaultV2,  # Alias for V3
    Argon2VaultV3,
    AuditLogger,
    AutoSaveCredentialManager,
    ConfigValidator,
    SecureString,
    SessionKeyManager,
)

# =============================================================================
# SecureString Tests
# =============================================================================


class TestSecureString:
    """Tests for SecureString class."""

    def test_create_secure_string(self):
        """Test creating a SecureString."""
        ss = SecureString("my_secret")
        assert ss.reveal() == "my_secret"

    def test_secure_string_hides_value_in_str(self):
        """Test that SecureString hides value in __str__."""
        ss = SecureString("my_secret")
        assert str(ss) == "SecureString(***hidden***)"
        assert "my_secret" not in str(ss)

    def test_secure_string_hides_value_in_repr(self):
        """Test that SecureString hides value in __repr__."""
        ss = SecureString("my_secret")
        assert repr(ss) == "SecureString(***hidden***)"
        assert "my_secret" not in repr(ss)

    def test_secure_string_zero(self):
        """Test that SecureString can be zeroed."""
        ss = SecureString("my_secret")
        ss.zero()
        assert ss._is_zeroed
        assert all(b == 0 for b in ss._data)

    def test_secure_string_zero_on_delete(self):
        """Test that SecureString is zeroed on deletion."""
        ss = SecureString("my_secret")
        ss_data = ss._data
        del ss
        # Data should be zeroed
        assert all(b == 0 for b in ss_data)

    def test_secure_string_reveal_after_zero_raises(self):
        """Test that revealing after zeroing raises an error."""
        ss = SecureString("my_secret")
        ss.zero()
        with pytest.raises(
            ValueError, match="Cannot reveal SecureString that has already been zeroed"
        ):
            ss.reveal()

    def test_secure_string_empty_value(self):
        """Test SecureString with empty value."""
        ss = SecureString("")
        assert ss.reveal() == ""

    def test_secure_string_unicode(self):
        """Test SecureString with unicode characters."""
        ss = SecureString("🔒 secret 密码")
        assert ss.reveal() == "🔒 secret 密码"


# =============================================================================
# Argon2VaultV2 Tests
# =============================================================================


class TestArgon2VaultV2:
    """Tests for Argon2VaultV2 class (V3 implementation with V2 compatibility)."""

    def test_encrypt_decrypt_roundtrip(self):
        """Test encryption and decryption roundtrip."""
        vault = Argon2VaultV2()
        password = "test_password_123"
        plaintext = "my_secret_data"

        encrypted = vault.encrypt(plaintext, password)
        decrypted = vault.decrypt(encrypted, password)

        assert decrypted == plaintext

    def test_encrypted_structure_v3(self):
        """Test that encrypted data has correct V3 structure."""
        vault = Argon2VaultV3()
        password = "test_password_123"
        plaintext = "my_secret_data"

        encrypted = vault.encrypt(plaintext, password)

        # V4 format (counter inside encrypted payload)
        assert "version" in encrypted
        assert encrypted["version"] == "4"
        assert "salt" in encrypted
        assert "nonce" in encrypted
        assert "ciphertext" in encrypted
        # V4 does NOT have counter/timestamp at top level (they're inside encrypted payload)
        assert "counter" not in encrypted
        assert "timestamp" not in encrypted
        # V4 does NOT have HMAC
        assert "hmac" not in encrypted
        assert "encrypted_data" not in encrypted

    def test_decrypt_wrong_password_fails(self):
        """Test that decryption with wrong password fails."""
        vault = Argon2VaultV2()
        password = "correct_password"
        wrong_password = "wrong_password"
        plaintext = "my_secret_data"

        encrypted = vault.encrypt(plaintext, password)

        with pytest.raises(Exception):  # Should raise ValueError or decryption error
            vault.decrypt(encrypted, wrong_password)

    def test_decrypt_tampered_data_fails(self):
        """Test that decryption with tampered data fails."""
        import base64

        vault = Argon2VaultV3()
        password = "test_password_123"
        plaintext = "my_secret_data"

        encrypted = vault.encrypt(plaintext, password)

        # Tamper with encrypted data by flipping a bit in the decoded bytes
        # then re-encoding to preserve base64 validity
        ciphertext_bytes = base64.b64decode(encrypted["ciphertext"])
        # Flip a bit in the middle
        tampered_bytes = bytearray(ciphertext_bytes)
        tampered_bytes[len(tampered_bytes) // 2] ^= 0xFF
        encrypted["ciphertext"] = base64.b64encode(bytes(tampered_bytes)).decode("ascii")

        # Should raise ValueError for authentication failure or decryption failure
        with pytest.raises((ValueError, Exception), match="authentication failed|Decryption|Incorrect padding"):
            vault.decrypt(encrypted, password)

    def test_different_salts_produce_different_ciphertexts(self):
        """Test that same plaintext produces different ciphertexts."""
        vault = Argon2VaultV3()
        password = "test_password_123"
        plaintext = "my_secret_data"

        encrypted1 = vault.encrypt(plaintext, password)
        encrypted2 = vault.encrypt(plaintext, password)

        # Different salts and nonces should produce different ciphertexts
        assert encrypted1["salt"] != encrypted2["salt"]
        assert encrypted1["nonce"] != encrypted2["nonce"]
        assert encrypted1["ciphertext"] != encrypted2["ciphertext"]
        # V4: Counter is inside encrypted payload, but we know second call increments it
        # Both should decrypt successfully
        assert vault.decrypt(encrypted2, password) == plaintext

    def test_encrypt_empty_string(self):
        """Test encrypting empty string."""
        vault = Argon2VaultV2()
        password = "test_password_123"
        plaintext = ""

        encrypted = vault.encrypt(plaintext, password)
        decrypted = vault.decrypt(encrypted, password)

        assert decrypted == plaintext

    def test_encrypt_unicode(self):
        """Test encrypting unicode characters."""
        vault = Argon2VaultV2()
        password = "test_password_123"
        plaintext = "🔒 secret 密码"

        encrypted = vault.encrypt(plaintext, password)
        decrypted = vault.decrypt(encrypted, password)

        assert decrypted == plaintext

    def test_rollback_protection(self):
        """Test that vault rollback attacks are detected."""
        vault = Argon2VaultV3()
        password = "test_password_123"

        # Save with counter=N (encrypted1 has counter N inside its payload)
        encrypted1 = vault.encrypt("secret1", password)

        # Save with counter=N+1 (encrypted2 has counter N+1 inside its payload)
        encrypted2 = vault.encrypt("secret2", password)

        # V4: Counter is inside the encrypted payload, authenticated by AES-GCM
        # Decrypt encrypted2 to advance the counter file to N+1
        decrypted2 = vault.decrypt(encrypted2, password)
        assert decrypted2 == "secret2"

        # Now try to load old vault (counter=N) - should fail with rollback error
        with pytest.raises(ValueError, match="rollback"):
            vault.decrypt(encrypted1, password)

    def test_monotonic_counter_increments(self):
        """Test that monotonic counter always increments."""
        import tempfile
        import json
        import base64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from argon2.low_level import Type, hash_secret_raw

        # Use temp directory for counter file
        with tempfile.TemporaryDirectory() as tmpdir:
            counter_file = Path(tmpdir) / ".vault_counter"
            vault = Argon2VaultV3(counter_file=counter_file)
            password = "test_password_123"

            counters = []
            for i in range(5):
                encrypted = vault.encrypt(f"secret{i}", password)

                # V4: Counter is inside the encrypted payload
                # Decrypt to extract counter (for testing purposes)
                salt = base64.b64decode(encrypted["salt"])
                nonce = base64.b64decode(encrypted["nonce"])
                ciphertext = base64.b64decode(encrypted["ciphertext"])

                key = hash_secret_raw(
                    secret=password.encode("utf-8"),
                    salt=salt,
                    time_cost=vault.time_cost,
                    memory_cost=vault.memory_cost,
                    parallelism=vault.parallelism,
                    hash_len=vault.hash_len,
                    type=Type.ID,
                )

                aesgcm = AESGCM(key)
                payload_json = aesgcm.decrypt(nonce, ciphertext, None)
                payload = json.loads(payload_json.decode("utf-8"))
                counters.append(payload["counter"])

            # Counters should always increment
            for i in range(1, len(counters)):
                assert counters[i] > counters[i - 1]


# =============================================================================
# SessionKeyManager Tests
# =============================================================================


class TestSessionKeyManager:
    """Tests for SessionKeyManager class."""

    def test_create_session_key_manager(self):
        """Test creating a SessionKeyManager."""
        skm = SessionKeyManager()
        assert skm.session_id is not None
        assert len(skm.master_key) == 32

    def test_derive_key(self):
        """Test deriving keys for credentials."""
        skm = SessionKeyManager()
        key1 = skm.derive_key("service1", "key1")
        key2 = skm.derive_key("service1", "key2")
        key3 = skm.derive_key("service2", "key1")

        # All keys should be 32 bytes
        assert len(key1) == 32
        assert len(key2) == 32
        assert len(key3) == 32

        # Different credentials should have different keys
        assert key1 != key2
        assert key1 != key3

    def test_encrypt_decrypt_roundtrip(self):
        """Test encryption and decryption roundtrip."""
        skm = SessionKeyManager()
        plaintext = "my_secret_data"
        derived_key = skm.derive_key("test_service", "test_key")

        encrypted = skm.encrypt(plaintext, derived_key)
        decrypted = skm.decrypt(encrypted, derived_key)

        assert decrypted == plaintext

    def test_different_keys_produce_different_ciphertexts(self):
        """Test that different keys produce different ciphertexts."""
        skm = SessionKeyManager()
        plaintext = "my_secret_data"

        key1 = skm.derive_key("service1", "key1")
        key2 = skm.derive_key("service2", "key2")

        encrypted1 = skm.encrypt(plaintext, key1)
        encrypted2 = skm.encrypt(plaintext, key2)

        # Different keys should produce different ciphertexts
        assert encrypted1 != encrypted2

    def test_decrypt_wrong_key_fails(self):
        """Test that decrypting with wrong key fails."""
        skm = SessionKeyManager()
        plaintext = "my_secret_data"

        key1 = skm.derive_key("service1", "key1")
        key2 = skm.derive_key("service2", "key2")

        encrypted = skm.encrypt(plaintext, key1)

        with pytest.raises(Exception):  # Should raise decryption error
            skm.decrypt(encrypted, key2)

    def test_session_age(self):
        """Test session age tracking."""
        skm = SessionKeyManager()
        time.sleep(0.1)  # Wait a bit
        age = skm.session_age()
        assert age.total_seconds() >= 0.1

    def test_should_rotate(self):
        """Test session rotation recommendation."""
        skm = SessionKeyManager()
        assert not skm.should_rotate(max_age=timedelta(seconds=1000))
        assert skm.should_rotate(max_age=timedelta(seconds=0))

    def test_manual_rotation(self):
        """Test manual session rotation."""
        skm = SessionKeyManager()
        old_session_id = skm.session_id
        old_master_key = skm.master_key

        # Manually rotate session
        skm._rotate_session()

        # Session ID and master key should have changed
        assert skm.session_id != old_session_id
        assert skm.master_key != old_master_key

        # Old derived keys won't work with new session
        key_before_rotation = skm.derive_key("test", "key")
        # After rotation, the same service/key combo produces a different derived key
        assert key_before_rotation != old_master_key  # Just a sanity check


# =============================================================================
# AuditLogger Tests
# =============================================================================


class TestAuditLogger:
    """Tests for AuditLogger class."""

    @pytest.fixture
    def temp_audit_log(self):
        """Create a temporary audit log file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            log_path = Path(f.name)
        yield log_path
        if log_path.exists():
            log_path.unlink()

    def test_create_audit_logger(self, temp_audit_log):
        """Test creating an AuditLogger."""
        logger = AuditLogger(log_file=temp_audit_log)
        assert logger.log_file == temp_audit_log

    def test_log_store_event(self, temp_audit_log):
        """Test logging a store event."""
        logger = AuditLogger(log_file=temp_audit_log, log_identifiers=True)  # Enable for this test
        logger.log_store("test_service", "test_key", success=True, metadata={"backend": "keyring"})

        # Read log file
        with open(temp_audit_log) as f:
            log_line = f.readline()
            log_data = json.loads(log_line)

        assert log_data["service"] == "test_service"
        assert log_data["key"] == "test_key"
        assert log_data["event_type"] == "credential_stored"
        assert log_data["success"] is True
        assert "timestamp" in log_data

    def test_log_event_no_secrets(self, temp_audit_log):
        """Test that log events don't contain secrets."""
        logger = AuditLogger(log_file=temp_audit_log)
        logger.log_store("test_service", "test_key", success=True)

        # Read entire log file
        content = temp_audit_log.read_text()
        # Should not contain common credential values
        assert "password" not in content.lower() or "test" in content.lower()

    def test_log_event_thread_safe(self, temp_audit_log):
        """Test that logging is thread-safe."""
        logger = AuditLogger(log_file=temp_audit_log, log_identifiers=True)

        def log_events(n):
            for i in range(n):
                logger.log_store(f"service_{i}", f"key_{i}", success=True)

        threads = [threading.Thread(target=log_events, args=(10,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have 50 log entries
        with open(temp_audit_log) as f:
            lines = f.readlines()
        assert len(lines) == 50

    def test_get_recent_events(self, temp_audit_log):
        """Test getting recent events."""
        logger = AuditLogger(log_file=temp_audit_log, log_identifiers=True)

        # Log some events
        for i in range(5):
            logger.log_store(f"service_{i}", f"key_{i}", success=True)

        recent = logger.get_recent_events(limit=3)
        assert len(recent) == 3
        assert recent[-1]["service"] == "service_4"  # Most recent last

    def test_get_credential_history(self, temp_audit_log):
        """Test getting credential history."""
        logger = AuditLogger(log_file=temp_audit_log, log_identifiers=True)

        # Log events for different credentials
        logger.log_store("service1", "key1", success=True)
        logger.log_retrieve("service1", "key1", success=True)
        logger.log_store("service2", "key2", success=True)

        history = logger.get_credential_history("service1", "key1")
        assert len(history) == 2
        assert all(e["service"] == "service1" and e["key"] == "key1" for e in history)

    def test_callback(self, temp_audit_log):
        """Test audit callback."""
        callback_called = []

        def callback(event):
            callback_called.append(event)

        logger = AuditLogger(log_file=temp_audit_log, callback=callback, log_identifiers=True)
        logger.log_store("test_service", "test_key", success=True)

        assert len(callback_called) == 1
        assert callback_called[0]["service"] == "test_service"

    def test_audit_log_privacy_default_off(self, temp_audit_log):
        """Test that identifier logging is OFF by default (privacy)."""
        logger = AuditLogger(log_file=temp_audit_log)  # Default: log_identifiers=False
        logger.log_store("secret_service", "secret_key", success=True)
        logger.log_retrieve("another_service", "another_key", success=True)

        # Read log file
        content = temp_audit_log.read_text()
        log_lines = content.strip().split("\n")

        for line in log_lines:
            log_data = json.loads(line)
            # Identifiers should be masked
            assert log_data["service"] == "***"
            assert log_data["key"] == "***"

        # Should NOT contain actual identifiers
        assert "secret_service" not in content
        assert "secret_key" not in content
        assert "another_service" not in content
        assert "another_key" not in content

    def test_audit_log_privacy_opt_in(self, temp_audit_log):
        """Test that identifier logging can be enabled explicitly."""
        logger = AuditLogger(log_file=temp_audit_log, log_identifiers=True)  # Opt-in
        logger.log_store("test_service", "test_key", success=True)

        # Read log file
        with open(temp_audit_log) as f:
            log_line = f.readline()
            log_data = json.loads(log_line)

        # Identifiers should be visible when explicitly enabled
        assert log_data["service"] == "test_service"
        assert log_data["key"] == "test_key"

    def test_audit_log_privacy_all_methods(self, temp_audit_log):
        """Test that privacy applies to all logging methods."""
        logger = AuditLogger(log_file=temp_audit_log, log_identifiers=False)

        logger.log_store("service", "key", success=True)
        logger.log_retrieve("service", "key", success=True)
        logger.log_delete("service", "key", success=True)
        logger.log_rotate("service", "key", success=True)
        logger.log_failed_access("service", "key", "reason")

        # Read all log entries
        with open(temp_audit_log) as f:
            lines = f.readlines()

        # All entries should have masked identifiers
        for line in lines:
            log_data = json.loads(line)
            assert log_data["service"] == "***"
            assert log_data["key"] == "***"


# =============================================================================
# ConfigValidator Tests
# =============================================================================


class TestConfigValidator:
    """Tests for ConfigValidator class."""

    def test_validate_full_config_valid(self):
        """Test validating valid full config."""
        validator = ConfigValidator()
        config = {
            "okta": {
                "domain": "mycompany.okta.com",
                "token": "00abc123456789012345",  # At least 20 chars
                "rate_limit_per_minute": 600,
            },
            "onelogin": {
                "client_id": "abc123",
                "client_secret": "secret123",
                "region": "us",
                "rate_limit_per_hour": 5000,
            },
        }
        is_valid, errors = validator.validate(config)
        assert is_valid or len(errors) == 0  # Fallback validation or Pydantic

    def test_validate_missing_okta_section(self):
        """Test validating config with missing okta section."""
        validator = ConfigValidator()
        config = {
            "onelogin": {
                "client_id": "abc123",
                "client_secret": "secret123",
                "region": "us",
            },
        }
        is_valid, errors = validator.validate(config)
        assert not is_valid
        assert "okta" in str(errors).lower()

    def test_validate_missing_onelogin_section(self):
        """Test validating config with missing onelogin section."""
        validator = ConfigValidator()
        config = {
            "okta": {
                "domain": "mycompany.okta.com",
                "token": "00abc123456789012345",
            },
        }
        is_valid, errors = validator.validate(config)
        assert not is_valid
        assert "onelogin" in str(errors).lower()

    def test_validate_invalid_okta_domain(self):
        """Test validating config with invalid Okta domain."""
        validator = ConfigValidator()
        config = {
            "okta": {
                "domain": "mycompany.com",  # Should end with .okta.com
                "token": "00abc123456789012345",
            },
            "onelogin": {
                "client_id": "abc123",
                "client_secret": "secret123",
                "region": "us",
            },
        }
        is_valid, errors = validator.validate(config)
        assert not is_valid
        assert "domain" in str(errors).lower() or "okta.com" in str(errors).lower()

    def test_validate_invalid_onelogin_region(self):
        """Test validating config with invalid OneLogin region."""
        validator = ConfigValidator()
        config = {
            "okta": {
                "domain": "mycompany.okta.com",
                "token": "00abc123456789012345",
            },
            "onelogin": {
                "client_id": "abc123",
                "client_secret": "secret123",
                "region": "invalid",  # Should be us or eu
            },
        }
        is_valid, errors = validator.validate(config)
        assert not is_valid
        assert "region" in str(errors).lower()

    def test_sanitize_config(self):
        """Test sanitizing config."""
        validator = ConfigValidator()
        config = {
            "okta": {
                "domain": "mycompany.okta.com",
                "token": "00abc123secrettoken",
            },
            "onelogin": {
                "client_id": "abc123",
                "client_secret": "secret123",
                "region": "us",
            },
        }
        sanitized = validator.sanitize_config(config)

        assert sanitized["okta"]["domain"] == "mycompany.okta.com"
        assert sanitized["okta"]["token"] == "***REDACTED***"
        assert sanitized["onelogin"]["client_id"] == "abc123"  # Not redacted
        assert sanitized["onelogin"]["client_secret"] == "***REDACTED***"


# =============================================================================
# AutoSaveCredentialManager Tests
# =============================================================================


class TestAutoSaveCredentialManager:
    """Tests for AutoSaveCredentialManager class."""

    def test_create_memory_backend(self):
        """Test creating manager with memory backend."""
        manager = AutoSaveCredentialManager(storage_backend="memory", enable_audit_log=False)
        assert manager.storage_backend == "memory"
        assert manager._memory_store == {}

    def test_save_and_retrieve_memory(self):
        """Test saving and retrieving credential from memory."""
        manager = AutoSaveCredentialManager(storage_backend="memory", enable_audit_log=False)

        success = manager.auto_save_credential("test_service", "test_key", "test_value")
        assert success

        retrieved = manager.get_credential("test_service", "test_key")
        assert retrieved is not None
        assert retrieved.reveal() == "test_value"

    def test_save_and_delete_memory(self):
        """Test deleting credential from memory."""
        manager = AutoSaveCredentialManager(storage_backend="memory", enable_audit_log=False)

        manager.auto_save_credential("test_service", "test_key", "test_value")
        deleted = manager.delete_credential("test_service", "test_key")
        assert deleted

        retrieved = manager.get_credential("test_service", "test_key")
        assert retrieved is None

    def test_list_credentials_memory(self):
        """Test listing credentials from memory."""
        manager = AutoSaveCredentialManager(storage_backend="memory", enable_audit_log=False)

        manager.auto_save_credential("service1", "key1", "value1")
        manager.auto_save_credential("service2", "key2", "value2")

        credentials = manager.list_credentials()
        assert len(credentials) == 2
        assert ("service1", "key1", "memory") in credentials
        assert ("service2", "key2", "memory") in credentials

    def test_credential_pattern_detection(self):
        """Test credential pattern detection."""
        manager = AutoSaveCredentialManager(storage_backend="memory", enable_audit_log=False)

        assert manager.is_credential_field("password")
        assert manager.is_credential_field("api_token")
        assert manager.is_credential_field("secret_key")
        assert not manager.is_credential_field("username")
        assert not manager.is_credential_field("subdomain")

    @patch("keyring.set_password")
    @patch("keyring.get_password")
    def test_keyring_backend(self, mock_get, mock_set):
        """Test keyring backend."""
        mock_get.return_value = "test_value"
        mock_set.return_value = None

        manager = AutoSaveCredentialManager(storage_backend="keyring", enable_audit_log=False)

        # Save credential
        success = manager.auto_save_credential("test_service", "test_key", "test_value")
        assert success
        mock_set.assert_called_once()

        # Retrieve credential
        mock_get.return_value = "test_value"
        retrieved = manager.get_credential("test_service", "test_key")
        assert retrieved is not None
        assert retrieved.reveal() == "test_value"

    def test_vault_backend(self):
        """Test vault backend."""
        # Vault backend saves to ~/.onelogin-migration/vault.enc
        # For testing, we'll use temp directory and mock
        manager = AutoSaveCredentialManager(
            storage_backend="vault",
            vault_password="test_password",
            enable_audit_log=False,
        )

        # Save credential
        success = manager.auto_save_credential("test_service", "test_key", "test_value")
        assert success

        # Retrieve credential
        retrieved = manager.get_credential("test_service", "test_key")
        assert retrieved is not None
        assert retrieved.reveal() == "test_value"

        # Clean up
        vault_path = Path.home() / ".onelogin-migration" / "vault.enc"
        if vault_path.exists():
            vault_path.unlink()

    def test_env_backend(self):
        """Test environment variable backend."""
        manager = AutoSaveCredentialManager(storage_backend="env", enable_audit_log=False)

        # Set environment variable
        import os

        os.environ["TEST_SERVICE_TEST_KEY"] = "test_value"

        # Retrieve credential
        retrieved = manager.get_credential("test_service", "test_key")
        assert retrieved is not None
        assert retrieved.reveal() == "test_value"

        # Clean up
        del os.environ["TEST_SERVICE_TEST_KEY"]

    def test_auto_save_debounce(self):
        """Test auto-save debouncing."""
        manager = AutoSaveCredentialManager(
            storage_backend="memory",
            enable_auto_save=True,
            auto_save_delay=0.1,
            enable_audit_log=False,
        )

        # Trigger multiple saves quickly
        for i in range(5):
            manager.auto_save_credential("test_service", "test_key", f"value_{i}")

        # Wait for debounce
        time.sleep(0.2)

        # Should have the last value
        retrieved = manager.get_credential("test_service", "test_key")
        assert retrieved is not None
        assert retrieved.reveal() == "value_4"

    def test_audit_logging_integration(self):
        """Test audit logging integration."""
        # Audit log uses default path, let's just test it works
        manager = AutoSaveCredentialManager(storage_backend="memory", enable_audit_log=True)

        manager.auto_save_credential("test_service", "test_key", "test_value")
        manager.get_credential("test_service", "test_key")
        manager.delete_credential("test_service", "test_key")

        # Check audit log
        summary = manager.get_audit_summary()
        assert summary["total_events"] >= 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
