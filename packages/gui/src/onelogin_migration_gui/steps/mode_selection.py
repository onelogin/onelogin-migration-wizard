"""Mode selection page - choose between Discovery and Migration workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from ..helpers import ThemeToggle, add_branding, load_logo
from ..theme_manager import ThemeMode, get_theme_manager
from .base import BasePage

if TYPE_CHECKING:  # pragma: no cover
    from .. import WizardState


class ModeCard(QPushButton):
    """Large clickable card for mode selection."""

    def __init__(self, title: str, description: str, mode: str, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.theme_manager = get_theme_manager()
        self._is_selected = False

        # Configure button
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(180)
        self.setMaximumWidth(400)

        # Create internal layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # Title
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        title_label.setObjectName("ModeCardTitle")
        layout.addWidget(title_label)

        # Description
        desc_label = QLabel(description)
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setWordWrap(True)
        desc_label.setObjectName("ModeCardDescription")
        layout.addWidget(desc_label)

        # Connect theme changes
        self.theme_manager.theme_changed.connect(self._apply_theme)
        self.toggled.connect(self._on_toggled)

        # Apply initial theme
        self._apply_theme()

    def _on_toggled(self, checked: bool):
        """Handle toggle state change."""
        self._is_selected = checked
        self._apply_theme()

    def _apply_theme(self):
        """Apply current theme styling to the card."""
        bg = self.theme_manager.get_color("surface")
        border = self.theme_manager.get_color("border")
        primary = self.theme_manager.get_color("primary")
        text_primary = self.theme_manager.get_color("text_primary")
        text_secondary = self.theme_manager.get_color("text_secondary")

        # Different styling based on selection state
        if self._is_selected:
            border_color = primary
            border_width = "2px"
            background = self.theme_manager.get_color("surface_variant")
        else:
            border_color = border
            border_width = "1px"
            background = bg

        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {background};
                border: {border_width} solid {border_color};
                border-radius: 8px;
                padding: 0px;
            }}
            QPushButton:hover {{
                border-color: {primary};
                background-color: {self.theme_manager.get_color("surface_variant")};
            }}
            QPushButton:pressed {{
                background-color: {self.theme_manager.get_color("surface_variant")};
            }}
            QLabel#ModeCardTitle {{
                font-size: 18px;
                font-weight: 600;
                color: {text_primary};
                background: transparent;
                border: none;
            }}
            QLabel#ModeCardDescription {{
                font-size: 14px;
                color: {text_secondary};
                background: transparent;
                border: none;
            }}
        """
        )


class ModeSelectionPage(BasePage):
    """Initial page for selecting Discovery or Migration mode."""

    mode_changed = Signal(str)

    def __init__(self) -> None:
        self.suppress_brand_logo = True
        super().__init__("Choose Your Workflow")
        self._selected_mode: str = "migration"

        # Configure main layout
        self.body_layout.setSpacing(0)
        self.body_layout.setContentsMargins(40, 20, 40, 20)

        # Set proper size policy
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Theme toggle button in top-left corner
        theme_toggle_row = QHBoxLayout()
        theme_toggle = ThemeToggle(self)
        theme_toggle_row.addWidget(theme_toggle)
        theme_toggle_row.addStretch(1)
        self.body_layout.addLayout(theme_toggle_row)

        # Logo as the hero element
        self.large_logo_label = QLabel()
        self.large_logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.large_logo_label.setMaximumSize(450, 225)
        self.large_logo_label.setMinimumSize(360, 180)
        self.large_logo_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._using_text_logo = False
        large_logo = load_logo((450, 225))
        if not large_logo.isNull():
            scaled_logo = large_logo.scaled(
                450,
                225,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.large_logo_label.setPixmap(scaled_logo)
        else:
            self._using_text_logo = True
            self.large_logo_label.setText("OneLogin Migration Wizard")
            self._update_text_logo_style()

        # Connect theme change signal to update logo
        theme_manager = get_theme_manager()

        def update_large_logo(mode: ThemeMode):
            new_logo = load_logo((450, 225), mode)
            if not new_logo.isNull():
                scaled_logo = new_logo.scaled(
                    450,
                    225,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.large_logo_label.setPixmap(scaled_logo)
                self._using_text_logo = False
            else:
                self._using_text_logo = True
                self.large_logo_label.clear()
                self.large_logo_label.setText("OneLogin Migration Wizard")
                self._update_text_logo_style()

        theme_manager.theme_changed.connect(update_large_logo)
        if self._using_text_logo:
            theme_manager.theme_changed.connect(lambda *_: self._update_text_logo_style())

        # Add top stretch for optical centering
        self.body_layout.addStretch(2)

        # Add logo
        self.body_layout.addWidget(self.large_logo_label, 0, Qt.AlignmentFlag.AlignCenter)

        # Spacing
        self.body_layout.addSpacing(40)

        # Subtitle
        subtitle = QLabel("Select the workflow that best fits your needs")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setObjectName("ModeSelectionSubtitle")
        subtitle.setStyleSheet(
            f"""
            QLabel {{
                font-size: 16px;
                color: {theme_manager.get_color('text_secondary')};
            }}
        """
        )
        theme_manager.theme_changed.connect(
            lambda: subtitle.setStyleSheet(
                f"""
                QLabel {{
                    font-size: 16px;
                    color: {theme_manager.get_color('text_secondary')};
                }}
            """
            )
        )
        self.body_layout.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignCenter)

        # Spacing
        self.body_layout.addSpacing(30)

        # Mode selection cards
        cards_row = QHBoxLayout()
        cards_row.setSpacing(24)

        # Discovery mode card
        self.discovery_card = ModeCard(
            "Discovery",
            "Analyze your IAM environment",
            "discovery",
        )
        self.discovery_card.clicked.connect(lambda: self._select_mode("discovery"))
        cards_row.addWidget(self.discovery_card, 1)

        # Migration mode card
        self.migration_card = ModeCard(
            "Migration",
            "Analyze & Migrate to OneLogin",
            "migration",
        )
        self.migration_card.clicked.connect(lambda: self._select_mode("migration"))
        self.migration_card.setChecked(True)  # Default selection
        cards_row.addWidget(self.migration_card, 1)

        self.body_layout.addLayout(cards_row)

        # Bottom stretch for optical centering
        self.body_layout.addStretch(3)

        add_branding(self)

    def _update_text_logo_style(self):
        """Update text logo styling based on current theme."""
        theme_manager = get_theme_manager()
        text_color = theme_manager.get_color("text_primary")
        self.large_logo_label.setStyleSheet(
            f"""
            QLabel {{
                font-size: 32px;
                font-weight: 600;
                color: {text_color};
            }}
        """
        )

    def _select_mode(self, mode: str):
        """Handle mode selection."""
        self._selected_mode = mode

        # Update card states
        self.discovery_card.setChecked(mode == "discovery")
        self.migration_card.setChecked(mode == "migration")

        # Emit signal that mode changed
        self.mode_changed.emit(mode)

        # Emit completion signal to enable Next button
        self.completeChanged.emit()

    def can_proceed(self, state: WizardState) -> bool:
        """Always allow proceeding (a mode is always selected)."""
        return True

    def validate(self, state: WizardState) -> tuple[bool, str]:
        """Validate mode selection (always valid as a mode is always selected)."""
        return True, ""

    def collect(self, state: WizardState) -> None:
        """Store selected mode in wizard state."""
        super().collect(state)
        state.mode = self._selected_mode

    def on_enter(self, state: WizardState) -> None:
        """Initialize page with current mode."""
        super().on_enter(state)
        self._selected_mode = state.mode
        self._select_mode(state.mode)
