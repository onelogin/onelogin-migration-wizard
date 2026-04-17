"""Privacy-compliant anonymized telemetry manager.

This module provides telemetry collection that:
- Requires explicit user consent (via license acceptance)
- Anonymizes all identifiable data using SHA-256 hashing
- Buckets precise counts to prevent user identification
- Never collects PII (names, emails, domains, etc.)
- Complies with SOC2, GDPR, CCPA, and HIPAA standards
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

from .connector_db import ConnectorDatabase, get_default_connector_db

# Import encryption manager for transparent encryption
try:
    from .encryption import get_encryption_manager, is_encryption_available

    ENCRYPTION_AVAILABLE = is_encryption_available()
except ImportError:
    ENCRYPTION_AVAILABLE = False
    LOGGER.warning("Encryption not available - install cryptography package")

LOGGER = logging.getLogger(__name__)


class TelemetryManager:
    """Manages anonymized telemetry collection with user consent."""

    def __init__(self, db: ConnectorDatabase | None = None):
        """Initialize telemetry manager.

        Args:
            db: ConnectorDatabase instance (defaults to default instance)
        """
        self.db = db or get_default_connector_db()
        self._consent_checked = False
        self._consent_granted = False
        self._installation_id: str | None = None

        # Initialize encryption manager
        if ENCRYPTION_AVAILABLE:
            self._encryption_manager = get_encryption_manager()
        else:
            self._encryption_manager = None
            LOGGER.warning(
                "Telemetry encryption DISABLED - cryptography package not installed. "
                "Data will be SHA-256 hashed but not encrypted."
            )

    def _check_consent(self) -> bool:
        """Check if user has granted telemetry consent via license acceptance.

        Returns:
            True if consent granted, False otherwise
        """
        if self._consent_checked:
            return self._consent_granted

        conn = self.db.connect()
        cursor = conn.execute(
            """
            SELECT enabled, installation_id
            FROM telemetry_settings
            WHERE enabled = 1
            LIMIT 1
        """
        )
        row = cursor.fetchone()

        self._consent_granted = bool(row)
        if row:
            self._installation_id = row["installation_id"]

        self._consent_checked = True
        LOGGER.debug(
            "Telemetry consent check: %s", "granted" if self._consent_granted else "not granted"
        )
        return self._consent_granted

    def _hash_identifier(self, value: str, salt: str = "connector") -> str:
        """One-way hash and encrypt for anonymizing identifiers.

        Two-layer protection:
        1. SHA-256 hashing for anonymization (irreversible)
        2. AES-256-GCM encryption for additional security

        Args:
            value: String to hash and encrypt
            salt: Salt prefix for hashing

        Returns:
            Encrypted SHA-256 hash (or plain hash if encryption unavailable)
        """
        if not value:
            return ""

        # Layer 1: SHA-256 for anonymization (irreversible)
        hashed = hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()

        # Layer 2: AES-256-GCM encryption (protects against database access)
        if self._encryption_manager and self._encryption_manager.is_available():
            return self._encryption_manager.encrypt(hashed)

        # Fallback: return hashed value without encryption
        # (Still anonymous due to SHA-256, just not encrypted)
        return hashed

    @staticmethod
    def _bucket_count(count: int) -> str:
        """Convert precise count to privacy-preserving bucket.

        Prevents exact user/group/app counting which could identify organizations.

        Args:
            count: Precise count

        Returns:
            Bucketed range string (e.g., "51-200")
        """
        if count <= 10:
            return "1-10"
        elif count <= 50:
            return "11-50"
        elif count <= 200:
            return "51-200"
        elif count <= 1000:
            return "201-1000"
        else:
            return "1000+"

    def log_connector_decision(
        self,
        migration_run_id: str,
        okta_connector_name: str,
        suggested_onelogin_id: int | None,
        actual_onelogin_id: int | None,
        confidence_score: float,
        match_type: str,
    ) -> None:
        """Log connector mapping decision (anonymized).

        Records whether users accept our suggested mappings or override them.
        This helps improve connector matching accuracy over time.

        Args:
            migration_run_id: Unique ID for this migration run (UUID)
            okta_connector_name: Okta app name (will be hashed)
            suggested_onelogin_id: Our suggested OneLogin connector ID
            actual_onelogin_id: Actual OneLogin connector ID used
            confidence_score: Confidence score of the mapping (0-100)
            match_type: Type of match ('exact', 'fuzzy', 'manual', 'user_override')
        """
        if not self._check_consent():
            return

        try:
            conn = self.db.connect()
            conn.execute(
                """
                INSERT INTO connector_telemetry
                (installation_id, okta_connector_hash, onelogin_connector_id,
                 suggested, accepted, confidence_score, match_type, migration_run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    self._installation_id,
                    self._hash_identifier(okta_connector_name),  # Hashed, never plaintext
                    actual_onelogin_id,
                    suggested_onelogin_id == actual_onelogin_id if suggested_onelogin_id else None,
                    True,  # If we got here, user proceeded with migration
                    confidence_score,
                    match_type,
                    migration_run_id,
                ),
            )
            conn.commit()
            LOGGER.debug(
                "Logged connector decision (anonymized): match_type=%s, confidence=%.1f",
                match_type,
                confidence_score,
            )
        except Exception as e:
            # Telemetry failures should never break migrations
            LOGGER.warning("Failed to log telemetry (non-fatal): %s", e)

    def log_error_pattern(
        self,
        migration_run_id: str,
        error_category: str,
        component: str,
        http_status: int | None = None,
        retry_count: int = 0,
        resolved: bool = False,
    ) -> None:
        """Log error pattern without sensitive details.

        Only logs error categories and types, never full error messages which
        may contain PII or sensitive information.

        Args:
            migration_run_id: Unique ID for this migration run
            error_category: Error category (exception class name)
            component: Component where error occurred ('user_migration', 'app_migration', etc.)
            http_status: HTTP status code if applicable
            retry_count: Number of retry attempts
            resolved: Whether the error was eventually resolved via retry
        """
        if not self._check_consent():
            return

        try:
            conn = self.db.connect()
            conn.execute(
                """
                INSERT INTO error_telemetry
                (installation_id, error_category, component, http_status,
                 retry_count, resolved, migration_run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    self._installation_id,
                    error_category,  # Class name only, not message
                    component,
                    http_status,
                    retry_count,
                    resolved,
                    migration_run_id,
                ),
            )
            conn.commit()
            LOGGER.debug(
                "Logged error pattern: %s in %s (resolved=%s)", error_category, component, resolved
            )
        except Exception as e:
            LOGGER.warning("Failed to log error telemetry (non-fatal): %s", e)

    def log_migration_scenario(
        self,
        migration_run_id: str,
        user_count: int,
        group_count: int,
        app_count: int,
        duration_seconds: int,
        success_rate: float,
        dry_run: bool,
        concurrency_enabled: bool,
    ) -> None:
        """Log migration scenario with bucketed counts for privacy.

        Uses bucketed counts (e.g., "51-200") instead of exact counts to prevent
        organization identification.

        Args:
            migration_run_id: Unique ID for this migration run
            user_count: Number of users migrated (will be bucketed)
            group_count: Number of groups migrated (will be bucketed)
            app_count: Number of apps migrated (will be bucketed)
            duration_seconds: Total migration duration in seconds
            success_rate: Overall success rate percentage (0-100)
            dry_run: Whether this was a dry run
            concurrency_enabled: Whether concurrency was enabled
        """
        if not self._check_consent():
            return

        try:
            conn = self.db.connect()
            conn.execute(
                """
                INSERT INTO migration_scenario_telemetry
                (installation_id, migration_run_id, user_count_bucket, group_count_bucket,
                 app_count_bucket, duration_seconds, success_rate_percent, dry_run, concurrency_enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    self._installation_id,
                    migration_run_id,
                    self._bucket_count(user_count),  # Bucketed, not exact
                    self._bucket_count(group_count),
                    self._bucket_count(app_count),
                    duration_seconds,
                    success_rate,
                    dry_run,
                    concurrency_enabled,
                ),
            )
            conn.commit()
            LOGGER.debug(
                "Logged migration scenario: users=%s, groups=%s, apps=%s, success=%.1f%%",
                self._bucket_count(user_count),
                self._bucket_count(group_count),
                self._bucket_count(app_count),
                success_rate,
            )
        except Exception as e:
            LOGGER.warning("Failed to log scenario telemetry (non-fatal): %s", e)

    def export_telemetry_report(self) -> dict[str, Any]:
        """Export anonymized telemetry for analysis.

        Returns aggregated, privacy-safe statistics about connector mappings,
        error patterns, and migration scenarios.

        Returns:
            Dictionary containing anonymized telemetry statistics
        """
        if not self._check_consent():
            return {
                "error": "Telemetry consent not granted",
                "message": "Accept the license agreement to enable telemetry",
            }

        conn = self.db.connect()

        # Connector mapping effectiveness
        cursor = conn.execute(
            """
            SELECT
                match_type,
                AVG(confidence_score) as avg_confidence,
                COUNT(*) as total_decisions,
                SUM(CASE WHEN accepted THEN 1 ELSE 0 END) as accepted_count,
                SUM(CASE WHEN suggested AND accepted THEN 1 ELSE 0 END) as correctly_suggested
            FROM connector_telemetry
            GROUP BY match_type
        """
        )
        connector_stats = [dict(row) for row in cursor.fetchall()]

        # Error patterns
        cursor = conn.execute(
            """
            SELECT
                error_category,
                component,
                COUNT(*) as occurrence_count,
                AVG(retry_count) as avg_retries,
                SUM(CASE WHEN resolved THEN 1 ELSE 0 END) as resolved_count,
                CAST(SUM(CASE WHEN resolved THEN 1 ELSE 0 END) AS REAL) / COUNT(*) * 100 as resolution_rate
            FROM error_telemetry
            GROUP BY error_category, component
            ORDER BY occurrence_count DESC
            LIMIT 20
        """
        )
        error_patterns = [dict(row) for row in cursor.fetchall()]

        # Migration scenarios
        cursor = conn.execute(
            """
            SELECT
                user_count_bucket,
                COUNT(*) as scenario_count,
                AVG(success_rate_percent) as avg_success_rate,
                AVG(duration_seconds) as avg_duration_seconds,
                SUM(CASE WHEN dry_run THEN 1 ELSE 0 END) as dry_run_count
            FROM migration_scenario_telemetry
            GROUP BY user_count_bucket
        """
        )
        scenarios = [dict(row) for row in cursor.fetchall()]

        return {
            "installation_id": self._installation_id,
            "generated_at": datetime.now().isoformat(),
            "connector_mapping_effectiveness": connector_stats,
            "error_patterns": error_patterns,
            "migration_scenarios": scenarios,
            "privacy_notice": "All data anonymized - no PII collected. Hashed identifiers cannot be reversed.",
        }

    def get_telemetry_status(self) -> dict[str, Any]:
        """Get current telemetry status and statistics.

        Returns:
            Dictionary with consent status and telemetry counts
        """
        conn = self.db.connect()

        # Check consent
        cursor = conn.execute(
            """
            SELECT enabled, user_consent_date, installation_id
            FROM telemetry_settings
            LIMIT 1
        """
        )
        row = cursor.fetchone()

        if not row:
            return {
                "enabled": False,
                "consent_date": None,
                "installation_id": None,
                "telemetry_counts": {
                    "connector_decisions": 0,
                    "error_patterns": 0,
                    "migration_scenarios": 0,
                },
            }

        # Get counts
        cursor = conn.execute("SELECT COUNT(*) FROM connector_telemetry")
        connector_count = cursor.fetchone()[0]

        cursor = conn.execute("SELECT COUNT(*) FROM error_telemetry")
        error_count = cursor.fetchone()[0]

        cursor = conn.execute("SELECT COUNT(*) FROM migration_scenario_telemetry")
        scenario_count = cursor.fetchone()[0]

        return {
            "enabled": bool(row["enabled"]),
            "consent_date": row["user_consent_date"],
            "installation_id": row["installation_id"],
            "telemetry_counts": {
                "connector_decisions": connector_count,
                "error_patterns": error_count,
                "migration_scenarios": scenario_count,
            },
        }

    def disable_telemetry(self) -> None:
        """Disable telemetry collection.

        User can re-enable by accepting the license again.
        """
        conn = self.db.connect()
        conn.execute(
            """
            UPDATE telemetry_settings
            SET enabled = 0,
                updated_at = CURRENT_TIMESTAMP
        """
        )
        conn.commit()
        self._consent_checked = False
        self._consent_granted = False
        LOGGER.info("Telemetry disabled by user")

    def clear_telemetry_data(self) -> int:
        """Clear all stored telemetry data.

        User's right to deletion under GDPR/CCPA.

        Returns:
            Total number of records deleted
        """
        conn = self.db.connect()

        # Count records before deletion
        cursor = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM connector_telemetry) +
                (SELECT COUNT(*) FROM error_telemetry) +
                (SELECT COUNT(*) FROM migration_scenario_telemetry) as total
        """
        )
        total_before = cursor.fetchone()[0]

        # Delete all telemetry data
        conn.execute("DELETE FROM connector_telemetry")
        conn.execute("DELETE FROM error_telemetry")
        conn.execute("DELETE FROM migration_scenario_telemetry")
        conn.commit()

        LOGGER.info("Cleared %d telemetry records (user-requested deletion)", total_before)
        return total_before


def get_telemetry_manager(db: ConnectorDatabase | None = None) -> TelemetryManager:
    """Get telemetry manager instance.

    Args:
        db: Optional ConnectorDatabase instance

    Returns:
        TelemetryManager instance
    """
    return TelemetryManager(db)
