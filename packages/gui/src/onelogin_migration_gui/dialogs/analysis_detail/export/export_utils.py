"""Shared helper functions for exporting table data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

__all__ = ["TableExportData", "gather_filter_context", "build_metadata_rows"]


@dataclass
class TableExportData:
    """Structured payload describing a sheet to export."""

    sheet_name: str
    headers: list[str]
    rows: list[list[str]]
    export_mode: str = "Full dataset"
    filter_context: dict[str, str] = field(default_factory=dict)
    include_metadata: bool = True


def gather_filter_context(
    table_name: str,
    providers: dict[str, Callable[[], dict[str, str]]],
) -> dict[str, str]:
    """Return filter context for a table based on registered providers."""
    provider = providers.get(table_name)
    if not provider:
        return {}
    try:
        context = provider()
    except Exception:
        return {}
    return context or {}


def build_metadata_rows(
    context: dict[str, str],
    export_mode: str,
    column_count: int,
    include_metadata: bool = True,
) -> list[list[str]]:
    """Build metadata rows (filters, export mode, timestamp) to prepend to sheets."""
    if not include_metadata:
        return []

    rows: list[list[str]] = []

    effective_columns = max(column_count, 1)

    def pad(row: list[str]) -> list[str]:
        if effective_columns <= len(row):
            return row[:effective_columns]
        return row + [""] * (effective_columns - len(row))

    if context:
        rows.append(pad(["Filter Context", "Value"]))
        for key, value in context.items():
            display = value if value else "(none)"
            rows.append(pad([key, display]))
        rows.append(pad(["", ""]))

    rows.append(pad(["Export Mode", export_mode]))
    rows.append(pad(["Generated", datetime.now().isoformat()]))
    rows.append(pad(["", ""]))
    return rows
