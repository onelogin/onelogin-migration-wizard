"""Status pill widget for summarizing app migration readiness."""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from ...theme_manager import get_theme_manager

Kind = Literal["success", "warning", "danger"]


class StatusPill(QFrame):
    """Rounded indicator pill driven by the active theme."""

    clicked = Signal(str)  # Emits the kind when clicked

    def __init__(
        self,
        kind: Kind,
        text: str,
        icon: QIcon | None = None,
        clickable: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._theme = get_theme_manager()
        self._kind = kind
        self._clickable = clickable

        # Apply theme-based styling
        self._apply_pill_style()

        # Connect to theme changes
        self._theme.theme_changed.connect(self._apply_pill_style)

        self.setFixedHeight(32)
        self.setMinimumWidth(180)

        if clickable:
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        layout = QHBoxLayout(self)
        v_padding = self._theme.get_spacing("sm")
        h_padding = self._theme.get_spacing("lg")
        layout.setContentsMargins(h_padding, v_padding, h_padding, v_padding)
        layout.setSpacing(self._theme.get_spacing("sm"))

        self.icon_label: QLabel | None = None
        if icon:
            self.icon_label = QLabel()
            self.icon_label.setPixmap(icon.pixmap(16, 16))
            layout.addWidget(self.icon_label)

        self.text_label = QLabel(text)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_label.setProperty("class", "pillLabel")
        layout.addWidget(self.text_label)

    def _apply_pill_style(self) -> None:
        """Apply pill styling using theme colors."""
        # Map kind to theme colors
        color_map = {
            "success": ("success", "success_light"),
            "warning": ("warning", "warning_light"),
            "danger": ("error", "error_light"),
        }

        main_color_key, light_color_key = color_map.get(self._kind, ("primary", "primary_light"))
        main_color = self._theme.get_color(main_color_key)
        light_color = self._theme.get_color(light_color_key)
        border_radius = self._theme.get_radius("round")

        hover_style = ""
        if self._clickable:
            hover_style = f"""
            QFrame:hover {{
                background-color: {main_color};
                color: white;
            }}
            QFrame:hover QLabel {{
                color: white;
            }}
            """

        self.setStyleSheet(
            f"""
            QFrame {{
                background-color: {light_color};
                border: 2px solid {main_color};
                border-radius: {border_radius}px;
            }}
            {hover_style}
            QLabel {{
                background-color: transparent;
                border: none;
                color: {main_color};
                font-weight: 700;
                font-size: 14px;
            }}
        """
        )

    def mousePressEvent(self, event) -> None:
        """Handle click events if clickable."""
        if self._clickable:
            self.clicked.emit(self._kind)
        super().mousePressEvent(event)

    def set_text(self, text: str) -> None:
        """Update the pill text."""
        self.text_label.setText(text)

    def set_icon(self, icon: QIcon | None) -> None:
        """Update or set the icon."""
        if icon:
            if not self.icon_label:
                self.icon_label = QLabel()
                self.layout().insertWidget(0, self.icon_label)
            self.icon_label.setPixmap(icon.pixmap(16, 16))
            self.icon_label.setVisible(True)
        elif self.icon_label:
            self.icon_label.setVisible(False)

    def set_clickable(self, clickable: bool) -> None:
        """Enable or disable clickability."""
        self._clickable = clickable
        if clickable:
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self._apply_pill_style()
