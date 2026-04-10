"""Export utilities for source-provider data."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


class SourceExporter:
    """Handles exporting data from the configured source provider."""

    @staticmethod
    def export_from_source(source_client: Any, categories: dict[str, bool]) -> dict[str, Any]:
        """Collect users, groups, and applications from the source provider.

        Args:
            source_client: Source API client instance
            categories: Dictionary of category toggles (users, groups, applications, policies)

        Returns:
            Dictionary containing exported data by category
        """
        provider_name = getattr(
            getattr(source_client, "settings", None), "provider_display_name", "source"
        )
        LOGGER.info("Starting export from %s", provider_name)
        export = source_client.export_all(categories)
        LOGGER.info(
            "Exported %s users, %s groups, %s applications",
            len(export.get("users", [])),
            len(export.get("groups", [])),
            len(export.get("applications", [])),
        )
        return export

    # Backward-compatible alias
    export_from_okta = export_from_source

    @staticmethod
    def save_export(
        export: dict[str, Any],
        destination: Path,
        source_label: str,
    ) -> Path:
        """Persist Okta export data to disk.

        Args:
            export: Dictionary containing exported data
            destination: Base directory or file path for export
            source_label: Label for the source (e.g., "okta-dev")

        Returns:
            Path to the main export file
        """
        if destination.suffix:
            export_path = destination
        else:
            destination.mkdir(parents=True, exist_ok=True)
            export_path = destination / "source_export.json"

        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(json.dumps(export, indent=2, sort_keys=True))
        LOGGER.info("Saved source export to %s", export_path)

        # Persist per-category snapshots for easier auditing
        export_directory = export_path.parent
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for key, value in export.items():
            filename = f"{source_label}_{key}_{timestamp}.json"
            bucket_path = export_directory / filename
            try:
                bucket_path.write_text(json.dumps(value, indent=2, sort_keys=True))
                LOGGER.info("Saved %s export to %s", key, bucket_path)
            except TypeError:
                # Fallback to raw serialization if non-JSON data slips through
                bucket_path.write_text(json.dumps(value, default=str, indent=2, sort_keys=True))
                LOGGER.info("Saved %s export to %s (with fallback serialization)", key, bucket_path)
        return export_path

    @staticmethod
    def load_export(path: Path) -> dict[str, Any]:
        """Load an export from disk.

        Args:
            path: Path to the export file

        Returns:
            Dictionary containing exported data

        Raises:
            FileNotFoundError: If export file doesn't exist
        """
        export_path = Path(path)
        if not export_path.exists():
            raise FileNotFoundError(f"Export file not found: {export_path}")
        return json.loads(export_path.read_text())


OktaExporter = SourceExporter


__all__ = ["SourceExporter", "OktaExporter"]
