"""Hybrid encryption key management for telemetry data.

This module provides automatic, transparent encryption for all telemetry data
with hybrid key management: machine-derived keys stored in OS keyring.

Design Principles:
- Machine-derived encryption keys (hardware UUID-based)
- OS keyring storage for persistence (macOS Keychain, Windows Credential Manager)
- Zero user interaction required
- Transparent encryption/decryption
- Automatic migration from legacy file-based keys
- AES-256-GCM authenticated encryption
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import secrets
import subprocess
import uuid
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# Try to import cryptography library
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    LOGGER.warning(
        "cryptography library not available - encryption disabled. "
        "Install with: pip install cryptography"
    )

# Try to import keyring library
try:
    import keyring

    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False
    LOGGER.warning(
        "keyring library not available - using file-based key storage. "
        "Install with: pip install keyring for better security"
    )


class EncryptionManager:
    """Hybrid encryption manager using machine-derived keys in OS keyring.

    This class handles automatic key derivation from machine hardware ID,
    secure storage in OS keyring (or file fallback), and transparent
    encryption/decryption of sensitive data.

    Key Storage Priority:
    1. OS keyring (macOS Keychain, Windows Credential Manager) - PREFERRED
    2. Legacy file migration (~/.onelogin-migration/.encryption_key)
    3. File-based fallback if keyring unavailable

    Key Derivation:
    - Derived from machine Hardware UUID (macOS) or Machine GUID (Windows)
    - Uses PBKDF2-HMAC-SHA256 with 100k iterations
    - Deterministic per machine but computationally infeasible to reverse
    """

    def __init__(self, use_keyring: bool = True):
        """Initialize encryption manager with hybrid key management.

        Args:
            use_keyring: Use OS keyring for key storage (default: True).
                        Set to False to force file-based storage (development only)
        """
        self.use_keyring = use_keyring and HAS_KEYRING

        # Legacy key file location (for migration)
        self.legacy_key_file = Path.home() / ".onelogin-migration" / ".encryption_key"

        # New key file location (app support directory)
        if platform.system() == "Darwin":
            app_support = (
                Path.home() / "Library" / "Application Support" / "OneLogin Migration Tool"
            )
        elif platform.system() == "Windows":
            app_support = Path(os.getenv("APPDATA", Path.home())) / "OneLogin Migration Tool"
        else:
            app_support = Path.home() / ".local" / "share" / "OneLogin Migration Tool"

        app_support.mkdir(parents=True, exist_ok=True)
        self.key_file = app_support / ".encryption_key"

        self._key: bytes | None = None
        self._aesgcm: AESGCM | None = None

        if CRYPTO_AVAILABLE:
            self._initialize_encryption()
        else:
            LOGGER.warning(
                "Encryption is DISABLED - cryptography package not installed. "
                "Telemetry will be stored in plaintext (already SHA-256 hashed). "
                "For production use, install: pip install cryptography"
            )

    def _get_machine_id(self) -> str:
        """Get stable machine identifier.

        Returns:
            Machine-specific identifier string (Hardware UUID on macOS,
            Machine GUID on Windows, MAC address as fallback)
        """
        try:
            if platform.system() == "Darwin":
                # macOS: Use Hardware UUID from system_profiler
                result = subprocess.run(
                    ["system_profiler", "SPHardwareDataType"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                for line in result.stdout.split("\n"):
                    if "Hardware UUID" in line:
                        uuid_str = line.split(":")[1].strip()
                        LOGGER.debug("Using macOS Hardware UUID for key derivation")
                        return uuid_str

            elif platform.system() == "Windows":
                # Windows: Use MachineGuid from registry
                try:
                    import winreg

                    key = winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        r"SOFTWARE\Microsoft\Cryptography",
                        0,
                        winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
                    )
                    machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                    winreg.CloseKey(key)
                    LOGGER.debug("Using Windows MachineGuid for key derivation")
                    return machine_guid
                except Exception as e:
                    LOGGER.warning("Failed to get Windows MachineGuid: %s", e)

            # Fallback: Use MAC address (less stable but universal)
            mac = uuid.getnode()
            mac_str = ":".join(
                [f"{(mac >> elements) & 0xFF:02x}" for elements in range(0, 8 * 6, 8)][::-1]
            )
            LOGGER.info("Using MAC address for key derivation (fallback)")
            return mac_str

        except Exception as e:
            LOGGER.error("Failed to get machine ID: %s", e)
            # Last resort: hostname + user
            fallback = f"{platform.node()}:{os.getenv('USER', 'unknown')}"
            LOGGER.warning("Using hostname+user as machine ID (least stable)")
            return fallback

    def _derive_key_from_machine(self) -> bytes:
        """Derive encryption key from machine hardware ID.

        Uses PBKDF2-HMAC-SHA256 to derive a 256-bit key from the machine's
        hardware UUID. This makes the key deterministic per machine but
        computationally infeasible to reverse.

        Returns:
            32-byte AES-256 key derived from machine ID
        """
        machine_id = self._get_machine_id()

        # Application-specific salt (public, hardcoded)
        app_salt = b"onelogin-migration-tool-db-encryption-v1"

        # Derive 256-bit key using PBKDF2-HMAC-SHA256
        # High iteration count for security (100k iterations)
        derived_key = hashlib.pbkdf2_hmac(
            "sha256",
            machine_id.encode("utf-8"),
            app_salt,
            iterations=100000,
            dklen=32,  # 256 bits for AES-256
        )

        LOGGER.debug(
            "Derived encryption key from machine ID using PBKDF2-HMAC-SHA256 " "(100k iterations)"
        )
        return derived_key

    def _initialize_encryption(self) -> None:
        """Initialize encryption with hybrid keyring + machine-derived approach."""
        # Try to load from keyring first
        if self.use_keyring:
            key_hex = self._load_from_keyring()
            if key_hex:
                self._key = bytes.fromhex(key_hex)
                LOGGER.info("Loaded encryption key from OS keyring")
                self._aesgcm = AESGCM(self._key) if self._key else None
                return

        # No keyring key - check for file-based keys (legacy or new location)
        if self.legacy_key_file.exists():
            LOGGER.info("Migrating encryption key from legacy location to keyring...")
            self._migrate_file_to_keyring(self.legacy_key_file)
            return
        elif self.key_file.exists():
            LOGGER.info("Migrating encryption key from file to keyring...")
            self._migrate_file_to_keyring(self.key_file)
            return

        # No existing key - derive from machine ID
        LOGGER.info("Generating new encryption key from machine hardware ID...")
        self._key = self._derive_key_from_machine()

        # Store in keyring for persistence
        if self.use_keyring:
            self._save_to_keyring(self._key.hex())
            LOGGER.info("Saved derived key to OS keyring")
        else:
            # Fallback: save to file with warning
            LOGGER.warning(
                "OS keyring not available - saving to file. "
                "Install 'keyring' package for better security."
            )
            self._save_to_file_fallback()

        # Initialize cipher
        self._aesgcm = AESGCM(self._key) if self._key else None
        LOGGER.info("Encryption initialized with AES-256-GCM")

    def _load_from_keyring(self) -> str | None:
        """Load encryption key from OS keyring.

        Returns:
            Hex-encoded key string, or None if not found
        """
        try:
            key_hex = keyring.get_password("onelogin-migration-tool", "db_encryption_key")
            return key_hex
        except Exception as e:
            LOGGER.debug("Failed to load from keyring: %s", e)
            return None

    def _save_to_keyring(self, key_hex: str) -> None:
        """Save encryption key to OS keyring.

        Args:
            key_hex: Hex-encoded key string
        """
        try:
            keyring.set_password("onelogin-migration-tool", "db_encryption_key", key_hex)
        except Exception as e:
            LOGGER.error("Failed to save key to keyring: %s", e)
            raise

    def _migrate_file_to_keyring(self, key_file_path: Path) -> None:
        """Migrate encryption key from file to keyring.

        Args:
            key_file_path: Path to the key file to migrate
        """
        try:
            # Load old key from file
            with key_file_path.open("r") as f:
                key_data = json.load(f)

            self._key = bytes.fromhex(key_data["key"])

            # Save to keyring if available
            if self.use_keyring:
                self._save_to_keyring(key_data["key"])

                # Rename old file to .backup
                backup_file = key_file_path.with_suffix(".key.backup")
                key_file_path.rename(backup_file)
                LOGGER.info(
                    "Migrated encryption key from file to OS keyring. " "Old file renamed to: %s",
                    backup_file,
                )
            else:
                # Can't migrate without keyring - keep using file
                LOGGER.warning(
                    "Cannot migrate to keyring (not available). " "Continuing with file-based key."
                )

            # Initialize cipher
            self._aesgcm = AESGCM(self._key) if self._key else None

        except Exception as e:
            LOGGER.error("Failed to migrate key from file: %s", e)
            raise

    def _save_to_file_fallback(self) -> None:
        """Save key to file as fallback (when keyring unavailable)."""
        # Ensure parent directory exists with secure permissions
        self.key_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        key_data = {
            "version": 1,
            "algorithm": "AES-256-GCM",
            "key": self._key.hex(),
            "source": "machine-derived",
            "warning": "DO NOT DELETE - Derived from machine hardware ID",
        }

        # Write key file with secure permissions
        fd = os.open(
            self.key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode=0o600  # Owner read/write only
        )

        try:
            with os.fdopen(fd, "w") as f:
                json.dump(key_data, f, indent=2)
        except:
            os.close(fd)
            raise

        LOGGER.info("Saved encryption key to file (fallback): %s", self.key_file)

    def _generate_and_save_key(self) -> None:
        """Generate a new 256-bit encryption key and save securely."""
        # Generate cryptographically secure random key
        self._key = secrets.token_bytes(32)  # 256 bits for AES-256

        # Prepare key metadata
        key_data = {
            "version": 1,
            "algorithm": "AES-256-GCM",
            "key": self._key.hex(),  # Store as hex string
            "warning": "DO NOT DELETE - Required for decrypting telemetry data",
        }

        # Write key file with secure permissions
        # Use file descriptor to set permissions before writing
        fd = os.open(
            self.key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode=0o600  # Owner read/write only
        )

        try:
            with os.fdopen(fd, "w") as f:
                json.dump(key_data, f, indent=2)
        except:
            os.close(fd)
            raise

        LOGGER.info("Generated new encryption key: %s (permissions: 0o600)", self.key_file)

    def _load_key(self) -> None:
        """Load encryption key from secure key file."""
        try:
            # Verify file permissions before loading
            mode = os.stat(self.key_file).st_mode & 0o777
            if mode != 0o600:
                # Fix permissions if incorrect
                os.chmod(self.key_file, 0o600)
                LOGGER.warning(
                    "Fixed insecure key file permissions: %s (was %s, now 0o600)",
                    self.key_file,
                    oct(mode),
                )

            # Load key
            with self.key_file.open("r") as f:
                key_data = json.load(f)

            self._key = bytes.fromhex(key_data["key"])

            LOGGER.debug("Loaded encryption key from %s", self.key_file)

        except Exception as e:
            LOGGER.error("Failed to load encryption key: %s", e)
            raise RuntimeError(
                f"Cannot load encryption key from {self.key_file}. "
                "Telemetry data may be inaccessible."
            ) from e

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string value.

        Args:
            plaintext: String to encrypt

        Returns:
            Encrypted string with "enc:" prefix, or plaintext if encryption unavailable
        """
        if not CRYPTO_AVAILABLE or not self._aesgcm:
            # Encryption not available - return plaintext
            # (Telemetry is already SHA-256 hashed, so this is still anonymous)
            return plaintext

        try:
            # Generate random nonce (96 bits for GCM)
            nonce = secrets.token_bytes(12)

            # Encrypt with authenticated encryption
            ciphertext = self._aesgcm.encrypt(
                nonce, plaintext.encode("utf-8"), None  # No additional authenticated data
            )

            # Combine nonce + ciphertext and encode as hex
            combined = nonce + ciphertext
            encrypted_hex = combined.hex()

            # Add prefix to identify encrypted values
            return f"enc:{encrypted_hex}"

        except Exception as e:
            LOGGER.error("Encryption failed: %s", e)
            # Fail-safe: return plaintext to avoid data loss
            return plaintext

    def decrypt(self, encrypted: str) -> str:
        """Decrypt an encrypted string value.

        Args:
            encrypted: Encrypted string (with "enc:" prefix)

        Returns:
            Decrypted plaintext string

        Raises:
            ValueError: If decryption fails (wrong key, corrupted data)
        """
        if not CRYPTO_AVAILABLE or not self._aesgcm:
            raise RuntimeError(
                "Cannot decrypt - cryptography package not installed. "
                "Install with: pip install cryptography"
            )

        # Remove "enc:" prefix if present
        if encrypted.startswith("enc:"):
            encrypted = encrypted[4:]

        try:
            # Decode from hex
            combined = bytes.fromhex(encrypted)

            # Split nonce and ciphertext
            nonce = combined[:12]
            ciphertext = combined[12:]

            # Decrypt
            plaintext_bytes = self._aesgcm.decrypt(nonce, ciphertext, None)

            return plaintext_bytes.decode("utf-8")

        except Exception as e:
            raise ValueError(f"Decryption failed: {e}") from e

    def is_encrypted(self, value: str) -> bool:
        """Check if a value is encrypted.

        Args:
            value: String value to check

        Returns:
            True if encrypted (has "enc:" prefix), False otherwise
        """
        return value.startswith("enc:")

    def is_available(self) -> bool:
        """Check if encryption is available.

        Returns:
            True if cryptography package is installed and key loaded
        """
        return CRYPTO_AVAILABLE and self._aesgcm is not None

    def get_key_info(self) -> dict:
        """Get information about the encryption key.

        Returns:
            Dictionary with key metadata
        """
        return {
            "encryption_available": CRYPTO_AVAILABLE,
            "key_loaded": self._key is not None,
            "key_file": str(self.key_file),
            "key_exists": self.key_file.exists(),
            "algorithm": "AES-256-GCM" if self._key else None,
        }


# Global encryption manager instance
_encryption_manager: EncryptionManager | None = None


def get_encryption_manager() -> EncryptionManager:
    """Get global encryption manager instance.

    Returns:
        Singleton EncryptionManager instance
    """
    global _encryption_manager

    if _encryption_manager is None:
        _encryption_manager = EncryptionManager()

    return _encryption_manager


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value using the global encryption manager.

    Args:
        plaintext: String to encrypt

    Returns:
        Encrypted string with "enc:" prefix
    """
    manager = get_encryption_manager()
    return manager.encrypt(plaintext)


def decrypt_value(encrypted: str) -> str:
    """Decrypt an encrypted string value.

    Args:
        encrypted: Encrypted string (with "enc:" prefix)

    Returns:
        Decrypted plaintext string
    """
    manager = get_encryption_manager()
    return manager.decrypt(encrypted)


def is_encryption_available() -> bool:
    """Check if encryption is available.

    Returns:
        True if cryptography package is installed
    """
    return CRYPTO_AVAILABLE


def migrate_database_encryption(db_path: Path | None = None) -> dict:
    """Migrate existing database to use encryption.

    This function encrypts all plaintext telemetry data in the database.
    Safe to run multiple times (skips already-encrypted data).

    Args:
        db_path: Path to database file

    Returns:
        Dictionary with migration statistics
    """
    import sqlite3

    if db_path is None:
        db_path = Path.home() / ".onelogin-migration" / "connectors.db"

    if not db_path.exists():
        return {
            "status": "error",
            "message": "Database not found",
            "path": str(db_path),
        }

    manager = get_encryption_manager()

    if not manager.is_available():
        return {
            "status": "error",
            "message": "Encryption not available - install cryptography package",
            "encrypted": 0,
        }

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    encrypted_count = 0
    skipped_count = 0

    try:
        # Encrypt connector_telemetry.okta_connector_hash
        cursor = conn.execute(
            """
            SELECT rowid, okta_connector_hash
            FROM connector_telemetry
            WHERE okta_connector_hash IS NOT NULL
        """
        )

        rows = cursor.fetchall()

        for row in rows:
            rowid = row["rowid"]
            current_value = row["okta_connector_hash"]

            # Skip if already encrypted
            if manager.is_encrypted(current_value):
                skipped_count += 1
                continue

            # Encrypt the value
            encrypted_value = manager.encrypt(current_value)

            # Update database
            conn.execute(
                """
                UPDATE connector_telemetry
                SET okta_connector_hash = ?
                WHERE rowid = ?
            """,
                (encrypted_value, rowid),
            )

            encrypted_count += 1

        conn.commit()

        LOGGER.info(
            "Database encryption migration complete: %d encrypted, %d skipped",
            encrypted_count,
            skipped_count,
        )

        return {
            "status": "success",
            "encrypted": encrypted_count,
            "skipped": skipped_count,
            "total": encrypted_count + skipped_count,
        }

    except Exception as e:
        conn.rollback()
        LOGGER.error("Database encryption migration failed: %s", e)
        return {
            "status": "error",
            "message": str(e),
            "encrypted": encrypted_count,
        }
    finally:
        conn.close()
