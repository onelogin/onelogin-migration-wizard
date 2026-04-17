"""SectionCard widget containing stat card grids and optional header actions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
)

from ...theme_manager import get_theme_manager
from .stat_card import StatCard


class SectionCard(QFrame):
    """Reusable section container with header + grid of stat cards."""

    def __init__(self, title: str, help_tooltip: str | None = None, parent=None):
        super().__init__(parent)
        self._theme = get_theme_manager()
        self._columns = 3

        # Set size policy to allow vertical expansion
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Apply card styling via ThemeManager
        self._apply_card_style()

        # Connect to theme changes
        self._theme.theme_changed.connect(self._apply_card_style)

        padding = self._theme.get_spacing("sm")

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(padding, padding, padding, padding)
        root_layout.setSpacing(self._theme.get_spacing("md"))

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(self._theme.get_spacing("sm"))

        self.title_label = QLabel(title)
        self.title_label.setProperty("class", "sectionTitle")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        self.help_button: QToolButton | None = None
        if help_tooltip:
            self.help_button = QToolButton()
            self.help_button.setText("?")
            self.help_button.setProperty("class", "helpButton")
            self.help_button.setCursor(Qt.CursorShape.WhatsThisCursor)
            self.help_button.setToolTip(help_tooltip)
            self.help_button.setFixedSize(24, 24)
            # Style the help button
            self._style_help_button()
            self._theme.theme_changed.connect(self._style_help_button)
            header_layout.addWidget(self.help_button)

        root_layout.addLayout(header_layout)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        # Spacious grid gaps: 16px both horizontal and vertical
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(16)
        # Add the grid with stretch factor to fill available vertical space
        root_layout.addLayout(self.grid, 1)

        self._cards: list[StatCard] = []

    def _apply_card_style(self) -> None:
        """Apply card styling using ThemeManager."""
        card_style = self._theme.get_card_style(elevated=True, padding="md")
        self.setStyleSheet(card_style)

    def _style_help_button(self) -> None:
        """Style the help button using theme colors."""
        info_color = self._theme.get_color("info")
        info_light = self._theme.get_color("info_light")
        text_color = self._theme.get_color("text_primary")
        border_radius = self._theme.get_radius("round")

        if self.help_button:
            self.help_button.setStyleSheet(
                f"""
                QToolButton {{
                    background-color: {info_light};
                    color: {info_color};
                    border: 1px solid {info_color};
                    border-radius: {border_radius}px;
                    font-weight: bold;
                    font-size: 12px;
                }}
                QToolButton:hover {{
                    background-color: {info_color};
                    color: white;
                }}
            """
            )

    def add_stat_card(self, card: StatCard) -> None:
        """Append a stat card and refresh layout."""
        self._cards.append(card)
        self._reflow_cards()

    def clear_cards(self) -> None:
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()

    def set_grid_columns(self, columns: int) -> None:
        self._columns = max(1, columns)
        self._reflow_cards()

    def _reflow_cards(self) -> None:
        # Clear the grid
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)

        if not self._cards:
            return

        # Clear all previous stretch settings
        for i in range(self.grid.columnCount()):
            self.grid.setColumnStretch(i, 0)
        for i in range(self.grid.rowCount()):
            self.grid.setRowStretch(i, 0)

        # Track which rows we use
        rows_used = set()

        # Add cards to grid
        for index, card in enumerate(self._cards):
            row = index // self._columns
            col = index % self._columns
            self.grid.addWidget(card, row, col)
            rows_used.add(row)

        # Set column stretch to distribute width evenly across all columns
        for col in range(self._columns):
            self.grid.setColumnStretch(col, 1)

        # Set row stretch to 1 to expand rows and fill available space
        for row in rows_used:
            self.grid.setRowStretch(row, 1)

    def resizeEvent(self, event) -> None:  # noqa: D401
        """Adjust grid columns based on available width."""
        super().resizeEvent(event)
        # Note: Keeping the fixed column count set via set_grid_columns
        # The grid will automatically handle overflow with scroll if needed
