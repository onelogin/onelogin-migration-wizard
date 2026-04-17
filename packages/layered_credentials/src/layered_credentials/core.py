from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

try:
    from argon2.low_level import Type, hash_secret_raw

    HAS_ARGON2 = True
except ImportError:
    HAS_ARGON2 = False

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

try:
    import keyring

    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False

try:
    from pydantic import BaseModel, Field, ValidationError, field_validator

    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False

try:
    from filelock import FileLock

    HAS_FILELOCK = True
except ImportError:
    HAS_FILELOCK = False


# ============================================================================
# Custom Exceptions
# ============================================================================


class LayeredCredentialsError(Exception):
    """Base exception for all layered_credentials errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        """Initialize with message and optional details.

        Args:
            message: Human-readable error message
            details: Additional context (e.g., {"service": "okta", "key": "token"})
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SecureStringError(LayeredCredentialsError):
    """Errors related to SecureString operations."""

    pass


class VaultError(LayeredCredentialsError):
    """Base class for vault-related errors."""

    pass


class VaultDecryptionError(VaultError):
    """Failed to decrypt vault data."""

    pass


class VaultEncryptionError(VaultError):
    """Failed to encrypt vault data."""

    pass


class VaultRollbackError(VaultError):
    """Vault rollback attack detected."""

    pass


class VaultCorruptionError(VaultError):
    """Vault file is corrupted or invalid."""

    pass


class KeyringError(LayeredCredentialsError):
    """Errors related to OS keyring operations."""

    pass


class BackupError(LayeredCredentialsError):
    """Errors during backup operations."""

    pass


class RestoreError(LayeredCredentialsError):
    """Errors during restore operations."""

    pass


class ConfigValidationError(LayeredCredentialsError):
    """Configuration validation failed."""

    pass


class AuditError(LayeredCredentialsError):
    """Audit log errors."""

    pass


class TamperDetectedError(AuditError):
    """Audit log tampering detected."""

    pass


LOGGER = logging.getLogger(__name__)


DEFAULT_APP_NAME = "layered-credentials"


def _normalize_app_name(app_name: str | None) -> str:
    """Return a filesystem-friendly app name used for defaults."""
    value = (app_name or DEFAULT_APP_NAME).strip().lower()
    if not value:
        value = DEFAULT_APP_NAME
    sanitized = []
    for char in value:
        if char.isalnum():
            sanitized.append(char)
        elif char in {"-", "_", "."}:
            sanitized.append(char)
        elif char.isspace():
            sanitized.append("-")
        else:
            sanitized.append("-")
    slug = "".join(sanitized).strip("-")
    return slug or DEFAULT_APP_NAME


def _default_storage_dir(app_name: str) -> Path:
    """Return the default storage directory for the application."""
    slug = _normalize_app_name(app_name)
    if not slug.startswith("."):
        slug = f".{slug}"
    return Path.home() / slug


def _default_keyring_service(app_name: str) -> str:
    """Return the keyring service identifier for the application."""
    slug = _normalize_app_name(app_name).replace(".", "-")
    return f"{slug}-credentials"


# ============================================================================
# Cross-Platform File Permissions
# ============================================================================


def secure_file_permissions(path: Path) -> None:
    """Set owner-only permissions on file (cross-platform).

    This function ensures that sensitive files are only accessible by the
    current user, using the appropriate mechanism for each platform:

    - Unix/Linux/macOS: chmod 0o600 (rw-------)
    - Windows: Set ACL to deny all except current user using icacls

    Args:
        path: File to secure

    Note:
        On Windows, this requires the icacls command to be available.
        If permission setting fails, a warning is logged but execution continues.
    """
    if sys.platform == "win32":
        _secure_file_permissions_windows(path)
    else:
        _secure_file_permissions_unix(path)


def _secure_file_permissions_windows(path: Path) -> None:
    """Set Windows ACL to owner-only using icacls.

    This uses the Windows icacls command to:
    1. Remove inherited permissions (/inheritance:r)
    2. Grant full access only to current user (/grant:r)

    Args:
        path: File to secure

    Note:
        If icacls fails or is not available, a warning is logged but the
        operation is non-fatal. The file remains usable but with default
        Windows permissions.
    """
    try:
        # Get current user (Windows USERNAME environment variable)
        username = os.getenv("USERNAME")
        if not username:
            LOGGER.warning(f"USERNAME environment variable not set, cannot set ACL on {path}")
            return

        # Remove all inherited permissions and grant only to current user
        # /inheritance:r = remove inheritance
        # /grant:r = grant with replace (removes other permissions)
        result = subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{username}:(F)",
            ],
            check=True,
            capture_output=True,
            timeout=5,
            text=True,
        )
        LOGGER.debug(f"Set Windows ACL on {path} for user {username}")

    except FileNotFoundError:
        LOGGER.warning(
            f"icacls command not found, cannot set ACL on {path}. "
            "File permissions may not be restricted."
        )
    except subprocess.TimeoutExpired:
        LOGGER.warning(f"icacls command timed out while setting ACL on {path}")
    except subprocess.CalledProcessError as e:
        LOGGER.warning(
            f"Failed to set Windows ACL on {path}: {e.stderr.strip() if e.stderr else e}"
        )
    except Exception as e:
        LOGGER.warning(f"Unexpected error setting Windows ACL on {path}: {e}")


def _secure_file_permissions_unix(path: Path) -> None:
    """Set Unix permissions to 0o600 (owner read/write only).

    Args:
        path: File to secure

    Note:
        If chmod fails, a warning is logged but the operation is non-fatal.
    """
    try:
        os.chmod(path, 0o600)
        LOGGER.debug(f"Set Unix permissions 0o600 on {path}")
    except OSError as e:
        LOGGER.warning(f"Failed to set Unix permissions on {path}: {e}")
    except Exception as e:
        LOGGER.warning(f"Unexpected error setting Unix permissions on {path}: {e}")


# ============================================================================
# Audit Key Storage Backends
# ============================================================================


class AuditKeyBackend(ABC):
    """Abstract base class for audit key storage backends.

    Audit keys are used for HMAC-based tamper-evident audit logging.
    Different backends provide different security and operational characteristics:

    - FileAuditKeyBackend: Simple file-based storage (default, portable)
    - KeyringAuditKeyBackend: OS-native secure storage (hardware-backed on some systems)
    - EnvironmentAuditKeyBackend: Environment variable (for containerized deployments)

    The choice of backend depends on your threat model and operational environment.
    """

    @abstractmethod
    def store_key(self, key: bytes) -> None:
        """Store the audit key.

        Args:
            key: 32-byte audit key to store

        Raises:
            Exception: If key storage fails
        """
        pass

    @abstractmethod
    def retrieve_key(self) -> bytes | None:
        """Retrieve the stored audit key.

        Returns:
            32-byte audit key, or None if not found

        Raises:
            Exception: If key retrieval fails
        """
        pass

    @abstractmethod
    def delete_key(self) -> None:
        """Delete the stored audit key.

        Raises:
            Exception: If key deletion fails
        """
        pass


class FileAuditKeyBackend(AuditKeyBackend):
    """File-based audit key storage (default backend).

    Stores the audit key in a file adjacent to the audit log with secure permissions.
    This is the default backend for maximum portability across platforms.

    Security characteristics:
    - Owner-only file permissions (0o600 on Unix, ACL on Windows)
    - Simple file-based storage
    - No additional dependencies

    Trade-offs:
    - Key file compromise allows audit log forgery
    - File system access required
    - Not hardware-backed
    """

    def __init__(self, key_file: Path):
        """Initialize file-based audit key backend.

        Args:
            key_file: Path to key file (typically .audit_key)
        """
        self.key_file = key_file

    def store_key(self, key: bytes) -> None:
        """Store audit key to file with secure permissions."""
        if len(key) != 32:
            raise ValueError("Audit key must be 32 bytes")

        try:
            self.key_file.write_bytes(key)
            # Secure permissions (cross-platform)
            secure_file_permissions(self.key_file)
            LOGGER.debug(f"Stored audit key to {self.key_file}")
        except Exception as e:
            raise AuditError(f"Failed to store audit key to file: {e}")

    def retrieve_key(self) -> bytes | None:
        """Retrieve audit key from file."""
        if not self.key_file.exists():
            return None

        try:
            key_data = self.key_file.read_bytes()
            if len(key_data) != 32:
                LOGGER.warning(
                    f"Invalid audit key file (expected 32 bytes, got {len(key_data)})"
                )
                return None
            return key_data
        except Exception as e:
            LOGGER.warning(f"Failed to retrieve audit key from file: {e}")
            return None

    def delete_key(self) -> None:
        """Delete audit key file."""
        try:
            if self.key_file.exists():
                self.key_file.unlink()
                LOGGER.debug(f"Deleted audit key file {self.key_file}")
        except Exception as e:
            raise AuditError(f"Failed to delete audit key file: {e}")


class KeyringAuditKeyBackend(AuditKeyBackend):
    """OS-native keyring audit key storage (recommended for security).

    Stores the audit key in the OS-native secure storage:
    - Windows: Windows Credential Manager (DPAPI-protected)
    - macOS: Keychain (hardware-backed on T2/M1+ Macs)
    - Linux: Secret Service API (GNOME Keyring, KWallet)

    Security characteristics:
    - OS-level encryption
    - Hardware-backed on supported systems
    - Per-user isolation
    - Audit trail (on some systems)

    Trade-offs:
    - Requires keyring library and OS support
    - May require user interaction (on some systems)
    - Not portable across machines

    Requires: pip install keyring
    """

    def __init__(self, service_name: str, key_name: str = "audit-key"):
        """Initialize keyring-based audit key backend.

        Args:
            service_name: Keyring service name (e.g., "my-app-audit")
            key_name: Key identifier within service (default: "audit-key")
        """
        if not HAS_KEYRING:
            raise ImportError(
                "keyring library is required for KeyringAuditKeyBackend. "
                "Install with: pip install keyring"
            )

        self.service_name = service_name
        self.key_name = key_name

    def store_key(self, key: bytes) -> None:
        """Store audit key to OS keyring."""
        if len(key) != 32:
            raise ValueError("Audit key must be 32 bytes")

        try:
            # Encode key as base64 for storage
            encoded_key = base64.b64encode(key).decode("ascii")
            keyring.set_password(self.service_name, self.key_name, encoded_key)
            LOGGER.debug(
                f"Stored audit key to keyring service={self.service_name}, key={self.key_name}"
            )
        except Exception as e:
            raise AuditError(f"Failed to store audit key to keyring: {e}")

    def retrieve_key(self) -> bytes | None:
        """Retrieve audit key from OS keyring."""
        try:
            encoded_key = keyring.get_password(self.service_name, self.key_name)
            if encoded_key is None:
                return None

            # Decode from base64
            key_data = base64.b64decode(encoded_key)
            if len(key_data) != 32:
                LOGGER.warning(
                    f"Invalid audit key in keyring (expected 32 bytes, got {len(key_data)})"
                )
                return None
            return key_data
        except Exception as e:
            LOGGER.warning(f"Failed to retrieve audit key from keyring: {e}")
            return None

    def delete_key(self) -> None:
        """Delete audit key from OS keyring."""
        try:
            keyring.delete_password(self.service_name, self.key_name)
            LOGGER.debug(
                f"Deleted audit key from keyring service={self.service_name}, key={self.key_name}"
            )
        except keyring.errors.PasswordDeleteError:
            # Key doesn't exist, that's fine
            pass
        except Exception as e:
            raise AuditError(f"Failed to delete audit key from keyring: {e}")


class EnvironmentAuditKeyBackend(AuditKeyBackend):
    """Environment variable audit key storage (for containerized deployments).

    Retrieves the audit key from an environment variable. Useful for:
    - Containerized applications (Docker, Kubernetes)
    - Cloud deployments (AWS Secrets Manager, HashiCorp Vault)
    - CI/CD pipelines

    Security characteristics:
    - Key provided externally (user manages key lifecycle)
    - No local storage
    - Suitable for ephemeral environments

    Trade-offs:
    - User must provide key via environment
    - Environment variables may be visible in process listings
    - No automatic key generation

    The key must be base64-encoded and set in the specified environment variable.
    """

    def __init__(self, env_var_name: str = "AUDIT_KEY_B64"):
        """Initialize environment variable audit key backend.

        Args:
            env_var_name: Environment variable name (default: AUDIT_KEY_B64)
        """
        self.env_var_name = env_var_name

    def store_key(self, key: bytes) -> None:
        """Store audit key (no-op for environment backend).

        The environment backend is read-only. Users must set the
        environment variable externally.
        """
        LOGGER.warning(
            f"EnvironmentAuditKeyBackend does not support storing keys. "
            f"Set {self.env_var_name} environment variable manually."
        )

    def retrieve_key(self) -> bytes | None:
        """Retrieve audit key from environment variable."""
        try:
            encoded_key = os.getenv(self.env_var_name)
            if not encoded_key:
                return None

            # Decode from base64
            key_data = base64.b64decode(encoded_key)
            if len(key_data) != 32:
                LOGGER.warning(
                    f"Invalid audit key in {self.env_var_name} "
                    f"(expected 32 bytes, got {len(key_data)})"
                )
                return None
            return key_data
        except Exception as e:
            LOGGER.warning(f"Failed to retrieve audit key from environment: {e}")
            return None

    def delete_key(self) -> None:
        """Delete audit key (no-op for environment backend).

        The environment backend is read-only. Users must unset the
        environment variable externally.
        """
        LOGGER.warning(
            f"EnvironmentAuditKeyBackend does not support deleting keys. "
            f"Unset {self.env_var_name} environment variable manually."
        )


class SecureString:
    """Memory-protected string with automatic zeroing and context manager support.

    This class stores sensitive strings in a mutable bytearray that can be
    overwritten with zeros before deallocation, reducing the risk of
    credentials remaining in memory after use.

    IMPORTANT LIMITATIONS:
    - Python may create temporary string copies during string operations
    - This class reduces but cannot eliminate the risk of secrets in memory
    - Use get_bytes() or use_secret() to avoid creating str copies
    - After zeroing, the original string value cannot be recovered

    Example (Context Manager - Recommended):
        >>> with SecureString.from_secret("api_token_12345") as token:
        ...     # Use token within this block
        ...     print(token.reveal())  # or token.get_bytes()
        ... # Automatically zeroed after exiting the block

    Example (Callback Pattern - No String Copies):
        >>> token = SecureString("api_token_12345")
        >>> token.use_secret(lambda secret_bytes: print(secret_bytes))
        >>> # Secret bytes are only accessible inside the callback

    Example (Traditional):
        >>> token = SecureString("api_token_12345")
        >>> print(token)  # Output: SecureString(***hidden***)
        >>> actual_value = token.reveal()  # Get the actual value
        >>> token.zero()  # Overwrite memory
        >>> # token.reveal() now raises ValueError
    """

    def __init__(self, value: str):
        """Initialize secure string.

        Args:
            value: The sensitive string to protect
        """
        self._data = bytearray(value.encode("utf-8"))
        self._is_zeroed = False

    @classmethod
    def from_secret(cls, value: str) -> "SecureString":
        """Create a SecureString from a secret value.

        This is the recommended way to create SecureString instances,
        especially when using as a context manager.

        Args:
            value: The sensitive string to protect

        Returns:
            SecureString instance

        Example:
            >>> with SecureString.from_secret("my_secret") as token:
            ...     print(token.reveal())
        """
        return cls(value)

    def reveal(self) -> str:
        """Get the actual string value.

        WARNING: This creates a Python str copy of the secret, which may
        remain in memory even after zeroing the SecureString. For better
        security, use get_bytes() or use_secret() instead.

        Returns:
            The unprotected string value

        Raises:
            ValueError: If the string has already been zeroed
        """
        if self._is_zeroed:
            raise SecureStringError("Cannot reveal SecureString that has already been zeroed")
        return self._data.decode("utf-8")

    def get_bytes(self) -> bytes:
        """Get the secret as immutable bytes without creating a str copy.

        This is more secure than reveal() as it avoids creating a Python
        string that may linger in memory.

        Returns:
            The secret as bytes

        Raises:
            ValueError: If the string has already been zeroed
        """
        if self._is_zeroed:
            raise SecureStringError("Cannot get bytes from SecureString that has already been zeroed")
        return bytes(self._data)

    def get_memoryview(self) -> memoryview:
        """Get a memoryview of the secret bytes without copying.

        This provides zero-copy access to the secret data. The memoryview
        becomes invalid after zeroing.

        Returns:
            memoryview of the secret bytes

        Raises:
            ValueError: If the string has already been zeroed
        """
        if self._is_zeroed:
            raise SecureStringError(
                "Cannot get memoryview from SecureString that has already been zeroed"
            )
        return memoryview(self._data)

    def use_secret(self, callback: Callable[[bytes], Any]) -> Any:
        """Execute a callback with the secret bytes without creating copies.

        This pattern ensures the secret is only accessible within the callback
        and minimizes the risk of copies lingering in memory.

        Args:
            callback: Function that takes bytes and returns any value

        Returns:
            The return value from the callback

        Raises:
            ValueError: If the string has already been zeroed

        Example:
            >>> token = SecureString("secret")
            >>> result = token.use_secret(lambda s: s.decode() + "_suffix")
        """
        if self._is_zeroed:
            raise SecureStringError("Cannot use SecureString that has already been zeroed")
        return callback(bytes(self._data))

    def zero(self) -> None:
        """Overwrite memory with zeros and mark as zeroed.

        After calling this method, all access methods will raise ValueError.
        The memory is overwritten byte-by-byte to ensure complete zeroing.
        """
        if not self._is_zeroed:
            # Overwrite memory with zeros byte-by-byte
            for i in range(len(self._data)):
                self._data[i] = 0
            self._is_zeroed = True

    def is_zeroed(self) -> bool:
        """Check if the secret has been zeroed.

        Returns:
            True if zeroed, False otherwise
        """
        return self._is_zeroed

    def __enter__(self) -> "SecureString":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - automatically zero memory."""
        self.zero()

    def __str__(self) -> str:
        """String representation hides value."""
        return "SecureString(***hidden***)"

    def __repr__(self) -> str:
        """Repr hides value."""
        return "SecureString(***hidden***)"

    def __del__(self) -> None:
        """Automatically zero memory on destruction."""
        try:
            self.zero()
        except Exception:
            pass  # Avoid exceptions in __del__


class Argon2VaultV3:
    """Argon2id-based encryption vault with authenticated encryption.

    This vault uses industry-standard cryptographic algorithms:
    - Key Derivation: Argon2id (winner of Password Hashing Competition)
    - Encryption: AES-256-GCM (NIST approved, provides built-in authentication)

    Security improvements in V3:
    - Removed redundant HMAC (AES-GCM already provides authentication)
    - Added monotonic counter for rollback protection
    - Added timestamp for age verification

    Security improvements in V4:
    - Counter included inside authenticated encrypted payload (prevents manipulation)
    - Atomic writes using temporary files + os.replace()
    - Cross-process file locking for all read/write operations
    - Counter updates are atomic with vault writes

    Storage Format V4:
        {
            "version": "4",
            "salt": "<base64-encoded-16-bytes>",
            "nonce": "<base64-encoded-12-bytes>",
            "ciphertext": "<base64-encrypted-payload-with-counter-and-data>"
        }

        Where decrypted payload contains:
        {
            "counter": <monotonic-counter>,
            "timestamp": <unix-timestamp>,
            "data": "<actual-plaintext>"
        }

    Storage Format V3 (backwards compatible):
        {
            "version": "3",
            "counter": <monotonic-counter>,
            "timestamp": <unix-timestamp>,
            "salt": "<base64-encoded-16-bytes>",
            "nonce": "<base64-encoded-12-bytes>",
            "ciphertext": "<base64-encoded-ciphertext-with-gcm-tag>"
        }

    Argon2id Parameter Recommendations:
    - time_cost: Number of iterations (default: 3, OWASP min: 2, recommended: 2-4)
    - memory_cost: Memory in KiB (default: 65536 = 64 MB, OWASP min: 19456 = 19 MB)
    - parallelism: Number of threads (default: 4, OWASP min: 1, recommended: 1-4)
    - hash_len: Output key length in bytes (default: 32 = 256 bits, for AES-256)
    - salt_len: Salt length in bytes (default: 16 = 128 bits, NIST min: 16)
    - nonce_len: Nonce length in bytes (default: 12 = 96 bits, AES-GCM standard)

    See: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
    """

    # Default Argon2id parameters (recommended by OWASP)
    DEFAULT_TIME_COST = 3  # Number of iterations
    DEFAULT_MEMORY_COST = 65536  # 64 MB (in KiB)
    DEFAULT_PARALLELISM = 4  # Number of threads
    DEFAULT_HASH_LEN = 32  # 256 bits (for AES-256)
    DEFAULT_SALT_LEN = 16  # 128 bits
    DEFAULT_NONCE_LEN = 12  # 96 bits (AES-GCM standard)

    # Validation bounds (based on OWASP and security best practices)
    MIN_TIME_COST = 1  # Absolute minimum
    MAX_TIME_COST = 100  # Prevent DoS
    MIN_MEMORY_COST = 8192  # 8 MB absolute minimum
    MAX_MEMORY_COST = 1048576  # 1 GB max (prevent DoS)
    MIN_PARALLELISM = 1
    MAX_PARALLELISM = 64  # Prevent excessive resource usage
    MIN_HASH_LEN = 16  # 128 bits minimum
    MAX_HASH_LEN = 64  # 512 bits maximum
    MIN_SALT_LEN = 8  # Absolute minimum (NIST recommends 16)
    MAX_SALT_LEN = 64  # Reasonable maximum
    MIN_NONCE_LEN = 12  # AES-GCM standard
    MAX_NONCE_LEN = 16  # Reasonable maximum

    def __init__(
        self,
        counter_file: Path | None = None,
        time_cost: int | None = None,
        memory_cost: int | None = None,
        parallelism: int | None = None,
        hash_len: int | None = None,
        salt_len: int | None = None,
        nonce_len: int | None = None,
    ):
        """Initialize the vault with configurable cryptographic parameters.

        Args:
            counter_file: Path used to persist the monotonic counter for rollback protection.
            time_cost: Argon2 time cost (iterations). Default: 3 (OWASP recommended)
            memory_cost: Argon2 memory cost in KiB. Default: 65536 (64 MB)
            parallelism: Argon2 parallelism (threads). Default: 4
            hash_len: Key length in bytes. Default: 32 (256 bits for AES-256)
            salt_len: Salt length in bytes. Default: 16 (128 bits)
            nonce_len: Nonce length in bytes. Default: 12 (96 bits, AES-GCM standard)

        Raises:
            ValueError: If any parameter is outside acceptable ranges
            ImportError: If required cryptographic libraries are not installed
        """
        if not HAS_ARGON2:
            raise ImportError("argon2-cffi is required for Argon2VaultV3")
        if not HAS_CRYPTOGRAPHY:
            raise ImportError("cryptography is required for Argon2VaultV3")
        if not HAS_FILELOCK:
            raise ImportError("filelock is required for Argon2VaultV3")

        # Set parameters with defaults
        self.time_cost = time_cost if time_cost is not None else self.DEFAULT_TIME_COST
        self.memory_cost = memory_cost if memory_cost is not None else self.DEFAULT_MEMORY_COST
        self.parallelism = parallelism if parallelism is not None else self.DEFAULT_PARALLELISM
        self.hash_len = hash_len if hash_len is not None else self.DEFAULT_HASH_LEN
        self.salt_len = salt_len if salt_len is not None else self.DEFAULT_SALT_LEN
        self.nonce_len = nonce_len if nonce_len is not None else self.DEFAULT_NONCE_LEN

        # Validate parameters
        self._validate_parameters()

        if counter_file is None:
            counter_file = _default_storage_dir(DEFAULT_APP_NAME) / ".vault_counter"
        self.counter_file = Path(counter_file)
        self.counter_file.parent.mkdir(parents=True, exist_ok=True)

        # Lock file for atomic counter operations
        self.lock_file = self.counter_file.parent / ".vault.lock"

    def _validate_parameters(self) -> None:
        """Validate cryptographic parameters against acceptable ranges.

        Raises:
            ValueError: If any parameter is outside acceptable ranges
        """
        # Validate time_cost
        if not (self.MIN_TIME_COST <= self.time_cost <= self.MAX_TIME_COST):
            raise ValueError(
                f"time_cost must be between {self.MIN_TIME_COST} and {self.MAX_TIME_COST}, "
                f"got {self.time_cost}"
            )

        # Validate memory_cost
        if not (self.MIN_MEMORY_COST <= self.memory_cost <= self.MAX_MEMORY_COST):
            raise ValueError(
                f"memory_cost must be between {self.MIN_MEMORY_COST} KiB "
                f"and {self.MAX_MEMORY_COST} KiB, got {self.memory_cost}"
            )

        # Validate parallelism
        if not (self.MIN_PARALLELISM <= self.parallelism <= self.MAX_PARALLELISM):
            raise ValueError(
                f"parallelism must be between {self.MIN_PARALLELISM} and {self.MAX_PARALLELISM}, "
                f"got {self.parallelism}"
            )

        # Validate hash_len (must be valid AES key size)
        valid_key_sizes = [16, 24, 32]  # AES-128, AES-192, AES-256
        if self.hash_len not in valid_key_sizes:
            raise ValueError(
                f"hash_len must be 16, 24, or 32 bytes (AES-128, AES-192, or AES-256), "
                f"got {self.hash_len}"
            )

        # Validate salt_len
        if not (self.MIN_SALT_LEN <= self.salt_len <= self.MAX_SALT_LEN):
            raise ValueError(
                f"salt_len must be between {self.MIN_SALT_LEN} and {self.MAX_SALT_LEN} bytes, "
                f"got {self.salt_len}"
            )
        if self.salt_len < 16:
            LOGGER.warning(
                f"salt_len={self.salt_len} is below NIST recommendation of 16 bytes (128 bits)"
            )

        # Validate nonce_len
        if not (self.MIN_NONCE_LEN <= self.nonce_len <= self.MAX_NONCE_LEN):
            raise ValueError(
                f"nonce_len must be between {self.MIN_NONCE_LEN} and {self.MAX_NONCE_LEN} bytes, "
                f"got {self.nonce_len}"
            )

        # Security warnings for weak configurations
        if self.time_cost < 2:
            LOGGER.warning(
                f"time_cost={self.time_cost} is below OWASP minimum recommendation of 2"
            )
        if self.memory_cost < 19456:  # 19 MB
            LOGGER.warning(
                f"memory_cost={self.memory_cost} KiB is below OWASP minimum recommendation "
                f"of 19456 KiB (19 MB)"
            )

    def get_parameters(self) -> dict[str, int]:
        """Get current cryptographic parameters.

        Returns:
            Dictionary with all configurable parameters
        """
        return {
            "time_cost": self.time_cost,
            "memory_cost": self.memory_cost,
            "parallelism": self.parallelism,
            "hash_len": self.hash_len,
            "salt_len": self.salt_len,
            "nonce_len": self.nonce_len,
        }

    def _load_counter(self) -> int:
        """Load monotonic counter from persistent storage with file locking.

        Must be called within a file lock context.
        """
        if self.counter_file.exists():
            try:
                return int(self.counter_file.read_text().strip())
            except (OSError, ValueError):
                return 0
        return 0

    def _save_counter(self, counter: int) -> None:
        """Save monotonic counter to persistent storage with atomic write.

        Must be called within a file lock context.
        Uses atomic write via temporary file + os.replace().
        """
        try:
            # Write to temp file first
            temp_file = self.counter_file.parent / f".vault_counter.tmp.{os.getpid()}"
            temp_file.write_text(str(counter))

            # Secure permissions (cross-platform)
            secure_file_permissions(temp_file)

            # Atomic replace
            os.replace(temp_file, self.counter_file)
        except OSError as e:
            LOGGER.warning(f"Failed to save vault counter: {e}")

    def encrypt(self, plaintext: str, password: str) -> dict[str, Any]:
        """Encrypt plaintext using Argon2id + AES-256-GCM with rollback protection.

        V4 improvements:
        - Counter is inside the authenticated encrypted payload (tamper-proof)
        - Atomic counter update with file locking
        - Cross-process safe

        Args:
            plaintext: The data to encrypt
            password: The encryption password

        Returns:
            Dictionary with V4 encrypted data (salt, nonce, ciphertext)
        """
        import time

        # NOTE: Lock should be acquired by caller for atomic read-modify-write
        # Increment monotonic counter (rollback protection)
        counter = self._load_counter() + 1

        # Create payload with counter inside (authenticated by AES-GCM)
        payload = {
            "counter": counter,
            "timestamp": int(time.time()),
            "data": plaintext,
        }
        payload_json = json.dumps(payload)

        # Generate random salt and nonce (using configured lengths)
        salt = secrets.token_bytes(self.salt_len)
        nonce = secrets.token_bytes(self.nonce_len)

        # Derive key using Argon2id (using configured parameters)
        key = hash_secret_raw(
            secret=password.encode("utf-8"),
            salt=salt,
            time_cost=self.time_cost,
            memory_cost=self.memory_cost,
            parallelism=self.parallelism,
            hash_len=self.hash_len,
            type=Type.ID,  # Argon2id
        )

        # Encrypt payload with AES-GCM (includes authentication tag)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, payload_json.encode("utf-8"), None)

        # Atomically save counter (after encryption succeeds)
        self._save_counter(counter)

        return {
            "version": "4",
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }

    def decrypt(self, encrypted: dict[str, Any], password: str) -> str:
        """Decrypt ciphertext with rollback protection.

        Supports V4, V3, and V2 formats for backwards compatibility.

        Args:
            encrypted: Dictionary with encrypted data from encrypt()
            password: The decryption password

        Returns:
            The decrypted plaintext

        Raises:
            ValueError: If rollback detected, authentication fails, or decryption fails
        """
        # Check version
        version = encrypted.get("version", "2")

        if version == "4":
            return self._decrypt_v4(encrypted, password)
        elif version == "3":
            return self._decrypt_v3(encrypted, password)
        elif version == "2":
            return self._decrypt_v2(encrypted, password)
        else:
            raise ValueError(f"Unsupported vault version: {version}")

    def _decrypt_v4(self, encrypted: dict[str, Any], password: str) -> str:
        """Decrypt V4 format with counter inside authenticated payload.

        V4 improvements:
        - Counter is inside the encrypted payload (tamper-proof)
        - File locking for cross-process safety
        - Atomic counter updates

        Args:
            encrypted: V4 format encrypted data
            password: Decryption password

        Returns:
            Decrypted plaintext

        Raises:
            ValueError: If rollback detected, authentication fails, or decryption fails
        """
        # Extract components (V4)
        salt = base64.b64decode(encrypted["salt"])
        nonce = base64.b64decode(encrypted["nonce"])
        ciphertext = base64.b64decode(encrypted["ciphertext"])

        # Derive key (using configured parameters)
        key = hash_secret_raw(
            secret=password.encode("utf-8"),
            salt=salt,
            time_cost=self.time_cost,
            memory_cost=self.memory_cost,
            parallelism=self.parallelism,
            hash_len=self.hash_len,
            type=Type.ID,
        )

        # Decrypt (AES-GCM verifies authentication tag automatically)
        try:
            aesgcm = AESGCM(key)
            payload_json = aesgcm.decrypt(nonce, ciphertext, None)
            payload = json.loads(payload_json.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Decryption or authentication failed: {e}")

        # Extract counter from authenticated payload
        vault_counter = payload.get("counter", 0)

        # NOTE: Lock should be acquired by caller for atomic read-modify-write
        # Rollback protection: verify counter hasn't decreased
        current_counter = self._load_counter()
        if vault_counter < current_counter:
            raise VaultRollbackError(
                f"Vault rollback attack detected! "
                f"Current counter: {current_counter}, Vault counter: {vault_counter}. "
                f"Someone may be trying to restore an old vault copy.",
                details={
                    "current_counter": current_counter,
                    "vault_counter": vault_counter,
                },
            )

        # Update counter if newer
        if vault_counter > current_counter:
            self._save_counter(vault_counter)

        # Return the actual data
        return payload["data"]

    def _decrypt_v3(self, encrypted: dict[str, Any], password: str) -> str:
        """Decrypt V3 format (counter outside encrypted payload) for backwards compatibility.

        Args:
            encrypted: V3 format encrypted data
            password: Decryption password

        Returns:
            Decrypted plaintext

        Raises:
            ValueError: If rollback detected, authentication fails, or decryption fails
        """
        # Extract components (V3)
        salt = base64.b64decode(encrypted["salt"])
        nonce = base64.b64decode(encrypted["nonce"])
        ciphertext = base64.b64decode(encrypted["ciphertext"])
        vault_counter = encrypted.get("counter", 0)

        # NOTE: Lock should be acquired by caller for atomic read-modify-write
        # Rollback protection: verify counter hasn't decreased
        current_counter = self._load_counter()
        if vault_counter < current_counter:
            raise VaultRollbackError(
                f"Vault rollback attack detected! "
                f"Current counter: {current_counter}, Vault counter: {vault_counter}. "
                f"Someone may be trying to restore an old vault copy.",
                details={
                    "current_counter": current_counter,
                    "vault_counter": vault_counter,
                },
            )

        # Update counter
        if vault_counter > current_counter:
            self._save_counter(vault_counter)

        # Derive key (using configured parameters)
        key = hash_secret_raw(
            secret=password.encode("utf-8"),
            salt=salt,
            time_cost=self.time_cost,
            memory_cost=self.memory_cost,
            parallelism=self.parallelism,
            hash_len=self.hash_len,
            type=Type.ID,
        )

        # Decrypt (AES-GCM verifies authentication tag automatically)
        try:
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")
        except Exception as e:
            raise ValueError(f"Decryption or authentication failed: {e}")

    def _decrypt_v2(self, encrypted: dict[str, Any], password: str) -> str:
        """Decrypt V2 format (with redundant HMAC) for backwards compatibility.

        NOTE: V2 format uses hardcoded parameters (time_cost=3, memory_cost=65536,
        parallelism=4, hash_len=32) for backwards compatibility with older vaults.

        Args:
            encrypted: V2 format encrypted data
            password: Decryption password

        Returns:
            Decrypted plaintext
        """
        salt = base64.b64decode(encrypted["salt"])
        nonce = base64.b64decode(encrypted["nonce"])
        ciphertext = base64.b64decode(encrypted["encrypted_data"])
        stored_hmac = base64.b64decode(encrypted["hmac"])

        # Derive key (V2 uses hardcoded defaults for backwards compatibility)
        key = hash_secret_raw(
            secret=password.encode("utf-8"),
            salt=salt,
            time_cost=self.DEFAULT_TIME_COST,
            memory_cost=self.DEFAULT_MEMORY_COST,
            parallelism=self.DEFAULT_PARALLELISM,
            hash_len=self.DEFAULT_HASH_LEN,
            type=Type.ID,
        )

        # Verify HMAC (V2 compatibility)
        expected_hmac = hmac.new(key, ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(stored_hmac, expected_hmac):
            raise ValueError("HMAC verification failed - data may have been tampered with")

        # Decrypt
        try:
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")
        except Exception as e:
            raise ValueError(f"Decryption failed: {e}")


class SessionKeyManager:
    """Per-session derived keys for memory-only credentials.

    This class generates unique encryption keys for each credential in the current
    session, providing isolation even if the session master key is compromised.

    IMPORTANT: Credentials are only valid for the current session. When the process
    ends, all credentials in the memory backend are lost.

    Session Rotation:
    - Use rotate_session_with_reencryption() to safely rotate keys
    - Rotation invalidates old keys but can re-encrypt existing credentials
    - Configure max_age policy with should_rotate()
    - Default recommendation: rotate every 1 hour

    Example:
        >>> manager = SessionKeyManager()
        >>> # Store some credentials...
        >>> if manager.should_rotate():
        ...     manager.rotate_session_with_reencryption(credential_store)
    """

    def __init__(
        self,
        max_age: timedelta = timedelta(hours=1),
        auto_rotate: bool = False,
        rotation_callback: Callable[[SessionKeyManager], None] | None = None,
    ):
        """Initialize session manager with unique session ID and master key.

        Args:
            max_age: Maximum session age before rotation is recommended (default: 1 hour)
            auto_rotate: Enable automatic background rotation (default: False)
            rotation_callback: Callback function for automatic rotation.
                             Called with SessionKeyManager instance when rotation occurs.
                             The callback should handle credential re-encryption.
        """
        if not HAS_CRYPTOGRAPHY:
            raise ImportError("cryptography is required for SessionKeyManager")

        self.session_id = secrets.token_bytes(32)
        self.master_key = secrets.token_bytes(32)
        self.start_time = datetime.now()
        self.max_age = max_age
        self._rotation_count = 0

        # Auto-rotation support
        self._auto_rotate = auto_rotate
        self._rotation_callback = rotation_callback
        self._rotation_timer: threading.Timer | None = None
        self._shutdown_event = threading.Event()

        # Start auto-rotation if enabled
        if self._auto_rotate:
            self._schedule_rotation()

    def derive_key(self, service: str, key: str) -> bytes:
        """Derive a unique key for a specific credential.

        Args:
            service: Service name (e.g., "okta")
            key: Credential key (e.g., "token")

        Returns:
            32-byte derived key
        """
        info = f"{service}:{key}".encode() + self.session_id

        hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info)
        return hkdf.derive(self.master_key)

    def _rotate_session(self) -> None:
        """Rotate session keys (DEPRECATED - use rotate_session_with_reencryption).

        WARNING: This invalidates all existing encrypted credentials in memory!
        Only use when you explicitly need to rotate keys and can re-encrypt all
        credentials in the memory backend.

        Deprecated: Use rotate_session_with_reencryption() instead for safer rotation.
        """
        old_session_id = self.session_id.hex()[:8]

        # Generate new session
        self.session_id = secrets.token_bytes(32)
        self.master_key = secrets.token_bytes(32)
        self.start_time = datetime.now()
        self._rotation_count += 1

        # Log rotation (no secrets)
        LOGGER.warning(
            f"Session rotated (DEPRECATED method): {old_session_id}... → "
            f"{self.session_id.hex()[:8]}... (rotation #{self._rotation_count})"
        )

    def rotate_session_with_reencryption(
        self,
        credential_store: dict[tuple[str, str], bytes],
        on_failure: str = "skip",
    ) -> tuple[int, int, list[str]]:
        """Safely rotate session keys with automatic credential re-encryption.

        This method:
        1. Decrypts all credentials with old keys
        2. Generates new session keys
        3. Re-encrypts all credentials with new keys
        4. Updates the credential store in place

        Args:
            credential_store: Dictionary mapping (service, key) -> encrypted_bytes
                             This will be modified in place with re-encrypted credentials
            on_failure: What to do if re-encryption fails:
                       "skip" - Skip failed credentials (they become invalid)
                       "abort" - Abort rotation if any credential fails
                       "invalidate" - Remove failed credentials from store

        Returns:
            Tuple of (success_count, failure_count, error_messages)

        Raises:
            ValueError: If on_failure="abort" and any credential fails to re-encrypt

        Example:
            >>> manager = SessionKeyManager()
            >>> memory_store = {}  # Your credential store
            >>> # ... add credentials to store ...
            >>> if manager.should_rotate():
            ...     success, failed, errors = manager.rotate_session_with_reencryption(
            ...         memory_store, on_failure="skip"
            ...     )
            ...     print(f"Rotated {success} credentials, {failed} failed")
        """
        if not credential_store:
            # No credentials to re-encrypt, just rotate
            self._rotate_session()
            return (0, 0, [])

        # Step 1: Decrypt all credentials with current keys
        decrypted_credentials = {}
        decrypt_errors = []

        for (service, key), encrypted_bytes in credential_store.items():
            try:
                # Derive current key
                derived_key = self.derive_key(service, key)
                # Decrypt with current key
                plaintext = self.decrypt(encrypted_bytes, derived_key)
                decrypted_credentials[(service, key)] = plaintext
            except Exception as e:
                error_msg = f"Failed to decrypt {service}.{key}: {e}"
                decrypt_errors.append(error_msg)
                LOGGER.error(error_msg)

                if on_failure == "abort":
                    raise ValueError(
                        f"Rotation aborted: {error_msg}. "
                        f"Fix the issue or use on_failure='skip'"
                    )

        # Step 2: Generate new session keys
        old_session_id = self.session_id.hex()[:8]
        self.session_id = secrets.token_bytes(32)
        self.master_key = secrets.token_bytes(32)
        self.start_time = datetime.now()
        self._rotation_count += 1

        # Step 3: Re-encrypt all credentials with new keys
        success_count = 0
        failure_count = 0
        reencrypt_errors = []

        for (service, key), plaintext in decrypted_credentials.items():
            try:
                # Derive new key
                new_derived_key = self.derive_key(service, key)
                # Encrypt with new key
                new_encrypted = self.encrypt(plaintext, new_derived_key)
                # Update store
                credential_store[(service, key)] = new_encrypted
                success_count += 1
            except Exception as e:
                error_msg = f"Failed to re-encrypt {service}.{key}: {e}"
                reencrypt_errors.append(error_msg)
                failure_count += 1
                LOGGER.error(error_msg)

                if on_failure == "abort":
                    # Rotation already happened, can't roll back
                    raise ValueError(
                        f"Rotation partially completed: {error_msg}. "
                        f"{success_count} credentials re-encrypted, {failure_count} failed"
                    )
                elif on_failure == "invalidate":
                    # Remove failed credential from store
                    credential_store.pop((service, key), None)

        # Handle credentials that failed to decrypt
        for (service, key), encrypted_bytes in list(credential_store.items()):
            if (service, key) not in decrypted_credentials:
                # This credential failed to decrypt
                failure_count += 1
                if on_failure == "invalidate":
                    credential_store.pop((service, key), None)

        # Log rotation
        LOGGER.info(
            f"Session rotated: {old_session_id}... → {self.session_id.hex()[:8]}... "
            f"(rotation #{self._rotation_count}): "
            f"{success_count} credentials re-encrypted, {failure_count} failed"
        )

        all_errors = decrypt_errors + reencrypt_errors
        return (success_count, failure_count, all_errors)

    def encrypt(self, plaintext: str, derived_key: bytes) -> bytes:
        """Encrypt data with a derived key.

        Args:
            plaintext: Data to encrypt
            derived_key: Key from derive_key()

        Returns:
            Encrypted data (nonce + ciphertext)
        """
        nonce = secrets.token_bytes(12)
        aesgcm = AESGCM(derived_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return nonce + ciphertext

    def decrypt(self, encrypted: bytes, derived_key: bytes) -> str:
        """Decrypt data with a derived key.

        Args:
            encrypted: Data from encrypt()
            derived_key: Key from derive_key()

        Returns:
            Decrypted plaintext
        """
        nonce = encrypted[:12]
        ciphertext = encrypted[12:]
        aesgcm = AESGCM(derived_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")

    def session_age(self) -> timedelta:
        """Get the age of the current session.

        Returns:
            Time elapsed since session start
        """
        return datetime.now() - self.start_time

    def should_rotate(self, max_age: timedelta | None = None) -> bool:
        """Check if session should be rotated.

        Args:
            max_age: Maximum session age before rotation (default: use self.max_age)

        Returns:
            True if session should be rotated

        Example:
            >>> manager = SessionKeyManager(max_age=timedelta(hours=2))
            >>> if manager.should_rotate():
            ...     # Time to rotate
            ...     manager.rotate_session_with_reencryption(credential_store)
        """
        if max_age is None:
            max_age = self.max_age
        return self.session_age() >= max_age

    def get_rotation_count(self) -> int:
        """Get the number of times this session has been rotated.

        Returns:
            Number of rotations
        """
        return self._rotation_count

    def get_session_info(self) -> dict[str, Any]:
        """Get session information for monitoring/debugging.

        Returns:
            Dictionary with session information (no secrets)
        """
        return {
            "session_id_prefix": self.session_id.hex()[:8],
            "start_time": self.start_time.isoformat(),
            "age_seconds": self.session_age().total_seconds(),
            "max_age_seconds": self.max_age.total_seconds(),
            "rotation_count": self._rotation_count,
            "should_rotate": self.should_rotate(),
            "auto_rotate_enabled": self._auto_rotate,
        }

    def _schedule_rotation(self) -> None:
        """Schedule next automatic rotation based on max_age.

        This is an internal method called automatically when auto_rotate is enabled.
        The rotation will occur when the session age exceeds max_age.
        """
        if self._shutdown_event.is_set():
            return

        # Calculate time until next rotation
        age = self.session_age()
        remaining = self.max_age - age

        if remaining <= timedelta(0):
            # Already past max_age, rotate immediately
            remaining = timedelta(seconds=1)

        # Schedule timer
        self._rotation_timer = threading.Timer(
            remaining.total_seconds(),
            self._auto_rotation_callback,
        )
        self._rotation_timer.daemon = True  # Don't block application shutdown
        self._rotation_timer.start()

        LOGGER.debug(
            f"Scheduled automatic rotation in {remaining.total_seconds():.1f} seconds"
        )

    def _auto_rotation_callback(self) -> None:
        """Internal callback for automatic rotation.

        This is called by the Timer thread when automatic rotation is triggered.
        It invokes the user-provided rotation callback if available.
        """
        if self._shutdown_event.is_set():
            return

        try:
            LOGGER.info("Automatic session rotation triggered")

            if self._rotation_callback:
                # User callback should handle re-encryption
                self._rotation_callback(self)
                LOGGER.info("Automatic rotation completed via user callback")
            else:
                # No callback provided - just rotate (credentials will be invalid)
                LOGGER.warning(
                    "Auto-rotating without credential store callback - "
                    "credentials will be lost. Provide rotation_callback to handle re-encryption."
                )
                self._rotate_session()

            # Schedule next rotation
            if self._auto_rotate and not self._shutdown_event.is_set():
                self._schedule_rotation()

        except Exception as e:
            LOGGER.error(f"Automatic rotation failed: {e}", exc_info=True)
            # Don't reschedule on error - let user fix the issue

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop automatic rotation and wait for pending rotations.

        This should be called before application shutdown to ensure graceful
        termination of background rotation threads.

        Args:
            timeout: Maximum time to wait for pending rotation (seconds)

        Example:
            >>> manager = SessionKeyManager(auto_rotate=True, rotation_callback=callback)
            >>> # ... use manager ...
            >>> manager.shutdown()  # Clean shutdown
        """
        LOGGER.debug("Shutting down SessionKeyManager")
        self._shutdown_event.set()

        if self._rotation_timer and self._rotation_timer.is_alive():
            self._rotation_timer.cancel()
            self._rotation_timer.join(timeout=timeout)

            if self._rotation_timer.is_alive():
                LOGGER.warning(
                    f"Rotation timer did not stop within {timeout}s timeout"
                )

        LOGGER.debug("SessionKeyManager shutdown complete")

    def __enter__(self) -> SessionKeyManager:
        """Context manager entry - returns self."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - automatically calls shutdown().

        Example:
            >>> with SessionKeyManager(auto_rotate=True, rotation_callback=callback) as mgr:
            ...     # Use manager
            ...     pass
            ... # Automatically shut down
        """
        self.shutdown()


class AuditLogger:
    """Comprehensive audit logging with no secret exposure.

    All credential operations are logged to an audit file for compliance
    and security monitoring. Logs NEVER contain actual credential values.

    Security Feature: Identifier logging is opt-in (default: OFF) to prevent
    metadata leakage. When disabled, logs only track that operations occurred,
    not which specific credentials were accessed.
    """

    def __init__(
        self,
        log_file: Path | None = None,
        callback: Callable | None = None,
        log_identifiers: bool = False,
    ):
        """Initialize audit logger.

        Args:
            log_file: Path to audit log file (default: ~/.layered-credentials/audit.log)
            callback: Optional callback function for real-time event handling
            log_identifiers: Whether to log service/key identifiers (default: False for privacy)
        """
        if log_file is None:
            log_file = _default_storage_dir(DEFAULT_APP_NAME) / "audit.log"

        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.callback = callback
        self.log_identifiers = log_identifiers
        self._lock = threading.Lock()

    def _write_event(self, event: dict[str, Any]) -> None:
        """Write event to log file.

        Args:
            event: Event dictionary
        """
        with self._lock:
            with open(self.log_file, "a") as f:
                f.write(json.dumps(event) + "\n")

        # Call callback if provided
        if self.callback:
            try:
                self.callback(event)
            except Exception as e:
                LOGGER.error(f"Audit callback failed: {e}")

    def log_store(
        self, service: str, key: str, success: bool, metadata: dict | None = None
    ) -> None:
        """Log credential storage event.

        Args:
            service: Service name
            key: Credential key
            success: Whether operation succeeded
            metadata: Additional metadata (never include actual credential value!)
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "credential_stored",
            "service": service if self.log_identifiers else "***",
            "key": key if self.log_identifiers else "***",
            "success": success,
            "metadata": metadata or {},
        }
        self._write_event(event)

    def log_retrieve(self, service: str, key: str, success: bool) -> None:
        """Log credential retrieval event."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "credential_retrieved",
            "service": service if self.log_identifiers else "***",
            "key": key if self.log_identifiers else "***",
            "success": success,
            "metadata": {},
        }
        self._write_event(event)

    def log_delete(self, service: str, key: str, success: bool) -> None:
        """Log credential deletion event."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "credential_deleted",
            "service": service if self.log_identifiers else "***",
            "key": key if self.log_identifiers else "***",
            "success": success,
            "metadata": {},
        }
        self._write_event(event)

    def log_rotate(self, service: str, key: str, success: bool) -> None:
        """Log credential rotation event."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "credential_rotated",
            "service": service if self.log_identifiers else "***",
            "key": key if self.log_identifiers else "***",
            "success": success,
            "metadata": {},
        }
        self._write_event(event)

    def log_failed_access(self, service: str, key: str, reason: str) -> None:
        """Log failed access attempt."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "access_failed",
            "service": service if self.log_identifiers else "***",
            "key": key if self.log_identifiers else "***",
            "success": False,
            "metadata": {"reason": reason},
        }
        self._write_event(event)

    def get_recent_events(self, limit: int = 20) -> list[dict]:
        """Get recent audit events.

        Args:
            limit: Maximum number of events to return

        Returns:
            List of event dictionaries
        """
        if not self.log_file.exists():
            return []

        with open(self.log_file) as f:
            lines = f.readlines()

        events = []
        for line in lines[-limit:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        return events

    def get_credential_history(self, service: str, key: str) -> list[dict]:
        """Get history for a specific credential.

        Args:
            service: Service name
            key: Credential key

        Returns:
            List of events for this credential
        """
        if not self.log_file.exists():
            return []

        with open(self.log_file) as f:
            lines = f.readlines()

        events = []
        for line in lines:
            try:
                event = json.loads(line)
                if event.get("service") == service and event.get("key") == key:
                    events.append(event)
            except json.JSONDecodeError:
                continue

        return events


class TamperEvidentAuditLogger(AuditLogger):
    """Audit logger with tamper-evidence via HMAC chaining.

    Each log entry includes:
    - event_json: The actual event data
    - prev_hash: HMAC of the previous entry
    - current_hash: HMAC(audit_key, prev_hash || event_json)

    This creates a hash chain where tampering with any entry breaks the chain.

    Security Features:
    - Tamper detection: Modifying any log entry invalidates all subsequent hashes
    - Insertion detection: Cannot insert entries without breaking the chain
    - Truncation detection: Truncating log removes valid entries
    - Deletion detection: Deleting entries breaks the chain

    The audit key can be:
    - Derived from vault password using HKDF
    - Provided explicitly as a separate key
    - Automatically generated and stored securely
    """

    def __init__(
        self,
        log_file: Path | None = None,
        callback: Callable | None = None,
        log_identifiers: bool = False,
        audit_key: bytes | None = None,
        vault_password: str | None = None,
        enable_tamper_evidence: bool = True,
        audit_key_backend: AuditKeyBackend | None = None,
    ):
        """Initialize tamper-evident audit logger.

        Args:
            log_file: Path to audit log file
            callback: Optional callback function for real-time event handling
            log_identifiers: Whether to log service/key identifiers
            audit_key: Explicit audit key (32 bytes). If None, will be derived or loaded.
            vault_password: Vault password to derive audit key from (via HKDF)
            enable_tamper_evidence: Enable tamper-evidence (default: True)
            audit_key_backend: Backend for storing audit keys (default: FileAuditKeyBackend)
                             Options: FileAuditKeyBackend, KeyringAuditKeyBackend, EnvironmentAuditKeyBackend
        """
        super().__init__(log_file, callback, log_identifiers)

        self.enable_tamper_evidence = enable_tamper_evidence
        self.audit_key_backend = audit_key_backend

        if not self.enable_tamper_evidence:
            # Fall back to standard audit logging
            self.audit_key = None
            self.audit_key_backend = None
            return

        if not HAS_CRYPTOGRAPHY:
            LOGGER.warning(
                "cryptography library not available, disabling tamper-evidence"
            )
            self.enable_tamper_evidence = False
            self.audit_key = None
            self.audit_key_backend = None
            return

        # Initialize backend if not provided (backwards compatibility)
        if self.audit_key_backend is None and self.log_file:
            # Default to file-based backend for backwards compatibility
            key_file = self.log_file.parent / ".audit_key"
            self.audit_key_backend = FileAuditKeyBackend(key_file)
            LOGGER.debug(f"Using default FileAuditKeyBackend with key file: {key_file}")

        # Initialize or load audit key
        if audit_key:
            # Explicit key provided
            if len(audit_key) != 32:
                raise ValueError("Audit key must be 32 bytes")
            self.audit_key = audit_key
        elif vault_password:
            # Derive from vault password
            self.audit_key = self._derive_audit_key(vault_password)
        else:
            # Load or generate key using backend
            self.audit_key = self._load_or_generate_audit_key()

        # Load previous hash from last entry
        self._prev_hash = self._load_last_hash()

    def _derive_audit_key(self, vault_password: str) -> bytes:
        """Derive audit key from vault password using HKDF.

        Args:
            vault_password: Vault password

        Returns:
            32-byte audit key
        """
        # Use HKDF to derive audit key from vault password
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"audit-key-salt",  # Fixed salt for deterministic derivation
            info=b"layered-credentials-audit-key",
        )
        return hkdf.derive(vault_password.encode("utf-8"))

    def _load_or_generate_audit_key(self) -> bytes:
        """Load existing audit key or generate new one using the configured backend.

        If no backend is configured, generates a key but does not store it (in-memory only).

        Returns:
            32-byte audit key
        """
        # Try to retrieve existing key from backend
        if self.audit_key_backend:
            try:
                existing_key = self.audit_key_backend.retrieve_key()
                if existing_key:
                    LOGGER.debug("Loaded existing audit key from backend")
                    return existing_key
            except Exception as e:
                LOGGER.warning(f"Failed to load audit key from backend: {e}, generating new key")

        # Generate new key
        audit_key = secrets.token_bytes(32)
        LOGGER.debug("Generated new audit key")

        # Save key to backend
        if self.audit_key_backend:
            try:
                self.audit_key_backend.store_key(audit_key)
                LOGGER.debug("Stored new audit key to backend")
            except Exception as e:
                LOGGER.error(f"Failed to save audit key to backend: {e}")
        else:
            LOGGER.warning(
                "No audit key backend configured - key will only be available for this session"
            )

        return audit_key

    def _load_last_hash(self) -> str:
        """Load the hash of the last entry in the log.

        Robust implementation that handles:
        - Incomplete lines (interrupted writes)
        - UTF-8 decoding errors (seeking mid-character)
        - Corrupted JSON entries
        - Very long lines (expands buffer as needed)

        Returns:
            Previous hash (hex string) or empty string if log is empty
        """
        if not self.log_file.exists():
            return ""

        try:
            with open(self.log_file, "rb") as f:
                # Get file size
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                if file_size == 0:
                    return ""

                # Start with 4KB buffer, expand if needed
                buffer_size = min(4096, file_size)
                max_buffer = min(1024 * 1024, file_size)  # Max 1MB to prevent memory issues

                while buffer_size <= max_buffer:
                    # Seek to position
                    f.seek(max(0, file_size - buffer_size))
                    buffer = f.read(buffer_size)

                    # Try to decode UTF-8
                    try:
                        text = buffer.decode("utf-8")
                    except UnicodeDecodeError:
                        # Might have split a UTF-8 character, expand buffer
                        if buffer_size < max_buffer:
                            buffer_size = min(buffer_size * 2, max_buffer)
                            continue
                        else:
                            # Give up, try with error handling
                            text = buffer.decode("utf-8", errors="ignore")

                    # Split into lines
                    lines = text.splitlines()

                    # If we didn't read from the start, first line might be incomplete
                    if file_size - buffer_size > 0 and lines:
                        lines = lines[1:]  # Skip potentially incomplete first line

                    # Process lines in reverse order
                    for line in reversed(lines):
                        line = line.strip()
                        if not line:
                            continue

                        # Try to parse JSON
                        try:
                            entry = json.loads(line)
                            # Must have current_hash to be valid
                            if "current_hash" in entry:
                                return entry.get("current_hash", "")
                        except json.JSONDecodeError:
                            # Line is corrupted, try next one
                            continue

                    # No valid entry found in buffer, expand if possible
                    if buffer_size < max_buffer:
                        buffer_size = min(buffer_size * 2, max_buffer)
                    else:
                        # Searched entire file (or 1MB), no valid entry
                        break

        except Exception as e:
            LOGGER.error(f"Failed to load last hash: {e}")

        return ""

    def _compute_hash(self, prev_hash: str, event_json: str) -> str:
        """Compute HMAC for an event.

        Args:
            prev_hash: Previous entry's hash (hex string)
            event_json: Event data as JSON string

        Returns:
            HMAC as hex string
        """
        if not self.audit_key:
            return ""

        # Combine prev_hash and event_json
        data = prev_hash.encode("utf-8") + b"||" + event_json.encode("utf-8")

        # Compute HMAC
        h = hmac.new(self.audit_key, data, hashlib.sha256)
        return h.hexdigest()

    def _write_event(self, event: dict[str, Any]) -> None:
        """Write event to log file with tamper-evidence.

        Args:
            event: Event dictionary
        """
        with self._lock:
            if self.enable_tamper_evidence and self.audit_key:
                # Create tamper-evident entry
                event_json = json.dumps(event, sort_keys=True)
                current_hash = self._compute_hash(self._prev_hash, event_json)

                entry = {
                    "event": event,
                    "prev_hash": self._prev_hash,
                    "current_hash": current_hash,
                }

                # Write entry
                with open(self.log_file, "a") as f:
                    f.write(json.dumps(entry) + "\n")

                # Update previous hash for next entry
                self._prev_hash = current_hash
            else:
                # Fall back to standard logging
                with open(self.log_file, "a") as f:
                    f.write(json.dumps(event) + "\n")

        # Call callback if provided
        if self.callback:
            try:
                self.callback(event)
            except Exception as e:
                LOGGER.error(f"Audit callback failed: {e}")

    def verify_log(self) -> tuple[bool, list[str]]:
        """Verify the integrity of the audit log.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        if not self.enable_tamper_evidence or not self.audit_key:
            return (False, ["Tamper-evidence not enabled"])

        if not self.log_file.exists():
            return (True, [])  # Empty log is valid

        errors = []
        prev_hash = ""
        line_num = 0

        try:
            with open(self.log_file) as f:
                for line in f:
                    line_num += 1
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError as e:
                        errors.append(f"Line {line_num}: Invalid JSON - {e}")
                        continue

                    # Check for tamper-evident format
                    if "event" not in entry or "current_hash" not in entry:
                        # Old format (non-tamper-evident)
                        errors.append(
                            f"Line {line_num}: Not in tamper-evident format "
                            "(missing 'event' or 'current_hash')"
                        )
                        continue

                    # Verify prev_hash matches (constant-time comparison)
                    entry_prev_hash = entry.get("prev_hash", "")
                    if not hmac.compare_digest(entry_prev_hash, prev_hash):
                        errors.append(
                            f"Line {line_num}: prev_hash mismatch (hash chain broken)"
                        )
                        # Log detailed info securely for debugging (not returned to caller)
                        LOGGER.debug(
                            f"Line {line_num}: prev_hash mismatch - "
                            f"expected '{prev_hash}', got '{entry_prev_hash}'"
                        )

                    # Verify current_hash is correct (constant-time comparison)
                    event_json = json.dumps(entry["event"], sort_keys=True)
                    expected_hash = self._compute_hash(prev_hash, event_json)
                    entry_current_hash = entry.get("current_hash", "")

                    if not hmac.compare_digest(entry_current_hash, expected_hash):
                        errors.append(
                            f"Line {line_num}: current_hash mismatch (entry tampered)"
                        )
                        # Log detailed info securely for debugging (not returned to caller)
                        LOGGER.debug(
                            f"Line {line_num}: current_hash mismatch - "
                            f"expected '{expected_hash}', got '{entry_current_hash}'"
                        )

                    # Update prev_hash for next iteration
                    prev_hash = entry["current_hash"]

        except Exception as e:
            errors.append(f"Failed to read log file: {e}")

        is_valid = len(errors) == 0
        return (is_valid, errors)

    def get_recent_events(self, limit: int = 20) -> list[dict]:
        """Get recent audit events (unwraps tamper-evident format).

        Args:
            limit: Maximum number of events to return

        Returns:
            List of event dictionaries
        """
        if not self.log_file.exists():
            return []

        with open(self.log_file) as f:
            lines = f.readlines()

        events = []
        for line in lines[-limit:]:
            try:
                data = json.loads(line)
                # Check if it's tamper-evident format
                if "event" in data:
                    events.append(data["event"])
                else:
                    # Old format
                    events.append(data)
            except json.JSONDecodeError:
                continue

        return events

    def get_credential_history(self, service: str, key: str) -> list[dict]:
        """Get history for a specific credential (unwraps tamper-evident format).

        Args:
            service: Service name
            key: Credential key

        Returns:
            List of events for this credential
        """
        if not self.log_file.exists():
            return []

        with open(self.log_file) as f:
            lines = f.readlines()

        events = []
        for line in lines:
            try:
                data = json.loads(line)
                # Check if it's tamper-evident format
                if "event" in data:
                    event = data["event"]
                else:
                    event = data

                if event.get("service") == service and event.get("key") == key:
                    events.append(event)
            except json.JSONDecodeError:
                continue

        return events

    def rotate_audit_key(self, new_vault_password: str | None = None) -> None:
        """Rotate the audit HMAC key when vault password changes.

        This ensures that after a password rotation:
        - Old audit entries remain valid with the old key
        - New entries use a new key derived from the new password
        - A marker event is logged to indicate the key rotation point

        Args:
            new_vault_password: New vault password to derive new audit key from.
                               If None, generates a new random key.

        Example:
            >>> logger = TamperEvidentAuditLogger(vault_password="old_pass")
            >>> logger.rotate_audit_key(new_vault_password="new_pass")
        """
        if not self.enable_tamper_evidence or not self.audit_key:
            LOGGER.warning("Audit key rotation skipped - tamper-evidence not enabled")
            return

        import time

        with self._lock:
            # Log key rotation marker with old key
            rotation_event = {
                "timestamp": datetime.now().isoformat(),
                "event_type": "audit_key_rotated",
                "reason": "vault_password_change",
                "metadata": {
                    "old_key_hash": hashlib.sha256(self.audit_key).hexdigest()[:16],
                    "rotation_time": int(time.time()),
                },
            }

            # Write rotation marker with current (old) key
            self._write_event(rotation_event)

            # Derive or generate new key
            if new_vault_password:
                new_key = self._derive_audit_key(new_vault_password)
            else:
                new_key = secrets.token_bytes(32)

            # Update to new key
            self.audit_key = new_key

            # Reset hash chain (new key starts fresh chain)
            self._prev_hash = ""

            LOGGER.info(
                f"Audit key rotated (old key hash: {rotation_event['metadata']['old_key_hash']})"
            )


# Pydantic models for schema validation
if HAS_PYDANTIC:

    class OktaConfig(BaseModel):
        """Okta configuration schema."""

        domain: str = Field(..., description="Okta domain (e.g., company.okta.com)")
        token: str = Field(..., min_length=20, description="Okta API token")
        rate_limit_per_minute: int = Field(default=600, ge=1, le=10000)
        page_size: int = Field(default=200, ge=1, le=10000)

        @field_validator("domain")
        @classmethod
        def validate_domain(cls, v: str) -> str:
            if not v.endswith(".okta.com"):
                raise ValueError("Okta domain must end with .okta.com")
            return v

    class OneLoginConfig(BaseModel):
        """OneLogin configuration schema."""

        client_id: str = Field(..., description="OneLogin client ID")
        client_secret: str = Field(..., description="OneLogin client secret")
        region: Literal["us", "eu"] = Field(..., description="OneLogin region")
        subdomain: str | None = Field(None, description="OneLogin subdomain")
        rate_limit_per_hour: int = Field(default=5000, ge=1, le=10000)

    class MigrationConfig(BaseModel):
        """Complete migration configuration schema."""

        okta: OktaConfig
        onelogin: OneLoginConfig


class ConfigValidator:
    """Pydantic-based schema validation for YAML configs.

    This class validates configuration files to catch errors before
    credentials are stored or migration begins.
    """

    def __init__(self):
        """Initialize validator."""
        self.has_pydantic = HAS_PYDANTIC

    def validate(self, config: dict[str, Any]) -> tuple[bool, list[str]]:
        """Validate configuration against schema.

        Args:
            config: Configuration dictionary

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        if not self.has_pydantic:
            # Fallback to basic validation
            return self._basic_validation(config)

        try:
            MigrationConfig(**config)
            return (True, [])
        except ValidationError as e:
            errors = [
                f"{err['loc'][0]}.{err['loc'][1] if len(err['loc']) > 1 else ''}: {err['msg']}"
                for err in e.errors()
            ]
            return (False, errors)

    def _basic_validation(self, config: dict[str, Any]) -> tuple[bool, list[str]]:
        """Basic validation without Pydantic.

        Args:
            config: Configuration dictionary

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Check okta section
        if "okta" not in config:
            errors.append("Missing 'okta' section")
        else:
            okta = config["okta"]
            if "domain" not in okta:
                errors.append("okta.domain is required")
            elif not okta["domain"].endswith(".okta.com"):
                errors.append("okta.domain must end with .okta.com")

            if "token" not in okta:
                errors.append("okta.token is required")
            elif len(okta["token"]) < 20:
                errors.append("okta.token too short")

        # Check onelogin section
        if "onelogin" not in config:
            errors.append("Missing 'onelogin' section")
        else:
            ol = config["onelogin"]
            if "client_id" not in ol:
                errors.append("onelogin.client_id is required")
            if "client_secret" not in ol:
                errors.append("onelogin.client_secret is required")
            if "region" not in ol:
                errors.append("onelogin.region is required")
            elif ol["region"] not in ["us", "eu"]:
                errors.append("onelogin.region must be 'us' or 'eu'")

        return (len(errors) == 0, errors)

    def sanitize_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Sanitize config by redacting secrets.

        Args:
            config: Configuration dictionary

        Returns:
            Sanitized copy with secrets redacted
        """
        import copy

        sanitized = copy.deepcopy(config)

        # Redact Okta token
        if "okta" in sanitized and "token" in sanitized["okta"]:
            sanitized["okta"]["token"] = "***REDACTED***"

        # Redact OneLogin secrets
        if "onelogin" in sanitized:
            if "client_secret" in sanitized["onelogin"]:
                sanitized["onelogin"]["client_secret"] = "***REDACTED***"

        return sanitized


class AutoSaveCredentialManager:
    """Main credential manager with auto-save and multi-backend support.

    This is the primary interface for credential management in the application.
    It supports multiple storage backends and provides auto-save functionality
    with debouncing.
    """

    # Patterns that indicate a field contains credentials
    CREDENTIAL_PATTERNS = [
        "token",
        "secret",
        "password",
        "key",
        "api_token",
        "api_key",
        "credential",
        "auth",
        "bearer",
        "client_id",
        "client_secret",
        "access_key",
        "secret_key",
    ]

    def __init__(
        self,
        storage_backend: Literal["keyring", "vault", "memory", "env"] = "keyring",
        vault_password: str | None = None,
        enable_auto_save: bool = True,
        enable_audit_log: bool = True,
        audit_log_identifiers: bool = False,
        auto_save_delay: float = 2.0,
        app_name: str = DEFAULT_APP_NAME,
        storage_dir: str | Path | None = None,
        keyring_service: str | None = None,
        audit_log_file: str | Path | None = None,
    ):
        """Initialize credential manager.

        Args:
            storage_backend: Storage backend to use
            vault_password: Password for vault backend (required if backend="vault")
            enable_auto_save: Enable automatic credential saving
            enable_audit_log: Enable audit logging
            audit_log_identifiers: Log service/key identifiers (default: False for privacy)
            auto_save_delay: Debounce delay in seconds
            app_name: Application name used to derive default paths and identifiers
            storage_dir: Explicit directory for storing vaults, counters, and logs
            keyring_service: Override service identifier used with the OS keyring backend
            audit_log_file: Override path for audit logs
        """
        self.storage_backend = storage_backend
        self.vault_password = vault_password
        self.enable_auto_save = enable_auto_save
        self.enable_audit_log = enable_audit_log
        self.auto_save_delay = auto_save_delay
        self.app_name = app_name.strip() or DEFAULT_APP_NAME

        if storage_dir is not None:
            self.storage_dir = Path(storage_dir).expanduser()
        else:
            self.storage_dir = _default_storage_dir(self.app_name)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.keyring_service = keyring_service or _default_keyring_service(self.app_name)
        if audit_log_file is not None:
            self.audit_log_file = Path(audit_log_file).expanduser()
        else:
            self.audit_log_file = self.storage_dir / "audit.log"
        self.vault_path = self.storage_dir / "vault.enc"
        self.vault_counter_file = self.storage_dir / ".vault_counter"
        self.keyring_tracking_file = self.storage_dir / ".keyring_credentials.json"

        # Initialize components
        self.session_manager = SessionKeyManager() if HAS_CRYPTOGRAPHY else None
        self.audit_logger = (
            AuditLogger(log_file=self.audit_log_file, log_identifiers=audit_log_identifiers)
            if enable_audit_log
            else None
        )
        self.config_validator = ConfigValidator()
        self.vault = (
            Argon2VaultV3(counter_file=self.vault_counter_file)
            if HAS_ARGON2 and HAS_CRYPTOGRAPHY
            else None
        )

        # Memory storage
        self._memory_store: dict[tuple[str, str], bytes] = {}
        self._lock = threading.Lock()

        # Keyring tracking (to support listing and backup)
        self._keyring_store: dict[tuple[str, str], dict[str, Any]] = {}
        if storage_backend == "keyring":
            self._load_keyring_tracking()

        # Validate backend requirements
        if storage_backend == "keyring" and not HAS_KEYRING:
            raise ImportError("keyring library is required for keyring backend")
        if storage_backend == "vault" and not vault_password:
            raise ValueError("vault_password is required when using vault backend")
        if storage_backend == "vault" and not (HAS_ARGON2 and HAS_CRYPTOGRAPHY):
            raise ImportError("argon2-cffi and cryptography are required for vault backend")

    def is_credential_field(self, field_name: str) -> bool:
        """Detect if field name indicates a credential.

        Args:
            field_name: Name of the field

        Returns:
            True if field contains credential data
        """
        field_lower = field_name.lower()
        return any(pattern in field_lower for pattern in self.CREDENTIAL_PATTERNS)

    def auto_save_credential(
        self, service: str, key: str, value: str, expires_in: timedelta | None = None
    ) -> bool:
        """Save credential to appropriate backend.

        Args:
            service: Logical service namespace (e.g., "stripe", "github")
            key: Credential identifier (e.g., "api_token", "client_secret")
            value: Credential value
            expires_in: Optional expiration time

        Returns:
            True if saved successfully
        """
        if not service or not key or not value:
            return False

        try:
            # Create SecureString
            secure_value = SecureString(value)

            # Save to backend
            if self.storage_backend == "keyring":
                self._save_to_keyring(service, key, value)
            elif self.storage_backend == "vault":
                self._save_to_vault(service, key, value, expires_in)
            elif self.storage_backend == "memory":
                self._save_to_memory(service, key, value)
            elif self.storage_backend == "env":
                # Environment variables are read-only
                pass

            # Log audit event
            if self.audit_logger:
                self.audit_logger.log_store(service, key, True, {"backend": self.storage_backend})

            # Zero the secure string
            secure_value.zero()

            return True
        except Exception as e:
            LOGGER.error(f"Failed to save credential {service}.{key}: {e}")
            if self.audit_logger:
                self.audit_logger.log_store(service, key, False, {"error": str(e)})
            return False

    def get_credential(self, service: str, key: str) -> SecureString | None:
        """Retrieve credential from storage.

        Args:
            service: Service name
            key: Credential key

        Returns:
            SecureString with credential value, or None if not found
        """
        try:
            value = None

            # Check backends in order: session memory, persistent storage, env
            if self.storage_backend == "memory":
                value = self._get_from_memory(service, key)
            elif self.storage_backend == "keyring":
                value = self._get_from_keyring(service, key)
            elif self.storage_backend == "vault":
                value = self._get_from_vault(service, key)
            elif self.storage_backend == "env":
                value = self._get_from_env(service, key)

            if value:
                if self.audit_logger:
                    self.audit_logger.log_retrieve(service, key, True)
                return SecureString(value)
            else:
                if self.audit_logger:
                    self.audit_logger.log_retrieve(service, key, False)
                return None
        except Exception as e:
            LOGGER.error(f"Failed to retrieve credential {service}.{key}: {e}")
            if self.audit_logger:
                self.audit_logger.log_failed_access(service, key, str(e))
            return None

    def delete_credential(self, service: str, key: str) -> bool:
        """Delete credential from storage.

        Args:
            service: Service name
            key: Credential key

        Returns:
            True if deleted successfully
        """
        try:
            # Delete from all backends
            if self.storage_backend == "keyring":
                try:
                    keyring.delete_password(self.keyring_service, f"{service}_{key}")
                except keyring.errors.PasswordDeleteError:
                    pass
                # Remove from tracking
                if (service, key) in self._keyring_store:
                    del self._keyring_store[(service, key)]
                    self._save_keyring_tracking()
            elif self.storage_backend == "vault":
                if not self.vault or not self.vault_password:
                    raise ValueError("Vault backend is not initialized")
                if not HAS_FILELOCK:
                    LOGGER.warning("filelock not available, deleting without lock")
                    self._delete_from_vault_unsafe(service, key)
                else:
                    vault_path = self.vault_path
                    if vault_path.exists():
                        # Use vault's canonical lock file for all vault operations
                        vault_lock = self.vault.lock_file

                        # Use file lock for atomic read-modify-write
                        with FileLock(vault_lock, timeout=15):
                            with vault_path.open() as handle:
                                encrypted_vault = json.load(handle)
                            vault_json = self.vault.decrypt(encrypted_vault, self.vault_password)
                            vault_data = json.loads(vault_json) if vault_json else {}

                            service_bucket = vault_data.get(service)
                            if isinstance(service_bucket, dict) and key in service_bucket:
                                del service_bucket[key]
                                if not service_bucket:
                                    vault_data.pop(service, None)

                                if vault_data:
                                    updated_plaintext = json.dumps(vault_data)
                                    encrypted = self.vault.encrypt(
                                        updated_plaintext, self.vault_password
                                    )

                                    # Atomic write: write to temp file then replace
                                    temp_vault = vault_path.parent / f".vault.enc.tmp.{os.getpid()}"
                                    try:
                                        with temp_vault.open("w") as handle:
                                            json.dump(encrypted, handle, indent=2)

                                        # Secure permissions (cross-platform)
                                        secure_file_permissions(temp_vault)

                                        # Atomic replace
                                        os.replace(temp_vault, vault_path)
                                    except Exception as e:
                                        # Clean up temp file on error
                                        if temp_vault.exists():
                                            try:
                                                temp_vault.unlink()
                                            except Exception:
                                                pass
                                        raise ValueError(f"Failed to save vault after delete: {e}")
                                else:
                                    try:
                                        vault_path.unlink()
                                    except FileNotFoundError:
                                        pass
                            # If the credential was not present, nothing to do
            elif self.storage_backend == "memory":
                with self._lock:
                    self._memory_store.pop((service, key), None)

            if self.audit_logger:
                self.audit_logger.log_delete(service, key, True)

            return True
        except Exception as e:
            LOGGER.error(f"Failed to delete credential {service}.{key}: {e}")
            if self.audit_logger:
                self.audit_logger.log_delete(service, key, False)
            return False

    def list_credentials(self) -> list[tuple[str, str, str]]:
        """List all stored credentials.

        Returns:
            List of (service, key, backend) tuples
        """
        credentials = []

        if self.storage_backend == "memory":
            for service, key in self._memory_store.keys():
                credentials.append((service, key, "memory"))
        elif self.storage_backend == "keyring":
            # List from tracking file
            for service, key in self._keyring_store.keys():
                credentials.append((service, key, "keyring"))

        return credentials

    def get_audit_summary(self) -> dict[str, Any]:
        """Return summary of recent audit events.

        Returns:
            Dictionary with audit statistics
        """
        if not self.audit_logger:
            return {"error": "Audit logging not enabled"}

        events = self.audit_logger.get_recent_events(limit=1000)

        by_type = {}
        for event in events:
            event_type = event.get("event_type", "unknown")
            by_type[event_type] = by_type.get(event_type, 0) + 1

        return {
            "total_events": len(events),
            "by_type": by_type,
            "most_accessed": [],  # TODO: Implement
            "recent_failures": [e for e in events if not e.get("success")],
        }

    # Backend implementation methods

    def _save_to_keyring(self, service: str, key: str, value: str) -> None:
        """Save to OS keyring.

        Handles both creating new entries and updating existing ones. On macOS, the keyring
        library may throw error -25244 (duplicate item) when trying to update an existing
        credential. This method handles that by deleting and re-creating the item.

        Also maintains a tracking file to support listing and backup operations.
        """
        if not HAS_KEYRING:
            raise ImportError("keyring library required")
        service_key = f"{service}_{key}"

        try:
            keyring.set_password(self.keyring_service, service_key, value)
        except Exception as e:
            # On macOS, error -25244 (errSecDuplicateItem) means the item already exists
            # Try to delete and re-create it
            error_str = str(e)
            if "-25244" in error_str or "duplicate" in error_str.lower():
                LOGGER.debug(f"Keyring item {service_key} already exists, attempting to update")
                try:
                    # Check if item exists
                    existing = keyring.get_password(self.keyring_service, service_key)
                    if existing is not None:
                        # Delete existing item
                        LOGGER.debug(f"Deleting existing keyring item: {service_key}")
                        keyring.delete_password(self.keyring_service, service_key)
                        # Re-create with new value
                        LOGGER.debug(f"Re-creating keyring item: {service_key}")
                        keyring.set_password(self.keyring_service, service_key, value)
                    else:
                        # Item doesn't exist but we got duplicate error - just retry
                        keyring.set_password(self.keyring_service, service_key, value)
                except Exception as retry_error:
                    # If all attempts fail, log warning but don't crash
                    LOGGER.warning(
                        f"Could not save credential {service}.{key} to keyring: {e}. "
                        f"Retry failed with: {retry_error}. "
                        f"Consider using a different storage backend (vault or memory)."
                    )
                    raise
            else:
                # Different error - just raise it
                raise

        # Track credential for listing and backup
        self._keyring_store[(service, key)] = {
            "service": service,
            "key": key,
            "created_at": datetime.now().isoformat(),
        }
        self._save_keyring_tracking()

    def _get_from_keyring(self, service: str, key: str) -> str | None:
        """Retrieve from OS keyring."""
        if not HAS_KEYRING:
            return None
        service_key = f"{service}_{key}"
        return keyring.get_password(self.keyring_service, service_key)

    def _load_keyring_tracking(self) -> None:
        """Load keyring credential tracking from file."""
        if not self.keyring_tracking_file.exists():
            self._keyring_store = {}
            return

        try:
            with open(self.keyring_tracking_file) as f:
                data = json.load(f)
            # Convert string keys back to tuples
            self._keyring_store = {
                (entry["service"], entry["key"]): entry
                for entry in data.get("credentials", [])
            }
        except Exception as e:
            LOGGER.warning(f"Failed to load keyring tracking: {e}")
            self._keyring_store = {}

    def _save_keyring_tracking(self) -> None:
        """Save keyring credential tracking to file."""
        try:
            # Convert to list format for JSON
            data = {
                "credentials": [
                    {"service": service, "key": key, **metadata}
                    for (service, key), metadata in self._keyring_store.items()
                ],
                "version": "1",
            }
            # Atomic write
            temp_file = self.keyring_tracking_file.with_suffix(".tmp")
            with open(temp_file, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, self.keyring_tracking_file)
        except Exception as e:
            LOGGER.warning(f"Failed to save keyring tracking: {e}")

    def _save_to_vault(
        self, service: str, key: str, value: str, expires_in: timedelta | None
    ) -> None:
        """Save to encrypted vault file with atomic write and file locking.

        This method uses:
        - File locking to prevent concurrent read/write races
        - Atomic writes via temporary file + os.replace()
        - Argon2VaultV3 encryption with rollback protection
        """
        if not self.vault or not self.vault_password:
            raise ValueError("Vault not initialized")
        if not HAS_FILELOCK:
            raise ImportError("filelock is required for vault operations")

        vault_path = self.vault_path
        vault_path.parent.mkdir(parents=True, exist_ok=True)

        # Use vault's canonical lock file for all vault operations
        vault_lock = self.vault.lock_file

        # Use file lock for atomic read-modify-write
        with FileLock(vault_lock, timeout=15):
            # Load existing vault or create new
            vault_data = {}
            if vault_path.exists():
                try:
                    with open(vault_path) as f:
                        encrypted_vault = json.load(f)
                    vault_json = self.vault.decrypt(encrypted_vault, self.vault_password)
                    vault_data = json.loads(vault_json)
                except Exception as e:
                    LOGGER.warning(f"Could not load existing vault: {e}")

            # Add new credential
            if service not in vault_data:
                vault_data[service] = {}
            vault_data[service][key] = {
                "value": value,
                "created": datetime.now().isoformat(),
                "expires": (datetime.now() + expires_in).isoformat() if expires_in else None,
            }

            # Encrypt
            vault_json = json.dumps(vault_data)
            encrypted = self.vault.encrypt(vault_json, self.vault_password)

            # Atomic write: write to temp file then replace
            temp_vault = vault_path.parent / f".vault.enc.tmp.{os.getpid()}"
            try:
                with open(temp_vault, "w") as f:
                    json.dump(encrypted, f, indent=2)

                # Secure permissions (cross-platform)
                secure_file_permissions(temp_vault)

                # Atomic replace
                os.replace(temp_vault, vault_path)
            except Exception as e:
                # Clean up temp file on error
                if temp_vault.exists():
                    try:
                        temp_vault.unlink()
                    except Exception:
                        pass
                raise ValueError(f"Failed to save vault: {e}")

    def _get_from_vault(self, service: str, key: str) -> str | None:
        """Retrieve from encrypted vault with file locking.

        Uses file locking to prevent TOCTOU races with concurrent writes.
        """
        if not self.vault or not self.vault_password:
            return None
        if not HAS_FILELOCK:
            LOGGER.warning("filelock not available, reading vault without lock")
            # Fall back to non-locked read for backwards compatibility
            return self._get_from_vault_unsafe(service, key)

        vault_path = self.vault_path
        if not vault_path.exists():
            return None

        # Use vault's canonical lock file for all vault operations
        vault_lock = self.vault.lock_file

        try:
            with FileLock(vault_lock, timeout=15):
                with open(vault_path) as f:
                    encrypted_vault = json.load(f)
                vault_json = self.vault.decrypt(encrypted_vault, self.vault_password)
                vault_data = json.loads(vault_json)

                if service in vault_data and key in vault_data[service]:
                    credential = vault_data[service][key]
                    # Check expiration
                    if credential.get("expires"):
                        expires = datetime.fromisoformat(credential["expires"])
                        if datetime.now() > expires:
                            return None
                    return credential["value"]
        except Exception as e:
            LOGGER.error(f"Failed to read from vault: {e}")

        return None

    def _get_from_vault_unsafe(self, service: str, key: str) -> str | None:
        """Retrieve from encrypted vault without file locking (fallback).

        Only used when filelock is not available.
        """
        vault_path = self.vault_path
        if not vault_path.exists():
            return None

        try:
            with open(vault_path) as f:
                encrypted_vault = json.load(f)
            vault_json = self.vault.decrypt(encrypted_vault, self.vault_password)
            vault_data = json.loads(vault_json)

            if service in vault_data and key in vault_data[service]:
                credential = vault_data[service][key]
                # Check expiration
                if credential.get("expires"):
                    expires = datetime.fromisoformat(credential["expires"])
                    if datetime.now() > expires:
                        return None
                return credential["value"]
        except Exception as e:
            LOGGER.error(f"Failed to read from vault: {e}")

        return None

    def _delete_from_vault_unsafe(self, service: str, key: str) -> None:
        """Delete from encrypted vault without file locking (fallback).

        Only used when filelock is not available.
        """
        vault_path = self.vault_path
        if not vault_path.exists():
            return

        try:
            with vault_path.open() as handle:
                encrypted_vault = json.load(handle)
            vault_json = self.vault.decrypt(encrypted_vault, self.vault_password)
            vault_data = json.loads(vault_json) if vault_json else {}

            service_bucket = vault_data.get(service)
            if isinstance(service_bucket, dict) and key in service_bucket:
                del service_bucket[key]
                if not service_bucket:
                    vault_data.pop(service, None)

                if vault_data:
                    updated_plaintext = json.dumps(vault_data)
                    encrypted = self.vault.encrypt(updated_plaintext, self.vault_password)
                    with vault_path.open("w") as handle:
                        json.dump(encrypted, handle)
                else:
                    try:
                        vault_path.unlink()
                    except FileNotFoundError:
                        pass
        except Exception as e:
            LOGGER.error(f"Failed to delete from vault: {e}")

    def _save_to_memory(self, service: str, key: str, value: str) -> None:
        """Save to session memory."""
        if not self.session_manager:
            raise ValueError("Session manager not initialized")

        with self._lock:
            session_key = self.session_manager.derive_key(service, key)
            encrypted = self.session_manager.encrypt(value, session_key)
            self._memory_store[(service, key)] = encrypted

    def _get_from_memory(self, service: str, key: str) -> str | None:
        """Retrieve from session memory."""
        if not self.session_manager:
            return None

        with self._lock:
            encrypted = self._memory_store.get((service, key))
            if encrypted:
                session_key = self.session_manager.derive_key(service, key)
                return self.session_manager.decrypt(encrypted, session_key)
        return None

    def _get_from_env(self, service: str, key: str) -> str | None:
        """Read from environment variables."""
        env_var = f"{service.upper()}_{key.upper()}"
        return os.environ.get(env_var)

    def backup_to_file(
        self, backup_path: Path, backup_password: str, vault_password: str | None = None
    ) -> dict[str, Any]:
        """Backup vault credentials to encrypted file.

        Creates an encrypted backup of all credentials stored in the vault backend.
        The backup is encrypted with a separate backup password for additional security.

        Args:
            backup_path: Path where backup file will be created
            backup_password: Password to encrypt the backup (should be different from vault password)
            vault_password: Vault password to decrypt credentials (required if backend is vault)

        Returns:
            Dictionary with backup statistics:
                - credentials_count: Number of credentials backed up
                - backend: Source backend type
                - timestamp: Backup creation timestamp
                - version: Backup format version

        Raises:
            ValueError: If vault backend is used but vault_password is None
            OSError: If backup file cannot be written

        Example:
            >>> manager = AutoSaveCredentialManager(backend="vault")
            >>> stats = manager.backup_to_file(
            ...     Path("backup.enc"),
            ...     backup_password="backup_secret",
            ...     vault_password="vault_secret"
            ... )
            >>> print(f"Backed up {stats['credentials_count']} credentials")
        """
        import time

        if self.storage_backend == "vault" and vault_password is None:
            raise ValueError("vault_password is required when backend is 'vault'")

        # Collect all credentials from vault
        backup_data = {
            "version": "1",
            "timestamp": int(time.time()),
            "backend": self.storage_backend,
            "credentials": {},
        }

        if self.storage_backend == "vault":
            # Read vault file
            vault_path = self.vault_path or (
                _default_storage_dir(DEFAULT_APP_NAME) / "vault.enc"
            )
            # Use vault's canonical lock file for all vault operations
            vault_lock = self.vault.lock_file

            if not vault_path.exists():
                LOGGER.warning(f"Vault file does not exist: {vault_path}")
                backup_data["credentials_count"] = 0
            else:
                with FileLock(vault_lock, timeout=15):
                    with open(vault_path) as f:
                        encrypted = json.load(f)

                    # Decrypt vault (use unique counter file for this operation)
                    counter_file = vault_path.parent / ".vault_counter"
                    vault = Argon2VaultV3(counter_file=counter_file)
                    plaintext = vault.decrypt(encrypted, vault_password)
                    vault_data = json.loads(plaintext)

                    # Extract credentials (vault_data is {service: {key: {...}}} format)
                    for service, service_data in vault_data.items():
                        if isinstance(service_data, dict):
                            for key, cred_data in service_data.items():
                                cred_key = f"{service}##{key}"
                                backup_data["credentials"][cred_key] = cred_data

                backup_data["credentials_count"] = len(backup_data["credentials"])
        elif self.storage_backend == "keyring":
            # Read credentials from keyring using tracking file
            for (service, key) in self._keyring_store.keys():
                # Retrieve actual value from keyring
                value = keyring.get_password(self.keyring_service, f"{service}_{key}")
                if value is not None:
                    cred_key = f"{service}##{key}"
                    backup_data["credentials"][cred_key] = {
                        "value": value,
                        "created_at": self._keyring_store.get((service, key), {}).get(
                            "created_at"
                        ),
                    }
            backup_data["credentials_count"] = len(backup_data["credentials"])
        else:
            # Other backends (memory, env) are not persisted
            LOGGER.warning(
                f"Backend '{self.storage_backend}' credentials are not persisted, cannot backup"
            )
            backup_data["credentials_count"] = 0

        # Encrypt backup with backup password (use temp counter file)
        backup_json = json.dumps(backup_data, indent=2)
        temp_counter = backup_path.parent / f".backup_counter.tmp.{os.getpid()}"
        backup_vault = Argon2VaultV3(counter_file=temp_counter)
        encrypted_backup = backup_vault.encrypt(backup_json, backup_password)

        # Clean up temp counter
        if temp_counter.exists():
            temp_counter.unlink()

        # Write backup to file
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with open(backup_path, "w") as f:
            json.dump(encrypted_backup, f, indent=2)

        LOGGER.info(
            f"Backed up {backup_data['credentials_count']} credentials to {backup_path}"
        )

        return {
            "credentials_count": backup_data["credentials_count"],
            "backend": backup_data["backend"],
            "timestamp": backup_data["timestamp"],
            "version": backup_data["version"],
        }

    def restore_from_file(
        self, backup_path: Path, backup_password: str, vault_password: str | None = None
    ) -> dict[str, Any]:
        """Restore credentials from encrypted backup file.

        Restores credentials from a backup file created with backup_to_file().
        Credentials are imported into the current backend.

        Args:
            backup_path: Path to backup file
            backup_password: Password to decrypt the backup
            vault_password: Vault password to encrypt credentials (required if backend is vault)

        Returns:
            Dictionary with restore statistics:
                - credentials_restored: Number of credentials restored
                - credentials_skipped: Number of credentials skipped (already exist)
                - backup_timestamp: Timestamp from backup
                - backup_version: Backup format version

        Raises:
            ValueError: If backup file is corrupted or password is wrong
            FileNotFoundError: If backup file does not exist

        Example:
            >>> manager = AutoSaveCredentialManager(backend="vault")
            >>> stats = manager.restore_from_file(
            ...     Path("backup.enc"),
            ...     backup_password="backup_secret",
            ...     vault_password="vault_secret"
            ... )
            >>> print(f"Restored {stats['credentials_restored']} credentials")
        """
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        if self.storage_backend == "vault" and vault_password is None:
            raise ValueError("vault_password is required when backend is 'vault'")

        # Read and decrypt backup (use temp counter file)
        with open(backup_path) as f:
            encrypted_backup = json.load(f)

        temp_counter = backup_path.parent / f".restore_counter.tmp.{os.getpid()}"
        backup_vault = Argon2VaultV3(counter_file=temp_counter)
        backup_json = backup_vault.decrypt(encrypted_backup, backup_password)
        backup_data = json.loads(backup_json)

        # Clean up temp counter
        if temp_counter.exists():
            temp_counter.unlink()

        # Validate backup format
        if backup_data.get("version") != "1":
            raise ValueError(
                f"Unsupported backup version: {backup_data.get('version')}"
            )

        credentials = backup_data.get("credentials", {})
        restored_count = 0
        skipped_count = 0

        if self.storage_backend == "vault":
            vault_path = self.vault_path or (
                _default_storage_dir(DEFAULT_APP_NAME) / "vault.enc"
            )
            # Use vault's canonical lock file for all vault operations
            vault_lock = self.vault.lock_file

            with FileLock(vault_lock, timeout=15):
                # Use counter file from vault path
                counter_file = vault_path.parent / ".vault_counter"
                vault = Argon2VaultV3(counter_file=counter_file)

                # Load existing vault or create new
                if vault_path.exists():
                    with open(vault_path) as f:
                        encrypted = json.load(f)
                    plaintext = vault.decrypt(encrypted, vault_password)
                    vault_data = json.loads(plaintext)
                else:
                    vault_data = {}

                # Restore credentials (backup format is service##key -> {...})
                for cred_key, cred_value in credentials.items():
                    # Split service##key format
                    if "##" in cred_key:
                        service, key = cred_key.split("##", 1)
                    else:
                        LOGGER.warning(f"Invalid credential key format: {cred_key}")
                        continue

                    # Check if already exists
                    if service in vault_data and key in vault_data.get(service, {}):
                        skipped_count += 1
                        LOGGER.debug(f"Skipping existing credential: {service}##{key}")
                    else:
                        if service not in vault_data:
                            vault_data[service] = {}
                        vault_data[service][key] = cred_value
                        restored_count += 1

                # Save updated vault (vault instance already created above)
                vault_json = json.dumps(vault_data)
                encrypted = vault.encrypt(vault_json, vault_password)

                # Atomic write
                temp_vault = vault_path.parent / f".vault.enc.tmp.{os.getpid()}"
                with open(temp_vault, "w") as f:
                    json.dump(encrypted, f, indent=2)

                # Secure permissions (cross-platform)
                secure_file_permissions(temp_vault)

                os.replace(temp_vault, vault_path)

        elif self.storage_backend == "keyring":
            # Restore to keyring
            for cred_key, cred_value in credentials.items():
                # Split service##key format
                if "##" in cred_key:
                    service, key = cred_key.split("##", 1)
                else:
                    LOGGER.warning(f"Invalid credential key format: {cred_key}")
                    continue

                # Check if already exists
                existing = keyring.get_password(self.keyring_service, f"{service}_{key}")
                if existing is not None:
                    skipped_count += 1
                    LOGGER.debug(f"Skipping existing credential: {service}##{key}")
                else:
                    # Extract value from credential data
                    if isinstance(cred_value, dict):
                        value = cred_value.get("value")
                    else:
                        value = cred_value

                    if value:
                        # Save using auto_save_credential to maintain tracking
                        self.auto_save_credential(service, key, value)
                        restored_count += 1

        else:
            LOGGER.warning(
                f"Backend '{self.storage_backend}' does not support restore, skipping"
            )

        LOGGER.info(
            f"Restored {restored_count} credentials, skipped {skipped_count} existing"
        )

        return {
            "credentials_restored": restored_count,
            "credentials_skipped": skipped_count,
            "backup_timestamp": backup_data.get("timestamp"),
            "backup_version": backup_data.get("version"),
        }

    def change_vault_password(
        self, old_password: str, new_password: str
    ) -> dict[str, Any]:
        """Change vault password and re-encrypt all credentials.

        Re-encrypts the entire vault with a new password. This is useful for:
        - Regular password rotation
        - Recovering from potential password compromise
        - Updating to stronger passwords

        Args:
            old_password: Current vault password
            new_password: New vault password

        Returns:
            Dictionary with operation statistics:
                - credentials_count: Number of credentials re-encrypted
                - timestamp: When password was changed

        Raises:
            ValueError: If old password is incorrect or backend is not vault
            OSError: If vault file cannot be read/written

        Example:
            >>> manager = AutoSaveCredentialManager(backend="vault")
            >>> stats = manager.change_vault_password("old_secret", "new_secret")
            >>> print(f"Re-encrypted {stats['credentials_count']} credentials")
        """
        import time

        if self.storage_backend != "vault":
            raise ValueError(
                f"Password change only supported for vault backend, not '{self.storage_backend}'"
            )

        vault_path = self.vault_path or (
            _default_storage_dir(DEFAULT_APP_NAME) / "vault.enc"
        )

        if not vault_path.exists():
            raise ValueError(f"Vault file does not exist: {vault_path}")

        # Use vault's canonical lock file for all vault operations
        vault_lock = self.vault.lock_file

        with FileLock(vault_lock, timeout=15):
            # Use counter file from vault path
            counter_file = vault_path.parent / ".vault_counter"
            vault = Argon2VaultV3(counter_file=counter_file)

            # Read and decrypt with old password
            with open(vault_path) as f:
                encrypted_old = json.load(f)

            try:
                plaintext = vault.decrypt(encrypted_old, old_password)
            except ValueError as e:
                raise ValueError(f"Failed to decrypt with old password: {e}")

            vault_data = json.loads(plaintext)
            # Count credentials (vault_data is {service: {key: {...}}})
            credentials_count = sum(
                len(service_data) for service_data in vault_data.values()
                if isinstance(service_data, dict)
            )

            # Re-encrypt with new password
            vault_json = json.dumps(vault_data)
            encrypted_new = vault.encrypt(vault_json, new_password)

            # Atomic write
            temp_vault = vault_path.parent / f".vault.enc.tmp.{os.getpid()}"
            with open(temp_vault, "w") as f:
                json.dump(encrypted_new, f, indent=2)

            # Secure permissions (cross-platform)
            secure_file_permissions(temp_vault)

            os.replace(temp_vault, vault_path)

        LOGGER.info(f"Changed vault password, re-encrypted {credentials_count} credentials")

        # Rotate audit key atomically with password change
        if self.audit_logger:
            # Check if audit logger supports key rotation (TamperEvidentAuditLogger)
            if hasattr(self.audit_logger, "rotate_audit_key"):
                self.audit_logger.rotate_audit_key(new_password)
                LOGGER.info("Audit key rotated with new vault password")

            # Log password change event
            self.audit_logger._write_event(
                {
                    "event_type": "password_change",
                    "timestamp": time.time(),
                    "credentials_count": credentials_count,
                }
            )

        return {
            "credentials_count": credentials_count,
            "timestamp": int(time.time()),
        }

    def migrate_vault_v3_to_v4(
        self, vault_password: str, create_backup: bool = True
    ) -> dict[str, Any]:
        """Migrate vault from V3 format to V4 format.

        V3 → V4 improvements:
        - Counter moved inside authenticated encrypted payload (more secure)
        - Counter is tamper-proof (part of AES-GCM authentication)

        Args:
            vault_password: Current vault password
            create_backup: Whether to create backup before migration (recommended)

        Returns:
            Dictionary with migration statistics:
                - credentials_count: Number of credentials migrated
                - old_format: Previous format version
                - new_format: New format version
                - backup_path: Path to backup file (if create_backup=True)
                - timestamp: When migration occurred

        Raises:
            ValueError: If vault is not V3 format or migration fails
            OSError: If vault file cannot be read/written

        Example:
            >>> manager = AutoSaveCredentialManager(backend="vault")
            >>> stats = manager.migrate_vault_v3_to_v4("my_password")
            >>> print(f"Migrated {stats['credentials_count']} credentials")
        """
        import time

        if self.storage_backend != "vault":
            raise ValueError(
                f"Migration only supported for vault backend, not '{self.storage_backend}'"
            )

        vault_path = self.vault_path or (
            _default_storage_dir(DEFAULT_APP_NAME) / "vault.enc"
        )

        if not vault_path.exists():
            raise ValueError(f"Vault file does not exist: {vault_path}")

        # Use vault's canonical lock file
        vault_lock = self.vault.lock_file

        with FileLock(vault_lock, timeout=15):
            # Read current vault
            with open(vault_path) as f:
                encrypted_data = json.load(f)

            # Check current format
            current_version = encrypted_data.get("version", "2")
            if current_version != "3":
                raise ValueError(
                    f"Vault is already in format V{current_version}. "
                    "Migration only needed for V3 vaults."
                )

            # Create backup if requested
            backup_path = None
            if create_backup:
                backup_path = vault_path.parent / f"vault.enc.v3.backup.{int(time.time())}"
                import shutil
                shutil.copy2(vault_path, backup_path)
                LOGGER.info(f"Created backup at {backup_path}")

            # Use counter file from vault path
            counter_file = vault_path.parent / ".vault_counter"
            vault = Argon2VaultV3(counter_file=counter_file)

            # Decrypt with V3 format
            try:
                plaintext = vault.decrypt(encrypted_data, vault_password)
            except ValueError as e:
                raise ValueError(f"Failed to decrypt vault: {e}")

            vault_data = json.loads(plaintext)

            # Count credentials
            credentials_count = sum(
                len(service_data) for service_data in vault_data.values()
                if isinstance(service_data, dict)
            )

            # Re-encrypt with V4 format (encrypt() always uses V4)
            vault_json = json.dumps(vault_data)
            encrypted_v4 = vault.encrypt(vault_json, vault_password)

            # Verify it's V4
            if encrypted_v4.get("version") != "4":
                raise ValueError("Migration failed: encrypted data is not V4 format")

            # Atomic write
            temp_vault = vault_path.parent / f".vault.enc.tmp.{os.getpid()}"
            with open(temp_vault, "w") as f:
                json.dump(encrypted_v4, f, indent=2)

            # Secure permissions (cross-platform)
            secure_file_permissions(temp_vault)

            os.replace(temp_vault, vault_path)

        LOGGER.info(
            f"Migrated vault from V3 to V4 format ({credentials_count} credentials)"
        )

        # Log migration in audit log
        if self.audit_logger:
            self.audit_logger._write_event(
                {
                    "event_type": "vault_migration",
                    "timestamp": time.time(),
                    "old_format": "V3",
                    "new_format": "V4",
                    "credentials_count": credentials_count,
                }
            )

        result = {
            "credentials_count": credentials_count,
            "old_format": "V3",
            "new_format": "V4",
            "timestamp": int(time.time()),
        }

        if backup_path:
            result["backup_path"] = str(backup_path)

        return result


# Backwards compatibility alias
Argon2VaultV2 = Argon2VaultV3

__all__ = [
    "SecureString",
    "Argon2VaultV3",
    "Argon2VaultV2",  # Backwards compatibility
    "SessionKeyManager",
    "AuditLogger",
    "TamperEvidentAuditLogger",
    "ConfigValidator",
    "AutoSaveCredentialManager",
]
