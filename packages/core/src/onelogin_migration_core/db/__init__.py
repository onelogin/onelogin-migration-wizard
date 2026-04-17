"""Database module for connector catalogs and migration telemetry."""

from .connector_db import ConnectorDatabase, get_default_connector_db, get_user_database
from .connector_refresh import ConnectorRefreshService, get_connector_refresh_service
from .database_manager import DatabaseManager, get_database_manager, reset_database_manager
from .db_security import EncryptedConnectorDatabase, check_database_security
from .encryption import (
    EncryptionManager,
    get_encryption_manager,
    is_encryption_available,
    migrate_database_encryption,
)
from .telemetry import TelemetryManager, get_telemetry_manager

__all__ = [
    "ConnectorDatabase",
    "get_default_connector_db",
    "get_user_database",
    "ConnectorRefreshService",
    "get_connector_refresh_service",
    "TelemetryManager",
    "get_telemetry_manager",
    "EncryptedConnectorDatabase",
    "check_database_security",
    "EncryptionManager",
    "get_encryption_manager",
    "is_encryption_available",
    "migrate_database_encryption",
    "DatabaseManager",
    "get_database_manager",
    "reset_database_manager",
]
