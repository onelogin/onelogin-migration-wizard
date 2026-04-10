"""Automatic connector catalog refresh service.

Keeps OneLogin connector catalog up-to-date by refreshing from the API
periodically (every 24 hours by default). Gracefully handles offline/error
scenarios by continuing with cached data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from threading import Thread
from typing import TYPE_CHECKING

from .connector_db import ConnectorDatabase, get_default_connector_db

if TYPE_CHECKING:
    from .clients import OneLoginClient

LOGGER = logging.getLogger(__name__)


class ConnectorRefreshService:
    """Manages automatic connector catalog updates."""

    REFRESH_INTERVAL_HOURS = 24

    def __init__(self, db: ConnectorDatabase | None = None):
        """Initialize refresh service.

        Args:
            db: ConnectorDatabase instance (defaults to default instance)
        """
        self.db = db or get_default_connector_db()

    def should_refresh(self, refresh_type: str = "onelogin") -> bool:
        """Check if connectors need refresh (>24hrs old or never refreshed).

        Args:
            refresh_type: Type of refresh to check ('onelogin', 'okta', 'mappings')

        Returns:
            True if refresh is needed, False if catalog is fresh
        """
        conn = self.db.connect()
        cursor = conn.execute(
            """
            SELECT MAX(completed_at) as last_update
            FROM connector_refresh_log
            WHERE refresh_type = ? AND status = 'success'
        """,
            (refresh_type,),
        )
        row = cursor.fetchone()

        if not row or not row["last_update"]:
            LOGGER.debug("Connector catalog never refreshed, refresh needed")
            return True  # Never refreshed

        try:
            last_update = datetime.fromisoformat(row["last_update"])
            age = datetime.now() - last_update
            needs_refresh = age > timedelta(hours=self.REFRESH_INTERVAL_HOURS)

            if needs_refresh:
                LOGGER.info(
                    "Connector catalog is %.1f hours old, refresh needed",
                    age.total_seconds() / 3600,
                )
            else:
                LOGGER.debug(
                    "Connector catalog is fresh (%.1f hours old)", age.total_seconds() / 3600
                )

            return needs_refresh
        except (ValueError, TypeError) as e:
            LOGGER.warning("Could not parse last refresh date: %s", e)
            return True  # Better to refresh if we can't determine age

    def refresh_onelogin_connectors(
        self, onelogin_client: OneLoginClient, background: bool = True
    ) -> bool:
        """Refresh OneLogin connector catalog from API.

        Args:
            onelogin_client: OneLoginClient instance for API access
            background: If True, run refresh in background thread (non-blocking)

        Returns:
            True if refresh initiated successfully (background) or completed (foreground)
        """
        if background:
            # Run in background thread, don't block application startup
            thread = Thread(
                target=self._do_refresh,
                args=(onelogin_client,),
                daemon=True,
                name="connector-refresh",
            )
            thread.start()
            LOGGER.info("Connector refresh started in background")
            return True
        else:
            # Run synchronously
            return self._do_refresh(onelogin_client)

    def _do_refresh(self, onelogin_client: OneLoginClient) -> bool:
        """Internal refresh implementation (called by refresh_onelogin_connectors).

        Args:
            onelogin_client: OneLoginClient instance

        Returns:
            True if refresh succeeded, False if failed (non-fatal)
        """
        conn = self.db.connect()
        refresh_id = None

        try:
            # Log refresh start
            cursor = conn.execute(
                """
                INSERT INTO connector_refresh_log (refresh_type, status)
                VALUES ('onelogin', 'running')
            """
            )
            refresh_id = cursor.lastrowid
            conn.commit()

            # Fetch from API
            LOGGER.info("Refreshing OneLogin connector catalog from API...")
            connectors = onelogin_client.list_connectors()

            if not connectors:
                LOGGER.warning("No connectors returned from API, keeping cached data")
                if refresh_id:
                    conn.execute(
                        """
                        UPDATE connector_refresh_log
                        SET status = 'skipped',
                            completed_at = CURRENT_TIMESTAMP,
                            error_message = 'No connectors returned from API'
                        WHERE id = ?
                    """,
                        (refresh_id,),
                    )
                    conn.commit()
                return False

            # Update database
            count = self.db.insert_onelogin_connectors_bulk(connectors)

            # Log success
            if refresh_id:
                conn.execute(
                    """
                    UPDATE connector_refresh_log
                    SET status = 'success',
                        completed_at = CURRENT_TIMESTAMP,
                        records_updated = ?
                    WHERE id = ?
                """,
                    (count, refresh_id),
                )
                conn.commit()

            LOGGER.info("Connector refresh complete: %d connectors updated", count)
            return True

        except Exception as e:
            # Log failure, but don't crash - use cached data
            LOGGER.warning("Connector refresh failed (using cached data): %s", e)

            if refresh_id:
                try:
                    conn.execute(
                        """
                        UPDATE connector_refresh_log
                        SET status = 'failed',
                            completed_at = CURRENT_TIMESTAMP,
                            error_message = ?
                        WHERE id = ?
                    """,
                        (str(e)[:500], refresh_id),
                    )  # Truncate error message
                    conn.commit()
                except Exception as log_error:
                    LOGGER.warning("Failed to log refresh error: %s", log_error)

            return False

    def refresh_if_stale(self, onelogin_client: OneLoginClient) -> None:
        """Check and refresh if needed (non-blocking).

        Called at application startup. If connectors are stale (>24hrs),
        triggers background refresh. Never blocks the application.

        Args:
            onelogin_client: OneLoginClient instance
        """
        if self.should_refresh("onelogin"):
            LOGGER.info("Connector catalog is stale, refreshing in background...")
            self.refresh_onelogin_connectors(onelogin_client, background=True)
        else:
            LOGGER.debug("Connector catalog is fresh, skipping refresh")

    def get_last_refresh_info(self, refresh_type: str = "onelogin") -> dict | None:
        """Get information about the last refresh operation.

        Args:
            refresh_type: Type of refresh to query

        Returns:
            Dict with refresh info or None if never refreshed
        """
        conn = self.db.connect()
        cursor = conn.execute(
            """
            SELECT *
            FROM connector_refresh_log
            WHERE refresh_type = ?
            ORDER BY completed_at DESC
            LIMIT 1
        """,
            (refresh_type,),
        )
        row = cursor.fetchone()

        return dict(row) if row else None

    def force_refresh(self, onelogin_client: OneLoginClient, background: bool = False) -> bool:
        """Force immediate refresh regardless of staleness.

        Useful for manual refresh via CLI or when user explicitly requests update.

        Args:
            onelogin_client: OneLoginClient instance
            background: Whether to run in background

        Returns:
            True if refresh initiated/completed successfully
        """
        LOGGER.info("Force refreshing connector catalog...")
        return self.refresh_onelogin_connectors(onelogin_client, background=background)


def get_connector_refresh_service(
    db: ConnectorDatabase | None = None,
) -> ConnectorRefreshService:
    """Get connector refresh service instance.

    Args:
        db: Optional ConnectorDatabase instance

    Returns:
        ConnectorRefreshService instance
    """
    return ConnectorRefreshService(db)
