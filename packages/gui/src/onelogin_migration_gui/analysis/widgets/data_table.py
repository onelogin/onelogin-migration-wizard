"""DataTable widget for displaying tabular data with theme integration."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem

from ...theme_manager import get_theme_manager
from ..utils import format_int


class DataTable(QTableWidget):
    """Themed table widget with sortable columns and right-aligned numeric values."""

    def __init__(
        self,
        headers: list[str],
        numeric_columns: list[int] | None = None,
        parent=None,
    ):
        """
        Initialize the data table.

        Args:
            headers: List of column header labels
            numeric_columns: List of column indices that contain numeric data (will be right-aligned)
            parent: Parent widget
        """
        super().__init__(parent)
        self._theme = get_theme_manager()
        self._numeric_columns = numeric_columns or []

        # Configure table
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        # Configure headers
        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        for i in range(len(headers)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)

        self.verticalHeader().setVisible(False)

        # Apply theme styling
        self._apply_table_style()

        # Connect to theme changes
        self._theme.theme_changed.connect(self._apply_table_style)

    def _apply_table_style(self) -> None:
        """Apply table styling using theme colors."""
        surface = self._theme.get_color("surface")
        surface_elevated = self._theme.get_color("surface_elevated")
        text_primary = self._theme.get_color("text_primary")
        text_secondary = self._theme.get_color("text_secondary")
        border = self._theme.get_color("border")
        primary = self._theme.get_color("primary")
        primary_light = self._theme.get_color("primary_light")
        neutral_100 = self._theme.get_color("neutral_100")
        spacing = self._theme.get_spacing("sm")

        self.setStyleSheet(
            f"""
            QTableWidget {{
                background-color: {surface};
                color: {text_primary};
                gridline-color: {border};
                border: 1px solid {border};
                border-radius: 8px;
                selection-background-color: {primary_light};
                selection-color: {text_primary};
            }}
            QTableWidget::item {{
                padding: {spacing}px;
                border: none;
            }}
            QTableWidget::item:selected {{
                background-color: {primary_light};
            }}
            QHeaderView::section {{
                background-color: {surface_elevated};
                color: {text_primary};
                padding: {spacing}px;
                border: none;
                border-bottom: 2px solid {border};
                font-weight: 600;
                text-align: left;
            }}
            QTableWidget::item:alternate {{
                background-color: {neutral_100};
            }}
        """
        )

    def add_row(self, row_data: list[Any]) -> None:
        """Add a row to the table with proper formatting."""
        row_position = self.rowCount()
        self.insertRow(row_position)

        for col_index, value in enumerate(row_data):
            # Format numeric values
            if col_index in self._numeric_columns and isinstance(value, int):
                display_value = format_int(value)
            else:
                display_value = str(value)

            item = QTableWidgetItem(display_value)

            # Right-align numeric columns
            if col_index in self._numeric_columns:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            else:
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            self.setItem(row_position, col_index, item)

    def set_data(self, rows: list[list[Any]]) -> None:
        """Clear the table and populate it with new data."""
        self.setRowCount(0)
        for row_data in rows:
            self.add_row(row_data)

    def clear_data(self) -> None:
        """Clear all rows from the table."""
        self.setRowCount(0)
