"""
Tests for audit key storage backends.

This module tests the pluggable audit key backend system:
- FileAuditKeyBackend: File-based storage
- KeyringAuditKeyBackend: OS-native secure storage
- EnvironmentAuditKeyBackend: Environment variable storage

Also tests integration with TamperEvidentAuditLogger.
"""

import base64
import os
import secrets
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# Import from layered_credentials
try:
    from layered_credentials.core import (
        AuditError,
        EnvironmentAuditKeyBackend,
        FileAuditKeyBackend,
        KeyringAuditKeyBackend,
        TamperEvidentAuditLogger,
    )
except ImportError:
    # Fallback for tests run before installation
    import sys
    from pathlib import Path

    layered_creds_src = Path(__file__).resolve().parents[2] / "layered_credentials" / "src"
    sys.path.insert(0, str(layered_creds_src))

    from layered_credentials.core import (
        AuditError,
        EnvironmentAuditKeyBackend,
        FileAuditKeyBackend,
        KeyringAuditKeyBackend,
        TamperEvidentAuditLogger,
    )


class TestFileAuditKeyBackend:
    """Test file-based audit key storage."""

    def test_store_and_retrieve_key(self):
        """Test storing and retrieving a key from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / ".audit_key"
            backend = FileAuditKeyBackend(key_file)

            # Generate a test key
            test_key = secrets.token_bytes(32)

            # Store the key
            backend.store_key(test_key)

            # Verify file exists
            assert key_file.exists()

            # Retrieve the key
            retrieved_key = backend.retrieve_key()
            assert retrieved_key == test_key

    def test_retrieve_nonexistent_key(self):
        """Test retrieving key when file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / ".audit_key"
            backend = FileAuditKeyBackend(key_file)

            # Retrieve from non-existent file
            retrieved_key = backend.retrieve_key()
            assert retrieved_key is None

    def test_store_invalid_key_length(self):
        """Test that storing wrong-length key raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / ".audit_key"
            backend = FileAuditKeyBackend(key_file)

            # Try to store 16-byte key (should be 32)
            with pytest.raises(ValueError, match="must be 32 bytes"):
                backend.store_key(b"short_key")

    def test_retrieve_corrupted_key(self):
        """Test that corrupted key file returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / ".audit_key"
            backend = FileAuditKeyBackend(key_file)

            # Write invalid key (wrong length)
            key_file.write_bytes(b"corrupted_key")

            # Retrieve should return None
            retrieved_key = backend.retrieve_key()
            assert retrieved_key is None

    def test_delete_key(self):
        """Test deleting key file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / ".audit_key"
            backend = FileAuditKeyBackend(key_file)

            # Store a key
            test_key = secrets.token_bytes(32)
            backend.store_key(test_key)
            assert key_file.exists()

            # Delete the key
            backend.delete_key()
            assert not key_file.exists()

    def test_delete_nonexistent_key(self):
        """Test deleting key when file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / ".audit_key"
            backend = FileAuditKeyBackend(key_file)

            # Delete non-existent key (should not raise)
            backend.delete_key()

    def test_file_permissions_are_secure(self):
        """Test that key file has secure permissions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / ".audit_key"
            backend = FileAuditKeyBackend(key_file)

            # Store a key
            test_key = secrets.token_bytes(32)
            backend.store_key(test_key)

            # On Unix, verify permissions are 0o600
            if os.name != "nt":  # Skip on Windows
                stat_result = os.stat(key_file)
                permissions = stat_result.st_mode & 0o777
                assert permissions == 0o600, f"Expected 0o600, got {oct(permissions)}"


class TestKeyringAuditKeyBackend:
    """Test keyring-based audit key storage."""

    def test_store_and_retrieve_key(self):
        """Test storing and retrieving a key from keyring."""
        try:
            import keyring
        except ImportError:
            pytest.skip("keyring library not installed")

        service_name = "test-layered-credentials"
        backend = KeyringAuditKeyBackend(service_name)

        try:
            # Generate a test key
            test_key = secrets.token_bytes(32)

            # Store the key
            backend.store_key(test_key)

            # Retrieve the key
            retrieved_key = backend.retrieve_key()
            assert retrieved_key == test_key

        finally:
            # Cleanup
            try:
                backend.delete_key()
            except Exception:
                pass

    def test_retrieve_nonexistent_key(self):
        """Test retrieving key when it doesn't exist in keyring."""
        try:
            import keyring
        except ImportError:
            pytest.skip("keyring library not installed")

        service_name = "test-layered-credentials-nonexistent"
        backend = KeyringAuditKeyBackend(service_name, key_name="nonexistent")

        # Retrieve from non-existent entry
        retrieved_key = backend.retrieve_key()
        assert retrieved_key is None

    def test_store_invalid_key_length(self):
        """Test that storing wrong-length key raises error."""
        try:
            import keyring
        except ImportError:
            pytest.skip("keyring library not installed")

        service_name = "test-layered-credentials"
        backend = KeyringAuditKeyBackend(service_name)

        # Try to store 16-byte key (should be 32)
        with pytest.raises(ValueError, match="must be 32 bytes"):
            backend.store_key(b"short_key")

    def test_delete_key(self):
        """Test deleting key from keyring."""
        try:
            import keyring
        except ImportError:
            pytest.skip("keyring library not installed")

        service_name = "test-layered-credentials-delete"
        backend = KeyringAuditKeyBackend(service_name)

        try:
            # Store a key
            test_key = secrets.token_bytes(32)
            backend.store_key(test_key)

            # Verify it exists
            assert backend.retrieve_key() == test_key

            # Delete the key
            backend.delete_key()

            # Verify it's gone
            assert backend.retrieve_key() is None

        finally:
            # Cleanup
            try:
                backend.delete_key()
            except Exception:
                pass

    def test_keyring_not_available(self):
        """Test error when keyring library is not available."""
        # Mock keyring as not available
        with mock.patch("layered_credentials.core.HAS_KEYRING", False):
            with pytest.raises(ImportError, match="keyring library is required"):
                KeyringAuditKeyBackend("test-service")


class TestEnvironmentAuditKeyBackend:
    """Test environment variable audit key storage."""

    def test_retrieve_key_from_environment(self):
        """Test retrieving key from environment variable."""
        backend = EnvironmentAuditKeyBackend("TEST_AUDIT_KEY")

        # Generate and encode a test key
        test_key = secrets.token_bytes(32)
        encoded_key = base64.b64encode(test_key).decode("ascii")

        # Set environment variable
        with mock.patch.dict(os.environ, {"TEST_AUDIT_KEY": encoded_key}):
            # Retrieve the key
            retrieved_key = backend.retrieve_key()
            assert retrieved_key == test_key

    def test_retrieve_nonexistent_key(self):
        """Test retrieving key when environment variable doesn't exist."""
        backend = EnvironmentAuditKeyBackend("NONEXISTENT_AUDIT_KEY")

        # Retrieve from non-existent env var
        retrieved_key = backend.retrieve_key()
        assert retrieved_key is None

    def test_retrieve_invalid_key_length(self):
        """Test that invalid key length returns None."""
        backend = EnvironmentAuditKeyBackend("TEST_AUDIT_KEY")

        # Set env var with wrong-length key
        invalid_key = base64.b64encode(b"short_key").decode("ascii")
        with mock.patch.dict(os.environ, {"TEST_AUDIT_KEY": invalid_key}):
            # Retrieve should return None
            retrieved_key = backend.retrieve_key()
            assert retrieved_key is None

    def test_retrieve_invalid_base64(self):
        """Test that invalid base64 returns None."""
        backend = EnvironmentAuditKeyBackend("TEST_AUDIT_KEY")

        # Set env var with invalid base64
        with mock.patch.dict(os.environ, {"TEST_AUDIT_KEY": "not-valid-base64!!!"}):
            # Retrieve should return None
            retrieved_key = backend.retrieve_key()
            assert retrieved_key is None

    def test_store_key_is_noop(self):
        """Test that storing key logs warning (environment backend is read-only)."""
        backend = EnvironmentAuditKeyBackend("TEST_AUDIT_KEY")

        # Store should not raise, just log warning
        test_key = secrets.token_bytes(32)
        backend.store_key(test_key)  # No assertion - just shouldn't crash

    def test_delete_key_is_noop(self):
        """Test that deleting key logs warning (environment backend is read-only)."""
        backend = EnvironmentAuditKeyBackend("TEST_AUDIT_KEY")

        # Delete should not raise, just log warning
        backend.delete_key()  # No assertion - just shouldn't crash


class TestTamperEvidentAuditLoggerWithBackends:
    """Test TamperEvidentAuditLogger integration with different backends."""

    def test_logger_with_file_backend(self):
        """Test logger with explicit file backend."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"
            key_file = Path(tmpdir) / ".audit_key"

            # Create logger with file backend
            backend = FileAuditKeyBackend(key_file)
            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                enable_tamper_evidence=True,
                audit_key_backend=backend,
            )

            # Log an event
            logger.log_store("test_service", "test_key", True)

            # Verify key file was created
            assert key_file.exists()

            # Verify audit log
            assert audit_file.exists()

    def test_logger_with_keyring_backend(self):
        """Test logger with keyring backend."""
        try:
            import keyring
        except ImportError:
            pytest.skip("keyring library not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            # Create logger with keyring backend
            backend = KeyringAuditKeyBackend("test-audit-logger")
            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                enable_tamper_evidence=True,
                audit_key_backend=backend,
            )

            try:
                # Log an event
                logger.log_store("test_service", "test_key", True)

                # Verify audit log
                assert audit_file.exists()

                # Verify key is in keyring
                retrieved_key = backend.retrieve_key()
                assert retrieved_key is not None
                assert len(retrieved_key) == 32

            finally:
                # Cleanup
                try:
                    backend.delete_key()
                except Exception:
                    pass

    def test_logger_with_environment_backend(self):
        """Test logger with environment backend."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            # Generate and set audit key in environment
            test_key = secrets.token_bytes(32)
            encoded_key = base64.b64encode(test_key).decode("ascii")

            with mock.patch.dict(os.environ, {"TEST_AUDIT_KEY": encoded_key}):
                # Create logger with environment backend
                backend = EnvironmentAuditKeyBackend("TEST_AUDIT_KEY")
                logger = TamperEvidentAuditLogger(
                    log_file=audit_file,
                    enable_tamper_evidence=True,
                    audit_key_backend=backend,
                )

                # Log an event
                logger.log_store("test_service", "test_key", True)

                # Verify audit log
                assert audit_file.exists()

    def test_logger_defaults_to_file_backend(self):
        """Test that logger defaults to file backend for backwards compatibility."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            # Create logger without explicit backend
            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                enable_tamper_evidence=True,
            )

            # Log an event
            logger.log_store("test_service", "test_key", True)

            # Verify default key file was created
            key_file = audit_file.parent / ".audit_key"
            assert key_file.exists()

    def test_logger_with_no_backend_still_works(self):
        """Test that logger works without backend (in-memory key only)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            # Create logger with explicit audit key (bypasses backend)
            test_key = secrets.token_bytes(32)
            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                enable_tamper_evidence=True,
                audit_key=test_key,  # Explicit key bypasses backend
            )

            # Log an event
            logger.log_store("test_service", "test_key", True)

            # Verify audit log
            assert audit_file.exists()

            # Verify no key file was created (using explicit key)
            key_file = audit_file.parent / ".audit_key"
            assert not key_file.exists()
