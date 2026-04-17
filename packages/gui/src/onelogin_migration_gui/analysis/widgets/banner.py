"""Banner widget for displaying status messages with theme integration."""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from ...theme_manager import get_theme_manager

Kind = Literal["success", "info", "warning", "error"]


class Banner(QFrame):
    """Themed banner for displaying status messages with optional auto-hide."""

    def __init__(
        self,
        kind: Kind,
        text: str,
        icon: QIcon | None = None,
        auto_hide_ms: int | None = None,
        parent=None,
    ):
        """
        Initialize the banner.

        Args:
            kind: Banner type (success, info, warning, error)
            text: Message text to display
            icon: Optional icon to display before text
            auto_hide_ms: If set, banner will auto-hide after this many milliseconds
            parent: Parent widget
        """
        super().__init__(parent)
        self._theme = get_theme_manager()
        self._kind = kind

        # Apply theme-based styling
        self._apply_banner_style()

        # Connect to theme changes
        self._theme.theme_changed.connect(self._apply_banner_style)

        # Set fixed height for conciseness
        self.setFixedHeight(40)

        layout = QHBoxLayout(self)
        h_padding = self._theme.get_spacing("md")
        v_padding = self._theme.get_spacing("sm")
        layout.setContentsMargins(h_padding, v_padding, h_padding, v_padding)
        layout.setSpacing(self._theme.get_spacing("sm"))

        self.icon_label: QLabel | None = None
        if icon:
            self.icon_label = QLabel()
            self.icon_label.setPixmap(icon.pixmap(20, 20))
            layout.addWidget(self.icon_label)

        self.text_label = QLabel(text)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.text_label.setWordWrap(True)
        self.text_label.setProperty("class", "bannerText")
        layout.addWidget(self.text_label)

        layout.addStretch()

        # Setup auto-hide timer if specified
        if auto_hide_ms:
            QTimer.singleShot(auto_hide_ms, self.hide)

    def _apply_banner_style(self) -> None:
        """Apply banner styling using theme colors."""
        # Map kind to theme colors
        color_map = {
            "success": ("success", "success_light"),
            "info": ("info", "info_light"),
            "warning": ("warning", "warning_light"),
            "error": ("error", "error_light"),
        }

        main_color_key, light_color_key = color_map.get(self._kind, ("info", "info_light"))
        main_color = self._theme.get_color(main_color_key)
        light_color = self._theme.get_color(light_color_key)
        border_radius = self._theme.get_radius("lg")

        self.setStyleSheet(
            f"""
            QFrame {{
                background-color: {light_color};
                border: 1px solid {main_color};
                border-radius: {border_radius}px;
            }}
            QLabel {{
                background-color: transparent;
                color: {main_color};
                border: none;
                font-size: 13px;
                font-weight: 600;
            }}
        """
        )

    def set_text(self, text: str) -> None:
        """Update the banner text."""
        self.text_label.setText(text)

    def set_icon(self, icon: QIcon | None) -> None:
        """Update or set the icon."""
        if icon:
            if not self.icon_label:
                self.icon_label = QLabel()
                self.layout().insertWidget(0, self.icon_label)
            self.icon_label.setPixmap(icon.pixmap(20, 20))
            self.icon_label.setVisible(True)
        elif self.icon_label:
            self.icon_label.setVisible(False)
