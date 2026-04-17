"""StickyFooter widget with navigation buttons."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton

from ...theme_manager import get_theme_manager


class StickyFooter(QFrame):
    """Footer with navigation buttons (Previous, Next, Load Profile)."""

    prev_clicked = Signal()
    next_clicked = Signal()
    load_profile_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = get_theme_manager()

        # Apply footer styling
        self._apply_footer_style()

        # Connect to theme changes
        self._theme.theme_changed.connect(self._apply_footer_style)

        layout = QHBoxLayout(self)
        padding = self._theme.get_spacing("md")
        layout.setContentsMargins(padding, padding, padding, padding)
        layout.setSpacing(self._theme.get_spacing("md"))

        # Left side: Load Profile button (secondary)
        self.load_profile_button = QPushButton("Load Profile")
        self.load_profile_button.clicked.connect(self.load_profile_clicked.emit)
        layout.addWidget(self.load_profile_button)

        layout.addStretch()

        # Right side: Previous and Next buttons
        self.prev_button = QPushButton("Previous")
        self.prev_button.clicked.connect(self.prev_clicked.emit)
        layout.addWidget(self.prev_button)

        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.next_clicked.emit)
        layout.addWidget(self.next_button)

        # Apply button styles via ThemeManager
        self._theme.theme_changed.connect(self._apply_button_styles)
        self._apply_button_styles()

    def _apply_footer_style(self) -> None:
        """Apply footer styling using theme colors."""
        surface = self._theme.get_color("surface")
        border = self._theme.get_color("border")
        shadow = self._theme.get_shadow("md")

        self.setStyleSheet(
            f"""
            QFrame {{
                background-color: {surface};
                border-top: 1px solid {border};
            }}
        """
        )

    def _apply_button_styles(self) -> None:
        """Apply button styling using ThemeManager."""
        if not hasattr(self, "next_button"):
            return
        # Next button is primary
        primary_style = self._theme.get_button_style("primary")
        self.next_button.setStyleSheet(primary_style)

        # Previous and Load Profile buttons are secondary
        secondary_style = self._theme.get_button_style("secondary")
        self.prev_button.setStyleSheet(secondary_style)
        self.load_profile_button.setStyleSheet(secondary_style)

    def set_prev_enabled(self, enabled: bool) -> None:
        """Enable or disable the Previous button."""
        self.prev_button.setEnabled(enabled)

    def set_next_enabled(self, enabled: bool) -> None:
        """Enable or disable the Next button."""
        self.next_button.setEnabled(enabled)

    def set_load_profile_enabled(self, enabled: bool) -> None:
        """Enable or disable the Load Profile button."""
        self.load_profile_button.setEnabled(enabled)
