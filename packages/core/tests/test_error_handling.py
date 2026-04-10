"""
Tests for error handling and custom exceptions.

This module tests:
- Custom exception hierarchy
- Exception details and context
- SecureStringError usage
- VaultError usage
- Error handling in various operations
"""

import tempfile
from pathlib import Path

import pytest

from onelogin_migration_core.credentials import (
    AutoSaveCredentialManager,
    LayeredCredentialsError,
    SecureString,
    SecureStringError,
    VaultRollbackError,
)


class TestExceptionHierarchy:
    """Test custom exception hierarchy."""

    def test_layered_credentials_error_base(self):
        """Test that LayeredCredentialsError is the base class."""
        err = LayeredCredentialsError("test error")
        assert isinstance(err, Exception)
        assert str(err) == "test error"
        assert err.message == "test error"
        assert err.details == {}

    def test_layered_credentials_error_with_details(self):
        """Test LayeredCredentialsError with details."""
        details = {"service": "okta", "key": "token", "attempt": 1}
        err = LayeredCredentialsError("test error", details=details)
        assert err.message == "test error"
        assert err.details == details
        assert err.details["service"] == "okta"
        assert err.details["key"] == "token"
        assert err.details["attempt"] == 1

    def test_secure_string_error_inheritance(self):
        """Test that SecureStringError inherits from LayeredCredentialsError."""
        err = SecureStringError("secure string error")
        assert isinstance(err, LayeredCredentialsError)
        assert isinstance(err, Exception)

    def test_vault_rollback_error_inheritance(self):
        """Test that VaultRollbackError inherits correctly."""
        from layered_credentials import VaultError, VaultRollbackError

        err = VaultRollbackError("rollback detected")
        assert isinstance(err, VaultError)
        assert isinstance(err, LayeredCredentialsError)
        assert isinstance(err, Exception)

    def test_all_exceptions_importable(self):
        """Test that all custom exceptions can be imported."""
        from layered_credentials import (
            AuditError,
            BackupError,
            ConfigValidationError,
            KeyringError,
            LayeredCredentialsError,
            RestoreError,
            SecureStringError,
            TamperDetectedError,
            VaultCorruptionError,
            VaultDecryptionError,
            VaultEncryptionError,
            VaultError,
            VaultRollbackError,
        )

        # Verify all are Exception subclasses
        exceptions = [
            LayeredCredentialsError,
            SecureStringError,
            VaultError,
            VaultDecryptionError,
            VaultEncryptionError,
            VaultRollbackError,
            VaultCorruptionError,
            KeyringError,
            BackupError,
            RestoreError,
            ConfigValidationError,
            AuditError,
            TamperDetectedError,
        ]

        for exc_class in exceptions:
            assert issubclass(exc_class, Exception)


class TestSecureStringErrors:
    """Test SecureString error handling."""

    def test_reveal_after_zero_raises_secure_string_error(self):
        """Test that revealing after zeroing raises SecureStringError."""
        secure = SecureString("test")
        secure.zero()

        with pytest.raises(SecureStringError) as exc_info:
            secure.reveal()

        assert "already been zeroed" in str(exc_info.value)

    def test_get_bytes_after_zero_raises_secure_string_error(self):
        """Test that get_bytes after zeroing raises SecureStringError."""
        secure = SecureString("test")
        secure.zero()

        with pytest.raises(SecureStringError) as exc_info:
            secure.get_bytes()

        assert "already been zeroed" in str(exc_info.value)

    def test_get_memoryview_after_zero_raises_secure_string_error(self):
        """Test that get_memoryview after zeroing raises SecureStringError."""
        secure = SecureString("test")
        secure.zero()

        with pytest.raises(SecureStringError) as exc_info:
            secure.get_memoryview()

        assert "already been zeroed" in str(exc_info.value)

    def test_use_secret_after_zero_raises_secure_string_error(self):
        """Test that use_secret after zeroing raises SecureStringError."""
        secure = SecureString("test")
        secure.zero()

        with pytest.raises(SecureStringError) as exc_info:
            secure.use_secret(lambda b: b.decode())

        assert "already been zeroed" in str(exc_info.value)


class TestVaultErrors:
    """Test vault-related error handling."""

    def test_vault_rollback_error_has_details(self):
        """Test that VaultRollbackError includes counter details."""
        # This test verifies the error is raised with proper details
        # We need to trigger a rollback scenario

        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault.enc"
            counter_file = Path(tmpdir) / ".vault_counter"

            from layered_credentials import Argon2VaultV3

            # Create a vault with counter
            vault1 = Argon2VaultV3(counter_file=counter_file)
            encrypted1 = vault1.encrypt("data1", "password")

            # Save to file
            import json

            with open(vault_path, "w") as f:
                json.dump(encrypted1, f)

            # Encrypt more data (increases counter)
            encrypted2 = vault1.encrypt("data2", "password")
            encrypted3 = vault1.encrypt("data3", "password")

            # Now try to decrypt old data (should trigger rollback)
            vault2 = Argon2VaultV3(counter_file=counter_file)

            with pytest.raises(VaultRollbackError) as exc_info:
                vault2.decrypt(encrypted1, "password")

            # Verify error has details
            error = exc_info.value
            assert isinstance(error, VaultRollbackError)
            assert "rollback attack" in str(error).lower()
            assert "details" in dir(error)
            assert "current_counter" in error.details
            assert "vault_counter" in error.details
            assert error.details["current_counter"] > error.details["vault_counter"]

    def test_vault_rollback_error_v3_format(self):
        """Test rollback detection in V3 format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            counter_file = Path(tmpdir) / ".vault_counter"

            from layered_credentials import Argon2VaultV3

            vault = Argon2VaultV3(counter_file=counter_file)

            # Create multiple encryptions
            enc1 = vault.encrypt("data1", "password")
            enc2 = vault.encrypt("data2", "password")
            enc3 = vault.encrypt("data3", "password")

            # Try to decrypt old version
            with pytest.raises(VaultRollbackError) as exc_info:
                vault.decrypt(enc1, "password")

            assert "rollback attack" in str(exc_info.value).lower()


class TestErrorContextTracking:
    """Test that errors include useful context for debugging."""

    def test_vault_rollback_error_context(self):
        """Test that VaultRollbackError provides debugging context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            counter_file = Path(tmpdir) / ".vault_counter"
            from layered_credentials import Argon2VaultV3

            vault = Argon2VaultV3(counter_file=counter_file)
            old_enc = vault.encrypt("old", "pass")
            _ = vault.encrypt("new1", "pass")
            _ = vault.encrypt("new2", "pass")

            with pytest.raises(VaultRollbackError) as exc_info:
                vault.decrypt(old_enc, "pass")

            error = exc_info.value
            # Should have counter values
            assert error.details["current_counter"] == 3
            assert error.details["vault_counter"] == 1

    def test_exception_can_be_caught_by_base_class(self):
        """Test that specific errors can be caught by base class."""
        secure = SecureString("test")
        secure.zero()

        # Can catch with specific exception
        with pytest.raises(SecureStringError):
            secure.reveal()

        # Can also catch with base exception
        with pytest.raises(LayeredCredentialsError):
            secure.get_bytes()


class TestErrorMessages:
    """Test that error messages are clear and actionable."""

    def test_secure_string_error_message_is_clear(self):
        """Test that SecureString errors have clear messages."""
        secure = SecureString("test")
        secure.zero()

        with pytest.raises(SecureStringError) as exc_info:
            secure.reveal()

        message = str(exc_info.value)
        assert "zeroed" in message.lower()
        assert "SecureString" in message

    def test_vault_rollback_error_message_is_actionable(self):
        """Test that rollback errors explain what happened."""
        with tempfile.TemporaryDirectory() as tmpdir:
            counter_file = Path(tmpdir) / ".vault_counter"
            from layered_credentials import Argon2VaultV3

            vault = Argon2VaultV3(counter_file=counter_file)
            old = vault.encrypt("old", "pass")
            _ = vault.encrypt("new", "pass")

            with pytest.raises(VaultRollbackError) as exc_info:
                vault.decrypt(old, "pass")

            message = str(exc_info.value)
            assert "rollback" in message.lower()
            assert "counter" in message.lower()
            # Should mention what might be happening
            assert "restore" in message.lower() or "old" in message.lower()


class TestBackwardsCompatibility:
    """Test that error handling changes don't break existing code."""

    def test_exceptions_can_be_caught_as_exception(self):
        """Test that custom exceptions are still regular exceptions."""
        secure = SecureString("test")
        secure.zero()

        # Should be catchable as plain Exception
        with pytest.raises(Exception):
            secure.reveal()

    def test_error_str_representation_works(self):
        """Test that errors can be converted to strings."""
        err = LayeredCredentialsError("test message", {"key": "value"})
        str_repr = str(err)
        assert "test message" in str_repr
        assert isinstance(str_repr, str)


class TestImportStructure:
    """Test that exceptions are properly exported."""

    def test_exceptions_importable_from_main_module(self):
        """Test that exceptions can be imported from layered_credentials."""
        # All should be importable from top level
        from layered_credentials import (
            LayeredCredentialsError,
            SecureStringError,
            VaultRollbackError,
        )

        assert LayeredCredentialsError is not None
        assert SecureStringError is not None
        assert VaultRollbackError is not None

    def test_all_exports_exceptions(self):
        """Test that __all__ includes exception classes."""
        import layered_credentials

        # Check that exception classes are in __all__
        assert "LayeredCredentialsError" in layered_credentials.__all__
        assert "SecureStringError" in layered_credentials.__all__
        assert "VaultRollbackError" in layered_credentials.__all__
        assert "BackupError" in layered_credentials.__all__
        assert "RestoreError" in layered_credentials.__all__
