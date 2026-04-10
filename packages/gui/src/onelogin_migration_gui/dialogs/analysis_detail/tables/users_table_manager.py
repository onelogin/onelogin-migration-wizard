"""Table manager for the Users tab."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from .base_table_manager import BaseTableManager

LOGGER = logging.getLogger(__name__)


class UsersTableManager(BaseTableManager):
    """Handle population, filtering, and pagination for the users table."""

    def __init__(
        self,
        dialog: AnalysisDetailDialog,
        table: QTableWidget,
        count_label: QLabel,
        page_label: QLabel,
        prev_button: QPushButton,
        next_button: QPushButton,
        search_field: QLineEdit,
        status_filter: QComboBox,
    ) -> None:
        super().__init__(dialog, table, count_label, page_label, prev_button, next_button)
        self._search_field = search_field
        self._status_filter = status_filter

    # --------------------------------------------------------------------- populate
    def populate(self) -> None:
        self._ensure_selection_column()
        self._reset_selection_state()
        total_users = len(self.dialog.all_users)
        # Use actual user IDs as keys for selection tracking
        all_user_ids = [str(user.get("id")) for user in self.dialog.all_users if user.get("id")]
        self._set_all_row_keys(all_user_ids)
        start_idx = self.dialog.users_current_page * self.dialog.page_size
        end_idx = min(start_idx + self.dialog.page_size, total_users)
        users_list = self.dialog.all_users[start_idx:end_idx]

        LOGGER.info(
            "Populating users table with %s users (page %s)",
            len(users_list),
            self.dialog.users_current_page + 1,
        )

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        users_data = self.dialog.analysis_data.get("users", {})

        for user in users_list:
            profile = user.get("profile", {})
            row = self.table.rowCount()
            self.table.insertRow(row)

            # Use user ID as the selection key
            user_id = str(user.get("id", ""))
            self._create_selection_cell(row, key=user_id)

            first_name = profile.get("firstName", "")
            last_name = profile.get("lastName", "")
            name = f"{first_name} {last_name}".strip() or "N/A"
            name_item = QTableWidgetItem(str(name))
            name_item.setToolTip(str(name))
            self.table.setItem(row, 1, name_item)

            email = profile.get("email") or profile.get("login") or "N/A"
            email_item = QTableWidgetItem(str(email))
            email_item.setToolTip(str(email))
            self.table.setItem(row, 2, email_item)

            status = user.get("status", "UNKNOWN")
            status_item = QTableWidgetItem(str(status))
            if status == "ACTIVE":
                status_item.setForeground(Qt.GlobalColor.darkGreen)
            elif status == "SUSPENDED":
                status_item.setForeground(Qt.GlobalColor.darkYellow)
            else:
                status_item.setForeground(Qt.GlobalColor.darkRed)
            self.table.setItem(row, 3, status_item)

            custom_attrs = users_data.get("custom_attributes", [])
            user_custom_attrs = [attr for attr in custom_attrs if profile.get(attr)]
            attr_count = len(user_custom_attrs)
            attr_text = (
                f"{attr_count} attr{'s' if attr_count != 1 else ''}" if attr_count > 0 else "-"
            )
            attr_item = QTableWidgetItem(attr_text)
            attr_item.setToolTip(attr_text if attr_text != "-" else "No custom attributes detected")
            self.table.setItem(row, 4, attr_item)

            groups_placeholder = QTableWidgetItem("See Groups tab")
            groups_placeholder.setToolTip("Group membership details available in Groups tab")
            self.table.setItem(row, 5, groups_placeholder)

        self.table.setSortingEnabled(True)
        self._update_select_all_checkbox()
        self.update_count()
        self.update_pagination()

    # ---------------------------------------------------------------------- filter
    def apply_filters(self) -> None:
        search_text = self._search_field.text().lower()
        status_filter = self._status_filter.currentText()

        for row in range(self.table.rowCount()):
            should_show = True

            if search_text:
                name = self.table.item(row, 1).text().lower()
                email = self.table.item(row, 2).text().lower()
                if search_text not in name and search_text not in email:
                    should_show = False

            if should_show and status_filter != "All":
                status = self.table.item(row, 3).text()
                if status != status_filter.upper():
                    should_show = False

            self.table.setRowHidden(row, not should_show)

        self.update_count()

    # ------------------------------------------------------------------- utilities
    def update_count(self) -> None:
        visible = self._visible_rows()
        total_on_page = self.table.rowCount()
        total_all = len(self.dialog.all_users)
        self.count_label.setText(
            f"Showing {visible:,} of {total_on_page:,} users on this page ({total_all:,} total)"
        )

    def update_pagination(self) -> None:
        total_users = len(self.dialog.all_users)
        total_pages = (
            (total_users + self.dialog.page_size - 1) // self.dialog.page_size
            if total_users > 0
            else 1
        )
        current_page_num = self.dialog.users_current_page + 1

        self.page_label.setText(f"Page {current_page_num:,} of {total_pages:,}")
        self.prev_button.setEnabled(self.dialog.users_current_page > 0)
        self.next_button.setEnabled(self.dialog.users_current_page < total_pages - 1)
