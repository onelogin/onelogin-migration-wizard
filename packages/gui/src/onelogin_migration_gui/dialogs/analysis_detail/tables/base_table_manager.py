"""Abstract base classes for analysis detail table managers."""

from __future__ import annotations

import types
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ....components import ModernCheckbox

if TYPE_CHECKING:  # pragma: no cover - for type hints only
    from ..analysis_detail import AnalysisDetailDialog


class BaseTableManager(ABC):
    """Shared behavior for table managers."""

    def __init__(
        self,
        dialog: AnalysisDetailDialog,
        table: QTableWidget,
        count_label: QLabel,
        page_label: QLabel,
        prev_button: QPushButton,
        next_button: QPushButton,
    ) -> None:
        self.dialog = dialog
        self.table = table
        self.count_label = count_label
        self.page_label = page_label
        self.prev_button = prev_button
        self.next_button = next_button
        self._selection_initialized = False
        self._row_checkboxes: list[ModernCheckbox] = []
        self._select_all_checkbox: ModernCheckbox | None = None
        self._checkbox_key_map: dict[ModernCheckbox, Any] = {}
        self._selection_default_state: bool = True
        self._selection_overrides: dict[Any, bool] = {}
        self._all_row_keys: list[Any] = []
        self._filtered_row_keys: list[Any] | None = None  # None means no filter (all keys)
        self._selection_column_width: int = 40

    @abstractmethod
    def populate(self) -> None:
        """Populate the table with data for the current page."""

    @abstractmethod
    def apply_filters(self) -> None:
        """Apply filter controls to the table."""

    @abstractmethod
    def update_count(self) -> None:
        """Update the count label for visible rows."""

    @abstractmethod
    def update_pagination(self) -> None:
        """Refresh pagination label and button states."""

    def _visible_rows(self) -> int:
        """Return the number of visible rows after filtering."""
        return sum(1 for row in range(self.table.rowCount()) if not self.table.isRowHidden(row))

    def _get_active_row_keys(self) -> list[Any]:
        """Get the row keys that should be considered for select all operations.

        Returns:
            list[Any]: Filtered keys if a filter is active, otherwise all keys.
        """
        return (
            self._filtered_row_keys if self._filtered_row_keys is not None else self._all_row_keys
        )

    def set_filtered_keys(self, keys: list[Any] | None) -> None:
        """Set the filtered row keys for select all operations.

        Args:
            keys: List of filtered keys, or None to clear the filter.
        """
        self._filtered_row_keys = keys
        self._update_select_all_checkbox()

    # ---------------------------------------------------------------- selection helpers
    def _ensure_selection_column(self) -> None:
        """Ensure the selection column and header checkbox are initialized."""
        if self._selection_initialized:
            return

        header_item = self.table.horizontalHeaderItem(0)
        if header_item is None:
            self.table.insertColumn(0)
            self.table.setHorizontalHeaderItem(0, QTableWidgetItem(""))
        else:
            header_item.setText("")

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionsMovable(False)
        header.setSectionsClickable(False)

        # Set column width to be narrow - just enough for the checkbox
        # Using a third of previous width as requested
        self._selection_column_width = 30  # Minimal width for 22px checkbox
        header.resizeSection(0, self._selection_column_width)

        # Set header alignment for selection column to center
        if header_item:
            header_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        # Create Select All checkbox
        # Note: Initial state will be set by _update_select_all_checkbox() after population
        select_all = ModernCheckbox(parent=header)

        # Set BOTH fixed size and size policy to prevent stretching
        select_all.setFixedSize(22, 22)  # Match welcome.py checkbox size
        select_all.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        select_all.setTristate(True)

        # Don't set initial checked state here - let _update_select_all_checkbox handle it

        # IMPORTANT: Use clicked signal instead of stateChanged for better tristate behavior
        # clicked fires on user interaction, stateChanged fires on any state change (including programmatic)
        select_all.clicked.connect(self._on_select_all_clicked)
        self._select_all_checkbox = select_all

        header.sectionResized.connect(lambda *_: self._position_select_all_checkbox())
        header.sectionMoved.connect(lambda *_: self._position_select_all_checkbox())
        try:
            header.geometriesChanged.connect(lambda: self._position_select_all_checkbox())  # type: ignore[attr-defined]
        except AttributeError:
            pass
        self.table.horizontalScrollBar().valueChanged.connect(
            lambda *_: self._position_select_all_checkbox()
        )

        self._selection_initialized = True
        self.table._analysis_selection_column = True
        self._position_select_all_checkbox()
        self._install_selection_sort_guard()

    def _reset_selection_state(self) -> None:
        """Clear row checkbox tracking for repopulation."""
        # IMPORTANT: Explicitly delete old checkboxes to free memory
        # This prevents accumulation of widgets in memory across page changes
        for checkbox in self._row_checkboxes:
            try:
                # Disconnect from theme manager before deletion
                if hasattr(checkbox, "theme_manager") and checkbox.theme_manager:
                    checkbox.theme_manager.theme_changed.disconnect(checkbox._on_theme_changed)
            except (RuntimeError, TypeError, AttributeError):
                pass  # Already disconnected

            # Delete the widget
            checkbox.deleteLater()

        # Clear tracking lists
        self._row_checkboxes = []
        self._checkbox_key_map = {}
        self.table._analysis_row_checkboxes = self._row_checkboxes
        self._update_select_all_checkbox()
        header = self.table.horizontalHeader()
        header.setSortIndicatorShown(False)
        header.setSectionsMovable(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)

    def _set_all_row_keys(self, keys: Sequence[Any]) -> None:
        """Register the full set of row identifiers for the current dataset."""
        self._all_row_keys = list(keys)
        key_set = set(self._all_row_keys)
        self._selection_overrides = {
            key: value for key, value in self._selection_overrides.items() if key in key_set
        }
        if not self._all_row_keys:
            self._selection_default_state = False
        self._update_select_all_checkbox()

    def _install_selection_sort_guard(self) -> None:
        """Ensure the selection column never participates in sorting."""
        if getattr(self.table, "_analysis_selection_sort_guard", False):
            return

        original_sort_items = self.table.sortItems
        original_sort_by_column = getattr(self.table, "sortByColumn", None)

        def guarded_sort_items(
            _self: QTableWidget, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder
        ) -> None:
            if column == 0:
                return
            original_sort_items(column, order)

        self.table.sortItems = types.MethodType(guarded_sort_items, self.table)

        if callable(original_sort_by_column):

            def guarded_sort_by_column(
                _self: QTableWidget, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder
            ) -> None:
                if column == 0:
                    return
                original_sort_by_column(column, order)  # type: ignore[misc]

            self.table.sortByColumn = types.MethodType(guarded_sort_by_column, self.table)  # type: ignore[assignment]

        self.table._analysis_selection_sort_guard = True

    def _create_selection_cell(self, row: int, *, key: Any | None = None) -> ModernCheckbox:
        """Create a checkbox cell at the selection column for the given row.

        The checkbox's initial state is determined by:
        1. Checking if this specific item has an override in _selection_overrides
        2. If no override exists, using the _selection_default_state

        This ensures that when you navigate between pages:
        - Items maintain their selection state (via overrides)
        - New items get the appropriate default state
        - Select All operations are properly reflected across all pages
        """
        identifier = key if key is not None else row
        checkbox = ModernCheckbox()

        # Set BOTH fixed size and size policy to prevent stretching
        checkbox.setFixedSize(22, 22)  # Match welcome.py checkbox size
        checkbox.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        # Get initial state: check for override first, then use default
        initial_state = self._selection_overrides.get(identifier, self._selection_default_state)

        checkbox.blockSignals(True)
        checkbox.setChecked(initial_state)
        checkbox.blockSignals(False)
        checkbox.stateChanged.connect(
            lambda state, chk=checkbox: self._on_row_checkbox_changed(chk, state)
        )

        # Create centered container for the checkbox
        # Let the cell width be controlled by the table column, not the container
        container = QWidget()
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        container.setStyleSheet("background: transparent;")
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)  # No margins
        layout.setSpacing(0)

        # Center the checkbox in the container
        layout.addStretch()
        layout.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch()

        self.table.setCellWidget(row, 0, container)
        self._row_checkboxes.append(checkbox)
        self._checkbox_key_map[checkbox] = identifier
        self.table._analysis_row_checkboxes = self._row_checkboxes
        return checkbox

    def _position_select_all_checkbox(self) -> None:
        if not self._selection_initialized or not self._select_all_checkbox:
            return
        header = self.table.horizontalHeader()
        x = header.sectionPosition(0)
        width = header.sectionSize(0)
        y_top = header.geometry().y()
        self._select_all_checkbox.move(
            max(0, x + (width - self._select_all_checkbox.width()) // 2),
            max(0, y_top + (header.height() - self._select_all_checkbox.height()) // 2),
        )

    def _on_select_all_clicked(self) -> None:
        """Handle Select All checkbox clicks - affects items based on current filter.

        IMPORTANT: This selects/deselects items based on the current filter:
        - If a filter is active (e.g., "Migration Status" filter), only affects filtered items
        - If no filter is active, affects ALL items in the category
        - In both cases, affects items across all pages (not just the current page)

        Logic:
        - The clicked signal fires AFTER Qt has already changed the checkbox state
        - So we use the NEW state to determine what the user wants
        - Checked (after click) -> user wants all checked
        - Unchecked (after click) -> user wants all unchecked
        - Partial (after click) -> treat as "select all"

        Implementation:
        - For filtered items: sets overrides for each filtered key
        - For unfiltered items: sets the default state and clears overrides
        - Updates visible checkboxes to reflect the new state
        """
        import logging

        logger = logging.getLogger(__name__)

        # Get the state AFTER the click (Qt has already changed it)
        new_state = self._select_all_checkbox.checkState()
        active_keys = self._get_active_row_keys()
        is_filtered = self._filtered_row_keys is not None

        logger.info(
            f"🔔 Select All clicked! New state after click: {new_state} (Checked={Qt.CheckState.Checked}, Unchecked={Qt.CheckState.Unchecked}, Partial={Qt.CheckState.PartiallyChecked})"
        )
        logger.info(
            f"   Current default: {self._selection_default_state}, Overrides count: {len(self._selection_overrides)}"
        )
        logger.info(
            f"   Filter active: {is_filtered}, Active items: {len(active_keys)}, Total items: {len(self._all_row_keys)}, Visible checkboxes: {len(self._row_checkboxes)}"
        )

        # Determine target state based on the NEW state (after click)
        # The checkbox state reflects what the user wants
        if new_state == Qt.CheckState.Unchecked:
            # Checkbox is now unchecked -> user wants all UNCHECKED
            target_checked = False
            logger.info("   → Setting to UNCHECKED")
        else:
            # Checkbox is now checked or partial -> user wants all CHECKED
            target_checked = True
            logger.info("   → Setting to CHECKED")

        if is_filtered:
            # Filter is active: only affect filtered items using overrides
            logger.info(f"   → Updating overrides for {len(active_keys)} filtered items")
            for key in active_keys:
                if target_checked:
                    # User wants these checked
                    if self._selection_default_state:
                        # Default is checked, so remove override (item matches default)
                        self._selection_overrides.pop(key, None)
                    else:
                        # Default is unchecked, so add override to check it
                        self._selection_overrides[key] = True
                else:
                    # User wants these unchecked
                    if self._selection_default_state:
                        # Default is checked, so add override to uncheck it
                        self._selection_overrides[key] = False
                    else:
                        # Default is unchecked, so remove override (item matches default)
                        self._selection_overrides.pop(key, None)
        else:
            # No filter: affect ALL items by changing the default state
            logger.info(f"   → Setting default state for ALL {len(self._all_row_keys)} items")
            self._selection_default_state = target_checked
            # Clear ALL overrides - this means every item gets the default state
            self._selection_overrides.clear()

        # Update all VISIBLE checkboxes on current page to match the new state
        updated_count = 0
        for checkbox in self._row_checkboxes:
            key = self._checkbox_key_map.get(checkbox)
            if key is not None:
                # Determine if this checkbox should be checked
                should_check = self._selection_overrides.get(key, self._selection_default_state)
                checkbox.blockSignals(True)  # Prevent triggering individual change handlers
                checkbox.setChecked(should_check)
                checkbox.blockSignals(False)
                updated_count += 1

        logger.info(f"   ✅ Updated {updated_count} visible checkboxes")

        # Persist state for debugging/inspection
        self.table._analysis_selection_default = self._selection_default_state
        self.table._analysis_selection_overrides = dict(self._selection_overrides)

        # Update the Select All checkbox to reflect the new state (should be all checked or all unchecked)
        self._update_select_all_checkbox()

    def _on_row_checkbox_changed(self, checkbox: ModernCheckbox, _state: int) -> None:
        """Handle individual checkbox changes and update override tracking.

        When a user clicks an individual checkbox:
        1. Record the new state in the overrides dictionary
        2. Update the Select All checkbox to reflect the collective state
        """
        import logging

        logger = logging.getLogger(__name__)

        key = self._checkbox_key_map.get(checkbox)
        if key is not None:
            checked = checkbox.isChecked()
            logger.info(
                f"📝 Individual checkbox changed: key={key}, checked={checked}, default={self._selection_default_state}"
            )

            # Track this checkbox's state in overrides
            if checked == self._selection_default_state:
                # Checkbox matches default, remove from overrides
                self._selection_overrides.pop(key, None)
                logger.info("   → Removed from overrides (matches default)")
            else:
                # Checkbox differs from default, add to overrides
                self._selection_overrides[key] = checked
                logger.info("   → Added to overrides (differs from default)")

        # Persist state for debugging/inspection
        self.table._analysis_selection_overrides = dict(self._selection_overrides)

        # Update Select All checkbox to reflect the new collective state
        logger.info(
            f"   → Updating Select All state (overrides count now: {len(self._selection_overrides)})"
        )
        self._update_select_all_checkbox()

    def _update_select_all_checkbox(self) -> None:
        """Update the Select All checkbox state based on active items.

        IMPORTANT: When a filter is active, only considers filtered items.
        When no filter is active, considers ALL items.

        How it works:
        - Gets active keys (filtered or all) using _get_active_row_keys()
        - Uses _selection_default_state (the default for ALL items)
        - Uses _selection_overrides (individual exceptions to the default)
        - Calculates how many of the ACTIVE items are actually checked

        States:
        - Checked: ALL active items are checked
        - Unchecked: ALL active items are unchecked
        - Indeterminate: SOME (but not all) active items are checked
        """
        import logging

        logger = logging.getLogger(__name__)

        if not self._select_all_checkbox:
            logger.warning("⚠️  Select All checkbox doesn't exist!")
            return

        # Get active keys (filtered or all)
        active_keys = self._get_active_row_keys()
        is_filtered = self._filtered_row_keys is not None
        total_items = len(active_keys)

        logger.info(
            f"🔄 Updating Select All state: filtered={is_filtered}, active_items={total_items}, "
            f"total_items={len(self._all_row_keys)}, default={self._selection_default_state}, overrides={len(self._selection_overrides)}"
        )

        if total_items == 0:
            # No items in current filter/category
            desired = Qt.CheckState.Unchecked
            tristate = False
            checked_count = 0
        else:
            # Calculate how many ACTIVE items are checked
            checked_count = 0
            for key in active_keys:
                # Check if this key is checked (using override if exists, otherwise default)
                is_checked = self._selection_overrides.get(key, self._selection_default_state)
                if is_checked:
                    checked_count += 1

            logger.info(f"   Calculated: {checked_count}/{total_items} active items checked")

            # Determine Select All state based on checked count
            if checked_count == 0:
                # None checked
                desired = Qt.CheckState.Unchecked
                tristate = False
                logger.info("   → Setting Select All to UNCHECKED")
            elif checked_count == total_items:
                # All checked
                desired = Qt.CheckState.Checked
                tristate = False
                logger.info("   → Setting Select All to CHECKED")
            else:
                # Some checked (partial state)
                desired = Qt.CheckState.PartiallyChecked
                tristate = True
                logger.info("   → Setting Select All to INDETERMINATE")

        # Update the Select All checkbox without triggering its change handler
        self._select_all_checkbox.blockSignals(True)
        self._select_all_checkbox.setTristate(tristate)
        self._select_all_checkbox.setCheckState(desired)
        self._select_all_checkbox.blockSignals(False)
        logger.info(f"   ✅ Select All updated to state={desired}")

    def _row_checkbox_at(self, row: int) -> ModernCheckbox | None:
        widget = self.table.cellWidget(row, 0)
        if not widget:
            return None
        return widget.findChild(ModernCheckbox)

    def selected_row_indexes(self) -> list[int]:
        """Return the list of row indexes whose selection checkbox is checked."""
        selected_rows: list[int] = []
        for row in range(self.table.rowCount()):
            checkbox = self._row_checkbox_at(row)
            if checkbox and checkbox.isChecked():
                selected_rows.append(row)
        return selected_rows

    def get_all_selected_keys(self) -> set[Any]:
        """Return the set of ALL selected item keys across all pages.

        This method accounts for:
        - The default selection state (all checked or all unchecked)
        - Individual overrides (specific items toggled differently)

        Returns:
            set[Any]: Set of keys for items that are selected.
                     If default is True and no overrides, returns all keys.
                     If default is False, returns only keys with True overrides.
        """
        selected_keys: set[Any] = set()

        if self._selection_default_state:
            # Default is checked, so start with all keys
            selected_keys = set(self._all_row_keys)
            # Remove unchecked overrides
            for key, is_checked in self._selection_overrides.items():
                if not is_checked and key in selected_keys:
                    selected_keys.remove(key)
        else:
            # Default is unchecked, so only include checked overrides
            selected_keys = {
                key for key, is_checked in self._selection_overrides.items() if is_checked
            }

        return selected_keys
