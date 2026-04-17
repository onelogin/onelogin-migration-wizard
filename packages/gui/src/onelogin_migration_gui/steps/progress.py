"""Progress page displayed during migration execution."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..components import ModernCard
from ..styles.button_styles import (
    DESTRUCTIVE_BUTTON_STYLE,
    SECONDARY_BUTTON_STYLE,
    SUCCESS_BUTTON_STYLE,
)
from .base import BasePage

if TYPE_CHECKING:  # pragma: no cover
    pass

OBJECT_KEYS = ("users", "groups", "applications", "policies")
# Map OBJECT_KEYS to display names for status cards
CATEGORY_DISPLAY_NAMES = {
    "users": "Users",
    "groups": "Groups",
    "applications": "Apps",
    "policies": "Custom Attributes",  # Policies are actually custom attributes
}
# Map to logging categories
CATEGORY_LOG_MAPPING = {
    "users": "users",
    "groups": "groups",
    "applications": "apps",
    "policies": "custom_attributes",
}


class ProgressPage(BasePage):
    cancel_requested = Signal()
    open_bulk_location_requested = Signal()
    finish_requested = Signal()

    def __init__(self) -> None:
        super().__init__("Migration Progress")
        self._bulk_path: str | None = None
        self._active_categories: set[str] = set()
        self._log_entries: deque[dict] = deque(maxlen=100)  # Keep last 100 entries
        self._current_filter: str = "all"  # "all", "info", "warning", "error"
        self._search_text: str = ""
        self._category_totals: dict[str, int] = {}
        self._category_completed: dict[str, int] = {}

        layout = self.body_layout

        # Header
        header = QLabel("Migration Progress")

        def update_header_style():
            heading_typo = self.theme_manager.get_typography("h2")
            header.setStyleSheet(
                f"""
                QLabel {{
                    font-size: {heading_typo['size']}px;
                    font-weight: {heading_typo['weight']};
                    color: {self.theme_manager.get_color('text_primary')};
                    margin-bottom: {self.theme_manager.get_spacing('md')}px;
                }}
            """
            )

        update_header_style()
        self.theme_manager.theme_changed.connect(update_header_style)
        layout.addWidget(header)

        # Overall progress bar
        self.overall_bar = QProgressBar()
        layout.addWidget(self.overall_bar)

        # Dynamic status cards container
        self.cards_container = QWidget()
        self.cards_layout = QGridLayout(self.cards_container)
        self.cards_layout.setHorizontalSpacing(self.theme_manager.get_spacing("md"))
        self.cards_layout.setVerticalSpacing(self.theme_manager.get_spacing("md"))
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.status_cards: dict[str, ModernCard] = {}
        self.status_card_labels: dict[str, QLabel] = {}

        # Create cards for all categories (will show/hide based on active categories)
        for idx, (key, display_name) in enumerate(CATEGORY_DISPLAY_NAMES.items()):
            card = self._create_status_card(display_name, key)
            self.status_cards[key] = card
            # Arrange in 2x2 grid
            row = idx // 2
            col = idx % 2
            self.cards_layout.addWidget(card, row, col)
            card.setVisible(False)  # Hidden by default

        # Configure column and row stretching for even distribution in 2x2 grid
        self.cards_layout.setColumnStretch(0, 1)  # First column takes equal space
        self.cards_layout.setColumnStretch(1, 1)  # Second column takes equal space
        self.cards_layout.setRowStretch(0, 1)  # First row
        self.cards_layout.setRowStretch(1, 1)  # Second row

        layout.addWidget(self.cards_container)

        # Activity Log with filtering
        log_group = QGroupBox("Activity Log")
        log_layout = QVBoxLayout(log_group)

        # Filter controls
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))

        self.severity_filter = QComboBox()
        self.severity_filter.addItems(["All Levels", "Info Only", "Warnings Only", "Errors Only"])
        self.severity_filter.currentTextChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.severity_filter)

        filter_row.addWidget(QLabel("Search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search logs...")
        self.search_box.textChanged.connect(self._on_search_changed)
        filter_row.addWidget(self.search_box)

        filter_row.addStretch()
        log_layout.addLayout(filter_row)

        # Log view
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        # Set monospace font for better readability
        from PySide6.QtGui import QFontDatabase

        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(10)
        self.log_view.setFont(font)

        log_layout.addWidget(self.log_view)
        layout.addWidget(log_group)

        # Buttons
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.cancel_button = QPushButton("Cancel Migration")
        self.open_folder_button = QPushButton("Open Export Folder")
        self.finish_button = QPushButton("Finish")

        def update_button_styles() -> None:
            self.cancel_button.setStyleSheet(DESTRUCTIVE_BUTTON_STYLE())
            self.open_folder_button.setStyleSheet(SECONDARY_BUTTON_STYLE())
            self.finish_button.setStyleSheet(SUCCESS_BUTTON_STYLE())

        update_button_styles()
        self.theme_manager.theme_changed.connect(update_button_styles)
        self.open_folder_button.setVisible(False)
        self.finish_button.setVisible(False)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.open_folder_button)
        button_row.addWidget(self.finish_button)
        layout.addLayout(button_row)

        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.open_folder_button.clicked.connect(self.open_bulk_location_requested.emit)
        self.finish_button.clicked.connect(self.finish_requested.emit)

    def _create_status_card(self, title: str, category_key: str) -> ModernCard:
        """Create a status card for a migration category."""
        card = ModernCard(title=title, accent_color="info", padding="md")

        # Add progress label
        progress_label = QLabel("0 / 0")
        progress_typo = self.theme_manager.get_typography("h2")

        def update_label_style():
            progress_label.setStyleSheet(
                f"""
                QLabel {{
                    font-size: {progress_typo['size']}px;
                    font-weight: {progress_typo['weight']};
                    color: {self.theme_manager.get_color('primary')};
                    margin-top: {self.theme_manager.get_spacing('sm')}px;
                }}
                """
            )

        update_label_style()
        self.theme_manager.theme_changed.connect(update_label_style)

        card.add_widget(progress_label)
        self.status_card_labels[category_key] = progress_label

        return card

    def _on_filter_changed(self, filter_text: str) -> None:
        """Handle severity filter change."""
        filter_map = {
            "All Levels": "all",
            "Info Only": "info",
            "Warnings Only": "warning",
            "Errors Only": "error",
        }
        self._current_filter = filter_map.get(filter_text, "all")
        self._refresh_log_display()

    def _on_search_changed(self, search_text: str) -> None:
        """Handle search text change."""
        self._search_text = search_text.lower()
        self._refresh_log_display()

    def _refresh_log_display(self) -> None:
        """Refresh the log display based on current filter and search."""
        self.log_view.clear()

        for entry_dict in self._log_entries:
            # Apply severity filter
            level = entry_dict.get("level", "INFO")
            if self._current_filter != "all":
                if self._current_filter == "info" and level != "INFO":
                    continue
                if self._current_filter == "warning" and level != "WARNING":
                    continue
                if self._current_filter == "error" and level not in ("ERROR", "FATAL"):
                    continue

            # Apply search filter
            message = entry_dict.get("message", "")
            if self._search_text and self._search_text not in message.lower():
                continue

            # Display the entry
            self._append_log_entry_to_view(entry_dict)

    def _append_log_entry_to_view(self, entry_dict: dict) -> None:
        """Append a single log entry to the view with color coding."""
        from ..logging_handler import LogEntry

        entry = LogEntry.from_dict(entry_dict)

        # Get color for this log level
        color = entry.level.to_color(self.theme_manager)

        # Format the message with HTML for color
        formatted_message = entry.format_display()

        # Use HTML to apply color
        html = f'<span style="color: {color};">{formatted_message}</span>'

        # Check if user was scrolled to the bottom before appending
        scrollbar = self.log_view.verticalScrollBar()
        was_at_bottom = scrollbar.value() == scrollbar.maximum()

        # Save horizontal scroll position to prevent jumping left/right
        h_scrollbar = self.log_view.horizontalScrollBar()
        h_scroll_pos = h_scrollbar.value()

        self.log_view.append(html)

        # Restore horizontal scroll position
        h_scrollbar.setValue(h_scroll_pos)

        # Only auto-scroll to bottom if user was already at bottom
        if was_at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def reset(self) -> None:
        """Reset the progress page to initial state."""
        self.overall_bar.setValue(0)
        for label in self.status_card_labels.values():
            label.setText("0 / 0")
        self.log_view.clear()
        self._log_entries.clear()
        self._bulk_path = None
        self._category_totals.clear()
        self._category_completed.clear()
        self.open_folder_button.setVisible(False)
        self.finish_button.setVisible(False)
        self.finish_button.setEnabled(False)
        self.severity_filter.setCurrentIndex(0)
        self.search_box.clear()

    def update_object(self, name: str, percent: int) -> None:
        """Update progress for a specific category (backward compatibility)."""
        # This is for backward compatibility with old code
        # The new method is update_category_progress
        pass

    def update_category_progress(self, category: str, completed: int, total: int) -> None:
        """Update progress for a migration category.

        Args:
            category: Category key (users, groups, applications, policies)
            completed: Number of items completed
            total: Total number of items
        """
        if category in self.status_card_labels:
            self._category_completed[category] = completed
            self._category_totals[category] = total
            label = self.status_card_labels[category]
            label.setText(f"{completed} / {total}")

    def set_active_categories(self, categories: dict[str, bool]) -> None:
        """Show/hide status cards based on selected categories.

        Args:
            categories: Dictionary mapping category keys to enabled status
        """
        active = {key for key, enabled in categories.items() if enabled}
        if not active:
            active = set(OBJECT_KEYS)

        self._active_categories = active

        for key, card in self.status_cards.items():
            visible = key in active
            card.setVisible(visible)

    def append_log(self, message: str) -> None:
        """Append a simple text message to the log (backward compatibility).

        Args:
            message: Log message to append
        """
        # For backward compatibility, treat as INFO level
        from datetime import datetime

        from ..logging_handler import LogEntry, LogLevel

        entry = LogEntry(
            timestamp=datetime.now(),
            level=LogLevel.INFO,
            category="general",
            message=message,
        )
        self.append_log_entry(entry.to_dict())

    def append_log_entry(self, entry_dict: dict) -> None:
        """Append a structured log entry.

        Args:
            entry_dict: Dictionary representation of LogEntry
        """
        # Add to deque (automatically limits to 100)
        self._log_entries.append(entry_dict)

        # Check if entry passes current filters
        level = entry_dict.get("level", "INFO")
        message = entry_dict.get("message", "")

        # Apply severity filter
        if self._current_filter != "all":
            if self._current_filter == "info" and level != "INFO":
                return
            if self._current_filter == "warning" and level != "WARNING":
                return
            if self._current_filter == "error" and level not in ("ERROR", "FATAL"):
                return

        # Apply search filter
        if self._search_text and self._search_text not in message.lower():
            return

        # Display the entry
        self._append_log_entry_to_view(entry_dict)

    @property
    def bulk_path(self) -> str | None:
        """Get the bulk export path."""
        return self._bulk_path

    def show_bulk_ready(self, path: str) -> None:
        """Show that bulk export is ready.

        Args:
            path: Path to the bulk export file
        """
        self._bulk_path = path
        self.open_folder_button.setVisible(True)
        self.append_log(f"Bulk upload CSV ready: {path}")
        self.finish_button.setVisible(True)
        self.finish_button.setEnabled(True)
