"""Database security utilities for encryption and secure storage.

This module provides optional encryption for sensitive telemetry data using
AES-256-GCM encryption with keys stored in the system keyring.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# Try to import cryptography library
try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2

    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    LOGGER.debug("cryptography library not available - encryption disabled")


class EncryptedConnectorDatabase:
    """SQLite database with transparent AES-256 encryption for sensitive data.

    This class provides an optional encrypted wrapper around ConnectorDatabase
    for users who want additional security for telemetry data.

    Key Features:
    - AES-256-GCM encryption (authenticated encryption)
    - Password-based key derivation (PBKDF2 with 100,000 iterations)
    - Keys stored securely in system keyring
    - Transparent encryption/decryption
    - Backward compatible with unencrypted databases

    Note: This uses application-level encryption, not SQLCipher. The database
    structure remains readable, but sensitive telemetry data is encrypted.
    """

    def __init__(self, db_path: Path | None = None, password: str | None = None):
        """Initialize encrypted database.

        Args:
            db_path: Path to database file. Defaults to ~/.onelogin-migration/connectors.db
            password: Encryption password. If None, attempts to load from keyring.

        Raises:
            ImportError: If cryptography library is not installed
            ValueError: If no password provided and none found in keyring
        """
        if not CRYPTO_AVAILABLE:
            raise ImportError(
                "Encryption requires 'cryptography' library. "
                "Install with: pip install cryptography"
            )

        from .connector_db import ConnectorDatabase

        if db_path is None:
            db_path = Path.home() / ".onelogin-migration" / "connectors.db"

        self.db_path = db_path
        self._base_db = ConnectorDatabase(db_path)
        self._password = password
        self._encryption_key: bytes | None = None

        # Initialize encryption key
        if password:
            self._encryption_key = self._derive_key(password)
        else:
            # Attempt to load from keyring
            self._encryption_key = self._load_key_from_keyring()

        if not self._encryption_key:
            raise ValueError(
                "No encryption password provided and no key found in keyring. "
                "Provide a password or run 'onelogin-migration-tool db set-password' first."
            )

    @staticmethod
    def _derive_key(password: str, salt: bytes | None = None) -> bytes:
        """Derive encryption key from password using PBKDF2.

        Args:
            password: User password
            salt: Optional salt (generated if not provided)

        Returns:
            32-byte encryption key suitable for AES-256
        """
        if salt is None:
            # Use fixed salt for consistent key derivation
            # In production, you'd want per-database salts stored in metadata
            salt = b"onelogin-migration-tool-v1"

        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=32,  # 256 bits for AES-256
            salt=salt,
            iterations=100000,  # OWASP recommended minimum
        )

        return kdf.derive(password.encode())

    def _load_key_from_keyring(self) -> bytes | None:
        """Load encryption key from system keyring.

        Returns:
            Encryption key bytes or None if not found
        """
        try:
            import keyring

            password = keyring.get_password("onelogin-migration-tool", "db-encryption")
            if password:
                return self._derive_key(password)
        except ImportError:
            LOGGER.debug("keyring library not available")
        except Exception as e:
            LOGGER.warning("Failed to load key from keyring: %s", e)

        return None

    def _save_key_to_keyring(self, password: str) -> bool:
        """Save encryption password to system keyring.

        Args:
            password: Encryption password

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            import keyring

            keyring.set_password("onelogin-migration-tool", "db-encryption", password)
            LOGGER.info("Encryption password saved to system keyring")
            return True
        except ImportError:
            LOGGER.warning("keyring library not available - password not saved")
            return False
        except Exception as e:
            LOGGER.warning("Failed to save key to keyring: %s", e)
            return False

    def encrypt_telemetry_data(self) -> int:
        """Encrypt existing plaintext telemetry data in the database.

        This is a one-time operation to upgrade an existing database to use encryption.

        Returns:
            Number of records encrypted
        """
        if not self._encryption_key:
            raise ValueError("No encryption key available")

        conn = self._base_db.connect()
        encrypted_count = 0

        # Encrypt connector telemetry hashes (additional layer beyond SHA-256)
        cursor = conn.execute(
            """
            SELECT rowid, okta_connector_hash
            FROM connector_telemetry
            WHERE okta_connector_hash NOT LIKE 'enc:%'
        """
        )

        rows = cursor.fetchall()
        for row in rows:
            rowid = row[0]
            plaintext = row[1]

            # Encrypt the hash
            encrypted = self._encrypt_value(plaintext)

            # Update with encrypted value
            conn.execute(
                """
                UPDATE connector_telemetry
                SET okta_connector_hash = ?
                WHERE rowid = ?
            """,
                (f"enc:{encrypted}", rowid),
            )

            encrypted_count += 1

        conn.commit()
        LOGGER.info("Encrypted %d telemetry records", encrypted_count)

        return encrypted_count

    def _encrypt_value(self, plaintext: str) -> str:
        """Encrypt a string value using AES-256-GCM.

        Args:
            plaintext: String to encrypt

        Returns:
            Base64-encoded encrypted value
        """
        if not self._encryption_key:
            raise ValueError("No encryption key available")

        import base64

        aesgcm = AESGCM(self._encryption_key)
        nonce = os.urandom(12)  # 96-bit nonce for GCM
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)

        # Combine nonce + ciphertext and encode
        combined = nonce + ciphertext
        return base64.b64encode(combined).decode("ascii")

    def _decrypt_value(self, encrypted: str) -> str:
        """Decrypt an AES-256-GCM encrypted value.

        Args:
            encrypted: Base64-encoded encrypted value

        Returns:
            Decrypted plaintext string
        """
        if not self._encryption_key:
            raise ValueError("No encryption key available")

        import base64

        # Decode from base64
        combined = base64.b64decode(encrypted)

        # Split nonce and ciphertext
        nonce = combined[:12]
        ciphertext = combined[12:]

        # Decrypt
        aesgcm = AESGCM(self._encryption_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)

        return plaintext.decode("utf-8")

    def verify_encryption(self) -> dict:
        """Verify encryption status of the database.

        Returns:
            Dictionary with encryption statistics
        """
        conn = self._base_db.connect()

        # Check connector telemetry
        cursor = conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN okta_connector_hash LIKE 'enc:%' THEN 1 ELSE 0 END) as encrypted
            FROM connector_telemetry
        """
        )
        telemetry_stats = cursor.fetchone()

        return {
            "encryption_enabled": self._encryption_key is not None,
            "telemetry_total": telemetry_stats[0],
            "telemetry_encrypted": telemetry_stats[1],
            "encryption_percentage": (
                (telemetry_stats[1] / telemetry_stats[0] * 100) if telemetry_stats[0] > 0 else 0
            ),
        }

    @classmethod
    def is_encryption_available(cls) -> bool:
        """Check if encryption is available (cryptography library installed).

        Returns:
            True if encryption is available, False otherwise
        """
        return CRYPTO_AVAILABLE

    @staticmethod
    def generate_password(length: int = 32) -> str:
        """Generate a secure random password for database encryption.

        Args:
            length: Password length in characters

        Returns:
            Secure random password
        """
        import secrets
        import string

        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return "".join(secrets.choice(alphabet) for _ in range(length))


def check_database_security(db_path: Path | None = None) -> dict:
    """Check security status of database.

    Args:
        db_path: Path to database file

    Returns:
        Dictionary with security assessment
    """
    if db_path is None:
        db_path = Path.home() / ".onelogin-migration" / "connectors.db"

    if not db_path.exists():
        return {
            "exists": False,
            "error": "Database file not found",
        }

    import stat

    file_stat = os.stat(db_path)
    mode = file_stat.st_mode & 0o777

    # Check permissions
    secure_permissions = mode == 0o600
    world_readable = bool(mode & stat.S_IROTH)
    group_readable = bool(mode & stat.S_IRGRP)

    # Check encryption
    encryption_available = EncryptedConnectorDatabase.is_encryption_available()

    result = {
        "exists": True,
        "path": str(db_path),
        "size_bytes": file_stat.st_size,
        "permissions": {
            "octal": oct(mode),
            "secure": secure_permissions,
            "world_readable": world_readable,
            "group_readable": group_readable,
            "recommendation": "OK" if secure_permissions else "Fix permissions to 0o600",
        },
        "encryption": {
            "available": encryption_available,
            "enabled": False,  # Would need to check database metadata
            "recommendation": (
                "Consider enabling encryption for additional security"
                if encryption_available
                else "Install 'cryptography' package to enable encryption"
            ),
        },
    }

    return result
