"""Modern UI components for the OneLogin Migration Wizard.

This module provides reusable, theme-aware UI components with a modern design:
- ModernCard: Card-based container with optional accent colors
- ModernButton: Styled button with multiple variants
- ModernLineEdit: Styled text input field
- ModernCheckbox: Styled checkbox with better visual feedback
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme_manager import ThemeMode, get_theme_manager


class ModernCard(QFrame):
    """Modern card component with theme-aware styling.

    Features:
    - Clean, elevated appearance with subtle shadows
    - Optional left-border accent color
    - Configurable padding
    - Automatic theme switching
    - Title and content sections

    Example:
        card = ModernCard(title="User Settings", accent_color="primary")
        card.add_widget(QLabel("Settings content here"))
    """

    def __init__(
        self,
        parent=None,
        title: str | None = None,
        accent_color: str | None = None,
        elevated: bool = True,
        padding: str = "lg",
    ):
        """Initialize modern card.

        Args:
            parent: Parent widget
            title: Optional card title
            accent_color: Optional left-border accent (e.g., 'primary', 'success')
            elevated: Whether to show elevated shadow
            padding: Padding size ('sm', 'md', 'lg')
        """
        super().__init__(parent)

        self.theme_manager = get_theme_manager()
        self.accent_color = accent_color
        self.elevated = elevated
        self.padding = padding

        # Set frame properties
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)

        # Create layout
        self.main_layout = QVBoxLayout(self)
        # Use tighter spacing for compact cards
        main_spacing = (
            self.theme_manager.get_spacing("xs")
            if padding == "xs"
            else self.theme_manager.get_spacing("md")
        )
        self.main_layout.setSpacing(main_spacing)
        self.main_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)

        # Add title if provided
        self.title_label = None
        if title:
            self.title_label = QLabel(title)
            title_typo = self.theme_manager.get_typography("h3")
            # Smaller title for compact cards
            title_size = 14 if padding == "xs" else title_typo["size"]
            title_margin = (
                self.theme_manager.get_spacing("xs")
                if padding == "xs"
                else self.theme_manager.get_spacing("sm")
            )
            self.title_label.setStyleSheet(
                f"""
                QLabel {{
                    font-size: {title_size}px;
                    font-weight: {title_typo['weight']};
                    color: {self.theme_manager.get_color('text_primary')} !important;
                    margin-bottom: {title_margin}px;
                    background: transparent;
                    border: none;
                }}
            """
            )
            self.main_layout.addWidget(self.title_label)

        # Content container
        self.content_layout = QVBoxLayout()
        # Use tighter spacing for compact cards
        content_spacing = (
            self.theme_manager.get_spacing("xs")
            if padding == "xs"
            else self.theme_manager.get_spacing("sm")
        )
        self.content_layout.setSpacing(content_spacing)
        self.content_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        self.main_layout.addLayout(self.content_layout)

        # Connect to theme changes
        self.theme_manager.theme_changed.connect(self._on_theme_changed)

        # Apply initial styling
        self._apply_theme()

    def add_widget(self, widget: QWidget) -> None:
        """Add a widget to the card's content area."""
        self.content_layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        """Add a layout to the card's content area."""
        self.content_layout.addLayout(layout)

    def _on_theme_changed(self, mode: ThemeMode) -> None:
        """Handle theme changes."""
        self._apply_theme()

    def _apply_theme(self) -> None:
        """Apply current theme styling to card."""
        # Use ThemeManager's card style generator
        card_style = self.theme_manager.get_card_style(
            accent_color=self.accent_color,
            elevated=self.elevated,
            padding=self.padding,
        )
        self.setStyleSheet(card_style)

        # Update title color if present
        if self.title_label:
            title_typo = self.theme_manager.get_typography("h3")
            # Apply same compact logic as init
            title_size = 14 if self.padding == "xs" else title_typo["size"]
            title_margin = (
                self.theme_manager.get_spacing("xs")
                if self.padding == "xs"
                else self.theme_manager.get_spacing("sm")
            )
            self.title_label.setStyleSheet(
                f"""
                QLabel {{
                    font-size: {title_size}px;
                    font-weight: {title_typo['weight']};
                    color: {self.theme_manager.get_color('text_primary')} !important;
                    margin-bottom: {title_margin}px;
                    background: transparent;
                    border: none;
                }}
            """
            )


class ModernButton(QPushButton):
    """Modern button component with theme-aware styling.

    Features:
    - Multiple variants: primary, secondary, ghost, danger
    - Smooth hover and press animations
    - Automatic theme switching
    - Consistent sizing and padding

    Example:
        btn = ModernButton("Save Changes", variant="primary")
        btn.clicked.connect(save_handler)
    """

    def __init__(
        self,
        text: str = "",
        parent=None,
        variant: str = "primary",
    ):
        """Initialize modern button.

        Args:
            text: Button text
            parent: Parent widget
            variant: Button variant ('primary', 'secondary', 'ghost', 'danger')
        """
        super().__init__(text, parent)

        self.theme_manager = get_theme_manager()
        self.variant = variant

        # Configure button
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Connect to theme changes
        self.theme_manager.theme_changed.connect(self._on_theme_changed)

        # Apply initial styling
        self._apply_theme()

    def set_variant(self, variant: str) -> None:
        """Change button variant and update styling."""
        self.variant = variant
        self._apply_theme()

    def _on_theme_changed(self, mode: ThemeMode) -> None:
        """Handle theme changes."""
        self._apply_theme()

    def _apply_theme(self) -> None:
        """Apply current theme styling to button."""
        button_style = self.theme_manager.get_button_style(variant=self.variant)
        self.setStyleSheet(button_style)


class ModernLineEdit(QLineEdit):
    """Modern text input field with theme-aware styling.

    Features:
    - Clean, minimal design
    - Focus state with colored border
    - Automatic theme switching
    - Placeholder text support

    Example:
        input_field = ModernLineEdit(placeholder="Enter your name")
    """

    def __init__(self, text: str = "", parent=None, placeholder: str = ""):
        """Initialize modern line edit.

        Args:
            text: Initial text
            parent: Parent widget
            placeholder: Placeholder text
        """
        super().__init__(text, parent)

        self.theme_manager = get_theme_manager()

        if placeholder:
            self.setPlaceholderText(placeholder)

        # Add these lines:
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Connect to theme changes
        self.theme_manager.theme_changed.connect(self._on_theme_changed)

        # Apply initial styling
        self._apply_theme()

    def _on_theme_changed(self, mode: ThemeMode) -> None:
        """Handle theme changes."""
        self._apply_theme()

    def _apply_theme(self) -> None:
        """Apply current theme styling to input."""
        input_style = self.theme_manager.get_input_style()
        # Ensure minimum height is set
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(input_style)


class ModernCheckbox(QCheckBox):
    """Modern checkbox with theme-aware styling.

    Features:
    - Larger, more visible checkbox
    - Smooth color transitions
    - Automatic theme switching
    - Better spacing and alignment

    Example:
        checkbox = ModernCheckbox("I agree to the terms")
    """

    # Class-level cache for stylesheet to avoid regenerating for every checkbox
    _stylesheet_cache = {}
    _cache_key = None

    def __init__(self, text: str = "", parent=None):
        """Initialize modern checkbox.

        Args:
            text: Checkbox label text
            parent: Parent widget
        """
        super().__init__(text, parent)

        self.theme_manager = get_theme_manager()

        # Configure checkbox
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Connect to theme changes
        # Use QueuedConnection to batch updates and prevent UI freezing
        self.theme_manager.theme_changed.connect(
            self._on_theme_changed, Qt.ConnectionType.QueuedConnection
        )

        # Apply initial styling
        self._apply_theme()

    # Note: __del__ removed - Qt handles signal disconnection automatically when widgets are destroyed
    # Explicit cleanup is done in _reset_selection_state() in base_table_manager.py

    def _on_theme_changed(self, mode: ThemeMode) -> None:
        """Handle theme changes - ONLY update if visible."""
        # OPTIMIZATION: Only update theme if widget is visible
        # This prevents updating hidden dialogs or off-screen widgets
        if not self.isVisible():
            # Mark that we need to update when shown
            self._theme_update_pending = True
            return

        # Clear cache when theme changes
        ModernCheckbox._stylesheet_cache.clear()
        ModernCheckbox._cache_key = None
        self._apply_theme()
        self._theme_update_pending = False

    def showEvent(self, event):
        """Handle widget show event - apply pending theme updates."""
        super().showEvent(event)
        # If theme changed while hidden, update now that we're visible
        if getattr(self, "_theme_update_pending", False):
            ModernCheckbox._stylesheet_cache.clear()
            ModernCheckbox._cache_key = None
            self._apply_theme()
            self._theme_update_pending = False

    def _apply_theme(self) -> None:
        """Apply current theme styling to checkbox - EXACT copy from welcome.py."""
        primary = self.theme_manager.get_color("primary")
        text_secondary = self.theme_manager.get_color("text_secondary")
        border = self.theme_manager.get_color("border")
        surface_elevated = self.theme_manager.get_color("surface_elevated")

        # Create cache key based on theme colors
        cache_key = f"{primary}_{text_secondary}_{border}_{surface_elevated}"

        # Use cached stylesheet if available
        if cache_key == ModernCheckbox._cache_key and cache_key in ModernCheckbox._stylesheet_cache:
            self.setStyleSheet(ModernCheckbox._stylesheet_cache[cache_key])
            return

        # EXACT styling from welcome.py - Qt will render its default checkmark
        # Note: QCheckBox background is transparent to match table cell background
        checkbox_style = f"""
            QCheckBox {{
                color: {text_secondary};
                font-size: 13px;
                spacing: 12px;
                background-color: transparent;
            }}
            QCheckBox::indicator {{
                width: 22px;
                height: 22px;
                border: 2px solid {border};
                border-radius: 3px;
                background: {surface_elevated};
            }}
            QCheckBox::indicator:hover {{
                border-color: {primary};
                background: rgba(100, 181, 246, 0.05);
            }}
            QCheckBox::indicator:checked {{
                background: {primary};
                border-color: {primary};
            }}
        """

        # Cache the stylesheet
        ModernCheckbox._stylesheet_cache[cache_key] = checkbox_style
        ModernCheckbox._cache_key = cache_key

        self.setStyleSheet(checkbox_style)


__all__ = [
    "ModernCard",
    "ModernButton",
    "ModernLineEdit",
    "ModernCheckbox",
]
