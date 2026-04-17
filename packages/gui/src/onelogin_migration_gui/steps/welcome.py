"""Welcome page with license acceptance requirements."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
)

from ..components import ModernButton
from ..helpers import ThemeToggle, add_branding, load_logo, resource_path
from ..theme_manager import ThemeMode, get_theme_manager
from .base import BasePage

if TYPE_CHECKING:  # pragma: no cover
    from .. import WizardState

_LICENSE_CANDIDATES = [
    "src/onelogin_migration_tool/assets/LICENSE",
    "src/onelogin_migration_tool/assets/LICENSE.txt",
    "LICENSE",
]


class LicenseDialog(QDialog):
    """Simple dialog to display the full license text with theme support."""

    def __init__(self, license_text: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("License Agreement")

        from ..theme_manager import get_theme_manager

        self.theme_manager = get_theme_manager()

        layout = QVBoxLayout(self)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QTextEdit.NoWrap)
        self.view.setPlainText(license_text)
        layout.addWidget(self.view)

        close_btn = ModernButton("Close", variant="primary")
        close_btn.clicked.connect(self.accept)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)
        self.resize(640, 480)

        # Apply theme
        self.theme_manager.theme_changed.connect(self._apply_theme)
        self._apply_theme()

    def _apply_theme(self):
        """Apply current theme to the dialog."""
        bg = self.theme_manager.get_color("background")
        surface = self.theme_manager.get_color("surface")
        text = self.theme_manager.get_color("text_primary")
        border = self.theme_manager.get_color("border")

        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {bg};
            }}
        """
        )

        self.view.setStyleSheet(
            f"""
            QTextEdit {{
                background-color: {surface};
                color: {text};
                font-family: 'Menlo', 'Courier New', monospace;
                font-size: 11pt;
                padding: 12px;
                border: 1px solid {border};
            }}
        """
        )


class WelcomePage(BasePage):
    """Initial wizard page with clean hero section and license acknowledgement."""

    def __init__(self) -> None:
        self.suppress_brand_logo = True
        super().__init__("Welcome")
        self._scrolled = False
        self._license_text: str = ""
        self._license_path: Path | None = None
        self._license_dialog: LicenseDialog | None = None

        # Configure main layout with proper sizing
        self.body_layout.setSpacing(0)
        self.body_layout.setContentsMargins(40, 20, 40, 20)

        # Set proper size policy for responsive behavior
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Theme toggle button in top-left corner
        theme_toggle_row = QHBoxLayout()
        theme_toggle = ThemeToggle(self)
        theme_toggle_row.addWidget(theme_toggle)
        theme_toggle_row.addStretch(1)
        self.body_layout.addLayout(theme_toggle_row)

        # Logo as the hero element (clean and focused)
        self.large_logo_label = QLabel()
        self.large_logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.large_logo_label.setMaximumSize(450, 225)  # Slightly larger, more prominent
        self.large_logo_label.setMinimumSize(360, 180)
        self.large_logo_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._using_text_logo = False
        large_logo = load_logo((450, 225))
        if not large_logo.isNull():
            # Scale to fit within constraints while maintaining aspect ratio
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

        # Add logo as the hero element
        self.body_layout.addWidget(self.large_logo_label, 0, Qt.AlignmentFlag.AlignCenter)

        # Generous spacing between logo and license card
        self.body_layout.addSpacing(50)

        # License section - appropriately sized card (not too wide, focused reading area)
        license_card = QGroupBox("License Agreement")
        license_card.setObjectName("LicenseCard")
        license_card.setMaximumWidth(700)  # Appropriate width for comfortable license reading
        license_card.setMinimumWidth(500)  # Don't let it get too narrow
        license_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        card_layout = QVBoxLayout(license_card)
        card_layout.setSpacing(0)  # Manual spacing control
        card_layout.setContentsMargins(24, 28, 24, 24)  # Comfortable padding
        card_layout.setSizeConstraint(
            QVBoxLayout.SizeConstraint.SetDefaultConstraint
        )  # Allow responsive resizing

        # License text view - appropriately sized for license content
        self.license_view = QTextEdit()
        self.license_view.setReadOnly(True)
        self.license_view.setMinimumHeight(240)  # Comfortable reading height
        self.license_view.setMaximumHeight(240)
        self.license_view.setObjectName("LicensePreview")
        self.license_view.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth
        )  # Wrap at widget width
        self.license_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )  # No horizontal scroll
        self.license_view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )  # Vertical scroll as needed
        self.license_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # Add license view with stretch factor 0 (don't let it expand)
        card_layout.addWidget(self.license_view, 0)

        # Spacing before bottom row
        card_layout.addSpacing(20)

        # Bottom row: checkbox (left) and button (right) on same horizontal line
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(16)
        bottom_row.setContentsMargins(0, 0, 0, 0)  # No internal margins

        # Acceptance checkbox (left-aligned)
        self.accept_checkbox = QCheckBox(
            "I accept the terms and conditions, including anonymized telemetry (no PII)"
        )
        self.accept_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        bottom_row.addWidget(self.accept_checkbox)

        # Spacer to push button to the right
        bottom_row.addStretch(1)

        # View full license button (right-aligned)
        self.view_full_button = QPushButton("View Full License")
        self.view_full_button.setEnabled(False)
        self.view_full_button.setCursor(Qt.CursorShape.PointingHandCursor)
        bottom_row.addWidget(self.view_full_button)

        card_layout.addLayout(bottom_row)

        # Add license card to layout (centered)
        self.body_layout.addWidget(license_card, 0, Qt.AlignmentFlag.AlignCenter)

        # Bottom stretch for optical centering (2:3 ratio creates ~40/60 split)
        # This positions content slightly above center (classic optical balance)
        self.body_layout.addStretch(3)

        add_branding(self)  # ensure branding overlays applied

        # Connect signals
        scrollbar = self.license_view.verticalScrollBar()
        scrollbar.valueChanged.connect(self._on_scroll)
        scrollbar.rangeChanged.connect(self._on_scroll)
        self.accept_checkbox.toggled.connect(lambda _: self.completeChanged.emit())
        self.view_full_button.clicked.connect(self._open_license_dialog)

        # Connect theme changes
        self.theme_manager.theme_changed.connect(self._apply_theme)

        self._load_license()
        self._apply_theme()

    def _open_license_dialog(self) -> None:
        # Always show the dialog - it provides a better user experience
        # and ensures the user can actually read the full license text
        if not self._license_text:
            return

        if self._license_dialog is None:
            dialog = LicenseDialog(self._license_text, self)
            dialog.setModal(False)
            dialog.setAttribute(Qt.WA_DeleteOnClose, True)
            dialog.destroyed.connect(self._clear_license_dialog)
            self._license_dialog = dialog

        self._license_dialog.show()
        self._license_dialog.raise_()
        self._license_dialog.activateWindow()

    def _clear_license_dialog(self) -> None:
        self._license_dialog = None

    def _apply_theme(self) -> None:
        """Apply current theme to all welcome page components."""
        # Check if widgets have been created yet (called from BasePage.__init__)
        license_card = self.findChild(QGroupBox, "LicenseCard")
        if not license_card:
            # Widgets not created yet, will be called again after __init__
            return

        # Get theme colors
        surface = self.theme_manager.get_color("surface")
        background = self.theme_manager.get_color("background")
        text_primary = self.theme_manager.get_color("text_primary")
        text_secondary = self.theme_manager.get_color("text_secondary")
        border = self.theme_manager.get_color("border")
        primary = self.theme_manager.get_color("primary")
        primary_hover = self.theme_manager.get_color("primary_light")

        # Style the license card (GroupBox)
        surface_elevated = self.theme_manager.get_color("surface_elevated")
        license_card_style = f"""
            QGroupBox#LicenseCard {{
                font-size: 15px;
                font-weight: 600;
                color: {text_primary};
                border: 1px solid {border};
                border-left: 4px solid {primary};
                border-radius: 4px;
                background-color: {surface_elevated};
                padding: 20px;
                margin-top: 12px;
            }}
            QGroupBox#LicenseCard::title {{
                subcontrol-origin: margin;
                left: 20px;
                padding: 0 8px;
                background-color: {surface_elevated};
            }}
        """

        # Style the license text view (appropriately sized for comfortable reading)
        license_view_style = f"""
            QTextEdit#LicensePreview {{
                background-color: {background};
                color: {text_primary};
                font-family: 'Menlo', 'Courier New', monospace;
                font-size: 10pt;
                padding: 14px 18px;
                border: 1px solid {border};
                border-radius: 4px;
            }}
        """

        # Style the "View Full License" button (clearly visible ghost style)
        button_style = f"""
            QPushButton {{
                background-color: {surface_elevated};
                color: {primary};
                border: 2px solid {primary};
                padding: 10px 24px;
                border-radius: 5px;
                font-size: 13px;
                font-weight: 600;
                min-height: 20px;
            }}
            QPushButton:hover {{
                background-color: rgba(100, 181, 246, 0.15);
                border-color: {primary_hover};
                color: {primary_hover};
            }}
            QPushButton:pressed {{
                background-color: rgba(100, 181, 246, 0.25);
                border-color: {primary};
            }}
            QPushButton:disabled {{
                color: {self.theme_manager.get_color('text_disabled')};
                border: 2px solid {border};
                background-color: {surface_elevated};
            }}
        """

        # Style the checkbox (larger, clearer target)
        checkbox_style = f"""
            QCheckBox {{
                color: {text_secondary};
                font-size: 13px;
                spacing: 12px;
                background-color: {surface_elevated};
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

        # Apply all styles (safe now that we've checked widgets exist)
        license_card.setStyleSheet(license_card_style)
        self.license_view.setStyleSheet(license_view_style)
        self.view_full_button.setStyleSheet(button_style)
        self.accept_checkbox.setStyleSheet(checkbox_style)
        self._update_text_logo_style()

    def _update_text_logo_style(self) -> None:
        """Style the fallback text logo using the current theme."""
        if not getattr(self, "_using_text_logo", False):
            return
        self.large_logo_label.setStyleSheet(
            f"""
            font-size: 36px;
            font-weight: 300;
            color: {self.theme_manager.get_color('primary')};
        """
        )

    def _load_license(self) -> None:
        """Populate the inline preview and enable fallbacks."""

        for relative_path in _LICENSE_CANDIDATES:
            path = resource_path(relative_path)
            if not path.exists():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            self._license_text = text
            self._license_path = path
            self.license_view.setPlainText(text)
            self.view_full_button.setEnabled(True)
            return

        # Fallback when no license could be loaded
        self._license_text = ""
        self._license_path = None
        self.license_view.setHtml(
            "<div style='color:#bbbbbb; font-size:10pt; text-align:center;"
            " padding: 24px;'>License file could not be loaded.</div>"
        )
        self.view_full_button.setEnabled(False)

    def _on_scroll(self, *_args) -> None:
        scrollbar = self.license_view.verticalScrollBar()
        max_value = scrollbar.maximum()
        self._scrolled = max_value == 0 or scrollbar.value() >= max_value
        self.completeChanged.emit()

    def can_proceed(self, state: WizardState) -> bool:
        if self.accept_checkbox.isChecked():
            # Initialize telemetry consent on license acceptance
            self._initialize_telemetry_consent()
        return self.accept_checkbox.isChecked()

    def validate(self, state: WizardState) -> tuple[bool, str]:
        if self.accept_checkbox.isChecked():
            # Ensure telemetry consent is recorded
            self._initialize_telemetry_consent()
            return True, ""
        return False, "Please accept the terms to continue."

    def _initialize_telemetry_consent(self) -> None:
        """Record user's telemetry consent via license acceptance.

        This is called when the user accepts the license agreement, which includes
        consent to anonymized telemetry collection as described in Section 6.
        """
        try:
            import logging
            from datetime import datetime

            from onelogin_migration_core.db import get_database_manager

            logger = logging.getLogger(__name__)

            # Use DatabaseManager for user-specific data (not the bundled catalog)
            db_manager = get_database_manager()

            # Check if consent already recorded
            cursor = db_manager.user_conn.execute(
                "SELECT installation_id FROM telemetry_settings WHERE enabled = 1"
            )
            existing = cursor.fetchone()

            if existing:
                logger.debug("Telemetry consent already recorded")
                return

            # Get or create installation ID
            installation_id = self._get_installation_id()

            # Record consent in user database
            db_manager.user_conn.execute(
                """
                INSERT OR REPLACE INTO telemetry_settings
                (enabled, user_consent_date, anonymized, installation_id)
                VALUES (1, ?, 1, ?)
            """,
                (datetime.now().isoformat(), installation_id),
            )
            db_manager.user_conn.commit()

            logger.info(
                "Telemetry consent granted via license acceptance (installation_id: %s...)",
                installation_id[:8],
            )

        except Exception as e:
            # Telemetry consent failures should not block the wizard
            import logging

            logging.getLogger(__name__).warning(
                "Failed to record telemetry consent (non-fatal): %s", e
            )

    def _get_installation_id(self) -> str:
        """Get or create anonymous installation ID (UUID).

        This UUID is used to track patterns across migrations without identifying
        the user or organization. It's stored locally and never transmitted.

        Returns:
            Installation ID (UUID format)
        """
        import uuid
        from pathlib import Path

        id_file = Path.home() / ".onelogin-migration" / ".installation_id"

        if id_file.exists():
            try:
                return id_file.read_text().strip()
            except Exception:
                pass  # Will regenerate below

        # Generate new UUID (not linked to user identity)
        installation_id = str(uuid.uuid4())

        try:
            id_file.parent.mkdir(parents=True, exist_ok=True)
            id_file.write_text(installation_id)
            id_file.chmod(0o600)  # User read/write only
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("Could not save installation ID (non-fatal): %s", e)

        return installation_id

    def on_enter(self, state: WizardState) -> None:
        super().on_enter(state)
        self.accept_checkbox.setChecked(False)
        self._scrolled = False
        self.license_view.verticalScrollBar().setValue(0)
        self.completeChanged.emit()
