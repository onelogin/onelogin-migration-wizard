"""Table manager for the Custom Attributes tab."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem

from ..utils.type_inference import detect_attribute_warning, infer_attribute_type
from .base_table_manager import BaseTableManager

LOGGER = logging.getLogger(__name__)


class AttributesTableManager(BaseTableManager):
    """Handle population, filtering, and pagination for custom attributes."""

    def __init__(
        self,
        dialog: AnalysisDetailDialog,
        table: QTableWidget,
        count_label: QLabel,
        page_label: QLabel,
        prev_button: QPushButton,
        next_button: QPushButton,
        search_field: QLineEdit,
    ) -> None:
        super().__init__(dialog, table, count_label, page_label, prev_button, next_button)
        self._search_field = search_field

    def populate(self) -> None:
        self._ensure_selection_column()
        self._reset_selection_state()
        total_attrs = len(self.dialog.all_custom_attrs)
        # Use attribute names as keys for selection tracking
        self._set_all_row_keys(self.dialog.all_custom_attrs)
        start_idx = self.dialog.attrs_current_page * self.dialog.page_size
        end_idx = min(start_idx + self.dialog.page_size, total_attrs)
        custom_attrs = self.dialog.all_custom_attrs[start_idx:end_idx]

        raw_export = self.dialog.analysis_data.get("raw_export", {})
        users_list = raw_export.get("users", [])

        LOGGER.info(
            "Populating attrs table with %s attrs (page %s)",
            len(custom_attrs),
            self.dialog.attrs_current_page + 1,
        )

        self.table.setRowCount(0)
        self.table.setSortingEnabled(False)

        for attr in custom_attrs:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # Use attribute name as the selection key
            self._create_selection_cell(row, key=attr)

            attr_item = QTableWidgetItem(attr)
            attr_item.setToolTip(attr)
            self.table.setItem(row, 1, attr_item)

            usage_count = 0
            observed_values: list[str] = []
            sample_values: list[str] = []
            for user in users_list:
                profile = user.get("profile", {})
                value = profile.get(attr)
                if value is None or value == "":
                    continue
                usage_count += 1
                observed_values.append(value)
                if len(sample_values) < 3:
                    sample_values.append(str(value)[:50])

            data_type = infer_attribute_type(observed_values)
            data_type_item = QTableWidgetItem(data_type)
            data_type_item.setData(Qt.ItemDataRole.UserRole, usage_count)
            self.table.setItem(row, 2, data_type_item)

            usage_pct = (
                (usage_count / self.dialog.total_user_count * 100)
                if self.dialog.total_user_count
                else 0.0
            )
            usage_text = (
                f"{usage_count:,} users ({usage_pct:.1f}%)" if usage_count else "No usage detected"
            )
            usage_item = QTableWidgetItem(usage_text)
            usage_item.setData(Qt.ItemDataRole.UserRole, usage_count)
            usage_item.setToolTip(usage_text)
            self.table.setItem(row, 3, usage_item)

            samples = ", ".join(sample_values) if sample_values else "(No values)"
            samples_item = QTableWidgetItem(samples)
            samples_item.setToolTip(
                samples if samples != "(No values)" else "No sample values captured."
            )
            self.table.setItem(row, 4, samples_item)

            required = (
                usage_count == self.dialog.total_user_count and self.dialog.total_user_count > 0
            )
            required_item = QTableWidgetItem("Yes" if required else "No")
            required_item.setData(Qt.ItemDataRole.UserRole, int(required))
            required_item.setForeground(QColor("#c62828" if required else "#455a64"))
            self.table.setItem(row, 5, required_item)

            warning = detect_attribute_warning(attr, observed_values, data_type)
            if warning:
                status_text = f"⚠ Review mapping – {warning}"
                status_color = "#f57c00"
            else:
                status_text = "Will be created automatically"
                status_color = "#1a237e"
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor(status_color))
            status_item.setToolTip(status_text)
            self.table.setItem(row, 6, status_item)

        self.table.setSortingEnabled(True)
        self._update_select_all_checkbox()
        self.update_count()
        self.update_pagination()

    def apply_filters(self) -> None:
        search_text = self._search_field.text().lower()

        for row in range(self.table.rowCount()):
            should_show = True
            if search_text:
                name = self.table.item(row, 1).text().lower()
                if search_text not in name:
                    should_show = False
            self.table.setRowHidden(row, not should_show)

        self.update_count()

    def update_count(self) -> None:
        visible = self._visible_rows()
        total_on_page = self.table.rowCount()
        total_all = len(self.dialog.all_custom_attrs)
        self.count_label.setText(
            f"Showing {visible:,} of {total_on_page:,} custom attributes on this page ({total_all:,} total)"
        )

    def update_pagination(self) -> None:
        total_attrs = len(self.dialog.all_custom_attrs)
        total_pages = (
            (total_attrs + self.dialog.page_size - 1) // self.dialog.page_size
            if total_attrs > 0
            else 1
        )
        current_page_num = self.dialog.attrs_current_page + 1

        self.page_label.setText(f"Page {current_page_num:,} of {total_pages:,}")
        self.prev_button.setEnabled(self.dialog.attrs_current_page > 0)
        self.next_button.setEnabled(self.dialog.attrs_current_page < total_pages - 1)
