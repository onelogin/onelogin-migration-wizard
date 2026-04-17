"""
Tests for cross-platform file permissions (secure_file_permissions).

This module tests that sensitive files are properly secured on all platforms:
- Unix/Linux/macOS: chmod 0o600 (owner read/write only)
- Windows: ACL set to owner-only using icacls
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest


# Import from layered_credentials since it's the source package
try:
    from layered_credentials.core import (
        secure_file_permissions,
        _secure_file_permissions_unix,
        _secure_file_permissions_windows,
    )
except ImportError:
    # Fallback for tests run before installation
    import sys
    from pathlib import Path

    # Add layered_credentials to path
    layered_creds_src = Path(__file__).resolve().parents[2] / "layered_credentials" / "src"
    sys.path.insert(0, str(layered_creds_src))

    from layered_credentials.core import (
        secure_file_permissions,
        _secure_file_permissions_unix,
        _secure_file_permissions_windows,
    )


class TestUnixFilePermissions:
    """Test Unix file permissions (chmod 0o600)."""

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test")
    def test_secure_file_permissions_unix(self):
        """Test that files get 0o600 permissions on Unix."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(b"sensitive data")

        try:
            # Set insecure permissions first
            os.chmod(tmp_path, 0o644)

            # Apply secure permissions
            _secure_file_permissions_unix(tmp_path)

            # Verify permissions are 0o600
            stat_result = os.stat(tmp_path)
            permissions = stat_result.st_mode & 0o777
            assert permissions == 0o600, f"Expected 0o600, got {oct(permissions)}"

        finally:
            tmp_path.unlink(missing_ok=True)

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test")
    def test_secure_file_permissions_unix_nonexistent_file(self):
        """Test that securing nonexistent file fails gracefully."""
        nonexistent = Path("/tmp/nonexistent_file_12345.txt")

        # Should not raise exception, just log warning
        _secure_file_permissions_unix(nonexistent)

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test")
    def test_secure_file_permissions_unix_read_only_directory(self):
        """Test that permission errors are handled gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "test.txt"
            tmp_path.write_text("test")

            # Make directory read-only
            os.chmod(tmpdir, 0o555)

            try:
                # Should not crash, just log warning
                _secure_file_permissions_unix(tmp_path)
            finally:
                # Restore permissions for cleanup
                os.chmod(tmpdir, 0o755)


class TestWindowsFilePermissions:
    """Test Windows file permissions (ACL via icacls)."""

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_secure_file_permissions_windows(self):
        """Test that files get owner-only ACL on Windows."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(b"sensitive data")

        try:
            # Apply secure permissions
            _secure_file_permissions_windows(tmp_path)

            # Verify ACL was set (check icacls output)
            result = subprocess.run(
                ["icacls", str(tmp_path)],
                capture_output=True,
                text=True,
                timeout=5,
            )

            # icacls output should show current user with full control (F)
            # and inheritance removed
            username = os.getenv("USERNAME")
            assert username in result.stdout
            assert "(F)" in result.stdout  # Full control

        finally:
            tmp_path.unlink(missing_ok=True)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_secure_file_permissions_windows_no_username_env(self):
        """Test graceful handling when USERNAME env var is not set."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(b"sensitive data")

        try:
            # Mock missing USERNAME environment variable
            with mock.patch.dict(os.environ, {}, clear=True):
                # Should not crash, just log warning
                _secure_file_permissions_windows(tmp_path)

        finally:
            tmp_path.unlink(missing_ok=True)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_secure_file_permissions_windows_icacls_not_found(self):
        """Test graceful handling when icacls is not available."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(b"sensitive data")

        try:
            # Mock icacls not found
            with mock.patch("subprocess.run", side_effect=FileNotFoundError("icacls not found")):
                # Should not crash, just log warning
                _secure_file_permissions_windows(tmp_path)

        finally:
            tmp_path.unlink(missing_ok=True)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_secure_file_permissions_windows_icacls_fails(self):
        """Test graceful handling when icacls command fails."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(b"sensitive data")

        try:
            # Mock icacls failure
            with mock.patch("subprocess.run", side_effect=subprocess.CalledProcessError(
                1, ["icacls"], stderr="Access denied"
            )):
                # Should not crash, just log warning
                _secure_file_permissions_windows(tmp_path)

        finally:
            tmp_path.unlink(missing_ok=True)


class TestCrossPlatformFilePermissions:
    """Test the cross-platform secure_file_permissions() entry point."""

    def test_secure_file_permissions_creates_secure_file(self):
        """Test that secure_file_permissions() works on current platform."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(b"sensitive data")

        try:
            # Apply secure permissions
            secure_file_permissions(tmp_path)

            # Verify file still exists and is readable by owner
            assert tmp_path.exists()
            assert tmp_path.read_bytes() == b"sensitive data"

            # On Unix, verify permissions
            if sys.platform != "win32":
                stat_result = os.stat(tmp_path)
                permissions = stat_result.st_mode & 0o777
                assert permissions == 0o600, f"Expected 0o600, got {oct(permissions)}"

        finally:
            tmp_path.unlink(missing_ok=True)

    def test_secure_file_permissions_path_object(self):
        """Test that Path objects are handled correctly."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(b"test")

        try:
            # Pass Path object (not string)
            secure_file_permissions(tmp_path)

            # Should succeed
            assert tmp_path.exists()

        finally:
            tmp_path.unlink(missing_ok=True)

    def test_secure_file_permissions_empty_file(self):
        """Test that empty files can be secured."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            # Leave empty

        try:
            secure_file_permissions(tmp_path)

            # Should succeed
            assert tmp_path.exists()
            assert tmp_path.stat().st_size == 0

        finally:
            tmp_path.unlink(missing_ok=True)

    def test_secure_file_permissions_large_file(self):
        """Test that large files can be secured."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            # Write 10MB of data
            tmp.write(b"x" * (10 * 1024 * 1024))

        try:
            secure_file_permissions(tmp_path)

            # Should succeed
            assert tmp_path.exists()
            assert tmp_path.stat().st_size == 10 * 1024 * 1024

        finally:
            tmp_path.unlink(missing_ok=True)

    def test_secure_file_permissions_doesnt_crash_on_nonexistent(self):
        """Test that nonexistent files don't crash the application."""
        nonexistent = Path("/tmp/definitely_does_not_exist_12345.txt")

        # Should not raise exception (just logs warning)
        secure_file_permissions(nonexistent)


class TestIntegrationWithVault:
    """Test that secure_file_permissions integrates properly with vault operations."""

    def test_vault_counter_file_permissions(self):
        """Test that vault counter files get secure permissions."""
        from layered_credentials import Argon2VaultV3

        with tempfile.TemporaryDirectory() as tmpdir:
            counter_file = Path(tmpdir) / ".vault_counter"

            # Create vault which will create counter file
            vault = Argon2VaultV3(counter_file=counter_file)

            # Encrypt some data (this will create the counter file)
            encrypted = vault.encrypt("test data", "password")

            # Verify counter file exists
            assert counter_file.exists()

            # On Unix, verify permissions
            if sys.platform != "win32":
                stat_result = os.stat(counter_file)
                permissions = stat_result.st_mode & 0o777
                assert permissions == 0o600, f"Counter file should be 0o600, got {oct(permissions)}"

    def test_audit_key_file_permissions(self):
        """Test that audit key files get secure permissions."""
        from layered_credentials import TamperEvidentAuditLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            audit_file = Path(tmpdir) / "audit.log"

            # Create logger which will create audit key file
            logger = TamperEvidentAuditLogger(
                log_file=audit_file,
                enable_tamper_evidence=True,
            )

            # Log an event
            logger.log_store("test_service", "test_key", True)

            # Verify audit key file exists
            key_file = audit_file.parent / ".audit_key"
            assert key_file.exists()

            # On Unix, verify permissions
            if sys.platform != "win32":
                stat_result = os.stat(key_file)
                permissions = stat_result.st_mode & 0o777
                assert permissions == 0o600, f"Audit key file should be 0o600, got {oct(permissions)}"
