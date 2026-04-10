"""Split button widget with primary action and menu."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QToolButton, QWidget

from ...theme_manager import get_theme_manager


class SplitButton(QWidget):
    """Composite widget combining a primary button with a dropdown menu."""

    triggered = Signal(str)

    def __init__(
        self,
        label: str,
        menu_items: Iterable[tuple[str, str]],
        parent=None,
        menu_label: str | None = None,
    ):
        super().__init__(parent)
        self._theme = get_theme_manager()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)  # Small gap between buttons

        self.primary_button = QPushButton(label)
        self.primary_button.setMinimumHeight(36)
        layout.addWidget(self.primary_button)

        self.menu_button = QToolButton()
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        if menu_label:
            # Use Unicode down arrow instead of Qt arrow for consistent sizing
            self.menu_button.setText(f"{menu_label}")
            self.menu_button.arrowType = "▼"
            self.menu_button.setMinimumWidth(130)
            self.menu_button.setMinimumHeight(36)  # Match primary button height
        else:
            self.menu_button.setArrowType(Qt.ArrowType.DownArrow)
            self.menu_button.setFixedWidth(30)
        layout.addWidget(self.menu_button)

        # Connect to theme changes
        self._theme.theme_changed.connect(self._apply_button_styles)
        self._apply_button_styles()

        self.menu = QMenu(self)
        for action_id, action_label in menu_items:
            action = self.menu.addAction(action_label)
            action.triggered.connect(lambda checked=False, aid=action_id: self.triggered.emit(aid))
        self.menu_button.setMenu(self.menu)

        self.primary_button.clicked.connect(lambda: self.triggered.emit("primary"))

    def _apply_button_styles(self) -> None:
        """Apply button styling using ThemeManager."""
        primary_style = self._theme.get_button_style("primary")
        self.primary_button.setStyleSheet(primary_style)

        # Style the menu button to match the primary button
        primary_color = self._theme.get_color("primary")
        primary_dark = self._theme.get_color("primary_dark")
        text_on_primary = self._theme.get_color("text_on_primary")
        border_radius = self._theme.get_radius("md")

        self.menu_button.setStyleSheet(
            f"""
            QToolButton {{
                background-color: {primary_color};
                color: {text_on_primary};
                border: none;
                border-radius: {border_radius}px;
                padding: 8px 12px;
                font-size: 14px;
                font-weight: 600;
            }}
            QToolButton:hover {{
                background-color: {primary_dark};
            }}
            QToolButton:pressed {{
                background-color: {primary_dark};
            }}
        """
        )

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable both buttons."""
        self.primary_button.setEnabled(enabled)
        self.menu_button.setEnabled(enabled)
