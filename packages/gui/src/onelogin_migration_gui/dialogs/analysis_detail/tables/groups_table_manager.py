"""Table manager for the Groups tab."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..utils.formatters import summarize_user
from ..utils.status_helpers import describe_group_type, determine_group_priority
from .base_table_manager import BaseTableManager

LOGGER = logging.getLogger(__name__)


class GroupsTableManager(BaseTableManager):
    """Handle population, filtering, and member previews for the groups table."""

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

    # --------------------------------------------------------------------- populate
    def populate(self) -> None:
        self._ensure_selection_column()
        self._reset_selection_state()
        total_groups = len(self.dialog.all_groups)
        # Use actual group IDs as keys for selection tracking
        all_group_ids = [str(group.get("id")) for group in self.dialog.all_groups if group.get("id")]
        self._set_all_row_keys(all_group_ids)
        start_idx = self.dialog.groups_current_page * self.dialog.page_size
        end_idx = min(start_idx + self.dialog.page_size, total_groups)
        groups_list = self.dialog.all_groups[start_idx:end_idx]

        LOGGER.info(
            "Populating groups table with %s groups (page %s)",
            len(groups_list),
            self.dialog.groups_current_page + 1,
        )

        self.table.setRowCount(0)
        self.table.setSortingEnabled(False)

        for group in groups_list:
            profile = group.get("profile", {})
            group_id = group.get("id")
            row = self.table.rowCount()
            self.table.insertRow(row)

            # Use group ID as the selection key
            self._create_selection_cell(row, key=str(group_id) if group_id else "")

            name = profile.get("name", "(No Name)")
            name_item = QTableWidgetItem(name)
            name_item.setToolTip(profile.get("description") or name)
            name_item.setData(
                Qt.ItemDataRole.UserRole, str(group_id) if group_id is not None else ""
            )
            self.table.setItem(row, 1, name_item)

            member_count = self.dialog.group_member_counts.get(str(group_id), 0)
            count_item = QTableWidgetItem(f"{member_count:,}")
            count_item.setData(Qt.ItemDataRole.UserRole, member_count)
            count_item.setToolTip(f"{member_count:,} members")
            self.table.setItem(row, 2, count_item)

            coverage_pct = (
                (member_count / self.dialog.total_user_count) * 100
                if self.dialog.total_user_count
                else 0.0
            )
            coverage_text = (
                f"{coverage_pct:.1f}% of users" if self.dialog.total_user_count else "N/A"
            )
            coverage_item = QTableWidgetItem(coverage_text)
            coverage_item.setData(Qt.ItemDataRole.UserRole, coverage_pct)
            coverage_item.setToolTip(coverage_text)
            self.table.setItem(row, 3, coverage_item)

            priority_text, priority_color = determine_group_priority(member_count)
            priority_item = QTableWidgetItem(priority_text)
            priority_item.setData(Qt.ItemDataRole.UserRole, member_count)
            priority_item.setForeground(QColor(priority_color))
            priority_item.setToolTip(priority_text)
            self.table.setItem(row, 4, priority_item)

            group_type_text = describe_group_type(group)
            group_type_item = QTableWidgetItem(group_type_text)
            group_type_item.setToolTip(group_type_text)
            self.table.setItem(row, 5, group_type_item)

            target_role = profile.get("name") or group.get("label") or "OneLogin Role"
            role_item = QTableWidgetItem(target_role)
            role_item.setToolTip(f"Target OneLogin role name: {target_role}")
            self.table.setItem(row, 6, role_item)

            if member_count == 0:
                for column in range(self.table.columnCount()):
                    item = self.table.item(row, column)
                    if item:
                        item.setBackground(QColor("#fff7e6"))

        self.table.setSortingEnabled(True)
        self._update_select_all_checkbox()
        self.update_count()
        self.update_pagination()

    # ---------------------------------------------------------------------- filter
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

    # ------------------------------------------------------------------- utilities
    def update_count(self) -> None:
        visible = self._visible_rows()
        total_on_page = self.table.rowCount()
        total_all = len(self.dialog.all_groups)
        self.count_label.setText(
            f"Showing {visible:,} of {total_on_page:,} groups on this page ({total_all:,} total)"
        )

    def update_pagination(self) -> None:
        total_groups = len(self.dialog.all_groups)
        total_pages = (
            (total_groups + self.dialog.page_size - 1) // self.dialog.page_size
            if total_groups > 0
            else 1
        )
        current_page_num = self.dialog.groups_current_page + 1

        self.page_label.setText(f"Page {current_page_num:,} of {total_pages:,}")
        self.prev_button.setEnabled(self.dialog.groups_current_page > 0)
        self.next_button.setEnabled(self.dialog.groups_current_page < total_pages - 1)

    # ----------------------------------------------------------- member inspection
    def handle_activation(self, row: int) -> None:
        if row < 0:
            return
        name_item = self.table.item(row, 1)
        if not name_item:
            return
        group_id = name_item.data(Qt.ItemDataRole.UserRole)
        if not group_id:
            return
        group_name = name_item.text()
        self.show_group_members(str(group_id), group_name)

    def show_group_members(self, group_id: str, group_name: str) -> None:
        dialog = QDialog(self.dialog)
        dialog.setWindowTitle(f"{group_name} — Members")
        dialog.resize(520, 420)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        member_ids = self.dialog.group_members_lookup.get(group_id, [])
        member_records = [
            summarize_user(self.dialog.user_lookup.get(user_id, {}), user_id)
            for user_id in member_ids
        ]
        member_records.sort(key=lambda record: record["name"].lower())

        header_label = QLabel(
            f"<b>{len(member_records):,} members</b> in this group."
            if member_records
            else "No members found for this group."
        )
        header_label.setWordWrap(True)
        layout.addWidget(header_label)

        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Name", "Email / Login", "Status"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        table.setRowCount(len(member_records))
        for row_index, record in enumerate(member_records):
            table.setItem(row_index, 0, QTableWidgetItem(record["name"]))
            table.setItem(row_index, 1, QTableWidgetItem(record["email"]))
            table.setItem(row_index, 2, QTableWidgetItem(record["status"]))

        layout.addWidget(table, 1)

        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        close_button.setStyleSheet(
            """
            QPushButton {
                background: #1976d2;
                color: white;
                padding: 6px 18px;
                border-radius: 4px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #1565c0;
            }
        """
        )
        close_layout.addWidget(close_button)
        layout.addLayout(close_layout)

        dialog.exec()
