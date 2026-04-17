"""Custom attributes tab."""

from __future__ import annotations

import csv
import io

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...theme_manager import get_theme_manager
from ..model import AnalysisModel, CustomAttributeRow
from ..utils import set_sticky
from ..widgets import DataTable, SectionCard, StatCard
from .base import AnalysisTab


class CustomAttributesTab(AnalysisTab):
    """Custom attribute mapping preview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = get_theme_manager()

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        root_layout.addWidget(self.scroll, 1)

        self.content = QWidget()
        padding = self._theme.get_spacing("md")
        main_layout = QVBoxLayout(self.content)
        main_layout.setContentsMargins(padding, padding, padding, padding)
        main_layout.setSpacing(self._theme.get_spacing("md"))

        # Summary section
        self.summary_section = SectionCard("Custom Attribute Summary")
        self.summary_section.set_grid_columns(3)
        main_layout.addWidget(self.summary_section)

        # Table header with copy button
        table_header = QWidget()
        table_header_layout = QGridLayout(table_header)
        table_header_layout.setContentsMargins(0, 0, 0, 0)
        table_header_layout.setSpacing(self._theme.get_spacing("md"))

        table_label = QLabel("Attribute Mapping Preview")
        font_size = self._theme.get_typography("h3")["size"]
        text_color = self._theme.get_color("text_primary")
        table_label.setStyleSheet(
            f"font-size: {font_size}px; color: {text_color}; font-weight: 600;"
        )
        self._theme.theme_changed.connect(lambda: self._update_table_label_style(table_label))
        table_header_layout.addWidget(table_label, 0, 0)

        self.copy_button = QPushButton("Copy mapping CSV")
        button_style = self._theme.get_button_style("secondary")
        self.copy_button.setStyleSheet(button_style)
        self._theme.theme_changed.connect(self._update_button_style)
        self.copy_button.clicked.connect(self.copy_to_clipboard)
        table_header_layout.addWidget(self.copy_button, 0, 1, Qt.AlignmentFlag.AlignRight)

        table_header_layout.setColumnStretch(0, 1)
        main_layout.addWidget(table_header)

        # Mapping table with DataTable widget
        self.table = DataTable(
            headers=["Source Attribute", "Target Field", "Status"],
            numeric_columns=[],  # No numeric columns
        )
        self.table.setMinimumHeight(400)
        main_layout.addWidget(self.table)

        main_layout.addStretch()

        set_sticky(self.scroll, self.content)

        self._rows: list[CustomAttributeRow] = []

    def _update_table_label_style(self, label: QLabel) -> None:
        """Update table label styling on theme change."""
        font_size = self._theme.get_typography("h3")["size"]
        text_color = self._theme.get_color("text_primary")
        label.setStyleSheet(f"font-size: {font_size}px; color: {text_color}; font-weight: 600;")

    def _update_button_style(self) -> None:
        """Update button styling on theme change."""
        button_style = self._theme.get_button_style("secondary")
        self.copy_button.setStyleSheet(button_style)

    def bind(self, model: AnalysisModel) -> None:
        """Populate custom attributes summary and mapping table."""
        # Clear and populate summary
        self.summary_section.clear_cards()
        summary_metrics = [
            ("Total", model.custom_attribute_summary.get("total", 0)),
            ("Used", model.custom_attribute_summary.get("used", 0)),
            ("Unused", model.custom_attribute_summary.get("unused", 0)),
        ]
        for label, value in summary_metrics:
            self.summary_section.add_stat_card(StatCard(label, value, auto_pluralize=False))

        # Populate mapping table
        self._rows = model.custom_attributes
        self.table.clear_data()
        for row in self._rows:
            self.table.add_row([row.source, row.target, row.status])

    def copy_to_clipboard(self) -> None:
        """Copy attribute mapping to clipboard as CSV."""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["source_attribute", "target_field", "status"])
        for row in self._rows:
            writer.writerow([row.source, row.target, row.status])
        QGuiApplication.clipboard().setText(buffer.getvalue())
