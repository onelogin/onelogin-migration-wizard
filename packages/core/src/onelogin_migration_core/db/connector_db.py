"""Connector database access layer for OneLogin migration tool.

This module provides a SQLite-backed database for:
- Okta and OneLogin connector catalogs
- Connector mappings between platforms
- Migration telemetry and analytics
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


class ConnectorDatabase:
    """SQLite database for connector catalogs and mappings."""

    def __init__(self, db_path: Path | None = None):
        """Initialize connector database.

        Args:
            db_path: Path to SQLite database file.
                    Defaults to bundled catalog or ~/.onelogin-migration/connectors.db
        """
        if db_path is None:
            # Try bundled catalog first (in resources directory)
            resources_path = Path(__file__).parent.parent / "resources" / "catalog.db"

            if resources_path.exists():
                db_path = resources_path
                self.is_bundled = True
                LOGGER.info("Using bundled catalog database: %s", db_path)
            else:
                # Fallback to legacy location
                db_path = Path.home() / ".onelogin-migration" / "connectors.db"
                self.is_bundled = False
                LOGGER.warning(
                    "Bundled catalog not found at %s, using legacy database: %s",
                    resources_path,
                    db_path,
                )
        else:
            # Explicit path provided - assume it's not bundled
            self.is_bundled = False

        self.db_path = db_path

        # Only create/modify permissions for user databases, not bundled catalogs
        if not self.is_bundled:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            # Create database file with secure permissions if it doesn't exist
            if not self.db_path.exists():
                self.db_path.touch(mode=0o600)
            else:
                # Fix permissions on existing database files
                import os
                import stat

                current_mode = os.stat(self.db_path).st_mode
                secure_mode = stat.S_IRUSR | stat.S_IWUSR  # 0o600 - owner read/write only

                if (current_mode & 0o777) != 0o600:
                    try:
                        os.chmod(self.db_path, secure_mode)
                        LOGGER.info(
                            "Updated database permissions to 0o600 (owner only): %s",
                            self.db_path,
                        )
                    except OSError as e:
                        LOGGER.warning("Failed to update database permissions: %s", e)

        self.conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Get or create database connection.

        Returns:
            Active SQLite connection with row factory enabled.
        """
        if self.conn is None:
            # Open bundled catalogs as read-only
            # Note: check_same_thread=False is safe for read-only bundled catalogs
            # and necessary for concurrent access when multithreading is enabled
            if self.is_bundled:
                self.conn = sqlite3.connect(
                    f"file:{self.db_path}?mode=ro",
                    uri=True,
                    check_same_thread=False,
                )
                LOGGER.debug("Opened bundled catalog as read-only (thread-safe)")
            else:
                self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                LOGGER.debug("Opened user database (thread-safe)")

            self.conn.row_factory = sqlite3.Row  # Enable column access by name
            # Enable foreign keys
            self.conn.execute("PRAGMA foreign_keys = ON")
        return self.conn

    def initialize_schema(self) -> None:
        """Initialize database schema from schema.sql file."""
        schema_path = Path(__file__).parent / "schema.sql"
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        conn = self.connect()
        schema_sql = schema_path.read_text()
        conn.executescript(schema_sql)
        conn.commit()
        LOGGER.info("Database schema initialized at %s", self.db_path)

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> ConnectorDatabase:
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.close()

    # ========================================================================
    # OneLogin Connectors
    # ========================================================================

    def insert_onelogin_connector(
        self,
        connector_id: int,
        name: str,
        icon_url: str | None = None,
        allows_new_parameters: bool = False,
        auth_method: int | None = None,
    ) -> None:
        """Insert a OneLogin connector into the database.

        Args:
            connector_id: OneLogin connector ID
            name: Connector display name
            icon_url: URL to connector icon
            allows_new_parameters: Whether connector allows custom parameters
            auth_method: Authentication method code
        """
        conn = self.connect()
        conn.execute(
            """
            INSERT OR REPLACE INTO onelogin_connectors
            (id, name, icon_url, allows_new_parameters, auth_method, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (connector_id, name, icon_url, allows_new_parameters, auth_method),
        )
        conn.commit()

    def insert_onelogin_connectors_bulk(self, connectors: list[dict[str, Any]]) -> int:
        """Bulk insert OneLogin connectors.

        Args:
            connectors: List of connector dictionaries with keys: id, name, icon_url, etc.

        Returns:
            Number of connectors inserted
        """
        conn = self.connect()
        cursor = conn.cursor()

        inserted = 0
        with_custom_params = 0
        for connector in connectors:
            try:
                allows_new_params = connector.get("allows_new_parameters", False)
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO onelogin_connectors
                    (id, name, icon_url, allows_new_parameters, auth_method, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        connector.get("id"),
                        connector.get("name"),
                        connector.get("icon_url"),
                        allows_new_params,
                        connector.get("auth_method"),
                    ),
                )
                inserted += 1
                if allows_new_params:
                    with_custom_params += 1
                    LOGGER.debug(
                        "Connector '%s' (id=%s) supports custom parameters",
                        connector.get("name"),
                        connector.get("id"),
                    )
            except sqlite3.Error as e:
                LOGGER.warning(
                    "Failed to insert OneLogin connector %s: %s",
                    connector.get("name"),
                    e,
                )

        conn.commit()
        LOGGER.info(
            "Inserted %d OneLogin connectors (%d support custom parameters)",
            inserted,
            with_custom_params,
        )
        return inserted

    def get_onelogin_connector(self, connector_id: int) -> dict[str, Any] | None:
        """Get OneLogin connector by ID.

        Args:
            connector_id: OneLogin connector ID

        Returns:
            Connector dictionary or None if not found
        """
        conn = self.connect()
        cursor = conn.execute(
            "SELECT * FROM onelogin_connectors WHERE id = ?",
            (connector_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def search_onelogin_connectors(self, name_pattern: str) -> list[dict[str, Any]]:
        """Search OneLogin connectors by name (case-insensitive).

        Args:
            name_pattern: SQL LIKE pattern (e.g., "%salesforce%")

        Returns:
            List of matching connector dictionaries
        """
        conn = self.connect()
        cursor = conn.execute(
            "SELECT * FROM onelogin_connectors WHERE name LIKE ? COLLATE NOCASE ORDER BY name",
            (name_pattern,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_all_onelogin_connectors(self) -> list[dict[str, Any]]:
        """Get all OneLogin connectors from the database.

        Returns:
            List of all OneLogin connector dictionaries, ordered by name.
        """
        conn = self.connect()
        cursor = conn.execute("SELECT * FROM onelogin_connectors ORDER BY name")
        return [dict(row) for row in cursor.fetchall()]

    def get_connectors_with_custom_parameters(self) -> list[dict[str, Any]]:
        """Get OneLogin connectors that support custom parameters.

        Returns:
            List of connector dictionaries where allows_new_parameters is TRUE.
        """
        conn = self.connect()
        cursor = conn.execute(
            "SELECT * FROM onelogin_connectors WHERE allows_new_parameters = 1 ORDER BY name"
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_connectors_stats(self) -> dict[str, int]:
        """Get statistics about connectors in the database.

        Returns:
            Dictionary with connector counts:
            - total: Total number of connectors
            - with_custom_params: Connectors that support custom parameters
            - without_custom_params: Connectors that don't support custom parameters
        """
        conn = self.connect()

        cursor = conn.execute("SELECT COUNT(*) as total FROM onelogin_connectors")
        total = cursor.fetchone()["total"]

        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM onelogin_connectors WHERE allows_new_parameters = 1"
        )
        with_params = cursor.fetchone()["count"]

        return {
            "total": total,
            "with_custom_params": with_params,
            "without_custom_params": total - with_params,
        }

    # ========================================================================
    # Okta Connectors
    # ========================================================================

    def insert_okta_connector(
        self,
        internal_name: str,
        display_name: str,
        label: str | None = None,
        category: str | None = None,
        logo_url: str | None = None,
        status: str | None = None,
        sign_on_modes: list[str] | None = None,
        features: list[str] | None = None,
    ) -> None:
        """Insert an Okta connector into the database.

        Args:
            internal_name: Okta's internal connector identifier
            display_name: User-facing connector name
            label: Alternative label
            category: App category
            logo_url: Logo URL
            status: Connector status
            sign_on_modes: List of supported sign-on modes
            features: List of features
        """
        conn = self.connect()
        conn.execute(
            """
            INSERT OR REPLACE INTO okta_connectors
            (internal_name, display_name, label, category, logo_url, status,
             sign_on_modes, features, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                internal_name,
                display_name,
                label,
                category,
                logo_url,
                status,
                json.dumps(sign_on_modes) if sign_on_modes else None,
                json.dumps(features) if features else None,
            ),
        )
        conn.commit()

    def insert_okta_connectors_bulk(self, connectors: list[dict[str, Any]]) -> int:
        """Bulk insert Okta connectors.

        Args:
            connectors: List of connector dictionaries

        Returns:
            Number of connectors inserted
        """
        conn = self.connect()
        cursor = conn.cursor()

        inserted = 0
        for connector in connectors:
            try:
                # Extract sign_on_modes and features
                sign_on_modes = connector.get("signOnModes") or connector.get("sign_on_modes")
                features = connector.get("features")

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO okta_connectors
                    (internal_name, display_name, label, category, logo_url, status,
                     sign_on_modes, features, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        connector.get("name") or connector.get("internal_name"),
                        connector.get("label") or connector.get("display_name"),
                        connector.get("label"),
                        connector.get("category"),
                        connector.get("logoUrl") or connector.get("logo_url"),
                        connector.get("status"),
                        json.dumps(sign_on_modes) if sign_on_modes else None,
                        json.dumps(features) if features else None,
                    ),
                )
                inserted += 1
            except sqlite3.Error as e:
                LOGGER.warning(
                    "Failed to insert Okta connector %s: %s",
                    connector.get("name") or connector.get("label"),
                    e,
                )

        conn.commit()
        LOGGER.info("Inserted %d Okta connectors", inserted)
        return inserted

    def get_okta_connector(self, internal_name: str) -> dict[str, Any] | None:
        """Get Okta connector by internal name.

        Args:
            internal_name: Okta's internal connector identifier

        Returns:
            Connector dictionary or None if not found
        """
        conn = self.connect()
        cursor = conn.execute(
            "SELECT * FROM okta_connectors WHERE internal_name = ?",
            (internal_name,),
        )
        row = cursor.fetchone()
        if row:
            result = dict(row)
            # Deserialize JSON fields
            if result.get("sign_on_modes"):
                result["sign_on_modes"] = json.loads(result["sign_on_modes"])
            if result.get("features"):
                result["features"] = json.loads(result["features"])
            return result
        return None

    def search_okta_connectors(self, name_pattern: str) -> list[dict[str, Any]]:
        """Search Okta connectors by name.

        Args:
            name_pattern: SQL LIKE pattern

        Returns:
            List of matching connector dictionaries
        """
        conn = self.connect()
        cursor = conn.execute(
            "SELECT * FROM okta_connectors WHERE display_name LIKE ? OR label LIKE ? ORDER BY display_name",
            (name_pattern, name_pattern),
        )
        return [dict(row) for row in cursor.fetchall()]

    # ========================================================================
    # Connector Mappings
    # ========================================================================

    def insert_connector_mapping(
        self,
        okta_internal_name: str,
        okta_display_name: str,
        onelogin_id: int,
        onelogin_name: str,
        match_type: str,
        confidence_score: float = 100.0,
        source: str = "automated",
        normalized_name: str | None = None,
        similarity_score: float | None = None,
    ) -> None:
        """Insert a connector mapping.

        Args:
            okta_internal_name: Okta connector internal name
            okta_display_name: Okta connector display name
            onelogin_id: OneLogin connector ID
            onelogin_name: OneLogin connector name
            match_type: Type of match ('exact', 'fuzzy', 'manual', 'user_override')
            confidence_score: Confidence score (0-100)
            source: Source of mapping ('automated', 'user_corrected', 'verified')
            normalized_name: Normalized name used for matching
            similarity_score: Similarity score for fuzzy matches
        """
        conn = self.connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO connector_mappings
                (okta_internal_name, okta_display_name, onelogin_id, onelogin_name,
                 match_type, confidence_score, source, normalized_name, similarity_score, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    okta_internal_name,
                    okta_display_name,
                    onelogin_id,
                    onelogin_name,
                    match_type,
                    confidence_score,
                    source,
                    normalized_name,
                    similarity_score,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # Mapping already exists, update it
            LOGGER.debug(
                "Mapping already exists, updating: %s -> %s",
                okta_internal_name,
                onelogin_id,
            )

    def insert_connector_mappings_bulk(self, mappings: list[dict[str, Any]]) -> int:
        """Bulk insert connector mappings.

        Args:
            mappings: List of mapping dictionaries

        Returns:
            Number of mappings inserted
        """
        conn = self.connect()
        cursor = conn.cursor()

        inserted = 0
        for mapping in mappings:
            try:
                # Convert similarity score to confidence if needed
                confidence = mapping.get("confidence_score", 100.0)
                if "similarity_score" in mapping and confidence == 100.0:
                    # For fuzzy matches, use similarity as confidence
                    confidence = float(mapping.get("similarity_score", 100.0))

                cursor.execute(
                    """
                    INSERT OR IGNORE INTO connector_mappings
                    (okta_internal_name, okta_display_name, onelogin_id, onelogin_name,
                     match_type, confidence_score, source, normalized_name, similarity_score, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        mapping.get("oktaInternalName") or mapping.get("okta_internal_name"),
                        mapping.get("oktaName") or mapping.get("okta_display_name"),
                        mapping.get("oneloginId") or mapping.get("onelogin_id"),
                        mapping.get("oneloginName") or mapping.get("onelogin_name"),
                        mapping.get("matchType") or mapping.get("match_type", "exact"),
                        confidence,
                        mapping.get("source", "automated"),
                        mapping.get("normalizedName") or mapping.get("normalized_name"),
                        mapping.get("similarityScore") or mapping.get("similarity_score"),
                    ),
                )
                inserted += cursor.rowcount
            except sqlite3.Error as e:
                LOGGER.warning(
                    "Failed to insert mapping %s -> %s: %s",
                    mapping.get("oktaInternalName"),
                    mapping.get("oneloginId"),
                    e,
                )

        conn.commit()
        LOGGER.info("Inserted %d connector mappings", inserted)
        return inserted

    def get_best_mapping(self, okta_internal_name: str) -> dict[str, Any] | None:
        """Get best connector mapping for an Okta connector.

        This returns the mapping with highest confidence score, or user override if available.

        Args:
            okta_internal_name: Okta connector internal name

        Returns:
            Best mapping dictionary or None if no mapping found
        """
        conn = self.connect()

        # First check for user override (skip if table doesn't exist in bundled catalog)
        if not self.is_bundled:
            try:
                cursor = conn.execute(
                    """
                    SELECT
                        uo.okta_internal_name,
                        oc.display_name as okta_display_name,
                        uo.preferred_onelogin_id as onelogin_id,
                        olc.name as onelogin_name,
                        'user_override' as match_type,
                        100.0 as confidence_score,
                        'user_corrected' as source,
                        uo.notes
                    FROM user_connector_overrides uo
                    JOIN okta_connectors oc ON uo.okta_internal_name = oc.internal_name
                    JOIN onelogin_connectors olc ON uo.preferred_onelogin_id = olc.id
                    WHERE uo.okta_internal_name = ?
                    """,
                    (okta_internal_name,),
                )
                row = cursor.fetchone()
                if row:
                    return dict(row)
            except sqlite3.OperationalError as e:
                # Table doesn't exist - skip user overrides
                LOGGER.debug(f"Skipping user overrides check: {e}")

        # Otherwise get best automated mapping
        cursor = conn.execute(
            """
            SELECT * FROM best_connector_mappings
            WHERE okta_internal_name = ?
            ORDER BY confidence_score DESC
            LIMIT 1
            """,
            (okta_internal_name,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_all_mappings(self, okta_internal_name: str) -> list[dict[str, Any]]:
        """Get all connector mappings for an Okta connector.

        Args:
            okta_internal_name: Okta connector internal name

        Returns:
            List of mapping dictionaries, ordered by confidence
        """
        conn = self.connect()
        cursor = conn.execute(
            """
            SELECT * FROM connector_mappings
            WHERE okta_internal_name = ?
            ORDER BY confidence_score DESC
            """,
            (okta_internal_name,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def set_user_override(
        self, okta_internal_name: str, onelogin_id: int, notes: str | None = None
    ) -> None:
        """Set user's preferred connector mapping.

        Args:
            okta_internal_name: Okta connector internal name
            onelogin_id: Preferred OneLogin connector ID
            notes: Optional notes about this override
        """
        conn = self.connect()
        conn.execute(
            """
            INSERT OR REPLACE INTO user_connector_overrides
            (okta_internal_name, preferred_onelogin_id, notes, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (okta_internal_name, onelogin_id, notes),
        )
        conn.commit()
        LOGGER.info("Set user override: %s -> %s", okta_internal_name, onelogin_id)

    # ========================================================================
    # Statistics & Analytics
    # ========================================================================

    def get_mapping_statistics(self) -> list[dict[str, Any]]:
        """Get mapping statistics grouped by match type and source.

        Returns:
            List of statistics dictionaries
        """
        conn = self.connect()
        cursor = conn.execute("SELECT * FROM mapping_statistics")
        return [dict(row) for row in cursor.fetchall()]

    def get_connector_counts(self) -> dict[str, int]:
        """Get counts of connectors and mappings.

        Returns:
            Dictionary with counts for okta, onelogin, mappings, etc.
        """
        conn = self.connect()

        counts = {}

        # Count Okta connectors
        cursor = conn.execute("SELECT COUNT(*) FROM okta_connectors")
        counts["okta_connectors"] = cursor.fetchone()[0]

        # Count OneLogin connectors
        cursor = conn.execute("SELECT COUNT(*) FROM onelogin_connectors")
        counts["onelogin_connectors"] = cursor.fetchone()[0]

        # Count mappings
        cursor = conn.execute("SELECT COUNT(*) FROM connector_mappings")
        counts["total_mappings"] = cursor.fetchone()[0]

        # Count exact matches
        cursor = conn.execute("SELECT COUNT(*) FROM connector_mappings WHERE match_type = 'exact'")
        counts["exact_matches"] = cursor.fetchone()[0]

        # Count fuzzy matches
        cursor = conn.execute("SELECT COUNT(*) FROM connector_mappings WHERE match_type = 'fuzzy'")
        counts["fuzzy_matches"] = cursor.fetchone()[0]

        # Count user overrides (skip if table doesn't exist in bundled catalog)
        if not self.is_bundled:
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM user_connector_overrides")
                counts["user_overrides"] = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                counts["user_overrides"] = 0
        else:
            counts["user_overrides"] = 0

        return counts

    def get_user_override(self, okta_internal_name: str) -> dict[str, Any] | None:
        """Get user's connector mapping override if it exists.

        Args:
            okta_internal_name: Okta connector internal name

        Returns:
            Override dictionary or None
        """
        if self.is_bundled:
            # Bundled catalog is read-only, no overrides
            return None

        conn = self.connect()
        try:
            cursor = conn.execute(
                """
                SELECT okta_internal_name, preferred_onelogin_id as onelogin_id, notes
                FROM user_connector_overrides
                WHERE okta_internal_name = ?
                """,
                (okta_internal_name,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        except sqlite3.OperationalError:
            # Table doesn't exist yet
            return None

    def save_user_override(self, okta_internal_name: str, onelogin_id: int, notes: str = None):
        """Save user's mapping override.

        Args:
            okta_internal_name: Okta connector internal name
            onelogin_id: Preferred OneLogin connector ID
            notes: Optional notes about the override
        """
        if self.is_bundled:
            raise RuntimeError("Cannot save overrides to read-only bundled catalog")

        conn = self.connect()
        conn.execute(
            """
            INSERT OR REPLACE INTO user_connector_overrides
            (okta_internal_name, preferred_onelogin_id, notes)
            VALUES (?, ?, ?)
            """,
            (okta_internal_name, onelogin_id, notes),
        )
        conn.commit()
        LOGGER.info("Saved user override: %s -> %d", okta_internal_name, onelogin_id)

    def save_user_override_batch(self, overrides: list[dict[str, Any]]):
        """Save multiple user mapping overrides at once (for bulk auto-save).

        Args:
            overrides: List of dicts with keys: okta_internal_name, onelogin_id, notes
        """
        if self.is_bundled:
            raise RuntimeError("Cannot save overrides to read-only bundled catalog")

        if not overrides:
            return

        conn = self.connect()
        conn.executemany(
            """
            INSERT OR REPLACE INTO user_connector_overrides
            (okta_internal_name, preferred_onelogin_id, notes)
            VALUES (?, ?, ?)
            """,
            [(o["okta_internal_name"], o["onelogin_id"], o.get("notes")) for o in overrides],
        )
        conn.commit()
        LOGGER.info("Saved %d user overrides in batch", len(overrides))


def get_default_connector_db() -> ConnectorDatabase:
    """Get default connector database instance.

    This returns the bundled read-only catalog for connector lookups.
    For writable operations (telemetry, user preferences), use get_user_database() instead.

    Returns:
        ConnectorDatabase using bundled catalog (read-only) or user database
    """
    return ConnectorDatabase()


def get_user_database() -> ConnectorDatabase:
    """Get user's writable database instance.

    This database is used for:
    - Telemetry data
    - User preferences and overrides
    - Migration history
    - Any data that needs to be written

    The database is automatically initialized with the full schema on first use.

    Returns:
        ConnectorDatabase at ~/.onelogin-migration/connectors.db (writable)
    """
    user_db_path = Path.home() / ".onelogin-migration" / "connectors.db"
    db = ConnectorDatabase(db_path=user_db_path)

    # Initialize schema if database is empty or missing required tables
    conn = db.connect()
    try:
        # Check if required tables exist (telemetry_settings and connector_refresh_log)
        cursor = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name IN ('telemetry_settings', 'connector_refresh_log')
            """
        )
        existing_tables = {row[0] for row in cursor.fetchall()}

        if len(existing_tables) < 2:  # Missing one or both required tables
            LOGGER.info(
                "Initializing user database schema at %s (missing tables: %s)",
                user_db_path,
                {"telemetry_settings", "connector_refresh_log"} - existing_tables,
            )
            db.initialize_schema()
    except Exception as e:
        LOGGER.warning("Error checking database schema: %s", e)
        # Try to initialize anyway
        try:
            db.initialize_schema()
        except Exception as init_error:
            LOGGER.error("Failed to initialize database schema: %s", init_error)

    return db
