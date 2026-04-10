"""Coordinator for exporting tables from the analysis detail dialog."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton, QTableWidget, QWidget

from ....styles.button_styles import ACTION_BUTTON_STYLE
from .export_utils import TableExportData, gather_filter_context
from .xlsx_exporter import XLSXExporter

LOGGER = logging.getLogger(__name__)

__all__ = ["ExportManager"]


class ExportManager:
    """Manage export actions for the analysis detail dialog."""

    def __init__(self, parent: QWidget):
        self._parent = parent
        self._data_providers: dict[str, Callable[[], TableExportData]] = {}
        self._filter_providers: dict[str, Callable[[], dict[str, str]]] = {}

    # Registration -----------------------------------------------------------------
    def register_table(
        self,
        name: str,
        table: QTableWidget,
        data_provider: Callable[[], TableExportData],
    ) -> None:
        """Associate a table widget and data provider with an export name."""
        _ = table  # Table reference retained for type clarity; exports use provided data instead.
        self._data_providers[name] = data_provider

    def set_filter_provider(self, name: str, provider: Callable[[], dict[str, str]]) -> None:
        self._filter_providers[name] = provider

    # UI Helpers -------------------------------------------------------------------
    def create_export_button(self, table_name: str) -> QPushButton:
        """Create a styled export button wired to this manager."""
        button = QPushButton("Export All Rows…")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(ACTION_BUTTON_STYLE())
        button.clicked.connect(lambda: self.export_table(table_name))
        return button

    # Export Operations ------------------------------------------------------------
    def export_table(self, table_name: str) -> None:
        """Export the full dataset for a single table to an XLSX workbook."""
        data_provider = self._data_providers.get(table_name)
        if data_provider is None:
            LOGGER.warning("No data provider registered for export name %s", table_name)
            QMessageBox.warning(
                self._parent,
                "Export Unavailable",
                f"No export data provider is configured for the '{table_name}' table.",
            )
            return

        try:
            export_data = data_provider()
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Failed to build export data for %s: %s", table_name, exc)
            QMessageBox.critical(
                self._parent,
                "Export Failed",
                f"Failed to prepare export data for '{table_name}':\n{exc}",
            )
            return

        if not export_data.headers:
            QMessageBox.information(
                self._parent,
                "Nothing to Export",
                f"The '{table_name}' table has no headers configured for export.",
            )
            return

        filter_context = gather_filter_context(table_name, self._filter_providers)
        if filter_context and not export_data.filter_context:
            export_data.filter_context = filter_context

        if not export_data.rows:
            QMessageBox.information(
                self._parent,
                "Nothing to Export",
                f"No rows found to export for '{table_name}'.",
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self._parent,
            f"Export {table_name.title()}",
            f"migration_analysis_{table_name}.xlsx",
            "Excel Workbook (*.xlsx)",
        )
        if not file_path:
            return

        path = Path(file_path)
        if path.suffix.lower() != ".xlsx":
            path = path.with_suffix(".xlsx")

        exporter = XLSXExporter()

        try:
            exporter.write_workbook(path, [export_data])
            QMessageBox.information(
                self._parent,
                "Export Successful",
                f"Successfully exported {table_name} to:\n{path}",
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Failed to export %s: %s", table_name, exc)
            QMessageBox.critical(
                self._parent,
                "Export Failed",
                f"Failed to export {table_name}:\n{exc}",
            )

    def collect_tables(self, table_names: Iterable[str]) -> list[TableExportData]:
        """Return export payloads for the requested tables without writing to disk."""
        sheets: list[TableExportData] = []
        missing: list[str] = []

        for name in table_names:
            data_provider = self._data_providers.get(name)
            if data_provider is None:
                missing.append(name)
                continue

            try:
                export_data = data_provider()
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("Failed to build export data for %s: %s", name, exc)
                raise

            if not export_data.headers or not export_data.rows:
                LOGGER.info(
                    "Skipping %s in collect_tables due to missing data (headers=%s, rows=%s)",
                    name,
                    bool(export_data.headers),
                    bool(export_data.rows),
                )
                continue

            filter_context = gather_filter_context(name, self._filter_providers)
            if filter_context and not export_data.filter_context:
                export_data.filter_context = filter_context

            sheets.append(export_data)

        if missing:
            LOGGER.warning("No data provider configured for tables: %s", ", ".join(missing))

        return sheets

    def export_all(self, table_names: Iterable[str]) -> None:
        """Export multiple tables into a single multi-sheet XLSX workbook."""
        sheets: list[TableExportData] = []
        missing: list[str] = []

        for name in table_names:
            data_provider = self._data_providers.get(name)
            if data_provider is None:
                missing.append(name)
                continue

            try:
                export_data = data_provider()
            except Exception as exc:  # noqa: BLE001
                LOGGER.error("Failed to build export data for %s: %s", name, exc)
                QMessageBox.critical(
                    self._parent,
                    "Export Failed",
                    f"Failed to prepare export data for '{name}':\n{exc}",
                )
                return

            if not export_data.headers or not export_data.rows:
                LOGGER.info(
                    "Skipping %s in multi-sheet export due to missing data (headers=%s, rows=%s)",
                    name,
                    bool(export_data.headers),
                    bool(export_data.rows),
                )
                continue

            filter_context = gather_filter_context(name, self._filter_providers)
            if filter_context and not export_data.filter_context:
                export_data.filter_context = filter_context

            sheets.append(export_data)

        if missing:
            LOGGER.warning("No data provider configured for tables: %s", ", ".join(missing))

        if not sheets:
            QMessageBox.information(
                self._parent,
                "Nothing to Export",
                "No tables contained data to export.",
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self._parent,
            "Export All Data",
            "migration_analysis_all_tables.xlsx",
            "Excel Workbook (*.xlsx)",
        )
        if not file_path:
            return

        path = Path(file_path)
        if path.suffix.lower() != ".xlsx":
            path = path.with_suffix(".xlsx")

        exporter = XLSXExporter()

        try:
            exporter.write_workbook(path, sheets)
            QMessageBox.information(
                self._parent,
                "Export Successful",
                f"Successfully exported all data to:\n{path}",
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Failed to export all data: %s", exc)
            QMessageBox.critical(
                self._parent,
                "Export Failed",
                f"Failed to export data:\n{exc}",
            )
