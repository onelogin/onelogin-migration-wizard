"""CollapsibleSectionCard widget - expandable/collapsible section container."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QToolButton

from ...theme_manager import get_theme_manager
from .section_card import SectionCard


class CollapsibleSectionCard(SectionCard):
    """SectionCard with collapsible content controlled by a toggle button."""

    toggled = Signal(bool)  # Emits True when expanded, False when collapsed

    def __init__(
        self, title: str, help_tooltip: str | None = None, collapsed: bool = False, parent=None
    ):
        """Initialize collapsible section card.

        Args:
            title: Section title
            help_tooltip: Optional tooltip for help button
            collapsed: Whether to start collapsed (default: False)
            parent: Parent widget
        """
        super().__init__(title, help_tooltip, parent)
        self._theme = get_theme_manager()
        self._collapsed = collapsed

        # Create toggle button
        self.toggle_button = QToolButton()
        self.toggle_button.setText("▼" if not collapsed else "▶")
        self.toggle_button.setProperty("class", "toggleButton")
        self.toggle_button.setFixedSize(20, 20)
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.setToolTip("Expand" if collapsed else "Collapse")
        self.toggle_button.clicked.connect(self.toggle_collapsed)

        # Style the toggle button
        self._style_toggle_button()
        self._theme.theme_changed.connect(self._style_toggle_button)

        # Insert toggle button at the start of the header
        root_layout = self.layout()
        if root_layout and root_layout.count() > 0:
            header_layout = root_layout.itemAt(0).layout()
            if header_layout:
                # Insert at position 0 (before title)
                header_layout.insertWidget(0, self.toggle_button)

    def _style_toggle_button(self) -> None:
        """Style the toggle button using theme colors."""
        text_color = self._theme.get_color("text_primary")
        hover_color = self._theme.get_color("primary")

        self.toggle_button.setStyleSheet(
            f"""
            QToolButton {{
                background-color: transparent;
                color: {text_color};
                border: none;
                font-size: 12px;
                font-weight: bold;
            }}
            QToolButton:hover {{
                color: {hover_color};
            }}
        """
        )

    def _hide_content(self) -> None:
        """Hide all widgets in the grid."""
        for i in range(self.grid.count()):
            item = self.grid.itemAt(i)
            if item and item.widget():
                item.widget().setVisible(False)
        # Force layout recalculation
        self.grid.activate()
        self.updateGeometry()
        self.adjustSize()

    def _show_content(self) -> None:
        """Show all widgets in the grid."""
        for i in range(self.grid.count()):
            item = self.grid.itemAt(i)
            if item and item.widget():
                item.widget().setVisible(True)
        # Force layout recalculation
        self.grid.activate()
        self.updateGeometry()

    def toggle_collapsed(self) -> None:
        """Toggle the collapsed state of the section."""
        self._collapsed = not self._collapsed

        if self._collapsed:
            self._hide_content()
        else:
            self._show_content()

        self.toggle_button.setText("▼" if not self._collapsed else "▶")
        self.toggle_button.setToolTip("Collapse" if not self._collapsed else "Expand")
        self.toggled.emit(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        """Programmatically set the collapsed state.

        Args:
            collapsed: True to collapse, False to expand
        """
        if self._collapsed != collapsed:
            self.toggle_collapsed()

    def is_collapsed(self) -> bool:
        """Check if the section is currently collapsed.

        Returns:
            True if collapsed, False if expanded
        """
        return self._collapsed

    def _reflow_cards(self) -> None:
        """Override to apply collapsed state after cards are added to grid."""
        super()._reflow_cards()
        # Apply collapsed state after cards are in the grid
        if self._collapsed:
            for i in range(self.grid.count()):
                item = self.grid.itemAt(i)
                if item and item.widget():
                    item.widget().setVisible(False)
