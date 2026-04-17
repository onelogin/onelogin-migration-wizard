"""Bulk user upload CSV generation."""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

_TEMPLATE_PACKAGE = "onelogin_migration_core.resources"
_TEMPLATE_FILENAME = "user-upload-template.csv"


class BulkUserCSVGenerator:
    """Generates CSV files for OneLogin bulk user uploads."""

    @staticmethod
    def load_template_headers() -> list[str]:
        """Load CSV headers from the bundled bulk user upload template.

        Returns:
            List of header column names

        Raises:
            FileNotFoundError: If template file doesn't exist
            ValueError: If template is empty
        """

        try:
            template_resource = resources.files(_TEMPLATE_PACKAGE).joinpath(_TEMPLATE_FILENAME)
            with template_resource.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.reader(handle)
                try:
                    headers = next(reader)
                except StopIteration as exc:  # pragma: no cover - defensive
                    raise ValueError(
                        f"Template {_TEMPLATE_FILENAME} is empty in package {_TEMPLATE_PACKAGE}"
                    ) from exc
        except (FileNotFoundError, ModuleNotFoundError):
            # Developer fallback: support running from a mono-repo checkout where
            # the legacy templates directory still exists.
            repo_root = Path(__file__).resolve()
            try:
                legacy_template = repo_root.parents[5] / "templates" / _TEMPLATE_FILENAME
            except IndexError:  # pragma: no cover - defensive
                legacy_template = Path()
            if not legacy_template.exists():
                raise FileNotFoundError(
                    f"Bulk user upload template not found. "
                    f"Searched package resources and {legacy_template}"
                )
            with legacy_template.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.reader(handle)
                try:
                    headers = next(reader)
                except StopIteration as exc:  # pragma: no cover - defensive
                    raise ValueError(f"Template {legacy_template} is empty") from exc
        return headers

    @staticmethod
    def write_csv(
        rows: list[tuple[dict[str, Any], dict[str, Any]]],
        template_headers: list[str],
        custom_attributes: list[str],
        output_dir: Path,
    ) -> Path:
        """Write bulk user upload CSV file.

        Args:
            rows: List of (base_payload, custom_attrs) tuples
            template_headers: Headers from the template file
            custom_attributes: Sorted list of custom attribute names
            output_dir: Directory to write the CSV file

        Returns:
            Path to the generated CSV file
        """
        base_headers = [h for h in template_headers if not h.startswith("custom_attribute")]
        headers = base_headers + custom_attributes
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = output_dir / f"bulk_user_upload_{timestamp}.csv"

        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for payload, attrs in rows:
                record: dict[str, Any] = {}
                for key in headers:
                    if key in custom_attributes:
                        value = attrs.get(key)
                    else:
                        value = payload.get(key)
                    record[key] = BulkUserCSVGenerator._csv_value(value)
                writer.writerow(record)

        return output_path

    @staticmethod
    def _csv_value(value: Any) -> str:
        """Convert a value to CSV-safe string format."""
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @staticmethod
    def ensure_custom_attributes(
        onelogin_client: Any,
        attributes: list[str],
        dry_run: bool,
    ) -> None:
        """Ensure custom attributes exist for bulk upload.

        Args:
            onelogin_client: OneLogin API client instance
            attributes: List of custom attribute names to create
            dry_run: Whether this is a dry run
        """
        if not attributes:
            return
        helper = getattr(onelogin_client, "ensure_custom_attribute_definitions", None)
        if not callable(helper):
            LOGGER.debug(
                "OneLogin client does not support custom attribute provisioning; skipping CSV attribute setup"
            )
            return
        payload = dict.fromkeys(attributes, "")
        if dry_run:
            LOGGER.info(
                "[DRY-RUN] Would ensure the following custom attributes exist in OneLogin: %s",
                ", ".join(attributes),
            )
            return
        try:
            helper(payload)
        except Exception:  # pragma: no cover - best effort logging
            LOGGER.exception(
                "Failed to ensure custom attribute definitions for bulk upload: %s",
                ", ".join(attributes),
            )


__all__ = ["BulkUserCSVGenerator"]
