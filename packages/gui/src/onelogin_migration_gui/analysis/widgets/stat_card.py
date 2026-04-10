"""StatCard widget for presenting KPI metrics."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout

from ...theme_manager import ThemeMode, get_theme_manager
from ..utils import format_int, pluralize


class ValueLabel(QLabel):
    """Label for displaying large numeric values with themed styling."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop)
        self.setWordWrap(True)
        self.setFrameShape(QLabel.Shape.NoFrame)
        self.setFrameShadow(QLabel.Shadow.Plain)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.adjustSize()


class StatCard(QFrame):
    """Compact KPI card with themed styling."""

    def __init__(
        self,
        label: str,
        value: str | int,
        caption: str | None = None,
        auto_pluralize: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._theme = get_theme_manager()
        self._raw_label = label
        self._auto_pluralize = auto_pluralize
        self._raw_value = value

        self.setObjectName("StatCard")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(self)
        padding = 16
        layout.setContentsMargins(padding, padding, padding, padding)
        layout.setSpacing(8)

        formatted_value = format_int(value) if isinstance(value, int) else str(value)

        self.value_label = ValueLabel(formatted_value, self)
        self.value_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        layout.addWidget(self.value_label, 0)

        if auto_pluralize and isinstance(value, int):
            display_label = pluralize(label, value, include_count=False)
        else:
            display_label = label

        self.label_label = QLabel(display_label.upper())
        self.label_label.setProperty("class", "statLabel")
        self.label_label.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop)
        self.label_label.setWordWrap(True)
        self.label_label.setFrameShape(QLabel.Shape.NoFrame)
        self.label_label.setFrameShadow(QLabel.Shadow.Plain)
        self.label_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        layout.addWidget(self.label_label, 0)

        self.caption_label: QLabel | None = None
        if caption:
            self.caption_label = QLabel(caption)
            self.caption_label.setProperty("class", "statCaption")
            self.caption_label.setAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            self.caption_label.setFrameShape(QLabel.Shape.NoFrame)
            self.caption_label.setFrameShadow(QLabel.Shadow.Plain)
            self.caption_label.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
            layout.addWidget(self.caption_label, 0)

        self._apply_text_styles()
        self._apply_card_style()
        self._theme.theme_changed.connect(self._apply_text_styles)
        self._theme.theme_changed.connect(self._apply_card_style)

    def _apply_card_style(self) -> None:
        """Apply themed styling that adapts to light and dark modes."""
        mode = self._theme.current_mode
        background = (
            self._theme.get_color("surface_elevated")
            if mode == ThemeMode.LIGHT
            else self._theme.get_color("surface")
        )
        border = self._theme.get_color("border")
        value_color = self._theme.get_color("primary")
        label_color = self._theme.get_color("text_secondary")
        caption_color = self._theme.get_color("text_primary")
        value_font = 52 if mode == ThemeMode.DARK else 48
        label_font = 13
        caption_font = 12
        radius = 12 if mode == ThemeMode.LIGHT else 10

        combined_style = f"""
            QFrame#StatCard {{
                background-color: {background};
                border: 1px solid {border};
                border-radius: {radius}px;
            }}
            QLabel#valueLabel {{
                color: {value_color};
                font-size: {value_font}px;
                font-weight: 700;
                background-color: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }}
            QLabel#textLabel {{
                color: {label_color};
                font-size: {label_font}px;
                font-weight: 600;
                letter-spacing: 1px;
                background-color: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }}
            QLabel#captionLabel {{
                color: {caption_color};
                font-size: {caption_font}px;
                background-color: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }}
        """
        self.setStyleSheet(combined_style)

    def _apply_text_styles(self) -> None:
        """Set object names for stylesheet targeting."""
        self.value_label.setObjectName("valueLabel")
        self.label_label.setObjectName("textLabel")
        if self.caption_label:
            self.caption_label.setObjectName("captionLabel")

    def set_value(self, value: str | int, auto_format: bool = True) -> None:
        """Update the value, with optional auto-formatting and pluralization."""
        self._raw_value = value

        if auto_format and isinstance(value, int):
            formatted_value = format_int(value)
        else:
            formatted_value = str(value)

        self.value_label.setText(formatted_value)
        self.value_label.update()

        if self._auto_pluralize and isinstance(value, int):
            display_label = pluralize(self._raw_label, value, include_count=False)
            self.label_label.setText(display_label.upper())

    def set_label(self, label: str) -> None:
        """Update the label."""
        self._raw_label = label
        if self._auto_pluralize and isinstance(self._raw_value, int):
            display_label = pluralize(label, self._raw_value, include_count=False)
        else:
            display_label = label
        self.label_label.setText(display_label.upper())

    def set_caption(self, caption: str | None) -> None:
        """Update or set the caption."""
        if caption and not self.caption_label:
            self.caption_label = QLabel(caption)
            self.caption_label.setProperty("class", "statCaption")
            self.caption_label.setAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            # CRITICAL: Remove any frame from the caption label
            self.caption_label.setFrameShape(QLabel.Shape.NoFrame)
            self.caption_label.setFrameShadow(QLabel.Shadow.Plain)
            layout = self.layout()
            if isinstance(layout, QVBoxLayout):
                layout.addWidget(self.caption_label)
        if self.caption_label:
            self.caption_label.setVisible(bool(caption))
            if caption:
                self.caption_label.setText(caption)
