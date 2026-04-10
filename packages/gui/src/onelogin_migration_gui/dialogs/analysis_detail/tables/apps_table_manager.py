"""Table manager for the Applications tab."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from ..utils.formatters import summarize_assigned_groups
from ..utils.status_helpers import app_status_details
from ..utils.validators import estimate_active_users, extract_group_ids
from .base_table_manager import BaseTableManager

if TYPE_CHECKING:
    from ..dialog import AnalysisDetailDialog

LOGGER = logging.getLogger(__name__)

APP_INDEX_ROLE = int(Qt.ItemDataRole.UserRole) + 100


class ApplicationsTableManager(BaseTableManager):
    """Handle population, filtering, and actions for the applications table."""

    def __init__(
        self,
        dialog: AnalysisDetailDialog,
        table: QTableWidget,
        count_label: QLabel,
        page_label: QLabel,
        prev_button: QPushButton,
        next_button: QPushButton,
        search_field: QLineEdit,
        type_filter: QComboBox,
        status_filter: QComboBox,
    ) -> None:
        super().__init__(dialog, table, count_label, page_label, prev_button, next_button)
        self._search_field = search_field
        self._type_filter = type_filter
        self._status_filter = status_filter
        self._status_map = {
            "Can Auto-Migrate": ["connector", "custom_saml"],  # Special case: multiple categories
            "Connector Match": "connector",
            "Custom SAML/OIDC": "custom_saml",
            "Needs Review": "review",
            "Manual Migration": "manual",
            "Inactive": "inactive",
        }
        # Track duplicate groups: maps duplicate_group_id -> list of app IDs
        self._duplicate_groups: dict[str, list[str]] = {}

    # --------------------------------------------------------------------- populate
    def populate(self) -> None:
        self._ensure_selection_column()
        self._reset_selection_state()
        total_apps = len(self.dialog.all_apps)
        # Use actual app IDs as keys for selection tracking
        all_app_ids = [str(app.get("id")) for app in self.dialog.all_apps if app.get("id")]
        self._set_all_row_keys(all_app_ids)

        # Build duplicate groups mapping and identify preferred apps
        self._duplicate_groups = {}
        preferred_app_ids: set[str] = set()
        for app in self.dialog.all_apps:
            migration_meta = app.get("_migration", {})
            if migration_meta.get("is_duplicate"):
                group_id = migration_meta.get("duplicate_group_id")
                app_id = str(app.get("id", ""))
                if group_id and app_id:
                    self._duplicate_groups.setdefault(group_id, []).append(app_id)
                    # Track which apps should be selected by default (preferred in their group)
                    if migration_meta.get("preferred_in_group"):
                        preferred_app_ids.add(app_id)

        # Set initial selection overrides for duplicate apps
        # By default, only the preferred app in each duplicate group should be selected
        if self._duplicate_groups:
            # Get all duplicate app IDs
            all_duplicate_ids = set()
            for app_ids in self._duplicate_groups.values():
                all_duplicate_ids.update(app_ids)

            # For each duplicate app, set selection based on whether it's preferred
            for app_id in all_duplicate_ids:
                if app_id in preferred_app_ids:
                    # Preferred app: ensure it's selected (matches default if default is True)
                    if not self._selection_default_state:
                        self._selection_overrides[app_id] = True
                else:
                    # Non-preferred duplicate: ensure it's NOT selected
                    if self._selection_default_state:
                        self._selection_overrides[app_id] = False

        start_idx = self.dialog.apps_current_page * self.dialog.page_size
        end_idx = min(start_idx + self.dialog.page_size, total_apps)
        apps_list = self.dialog.all_apps[start_idx:end_idx]

        LOGGER.info(
            "Populating apps table with %s apps (page %s)",
            len(apps_list),
            self.dialog.apps_current_page + 1,
        )

        self.table.setRowCount(0)
        self.table.setSortingEnabled(False)

        for app in apps_list:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # Use app ID as the selection key
            app_id = str(app.get("id", ""))
            self._create_selection_cell(row, key=app_id)

            name = app.get("label", app.get("name", "(No Name)"))

            # Append "(duplicate)" suffix if this app is marked as a duplicate
            migration_meta = app.get("_migration", {})
            if migration_meta.get("is_duplicate"):
                name = f"{name} (duplicate)"

            name_item = QTableWidgetItem(name)
            name_item.setToolTip(name)
            name_item.setData(APP_INDEX_ROLE, start_idx + row)
            self.table.setItem(row, 1, name_item)

            sign_on_mode = app.get("signOnMode") or "UNKNOWN"
            # Check for specific protocols - order matters for OIDC vs legacy OpenID
            if "SAML" in sign_on_mode:
                app_type = "SAML"
            elif "OPENID_CONNECT" in sign_on_mode:
                app_type = "OIDC"  # Modern OpenID Connect
            elif "OPENID" in sign_on_mode:
                app_type = "OpenID"  # Legacy OpenID
            elif "OAUTH" in sign_on_mode:
                app_type = "OAuth"
            else:
                app_type = "Custom"
            type_item = QTableWidgetItem(app_type)
            type_item.setToolTip(app_type)
            self.table.setItem(row, 2, type_item)

            status_details = app_status_details(app)
            status_item = QTableWidgetItem(status_details["label"])
            status_item.setForeground(QColor(status_details["color"]))
            status_item.setToolTip(status_details["tooltip"])
            status_item.setData(Qt.ItemDataRole.UserRole, status_details["sort_value"])
            status_item.setData(Qt.ItemDataRole.UserRole + 1, status_details.get("category_key"))
            self.table.setItem(row, 3, status_item)

            assigned_groups, tooltip = summarize_assigned_groups(app, self.dialog.group_lookup)
            groups_item = QTableWidgetItem(assigned_groups)
            groups_item.setToolTip(tooltip)
            groups_item.setData(Qt.ItemDataRole.UserRole, len(extract_group_ids(app)))
            self.table.setItem(row, 4, groups_item)

            estimated_users = estimate_active_users(app, self.dialog.group_members_lookup)
            users_text = f"{estimated_users:,}" if estimated_users is not None else "—"
            users_item = QTableWidgetItem(users_text)
            users_item.setData(Qt.ItemDataRole.UserRole, estimated_users or 0)
            if estimated_users is not None:
                users_item.setToolTip("Estimate based on unique users in assigned groups")
            else:
                users_item.setToolTip("No assigned groups available")
            self.table.setItem(row, 5, users_item)

        self.table.setSortingEnabled(True)
        # Apply filters to update filtered keys (in case filters were already set)
        self.apply_filters()
        self.update_pagination()

    # ---------------------------------------------------------------------- filter
    def apply_filters(self) -> None:
        search_text = self._search_field.text().lower()
        type_filter = self._type_filter.currentText()
        status_filter_value = self._status_filter.currentText()
        status_filter_key = self._status_map.get(status_filter_value)

        # Track which app IDs match the filter
        filtered_app_ids: list[str] = []

        # Determine if any filter is active
        has_filter = bool(search_text) or type_filter != "All" or bool(status_filter_key)

        # Apply filters to ALL apps (not just current page)
        if has_filter:
            for app in self.dialog.all_apps:
                should_show = True

                # Check search filter
                if search_text:
                    name = app.get("label", app.get("name", "")).lower()
                    if search_text not in name:
                        should_show = False

                # Check type filter
                if should_show and type_filter != "All":
                    sign_on_mode = app.get("signOnMode") or "UNKNOWN"
                    if "SAML" in sign_on_mode:
                        app_type = "SAML"
                    elif "OPENID_CONNECT" in sign_on_mode:
                        app_type = "OIDC"
                    elif "OPENID" in sign_on_mode:
                        app_type = "OpenID"
                    elif "OAUTH" in sign_on_mode:
                        app_type = "OAuth"
                    else:
                        app_type = "Custom"

                    if app_type != type_filter:
                        should_show = False

                # Check status filter
                if should_show and status_filter_key:
                    from ..utils.status_helpers import app_status_details

                    status_details = app_status_details(app)
                    item_key = status_details.get("category_key")

                    # Handle both single category and multiple categories (for "Can Auto-Migrate")
                    if isinstance(status_filter_key, list):
                        if item_key not in status_filter_key:
                            should_show = False
                    else:
                        if item_key != status_filter_key:
                            should_show = False

                # Add to filtered list if it matches
                if should_show:
                    app_id = str(app.get("id", ""))
                    if app_id:
                        filtered_app_ids.append(app_id)

        # Apply visibility to current page rows
        for row in range(self.table.rowCount()):
            should_show = True

            if search_text:
                name = self.table.item(row, 1).text().lower()
                if search_text not in name:
                    should_show = False

            if should_show and type_filter != "All":
                app_type = self.table.item(row, 2).text()
                if app_type != type_filter:
                    should_show = False

            if should_show and status_filter_key:
                status_item = self.table.item(row, 3)
                item_key = status_item.data(Qt.ItemDataRole.UserRole + 1) if status_item else None

                # Handle both single category and multiple categories (for "Can Auto-Migrate")
                if isinstance(status_filter_key, list):
                    if item_key not in status_filter_key:
                        should_show = False
                else:
                    if item_key != status_filter_key:
                        should_show = False

            self.table.setRowHidden(row, not should_show)

        # Update selection system with filtered keys
        if has_filter:
            self.set_filtered_keys(filtered_app_ids)
        else:
            self.set_filtered_keys(None)  # Clear filter

        self.update_count()

    # ------------------------------------------------------------------- utilities
    def update_count(self) -> None:
        visible = self._visible_rows()
        total_on_page = self.table.rowCount()
        total_all = len(self.dialog.all_apps)
        self.count_label.setText(
            f"Showing {visible:,} of {total_on_page:,} applications on this page ({total_all:,} total)"
        )

    def update_pagination(self) -> None:
        total_apps = len(self.dialog.all_apps)
        total_pages = (
            (total_apps + self.dialog.page_size - 1) // self.dialog.page_size
            if total_apps > 0
            else 1
        )
        current_page_num = self.dialog.apps_current_page + 1

        self.page_label.setText(f"Page {current_page_num:,} of {total_pages:,}")
        self.prev_button.setEnabled(self.dialog.apps_current_page > 0)
        self.next_button.setEnabled(self.dialog.apps_current_page < total_pages - 1)

    # --------------------------------------------------------- duplicate mutual exclusion
    def _on_row_checkbox_changed(self, checkbox, state: int) -> None:
        """Override to implement mutual exclusion for duplicate apps.

        When a duplicate app is checked, automatically uncheck other apps in the same duplicate group.
        """
        # Get the app ID for this checkbox
        app_id = self._checkbox_key_map.get(checkbox)

        if app_id and checkbox.isChecked():
            # User is checking this app - check if it's part of a duplicate group
            duplicate_group_id = None
            for group_id, app_ids in self._duplicate_groups.items():
                if app_id in app_ids:
                    duplicate_group_id = group_id
                    break

            if duplicate_group_id:
                # This app is part of a duplicate group
                # Uncheck all other apps in the same group
                other_app_ids = [
                    aid for aid in self._duplicate_groups[duplicate_group_id] if aid != app_id
                ]

                LOGGER.info(
                    "App '%s' is being checked - unchecking %d other apps in duplicate group '%s'",
                    app_id,
                    len(other_app_ids),
                    duplicate_group_id,
                )

                # Update overrides for other apps in the group to be unchecked
                for other_app_id in other_app_ids:
                    if self._selection_default_state:
                        # Default is checked, so add override to uncheck
                        self._selection_overrides[other_app_id] = False
                    else:
                        # Default is unchecked, so remove override (if any)
                        self._selection_overrides.pop(other_app_id, None)

                    # Update the checkbox widget if it's visible on the current page
                    for cb in self._row_checkboxes:
                        if self._checkbox_key_map.get(cb) == other_app_id:
                            cb.blockSignals(True)
                            cb.setChecked(False)
                            cb.blockSignals(False)
                            break

        # Call parent implementation to handle normal selection logic
        super()._on_row_checkbox_changed(checkbox, state)

    # ---------------------------------------------------------------------- actions
