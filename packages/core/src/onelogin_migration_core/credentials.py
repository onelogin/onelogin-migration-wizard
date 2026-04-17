"""Compatibility layer exposing layered-credentials management utilities.

This module keeps the original imports used across the migration tool while the
implementation now lives in the open-source ``layered-credentials`` package.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _add_local_package_path() -> None:
    """Ensure the extracted package can be imported when working from source."""
    package_src = Path(__file__).resolve().parents[3] / "layered_credentials" / "src"
    if package_src.exists() and str(package_src) not in sys.path:
        sys.path.insert(0, str(package_src))


try:
    from layered_credentials import (
        Argon2VaultV2,
        Argon2VaultV3,
        AuditError,
        AuditLogger,
        BackupError,
        ConfigValidationError,
        ConfigValidator,
        KeyringError,
        LayeredCredentialsError,
        RestoreError,
        SecureString,
        SecureStringError,
        SessionKeyManager,
        TamperDetectedError,
        TamperEvidentAuditLogger,
        VaultCorruptionError,
        VaultDecryptionError,
        VaultEncryptionError,
        VaultError,
        VaultRollbackError,
        AutoSaveCredentialManager as _BaseAutoSaveCredentialManager,
    )
except ModuleNotFoundError:  # pragma: no cover - executed only in editable installs
    _add_local_package_path()
    from layered_credentials import (  # type: ignore[no-redef]
        Argon2VaultV2,
        Argon2VaultV3,
        AuditError,
        AuditLogger,
        BackupError,
        ConfigValidationError,
        ConfigValidator,
        KeyringError,
        LayeredCredentialsError,
        RestoreError,
        SecureString,
        SecureStringError,
        SessionKeyManager,
        TamperDetectedError,
        TamperEvidentAuditLogger,
        VaultCorruptionError,
        VaultDecryptionError,
        VaultEncryptionError,
        VaultError,
        VaultRollbackError,
        AutoSaveCredentialManager as _BaseAutoSaveCredentialManager,
    )


DEFAULT_APP_NAME = "onelogin-migration"
DEFAULT_KEYRING_SERVICE = "onelogin-migration-tool"


class AutoSaveCredentialManager(_BaseAutoSaveCredentialManager):
    """Preserve historical defaults for the migration tool."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("app_name", DEFAULT_APP_NAME)
        kwargs.setdefault("keyring_service", DEFAULT_KEYRING_SERVICE)

        # Ensure the legacy storage root (~/.onelogin-migration/) remains in use
        if "storage_dir" not in kwargs and "app_name" not in kwargs:
            kwargs["storage_dir"] = _default_storage_dir(DEFAULT_APP_NAME)

        super().__init__(*args, **kwargs)


def _default_storage_dir(app_name: str) -> Path:
    """Recreate the legacy storage path used before extraction."""
    slug = app_name.strip().lower() or DEFAULT_APP_NAME
    if not slug.startswith("."):
        slug = f".{slug}"
    return Path.home() / slug


# Provide an alias for advanced callers that want the generic implementation
LayeredCredentialsAutoSaveCredentialManager = _BaseAutoSaveCredentialManager

__all__ = [
    # Core classes
    "SecureString",
    "Argon2VaultV3",
    "Argon2VaultV2",
    "SessionKeyManager",
    "AuditLogger",
    "TamperEvidentAuditLogger",
    "ConfigValidator",
    "AutoSaveCredentialManager",
    "LayeredCredentialsAutoSaveCredentialManager",
    # Exception classes
    "LayeredCredentialsError",
    "SecureStringError",
    "VaultError",
    "VaultDecryptionError",
    "VaultEncryptionError",
    "VaultRollbackError",
    "VaultCorruptionError",
    "KeyringError",
    "BackupError",
    "RestoreError",
    "ConfigValidationError",
    "AuditError",
    "TamperDetectedError",
]
