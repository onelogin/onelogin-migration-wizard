"""Intelligent credential extraction from YAML configuration files.

This module provides safe extraction and securing of credentials from YAML
configuration files, with automatic backup creation and credential detection.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .credentials import AutoSaveCredentialManager

LOGGER = logging.getLogger(__name__)


class CredentialExtractor:
    """Intelligent credential extraction from YAML configs.

    This class scans YAML configuration files for credential fields,
    extracts them securely, and creates sanitized versions of the configs
    with credential references instead of plaintext values.

    Example:
        >>> extractor = CredentialExtractor()
        >>> manager = AutoSaveCredentialManager(storage_backend="keyring")
        >>> sanitized, extracted, backup = extractor.extract_and_secure(
        ...     Path("config/migration.yaml"), manager
        ... )
        >>> print(f"Extracted {len(extracted)} credentials")
        >>> print(f"Backup saved to {backup}")
    """

    # Map of (section, field) -> credential_name
    CREDENTIAL_PATHS: dict[tuple[str, str], str] = {
        ("okta", "token"): "okta_token",
        ("okta", "api_token"): "okta_token",
        ("okta", "api_key"): "okta_api_key",
        ("onelogin", "client_id"): "onelogin_client_id",
        ("onelogin", "client_secret"): "onelogin_client_secret",
        ("onelogin", "api_key"): "onelogin_api_key",
    }

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

    def __init__(self):
        """Initialize credential extractor."""
        pass

    def detect_credentials(self, config: dict[str, Any]) -> list[tuple[str, str, str, list[str]]]:
        """Scan config for credential fields.

        This method recursively walks the configuration dictionary to find
        all fields that appear to contain credentials based on field names.

        Args:
            config: Configuration dictionary to scan

        Returns:
            List of (service, key, value, path) tuples for detected credentials
            where path is the full path list to reach the credential

        Example:
            >>> config = {
            ...     "okta": {"domain": "company.okta.com", "token": "00abc123..."},
            ...     "onelogin": {"client_id": "12345", "client_secret": "xyz789..."}
            ... }
            >>> credentials = extractor.detect_credentials(config)
            >>> # Returns: [("okta", "token", "00abc123...", ["okta", "token"]), ...]
        """
        credentials = []

        def is_credential_field(field_name: str) -> bool:
            """Check if field name indicates a credential."""
            field_lower = field_name.lower()
            return any(pattern in field_lower for pattern in self.CREDENTIAL_PATTERNS)

        def walk_dict(obj: Any, path: list[str] = None) -> None:
            """Recursively walk dictionary to find credentials."""
            if path is None:
                path = []

            if isinstance(obj, dict):
                for key, value in obj.items():
                    current_path = path + [key]

                    # Check if this is a credential field
                    if is_credential_field(key) and isinstance(value, str) and value:
                        # Determine service name (top-level section)
                        service = current_path[0] if current_path else "unknown"
                        # Store full path for accurate sanitization
                        credentials.append((service, key, value, current_path))
                    else:
                        # Continue walking
                        walk_dict(value, current_path)
            elif isinstance(obj, list):
                for item in obj:
                    walk_dict(item, path)

        walk_dict(config)
        return credentials

    def extract_and_secure(
        self, config_path: Path, credential_manager: AutoSaveCredentialManager
    ) -> tuple[dict[str, Any], list[str], Path]:
        """Extract credentials from YAML and store securely.

        This is the main method that:
        1. Loads the YAML configuration
        2. Detects all credentials
        3. Stores them securely using the credential manager
        4. Creates a timestamped backup of the original file
        5. Saves a sanitized version without credentials

        Args:
            config_path: Path to YAML configuration file
            credential_manager: Credential manager for secure storage

        Returns:
            Tuple of (sanitized_config, extracted_credential_names, backup_path)

        Raises:
            FileNotFoundError: If config file doesn't exist
            yaml.YAMLError: If YAML parsing fails
            ValueError: If credential storage fails

        Example:
            >>> manager = AutoSaveCredentialManager(storage_backend="keyring")
            >>> extractor = CredentialExtractor()
            >>> sanitized, extracted, backup = extractor.extract_and_secure(
            ...     Path("config/migration.yaml"), manager
            ... )
            >>> print(f"Extracted: {extracted}")
            >>> # ["okta_token", "onelogin_client_id", "onelogin_client_secret"]
        """
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        # Load YAML config
        LOGGER.info(f"Loading configuration from {config_path}")
        with open(config_path) as f:
            config = yaml.safe_load(f)

        if not config:
            raise ValueError("Configuration file is empty")

        # Detect credentials
        credentials = self.detect_credentials(config)
        LOGGER.info(f"Detected {len(credentials)} credentials in configuration")

        if not credentials:
            LOGGER.warning("No credentials detected in configuration")
            return (config, [], config_path)

        # Store credentials securely
        extracted_names = []
        failed_credentials = []

        for service, key, value, path in credentials:
            # Generate credential name
            cred_name = self.CREDENTIAL_PATHS.get((service, key), f"{service}_{key}")

            # Store credential
            LOGGER.debug(f"Storing credential: {service}.{key} (path: {'.'.join(path)})")
            success = credential_manager.auto_save_credential(service, key, value)

            if success:
                extracted_names.append(cred_name)
            else:
                failed_credentials.append(f"{service}.{key}")
                LOGGER.error(f"Failed to store credential: {service}.{key}")

        if failed_credentials:
            raise ValueError(f"Failed to store credentials: {', '.join(failed_credentials)}")

        # Create sanitized config (remove credentials, add source references)
        sanitized_config = self._sanitize_config(
            config, credentials, credential_manager.storage_backend
        )

        # Create timestamped backup
        backup_path = self._create_backup(config_path)
        LOGGER.info(f"Created backup: {backup_path}")

        # Save sanitized config to original path
        LOGGER.info(f"Saving sanitized configuration to {config_path}")
        with open(config_path, "w") as f:
            yaml.safe_dump(sanitized_config, f, default_flow_style=False, sort_keys=False)

        return (sanitized_config, extracted_names, backup_path)

    def _sanitize_config(
        self,
        config: dict[str, Any],
        credentials: list[tuple[str, str, str, list[str]]],
        backend: str,
    ) -> dict[str, Any]:
        """Create sanitized config with credential references.

        Args:
            config: Original configuration
            credentials: List of (service, key, value, path) tuples
            backend: Storage backend name

        Returns:
            Sanitized configuration with credentials removed
        """
        import copy

        sanitized = copy.deepcopy(config)

        # Remove credentials and add source references by following paths
        for service, key, value, path in credentials:
            # Navigate to the parent of the credential
            current = sanitized
            for path_key in path[:-1]:
                if not isinstance(current, dict) or path_key not in current:
                    # Path doesn't exist in sanitized copy, skip
                    break
                current = current[path_key]
            else:
                # We successfully navigated to the parent
                final_key = path[-1]
                if isinstance(current, dict) and final_key in current:
                    # Remove the credential value
                    del current[final_key]
                    # Add source reference
                    current[f"{final_key}_source"] = backend

        return sanitized

    def _create_backup(self, config_path: Path) -> Path:
        """Create timestamped backup of configuration file.

        Args:
            config_path: Path to configuration file

        Returns:
            Path to backup file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{config_path.stem}_backup_{timestamp}{config_path.suffix}"
        backup_path = config_path.parent / backup_name

        shutil.copy2(config_path, backup_path)
        return backup_path

    def restore_credentials(
        self, config_path: Path, credential_manager: AutoSaveCredentialManager
    ) -> dict[str, Any]:
        """Restore credentials from secure storage into config.

        This method is the reverse of extract_and_secure. It loads a sanitized
        config and populates credential fields from secure storage.

        Args:
            config_path: Path to sanitized YAML config
            credential_manager: Credential manager with stored credentials

        Returns:
            Configuration with credentials restored

        Example:
            >>> # After extract_and_secure has been run
            >>> config = extractor.restore_credentials(
            ...     Path("config/migration.yaml"), manager
            ... )
            >>> # config now has actual credential values
        """
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        # Load sanitized config
        with open(config_path) as f:
            config = yaml.safe_load(f)

        if not config:
            return {}

        # Find all *_source references
        def restore_section(section_name: str, section_data: dict[str, Any]) -> None:
            """Restore credentials in a config section."""
            source_keys = [k for k in section_data.keys() if k.endswith("_source")]

            for source_key in source_keys:
                # Get the original key name (remove _source suffix)
                credential_key = source_key[:-7]  # Remove "_source"

                # Retrieve from secure storage
                credential = credential_manager.get_credential(section_name, credential_key)

                if credential:
                    # Add credential back to config
                    section_data[credential_key] = credential.reveal()
                    # Remove source reference
                    del section_data[source_key]
                else:
                    LOGGER.warning(
                        f"Credential not found in storage: {section_name}.{credential_key}"
                    )

        # Restore credentials for each section
        for section_name, section_data in config.items():
            if isinstance(section_data, dict):
                restore_section(section_name, section_data)

        return config

    def migrate_config(
        self,
        source_path: Path,
        dest_path: Path,
        credential_manager: AutoSaveCredentialManager,
        create_backup: bool = True,
    ) -> tuple[Path, list[str]]:
        """Migrate a config file to use secure credential storage.

        This is a convenience method that combines extract_and_secure with
        saving to a new location.

        Args:
            source_path: Original config file
            dest_path: Destination for sanitized config
            credential_manager: Credential manager
            create_backup: Whether to create backup of source

        Returns:
            Tuple of (backup_path, extracted_credential_names)
        """
        # Extract and secure
        sanitized_config, extracted_names, backup_path = self.extract_and_secure(
            source_path, credential_manager
        )

        # Save to destination
        with open(dest_path, "w") as f:
            yaml.safe_dump(sanitized_config, f, default_flow_style=False, sort_keys=False)

        LOGGER.info(f"Migrated configuration saved to {dest_path}")

        return (backup_path, extracted_names)

    def validate_sanitized_config(self, config_path: Path) -> tuple[bool, list[str]]:
        """Validate that a config has been properly sanitized.

        Checks that no credential values remain in the config file.

        Args:
            config_path: Path to configuration file

        Returns:
            Tuple of (is_sanitized, list_of_remaining_credentials)
        """
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path) as f:
            config = yaml.safe_load(f)

        if not config:
            return (True, [])

        # Detect any remaining credentials
        remaining = self.detect_credentials(config)

        if remaining:
            remaining_names = [f"{service}.{key}" for service, key, _, _ in remaining]
            return (False, remaining_names)

        return (True, [])

    def get_credential_mapping(self, config: dict[str, Any]) -> dict[str, tuple[str, str]]:
        """Get a mapping of credential names to their (service, key) locations.

        Args:
            config: Configuration dictionary

        Returns:
            Dictionary mapping credential_name -> (service, key)

        Example:
            >>> mapping = extractor.get_credential_mapping(config)
            >>> # {"okta_token": ("okta", "token"), ...}
        """
        credentials = self.detect_credentials(config)
        mapping = {}

        for service, key, _, _ in credentials:
            cred_name = self.CREDENTIAL_PATHS.get((service, key), f"{service}_{key}")
            mapping[cred_name] = (service, key)

        return mapping


__all__ = ["CredentialExtractor"]
