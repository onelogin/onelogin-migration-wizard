"""Theme management system for the OneLogin Migration Wizard.

Provides light/dark theme support with comprehensive color palettes,
typography scales, spacing systems, and component styling templates.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication


class ThemeMode(Enum):
    """Available theme modes."""

    LIGHT = "light"
    DARK = "dark"


class ThemeManager(QObject):
    """Manages application theming with light/dark mode support.

    Signals:
        theme_changed: Emitted when theme changes, passes new ThemeMode
    """

    theme_changed = Signal(ThemeMode)

    # Color Palettes
    COLORS_LIGHT = {
        # Primary colors(Based on Brand Guidelines within OI)
        "primary": "#04aada",
        "primary_light": "#40535d",
        "primary_dark": "#162c36",
        # Secondary colors
        "secondary": "#3f2c69",
        "secondary_light": "#77c8b3",
        "secondary_dark": "#82a7c5",
        # Semantic colors
        "success": "#2e7d32",
        "success_light": "#81c784",
        "warning": "#f57c00",
        "warning_light": "#ffb74d",
        "error": "#c62828",
        "error_light": "#e57373",
        "info": "#0288d1",
        "info_light": "#4fc3f7",
        # Neutral colors
        "neutral_900": "#1a1a1a",
        "neutral_700": "#666666",
        "neutral_500": "#999999",
        "neutral_300": "#cccccc",
        "neutral_100": "#f5f5f5",
        # Surface colors
        "background": "#fafafa",
        "surface": "#ffffff",
        "surface_elevated": "#ffffff",
        # Text colors
        "text_primary": "#1a1a1a",
        "text_secondary": "#666666",
        "text_disabled": "#999999",
        "text_on_primary": "#ffffff",
        # Border colors
        "border": "#e0e0e0",
        "border_focus": "#1976d2",
        "divider": "#e0e0e0",
    }

    COLORS_DARK = {
        # Primary colors
        "primary": "#04aada",
        "primary_light": "#40535d",
        "primary_dark": "#2b566a",
        # Secondary colors
        "secondary": "#3f2c69",
        "secondary_light": "#77c8b3",
        "secondary_dark": "#82a7c5",
        # Semantic colors
        "success": "#81c784",
        "success_light": "#a5d6a7",
        "warning": "#ffb74d",
        "warning_light": "#ffcc80",
        "error": "#e57373",
        "error_light": "#ef9a9a",
        "info": "#4fc3f7",
        "info_light": "#81d4fa",
        # Neutral colors
        "neutral_100": "#1a1a1a",
        "neutral_300": "#2d2d2d",
        "neutral_500": "#555555",
        "neutral_700": "#bbbbbb",
        "neutral_900": "#f5f5f5",
        # Surface colors
        "background": "#1F1F1F",
        "surface": "#1e1e1e",
        "surface_elevated": "#2d2d2d",
        # Text colors
        "text_primary": "#f5f5f5",
        "text_secondary": "#bbbbbb",
        "text_disabled": "#777777",
        "text_on_primary": "#1a1a1a",
        # Border colors
        "border": "#3d3d3d",
        "border_focus": "#64b5f6",
        "divider": "#3d3d3d",
    }

    # Typography Scale
    TYPOGRAPHY = {
        "h1": {"size": 32, "weight": 700, "line_height": 1.2},
        "h2": {"size": 24, "weight": 700, "line_height": 1.3},
        "h3": {"size": 16, "weight": 600, "line_height": 1.4},
        "body": {"size": 13, "weight": 400, "line_height": 1.5},
        "caption": {"size": 11, "weight": 400, "line_height": 1.4},
        "button": {"size": 13, "weight": 600, "line_height": 1.0},
    }

    # Spacing System (in pixels)
    SPACING = {
        "xs": 4,
        "sm": 8,
        "md": 16,
        "lg": 24,
        "xl": 32,
        "xxl": 48,
    }

    # Border Radius
    RADIUS = {
        "sm": 2,
        "md": 4,
        "lg": 8,
        "xl": 12,
        "round": 9999,
    }

    # Shadows
    SHADOWS = {
        "none": "none",
        "sm": "0 1px 2px 0 rgba(0, 0, 0, 0.05)",
        "md": "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)",
        "lg": "0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)",
        "xl": "0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)",
    }

    _instance = None

    def __new__(cls):
        """Singleton pattern - only one ThemeManager instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize theme manager with saved or default theme."""
        if hasattr(self, "_initialized"):
            return
        super().__init__()
        self._initialized = True
        self._settings = QSettings("OneLogin", "MigrationWizard")
        self._current_mode = self._load_saved_theme()

    def _load_saved_theme(self) -> ThemeMode:
        """Load saved theme preference from settings, or detect system theme."""
        saved = self._settings.value("theme/mode", None)

        # If user has a saved preference, use it
        if saved:
            try:
                return ThemeMode(saved)
            except ValueError:
                pass  # Fall through to system detection

        # Otherwise, detect system theme
        return self._detect_system_theme()

    def _detect_system_theme(self) -> ThemeMode:
        """Detect the system's current theme preference.

        Returns:
            ThemeMode.DARK if system is in dark mode, otherwise ThemeMode.LIGHT
        """
        try:
            app = QGuiApplication.instance()
            if app:
                # PySide6 6.5+ has colorScheme() method
                style_hints = app.styleHints()
                if hasattr(style_hints, "colorScheme"):
                    color_scheme = style_hints.colorScheme()
                    if color_scheme == Qt.ColorScheme.Dark:
                        return ThemeMode.DARK
                    elif color_scheme == Qt.ColorScheme.Light:
                        return ThemeMode.LIGHT
        except Exception:
            pass  # Fall back to light mode if detection fails

        # Default to light mode if detection fails
        return ThemeMode.LIGHT

    def _save_theme(self, mode: ThemeMode) -> None:
        """Save theme preference to settings."""
        self._settings.setValue("theme/mode", mode.value)

    @property
    def current_mode(self) -> ThemeMode:
        """Get current theme mode."""
        return self._current_mode

    def switch_theme(self, mode: ThemeMode | None = None) -> None:
        """Switch to specified theme or toggle between light/dark.

        Args:
            mode: Theme to switch to. If None, toggles current theme.
        """
        if mode is None:
            # Toggle
            mode = ThemeMode.DARK if self._current_mode == ThemeMode.LIGHT else ThemeMode.LIGHT

        if mode != self._current_mode:
            self._current_mode = mode
            self._save_theme(mode)
            self.theme_changed.emit(mode)

    def get_color(self, color_name: str) -> str:
        """Get color value for current theme.

        Args:
            color_name: Name of color from palette (e.g., 'primary', 'surface')

        Returns:
            Hex color string (e.g., '#1976d2')
        """
        palette = self.COLORS_DARK if self._current_mode == ThemeMode.DARK else self.COLORS_LIGHT
        return palette.get(color_name, palette["primary"])

    def get_qcolor(self, color_name: str) -> QColor:
        """Get QColor object for current theme.

        Args:
            color_name: Name of color from palette

        Returns:
            QColor object
        """
        return QColor(self.get_color(color_name))

    def get_typography(self, style: str) -> dict[str, Any]:
        """Get typography settings for a style.

        Args:
            style: Typography style name (e.g., 'h1', 'body', 'button')

        Returns:
            Dictionary with 'size', 'weight', 'line_height'
        """
        return self.TYPOGRAPHY.get(style, self.TYPOGRAPHY["body"]).copy()

    def get_spacing(self, size: str) -> int:
        """Get spacing value.

        Args:
            size: Spacing size name ('xs', 'sm', 'md', 'lg', 'xl', 'xxl')

        Returns:
            Spacing value in pixels
        """
        return self.SPACING.get(size, self.SPACING["md"])

    def get_radius(self, size: str) -> int:
        """Get border radius value.

        Args:
            size: Radius size name ('sm', 'md', 'lg', 'xl', 'round')

        Returns:
            Radius value in pixels
        """
        return self.RADIUS.get(size, self.RADIUS["md"])

    def get_shadow(self, size: str) -> str:
        """Get box shadow CSS value.

        Args:
            size: Shadow size name ('none', 'sm', 'md', 'lg', 'xl')

        Returns:
            CSS box-shadow value
        """
        return self.SHADOWS.get(size, self.SHADOWS["none"])

    def get_card_style(
        self, accent_color: str | None = None, elevated: bool = False, padding: str = "md"
    ) -> str:
        """Generate stylesheet for card component.

        Args:
            accent_color: Left border accent color name (e.g., 'primary', 'success')
            elevated: Whether to show elevated shadow
            padding: Padding size ('sm', 'md', 'lg')

        Returns:
            Complete QSS stylesheet string
        """
        bg = self.get_color("surface_elevated" if elevated else "surface")
        border_color = self.get_color("border")
        text_color = self.get_color("text_primary")
        shadow = self.get_shadow("md" if elevated else "sm")
        pad = self.get_spacing(padding)
        radius = self.get_radius("md")

        accent_style = ""
        if accent_color:
            accent = self.get_color(accent_color)
            accent_style = f"border-left: 4px solid {accent};"

        return f"""
            QFrame {{
                background-color: {bg};
                border: 1px solid {border_color};
                border-radius: {radius}px;
                {accent_style}
                padding: {pad}px;
            }}
        """

    def get_button_style(self, variant: str = "primary") -> str:
        """Generate stylesheet for button component.

        Args:
            variant: Button variant ('primary', 'secondary', 'ghost', 'danger')

        Returns:
            Complete QSS stylesheet string
        """
        radius = self.get_radius("md")
        padding_h = self.get_spacing("md")
        padding_v = self.get_spacing("sm")

        if variant == "primary":
            bg = self.get_color("primary")
            bg_hover = self.get_color("primary_dark")
            text = self.get_color("text_on_primary")
            border = "none"
        elif variant == "secondary":
            bg = self.get_color("secondary")
            bg_hover = self.get_color("secondary_dark")
            text = self.get_color("text_on_primary")
            border = "none"
        elif variant == "danger":
            bg = self.get_color("error")
            bg_hover = self.get_color("error_light")
            text = self.get_color("text_on_primary")
            border = "none"
        else:  # ghost
            bg = "transparent"
            bg_hover = self.get_color(
                "neutral_100" if self._current_mode == ThemeMode.LIGHT else "neutral_300"
            )
            text = self.get_color("text_primary")
            border = f"1px solid {self.get_color('border')}"

        return f"""
            QPushButton {{
                background-color: {bg};
                color: {text};
                border: {border};
                border-radius: {radius}px;
                padding: {padding_v}px {padding_h}px;
                font-weight: 600;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {bg_hover};
            }}
            QPushButton:pressed {{
                background-color: {bg};
                padding-top: {padding_v + 1}px;
                padding-bottom: {padding_v - 1}px;
            }}
            QPushButton:disabled {{
                background-color: {self.get_color('neutral_100')};
                color: {self.get_color('text_disabled')};
                border: {border};
            }}
        """

    def get_input_style(self) -> str:
        """Generate stylesheet for input components (QLineEdit, QTextEdit, etc).

        Returns:
            Complete QSS stylesheet string
        """
        bg = self.get_color("surface")
        border = self.get_color("border")
        border_focus = self.get_color("border_focus")
        text = self.get_color("text_primary")
        radius = self.get_radius("md")
        padding = self.get_spacing("sm")

        return f"""
            QLineEdit, QTextEdit, QSpinBox {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: {radius}px;
                padding: {padding}px;
                color: {text};
                font-size: 13px;
            }}
            QLineEdit:focus, QTextEdit:focus, QSpinBox:focus {{
                border: 2px solid {border_focus};
            }}
            QLineEdit:disabled, QTextEdit:disabled, QSpinBox:disabled {{
                background-color: {self.get_color('neutral_100')};
                color: {self.get_color('text_disabled')};
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                background-color: {bg};
                border: 1px solid {border};
                width: 16px;
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
                background-color: {self.get_color('surface_elevated')};
            }}
            QSpinBox::up-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-bottom: 4px solid {text};
                width: 0;
                height: 0;
            }}
            QSpinBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid {text};
                width: 0;
                height: 0;
            }}
            QComboBox {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: {radius}px;
                padding: {padding}px;
                padding-right: 30px;
                color: {text};
                font-size: 13px;
            }}
            QComboBox:focus {{
                border: 2px solid {border_focus};
            }}
            QComboBox:disabled {{
                background-color: {self.get_color('neutral_100')};
                color: {self.get_color('text_disabled')};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 30px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {text};
                width: 0;
                height: 0;
                margin-right: 10px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {bg};
                border: 1px solid {border};
                selection-background-color: {border_focus};
                selection-color: {text};
                color: {text};
                outline: none;
            }}
            QComboBox QAbstractItemView::item {{
                padding: {padding}px;
                min-height: 30px;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {self.get_color('neutral_100')};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {border_focus};
                color: {self.get_color('text_on_primary')};
            }}
        """


# Global instance
_theme_manager = None


def get_theme_manager() -> ThemeManager:
    """Get the global ThemeManager instance."""
    global _theme_manager
    if _theme_manager is None:
        _theme_manager = ThemeManager()
    return _theme_manager
