"""Base classes shared by all wizard pages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QVBoxLayout, QWizardPage

from ..helpers import add_branding
from ..theme_manager import ThemeMode, get_theme_manager

if TYPE_CHECKING:  # pragma: no cover - type hinting only
    from .. import WizardState


class BasePage(QWizardPage):
    """Common foundation for wizard pages with branding decorations and theme support."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setTitle(title)
        self._state: WizardState | None = None

        # Initialize theme manager
        self.theme_manager = get_theme_manager()

        # Set up layouts
        self.body_layout = QVBoxLayout()
        container = QVBoxLayout()
        container.addLayout(self.body_layout)
        self.setLayout(container)

        # Add branding (logo and theme toggle)
        add_branding(self)

        # Connect to theme changes
        self.theme_manager.theme_changed.connect(self._on_theme_changed)

        # Apply initial theme
        self._apply_theme()

    # These hooks mirror the previous QWidget-based implementation
    def on_enter(self, state: WizardState) -> None:  # pragma: no cover - UI hook
        self._state = state

    def collect(self, state: WizardState) -> None:  # pragma: no cover - UI hook
        self._state = state

    def can_proceed(self, state: WizardState) -> bool:
        return True

    def validate(self, state: WizardState) -> tuple[bool, str]:
        """Validate page state before proceeding. Override in subclasses."""
        return True, ""

    # QWizard integration
    def isComplete(self) -> bool:  # pragma: no cover - Qt infrastructure
        if self._state is None:
            return super().isComplete()
        return self.can_proceed(self._state)

    # Theme integration
    def _on_theme_changed(self, mode: ThemeMode) -> None:
        """Handle theme changes."""
        self._apply_theme()

    def _apply_theme(self) -> None:
        """Apply current theme to the page.

        This provides base page styling. Subclasses can override to add
        custom theme-aware styling.
        """
        bg_color = self.theme_manager.get_color("background")
        text_color = self.theme_manager.get_color("text_primary")

        # Apply base page styling
        self.setStyleSheet(
            f"""
            QWizardPage {{
                background-color: {bg_color};
                color: {text_color};
            }}
            QLabel {{
                color: {text_color};
            }}
        """
        )
