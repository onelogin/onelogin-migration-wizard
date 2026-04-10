"""OneLogin Migration Core Library.

This package provides the core business logic for migrating identity data
from Okta to OneLogin. It can be used standalone or as a dependency for
CLI and GUI interfaces.

Modules:
- constants: Shared constants and field definitions
- transformers: Field transformation and normalization
- custom_attributes: Custom attribute discovery and provisioning
- state_manager: State persistence for resumable migrations
- csv_generator: Bulk user upload CSV generation
- exporters: Okta data export utilities
- importers: OneLogin data import utilities
- manager: High-level migration orchestration
- clients: API clients for Okta and OneLogin
- config: Configuration management
- credentials: Secure credential storage
- progress: Migration progress tracking

Example:
    >>> from onelogin_migration_core import MigrationManager, MigrationSettings
    >>> settings = MigrationSettings.from_file("config.yaml")
    >>> manager = MigrationManager(settings)
    >>> result = manager.run()
"""

from .clients import OktaClient, OneLoginClient
from .config import MigrationSettings
from .constants import (
    DEFAULT_APPLICATION_CONNECTORS,
    KNOWN_STANDARD_FIELDS,
)
from .csv_generator import BulkUserCSVGenerator
from .custom_attributes import CustomAttributeManager
from .exporters import OktaExporter
from .importers import MigrationAborted, OneLoginImporter
from .manager import MigrationManager
from .progress import MigrationProgress, ProgressSnapshot
from .state_manager import StateManager
from .transformers import FieldTransformer

__version__ = "0.2.0"

__all__ = [
    # Constants
    "DEFAULT_APPLICATION_CONNECTORS",
    "KNOWN_STANDARD_FIELDS",
    # Main classes
    "MigrationManager",
    "MigrationSettings",
    "OktaClient",
    "OneLoginClient",
    "MigrationProgress",
    "ProgressSnapshot",
    # Supporting classes
    "CustomAttributeManager",
    "BulkUserCSVGenerator",
    "OktaExporter",
    "OneLoginImporter",
    "StateManager",
    "FieldTransformer",
    "MigrationAborted",
]
