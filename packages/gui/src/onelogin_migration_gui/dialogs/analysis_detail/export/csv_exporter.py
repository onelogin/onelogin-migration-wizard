"""CSV export implementation for analysis detail tables."""

from __future__ import annotations

import csv
from pathlib import Path

from .export_utils import build_metadata_rows

__all__ = ["CSVExporter"]


class CSVExporter:
    """Write table data to CSV including metadata rows."""

    def write(
        self,
        path: Path,
        headers: list[str],
        rows: list[list[str]],
        filter_context: dict[str, str],
        selected_only: bool,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            for meta_row in build_metadata_rows(filter_context, selected_only, len(headers)):
                writer.writerow(meta_row)
            writer.writerow(headers)
            writer.writerows(rows)
