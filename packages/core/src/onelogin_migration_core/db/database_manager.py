"""Database manager for split catalog/user architecture.

This module manages both:
1. Catalog database (bundled, read-only) - connector catalogs and mappings
2. User database (runtime, writable) - telemetry and user overrides
"""

from __future__ import annotations

import logging
import os
import platform
import sqlite3
import sys
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


class DatabaseManager:
    """Manages both catalog (bundled) and user (runtime) databases."""

    def __init__(self):
        """Initialize database manager with both databases."""
        self.catalog_path = self._get_catalog_path()
        self.user_path = self._get_user_path()

        # Initialize connections
        self.catalog_conn: sqlite3.Connection | None = None
        self.user_conn: sqlite3.Connection | None = None

        # Connect to both databases
        self._connect_catalog()
        self._connect_user()

    def _get_catalog_path(self) -> Path:
        """Get path to bundled catalog database.

        Returns:
            Path to catalog.db (either bundled or development location)
        """
        if getattr(sys, "frozen", False):
            # Running as PyInstaller bundle
            bundle_dir = Path(sys._MEIPASS)
            catalog_path = bundle_dir / "resources" / "catalog.db"
            LOGGER.info("Running as bundle, catalog at: %s", catalog_path)
            return catalog_path
        else:
            # Development mode - check if resources/catalog.db exists
            resources_dir = Path(__file__).parent.parent / "resources"
            catalog_path = resources_dir / "catalog.db"

            if not catalog_path.exists():
                # Fall back to old location during migration
                old_path = Path.home() / ".onelogin-migration" / "connectors.db"
                if old_path.exists():
                    LOGGER.warning(
                        "Catalog database not found at %s, using legacy database at %s",
                        catalog_path,
                        old_path,
                    )
                    return old_path

            LOGGER.info("Development mode, catalog at: %s", catalog_path)
            return catalog_path

    def _get_user_path(self) -> Path:
        """Get path to user database.

        Returns:
            Path to user_data.db (in app resources directory for packaging)
        """
        if getattr(sys, "frozen", False):
            # Running as PyInstaller bundle - use writable app support directory
            if platform.system() == "Darwin":
                # macOS: ~/Library/Application Support/OneLogin Migration Tool/
                app_support = (
                    Path.home()
                    / "Library"
                    / "Application Support"
                    / "OneLogin Migration Tool"
                )
            elif platform.system() == "Windows":
                # Windows: %APPDATA%\OneLogin Migration Tool\
                app_support = (
                    Path(os.getenv("APPDATA", Path.home())) / "OneLogin Migration Tool"
                )
            else:
                # Linux: ~/.local/share/OneLogin Migration Tool/
                app_support = (
                    Path.home() / ".local" / "share" / "OneLogin Migration Tool"
                )

            app_support.mkdir(parents=True, exist_ok=True)
            return app_support / "user_data.db"
        else:
            # Development mode - use resources directory for simplicity
            resources_dir = Path(__file__).parent.parent / "resources"
            resources_dir.mkdir(parents=True, exist_ok=True)
            return resources_dir / "user_data.db"

    def _connect_catalog(self):
        """Connect to catalog database (read-only)."""
        if not self.catalog_path.exists():
            raise FileNotFoundError(
                f"Catalog database not found at {self.catalog_path}. "
                "Run 'python scripts/build_catalog_db.py' to create it."
            )

        try:
            # Open as read-only using URI
            # Note: check_same_thread=False is safe for read-only bundled catalogs
            # and necessary for concurrent access when multithreading is enabled
            self.catalog_conn = sqlite3.connect(
                f"file:{self.catalog_path}?mode=ro", uri=True, check_same_thread=False
            )
            self.catalog_conn.row_factory = sqlite3.Row
            LOGGER.info("Connected to catalog database: %s", self.catalog_path)
        except sqlite3.Error as e:
            LOGGER.error("Failed to connect to catalog database: %s", e)
            raise

    def _connect_user(self):
        """Connect to user database (create if needed)."""
        # Create database if it doesn't exist
        if not self.user_path.exists():
            self._create_user_database()

        # Fix permissions if needed
        current_mode = os.stat(self.user_path).st_mode
        if (current_mode & 0o777) != 0o600:
            try:
                os.chmod(self.user_path, 0o600)
                LOGGER.info("Updated user database permissions to 0o600")
            except OSError as e:
                LOGGER.warning("Failed to update user database permissions: %s", e)

        try:
            # Note: check_same_thread=False is safe for our use case with proper locking
            self.user_conn = sqlite3.connect(str(self.user_path), check_same_thread=False)
            self.user_conn.row_factory = sqlite3.Row
            self.user_conn.execute("PRAGMA foreign_keys = ON")
            LOGGER.info("Connected to user database: %s", self.user_path)
        except sqlite3.Error as e:
            LOGGER.error("Failed to connect to user database: %s", e)
            raise

    def _create_user_database(self):
        """Create user database with schema."""
        LOGGER.info("Creating new user database at %s", self.user_path)

        # Create with secure permissions
        self.user_path.touch(mode=0o600)

        # Load and execute schema
        schema_path = Path(__file__).parent / "user_data_schema.sql"
        if not schema_path.exists():
            raise FileNotFoundError(f"User data schema not found: {schema_path}")

        schema_sql = schema_path.read_text()

        conn = sqlite3.connect(str(self.user_path))
        try:
            conn.executescript(schema_sql)
            conn.commit()
            LOGGER.info("User database schema initialized")
        finally:
            conn.close()

    # ========================================================================
    # CATALOG QUERIES (Read-Only)
    # ========================================================================

    def get_onelogin_connector(self, connector_id: int) -> sqlite3.Row | None:
        """Get OneLogin connector from catalog by ID.

        Args:
            connector_id: OneLogin connector ID

        Returns:
            Connector row or None if not found
        """
        cursor = self.catalog_conn.execute(
            "SELECT * FROM onelogin_connectors WHERE id = ?", (connector_id,)
        )
        return cursor.fetchone()

    def get_onelogin_connector_by_name(self, name: str) -> sqlite3.Row | None:
        """Get OneLogin connector from catalog by name.

        Args:
            name: OneLogin connector name

        Returns:
            Connector row or None if not found
        """
        cursor = self.catalog_conn.execute(
            "SELECT * FROM onelogin_connectors WHERE name = ?", (name,)
        )
        return cursor.fetchone()

    def search_onelogin_connectors(
        self, search: str, limit: int = 10
    ) -> list[sqlite3.Row]:
        """Search OneLogin connectors in catalog.

        Args:
            search: Search term
            limit: Maximum number of results

        Returns:
            List of matching connector rows
        """
        cursor = self.catalog_conn.execute(
            """
            SELECT * FROM onelogin_connectors
            WHERE name LIKE ?
            ORDER BY name
            LIMIT ?
        """,
            (f"%{search}%", limit),
        )
        return cursor.fetchall()

    def get_okta_connector(self, internal_name: str) -> sqlite3.Row | None:
        """Get Okta connector from catalog.

        Args:
            internal_name: Okta internal connector name

        Returns:
            Connector row or None if not found
        """
        cursor = self.catalog_conn.execute(
            "SELECT * FROM okta_connectors WHERE internal_name = ?", (internal_name,)
        )
        return cursor.fetchone()

    def search_okta_connectors(self, search: str, limit: int = 10) -> list[sqlite3.Row]:
        """Search Okta connectors in catalog.

        Args:
            search: Search term
            limit: Maximum number of results

        Returns:
            List of matching connector rows
        """
        cursor = self.catalog_conn.execute(
            """
            SELECT * FROM okta_connectors
            WHERE internal_name LIKE ? OR display_name LIKE ?
            ORDER BY display_name
            LIMIT ?
        """,
            (f"%{search}%", f"%{search}%", limit),
        )
        return cursor.fetchall()

    def get_connector_mapping(self, okta_internal_name: str) -> dict[str, Any] | None:
        """Get best mapping for Okta connector (with user override if exists).

        This method checks user overrides first, then falls back to catalog mapping.

        Args:
            okta_internal_name: Okta connector internal name

        Returns:
            Dictionary with mapping info or None if not found
        """
        # Check user override first
        cursor = self.user_conn.execute(
            """
            SELECT
                preferred_onelogin_id as onelogin_connector_id,
                'user_override' as match_type,
                100.0 as confidence_score,
                notes
            FROM user_connector_overrides
            WHERE okta_internal_name = ?
        """,
            (okta_internal_name,),
        )

        override = cursor.fetchone()
        if override:
            # Get OneLogin connector details from catalog
            onelogin = self.get_onelogin_connector(override["onelogin_connector_id"])
            return {
                "okta_internal_name": okta_internal_name,
                "onelogin_id": override["onelogin_connector_id"],
                "onelogin_name": onelogin["name"] if onelogin else None,
                "match_type": "user_override",
                "confidence_score": 100.0,
                "source": "user",
                "notes": override["notes"],
            }

        # Fall back to catalog mapping
        cursor = self.catalog_conn.execute(
            """
            SELECT
                cm.onelogin_id,
                cm.match_type,
                cm.confidence_score,
                cm.source,
                ol.name as onelogin_name
            FROM connector_mappings cm
            JOIN onelogin_connectors ol ON cm.onelogin_id = ol.id
            WHERE cm.okta_internal_name = ?
            ORDER BY cm.confidence_score DESC
            LIMIT 1
        """,
            (okta_internal_name,),
        )

        mapping = cursor.fetchone()
        if mapping:
            return dict(mapping)

        return None

    def get_all_mappings_for_app(self, okta_internal_name: str) -> list[dict[str, Any]]:
        """Get all connector mappings for a specific Okta connector.

        Args:
            okta_internal_name: Okta connector internal name

        Returns:
            List of all mappings for this connector, ordered by confidence score
        """
        cursor = self.catalog_conn.execute(
            """
            SELECT
                cm.okta_internal_name,
                cm.onelogin_id,
                cm.match_type,
                cm.confidence_score,
                cm.source,
                ol.name as onelogin_name,
                ol.auth_method
            FROM connector_mappings cm
            JOIN onelogin_connectors ol ON cm.onelogin_id = ol.id
            WHERE cm.okta_internal_name = ?
            ORDER BY cm.confidence_score DESC
        """,
            (okta_internal_name,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_best_mapping(self, okta_internal_name: str) -> dict[str, Any] | None:
        """Alias for get_connector_mapping for backward compatibility.

        Args:
            okta_internal_name: Okta connector internal name

        Returns:
            Best mapping dictionary or None
        """
        return self.get_connector_mapping(okta_internal_name)

    def get_all_mappings(
        self, okta_internal_name: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all connector mappings (optionally for a specific Okta connector).

        Args:
            okta_internal_name: Optional Okta connector internal name.
                               If provided, returns mappings for that connector only.
                               If None, returns all mappings from catalog.

        Returns:
            List of mapping dictionaries
        """
        if okta_internal_name:
            return self.get_all_mappings_for_app(okta_internal_name)

        # Return all mappings from catalog
        cursor = self.catalog_conn.execute(
            """
            SELECT * FROM connector_mappings
            ORDER BY confidence_score DESC
        """
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_all_mappings_legacy(self) -> list[sqlite3.Row]:
        """Get all connector mappings from catalog.

        Returns:
            List of all mapping rows
        """
        cursor = self.catalog_conn.execute(
            """
            SELECT * FROM connector_mappings
            ORDER BY confidence_score DESC
        """
        )
        return cursor.fetchall()

    # ========================================================================
    # USER DATA OPERATIONS (Read/Write)
    # ========================================================================

    def save_user_override(
        self, okta_internal_name: str, onelogin_id: int, notes: str = None
    ):
        """Save user's mapping override.

        Args:
            okta_internal_name: Okta connector internal name
            onelogin_id: Preferred OneLogin connector ID
            notes: Optional notes about the override
        """
        self.user_conn.execute(
            """
            INSERT OR REPLACE INTO user_connector_overrides
            (okta_internal_name, preferred_onelogin_id, notes)
            VALUES (?, ?, ?)
        """,
            (okta_internal_name, onelogin_id, notes),
        )
        self.user_conn.commit()
        LOGGER.info("Saved user override: %s -> %d", okta_internal_name, onelogin_id)

    def get_user_override(self, okta_internal_name: str) -> sqlite3.Row | None:
        """Get user's mapping override if it exists.

        Args:
            okta_internal_name: Okta connector internal name

        Returns:
            Override row or None
        """
        cursor = self.user_conn.execute(
            """
            SELECT * FROM user_connector_overrides
            WHERE okta_internal_name = ?
        """,
            (okta_internal_name,),
        )
        return cursor.fetchone()

    def save_user_override_batch(self, overrides: list[dict[str, Any]]):
        """Save multiple user mapping overrides at once (for bulk auto-save).

        Args:
            overrides: List of dicts with keys: okta_internal_name, onelogin_id, notes
        """
        if not overrides:
            return

        self.user_conn.executemany(
            """
            INSERT OR REPLACE INTO user_connector_overrides
            (okta_internal_name, preferred_onelogin_id, notes)
            VALUES (?, ?, ?)
        """,
            [
                (o["okta_internal_name"], o["onelogin_id"], o.get("notes"))
                for o in overrides
            ],
        )
        self.user_conn.commit()
        LOGGER.info("Saved %d user overrides in batch", len(overrides))

    def delete_user_override(self, okta_internal_name: str):
        """Delete user's mapping override.

        Args:
            okta_internal_name: Okta connector internal name
        """
        self.user_conn.execute(
            """
            DELETE FROM user_connector_overrides
            WHERE okta_internal_name = ?
        """,
            (okta_internal_name,),
        )
        self.user_conn.commit()
        LOGGER.info("Deleted user override: %s", okta_internal_name)

    def save_telemetry(self, event_data: dict[str, Any]):
        """Save telemetry event to user database.

        Args:
            event_data: Telemetry event data
        """
        self.user_conn.execute(
            """
            INSERT INTO connector_telemetry
            (installation_id, okta_connector_hash, onelogin_connector_id,
             suggested, accepted, confidence_score, match_type, migration_run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                event_data.get("installation_id"),
                event_data.get("okta_connector_hash"),
                event_data.get("onelogin_connector_id"),
                event_data.get("suggested"),
                event_data.get("accepted"),
                event_data.get("confidence_score"),
                event_data.get("match_type"),
                event_data.get("migration_run_id"),
            ),
        )
        self.user_conn.commit()

    def get_telemetry_stats(self) -> dict[str, Any]:
        """Get telemetry statistics from user database.

        Returns:
            Dictionary with telemetry stats
        """
        cursor = self.user_conn.execute(
            """
            SELECT
                COUNT(*) as total_events,
                COUNT(DISTINCT okta_connector_hash) as unique_connectors,
                SUM(CASE WHEN accepted = 1 THEN 1 ELSE 0 END) as accepted_mappings,
                SUM(CASE WHEN suggested = 1 THEN 1 ELSE 0 END) as suggested_mappings,
                AVG(confidence_score) as avg_confidence
            FROM connector_telemetry
        """
        )
        return dict(cursor.fetchone())

    # ========================================================================
    # CONNECTION MANAGEMENT
    # ========================================================================

    def close(self):
        """Close both database connections."""
        if self.catalog_conn:
            self.catalog_conn.close()
            self.catalog_conn = None
            LOGGER.info("Closed catalog database connection")

        if self.user_conn:
            self.user_conn.close()
            self.user_conn = None
            LOGGER.info("Closed user database connection")

    def __enter__(self) -> DatabaseManager:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if exc_type is None and self.user_conn:
            self.user_conn.commit()
        elif self.user_conn:
            self.user_conn.rollback()
        self.close()


# Singleton instance
_db_manager: DatabaseManager | None = None


def get_database_manager() -> DatabaseManager:
    """Get singleton database manager instance.

    Returns:
        DatabaseManager instance
    """
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def reset_database_manager():
    """Reset singleton instance (useful for testing)."""
    global _db_manager
    if _db_manager:
        _db_manager.close()
    _db_manager = None
