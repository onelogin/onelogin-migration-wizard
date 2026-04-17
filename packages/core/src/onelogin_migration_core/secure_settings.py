"""Secure settings management without storing credentials in files.

This module provides a secure alternative to YAML configuration files by:
1. Storing non-sensitive settings in JSON format
2. Storing credentials exclusively in system keyring
3. Never persisting credentials to disk

Settings are stored in: ~/.onelogin-migration/settings.json
Credentials are stored in: System keyring (macOS Keychain, Windows Credential Manager, etc.)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NonSensitiveSettings(BaseModel):
    """Non-sensitive migration settings (safe to store in plaintext JSON)."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    # Migration settings
    dry_run: bool = True
    chunk_size: int = Field(default=200, ge=1, le=1000)
    export_directory: str = "artifacts"
    concurrency_enabled: bool = False
    max_workers: int = Field(default=4, ge=1, le=20)
    bulk_user_upload: bool = False

    # Metadata
    project: str = "migration"
    owner: str = ""

    # Source-provider settings (non-sensitive)
    source_provider: str = "okta"
    source_domain: str = ""
    source_rate_limit_per_minute: int = Field(default=600, ge=1)
    source_page_size: int = Field(default=200, ge=1, le=1000)

    # OneLogin settings (non-sensitive)
    onelogin_region: str = "us"  # us, eu, or custom
    onelogin_subdomain: str = ""
    onelogin_rate_limit_per_hour: int = Field(default=5000, ge=1)
    onelogin_client_id: str = ""  # Not sensitive (public identifier)

    @property
    def okta_domain(self) -> str:
        return self.source_domain

    @okta_domain.setter
    def okta_domain(self, value: str) -> None:
        self.source_domain = value

    @property
    def okta_rate_limit_per_minute(self) -> int:
        return self.source_rate_limit_per_minute

    @okta_rate_limit_per_minute.setter
    def okta_rate_limit_per_minute(self, value: int) -> None:
        self.source_rate_limit_per_minute = value

    @property
    def okta_page_size(self) -> int:
        return self.source_page_size

    @okta_page_size.setter
    def okta_page_size(self, value: int) -> None:
        self.source_page_size = value


class SecureSettingsManager:
    """Manages non-sensitive settings in JSON + credentials in keyring.

    This replaces the YAML-based configuration with a more secure approach:
    - Non-sensitive settings stored in ~/.onelogin-migration/settings.json
    - Credentials stored exclusively in system keyring via CredentialManager
    - No credentials ever written to disk

    Example:
        ```python
        from .secure_settings import SecureSettingsManager
        from .credentials import AutoSaveCredentialManager

        # Initialize managers
        settings_mgr = SecureSettingsManager()
        cred_mgr = AutoSaveCredentialManager(storage_backend="keyring")

        # Load settings
        settings = settings_mgr.load_settings()

        # Update settings
        settings.source_domain = "mycompany.okta.com"
        settings.dry_run = False
        settings_mgr.save_settings(settings)

        # Store credentials separately
        cred_mgr.auto_save_credential("source", "token", "00abc123...")
        cred_mgr.auto_save_credential("onelogin", "client_secret", "secret...")
        ```
    """

    def __init__(self, settings_dir: Path | None = None):
        """Initialize settings manager.

        Args:
            settings_dir: Directory to store settings.json. Defaults to ~/.onelogin-migration/
        """
        if settings_dir is None:
            settings_dir = Path.home() / ".onelogin-migration"

        self.settings_dir = settings_dir
        self.settings_file = settings_dir / "settings.json"

        # Ensure directory exists
        self.settings_dir.mkdir(parents=True, exist_ok=True)

    def load_settings(self) -> NonSensitiveSettings:
        """Load settings from JSON file.

        Returns:
            NonSensitiveSettings object with loaded or default values.
        """
        if not self.settings_file.exists():
            # Return defaults on first run
            return NonSensitiveSettings()

        try:
            data = json.loads(self.settings_file.read_text())
            return NonSensitiveSettings(**data)
        except Exception as exc:
            # If loading fails, return defaults and log error
            print(f"Warning: Failed to load settings from {self.settings_file}: {exc}")
            return NonSensitiveSettings()

    def save_settings(self, settings: NonSensitiveSettings) -> None:
        """Save settings to JSON file.

        Args:
            settings: NonSensitiveSettings object to save.
        """
        try:
            # Use Pydantic's model_dump for serialization
            data = settings.model_dump()

            # Write atomically (write to temp file, then rename)
            temp_file = self.settings_file.with_suffix(".tmp")
            temp_file.write_text(json.dumps(data, indent=2))
            temp_file.replace(self.settings_file)
        except Exception as exc:
            raise OSError(f"Failed to save settings to {self.settings_file}: {exc}")

    def reset_settings(self) -> NonSensitiveSettings:
        """Reset settings to defaults and save.

        Returns:
            Fresh NonSensitiveSettings with defaults.
        """
        settings = NonSensitiveSettings()
        self.save_settings(settings)
        return settings

    def export_settings(self, export_path: Path) -> None:
        """Export current settings to a specific path (for backup/sharing).

        Args:
            export_path: Path to export settings to.
        """
        settings = self.load_settings()
        export_path.write_text(json.dumps(settings.model_dump(), indent=2))

    def import_settings(self, import_path: Path) -> NonSensitiveSettings:
        """Import settings from a specific path.

        Args:
            import_path: Path to import settings from.

        Returns:
            Imported and saved NonSensitiveSettings.
        """
        data = json.loads(import_path.read_text())
        settings = NonSensitiveSettings(**data)
        self.save_settings(settings)
        return settings

    def import_from_yaml(self, yaml_path: Path) -> tuple[NonSensitiveSettings, dict[str, Any]]:
        """Import non-sensitive settings from legacy YAML config.

        This is used for migration from old YAML-based configs.
        Returns both the settings and the raw credential data that should be
        extracted and stored separately.

        Args:
            yaml_path: Path to YAML config file.

        Returns:
            Tuple of (NonSensitiveSettings, dict of credential data)
        """
        import yaml

        data = yaml.safe_load(yaml_path.read_text())

        # Extract non-sensitive settings
        source_raw = data.get("source") or data.get("okta") or {}
        settings = NonSensitiveSettings(
            dry_run=data.get("dry_run", True),
            chunk_size=data.get("chunk_size", 200),
            export_directory=data.get("export_directory", "artifacts"),
            concurrency_enabled=data.get("concurrency_enabled", False),
            max_workers=data.get("max_workers", 4),
            bulk_user_upload=data.get("bulk_user_upload", False),
            project=data.get("metadata", {}).get("project", "migration"),
            owner=data.get("metadata", {}).get("owner", ""),
            source_provider=source_raw.get("provider", "okta"),
            source_domain=source_raw.get("domain", ""),
            source_rate_limit_per_minute=source_raw.get("rate_limit_per_minute", 600),
            source_page_size=source_raw.get("page_size", 200),
            onelogin_region=data.get("onelogin", {}).get("region", "us"),
            onelogin_subdomain=data.get("onelogin", {}).get("subdomain", ""),
            onelogin_rate_limit_per_hour=data.get("onelogin", {}).get("rate_limit_per_hour", 5000),
            onelogin_client_id=data.get("onelogin", {}).get("client_id", ""),
        )

        # Extract credentials (to be stored separately)
        credentials = {}
        if "token" in source_raw:
            credentials["source_token"] = source_raw["token"]

        onelogin = data.get("onelogin", {})
        if "client_secret" in onelogin:
            credentials["onelogin_client_secret"] = onelogin["client_secret"]

        return settings, credentials

    def to_legacy_yaml_format(self, settings: NonSensitiveSettings) -> dict[str, Any]:
        """Convert settings to legacy YAML format (for compatibility).

        Note: This does NOT include credentials. Credentials should be
        retrieved from the credential manager separately.

        Args:
            settings: NonSensitiveSettings to convert.

        Returns:
            Dictionary in legacy YAML format.
        """
        return {
            "dry_run": settings.dry_run,
            "chunk_size": settings.chunk_size,
            "export_directory": settings.export_directory,
            "concurrency_enabled": settings.concurrency_enabled,
            "max_workers": settings.max_workers,
            "bulk_user_upload": settings.bulk_user_upload,
            "metadata": {
                "project": settings.project,
                "owner": settings.owner,
            },
            "source": {
                "provider": settings.source_provider,
                "domain": settings.source_domain,
                "token_source": "keyring",  # Indicate credentials stored securely
                "rate_limit_per_minute": settings.source_rate_limit_per_minute,
                "page_size": settings.source_page_size,
            },
            "onelogin": {
                "client_id": settings.onelogin_client_id,
                "client_secret_source": "keyring",  # Indicate credentials stored securely
                "region": settings.onelogin_region,
                "subdomain": settings.onelogin_subdomain,
                "rate_limit_per_hour": settings.onelogin_rate_limit_per_hour,
            },
        }


def get_default_settings_manager() -> SecureSettingsManager:
    """Get default settings manager instance.

    Returns:
        SecureSettingsManager using default location (~/.onelogin-migration/).
    """
    return SecureSettingsManager()
