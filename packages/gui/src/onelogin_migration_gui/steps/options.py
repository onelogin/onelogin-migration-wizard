"""Migration options page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QWidget

from ..components import ModernButton, ModernCard, ModernCheckbox, ModernLineEdit
from .base import BasePage

if TYPE_CHECKING:  # pragma: no cover
    from .. import WizardState


class OptionsPage(BasePage):
    def __init__(self) -> None:
        super().__init__("Step 4 – Migration Options")

        # Configure body_layout directly for compact single-view layout - no scroll area needed
        self.body_layout.setSpacing(
            self.theme_manager.get_spacing("md")
        )  # Compact spacing between sections (16px)
        self.body_layout.setContentsMargins(
            self.theme_manager.get_spacing("lg"),  # left (24px)
            self.theme_manager.get_spacing("md"),  # top (16px)
            self.theme_manager.get_spacing("lg"),  # right (24px)
            self.theme_manager.get_spacing("md"),  # bottom (16px)
        )

        # Mode Options Card - Compact padding
        mode_card = ModernCard(
            title="Mode Options", accent_color="primary", elevated=True, padding="sm"
        )

        self.dry_run = ModernCheckbox("Enable dry run (no writes)")
        mode_card.add_widget(self.dry_run)

        # Add help text for dry run - clean, no background
        mode_card.add_widget(
            self._create_help_label("Test migration without making any changes to OneLogin")
        )

        self.verbose = ModernCheckbox("Verbose logging")
        mode_card.add_widget(self.verbose)

        # Add help text for verbose - clean, no background
        mode_card.add_widget(self._create_help_label("Enable detailed logging for troubleshooting"))

        self.body_layout.addWidget(mode_card)

        # Performance Options Card - Compact padding (only concurrency toggle; worker tuning is automatic)
        perf_card = ModernCard(
            title="Performance Options", accent_color="secondary", elevated=True, padding="sm"
        )

        self.concurrency = ModernCheckbox("Enable multithreading")
        perf_card.add_widget(self.concurrency)
        perf_card.add_widget(
            self._create_help_label(
                "Worker count and chunk sizing are auto-tuned; this toggle just turns concurrency on/off."
            )
        )

        self.body_layout.addWidget(perf_card)

        # Export Options Card - Compact padding
        export_card = ModernCard(
            title="Export Options", accent_color="info", elevated=True, padding="sm"
        )

        # Export directory label - compact
        dir_label = QLabel("Export directory:")

        def update_dir_label_style():
            dir_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self.theme_manager.get_color('text_primary')};
                    font-weight: 600;
                    font-size: 14px;
                    background-color: transparent;
                    margin-bottom: {self.theme_manager.get_spacing('xs')}px;
                }}
            """
            )

        update_dir_label_style()
        self.theme_manager.theme_changed.connect(update_dir_label_style)
        export_card.add_widget(dir_label)

        browse_row = QHBoxLayout()
        browse_row.setSpacing(self.theme_manager.get_spacing("sm"))

        self.export_directory = ModernLineEdit(placeholder="Select export directory...")
        self.export_directory.setMinimumWidth(350)  # Compact minimum width

        browse_button = ModernButton("Browse…", variant="ghost")
        browse_button.setFixedWidth(100)  # Compact button width

        browse_row.addWidget(self.export_directory, 1)  # Give it stretch
        browse_row.addWidget(browse_button)
        export_card.add_layout(browse_row)

        self.bulk_upload = ModernCheckbox("Generate bulk user upload CSV")
        export_card.add_widget(self.bulk_upload)

        # Add help text for bulk upload - clean, no background
        export_card.add_widget(
            self._create_help_label("Generate a CSV file for bulk user upload to OneLogin")
        )

        self.body_layout.addWidget(export_card)

        # Add stretch at the bottom to push content to top
        self.body_layout.addStretch()

        browse_button.clicked.connect(self._select_directory)

    def _create_help_label(self, text: str) -> QLabel:
        """Create a consistently styled help text label that updates with theme changes.

        This ensures help text has no background and uses proper theme colors,
        following the clean styling approach from welcome.py.

        Args:
            text: The help text to display

        Returns:
            QLabel: A fully configured label with theme-aware styling
        """
        label = QLabel(text)
        label.setWordWrap(True)

        def update_style():
            label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self.theme_manager.get_color('text_secondary')};
                    font-size: 12px;
                    font-style: italic;
                    background-color: transparent;
                    border: none;
                    margin-top: 2px;
                    margin-left: 26px;
                }}
            """
            )

        update_style()
        self.theme_manager.theme_changed.connect(update_style)
        return label

    def _select_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Select Export Directory", self.export_directory.text()
        )
        if directory:
            self.export_directory.setText(directory)

    def on_enter(self, state: WizardState) -> None:
        super().on_enter(state)
        self.dry_run.setChecked(bool(state.options.get("dry_run", True)))
        self.concurrency.setChecked(bool(state.options.get("concurrency_enabled", False)))
        self.export_directory.setText(state.options.get("export_directory", ""))
        self.bulk_upload.setChecked(bool(state.options.get("bulk_user_upload", False)))
        self.verbose.setChecked(bool(state.options.get("verbose", False)))

    def collect(self, state: WizardState) -> None:
        super().collect(state)
        # Preserve existing worker sizing; it's tuned automatically elsewhere
        max_workers = state.options.get("max_workers", 4)
        chunk_size = state.options.get("chunk_size", 200)
        state.options.update(
            {
                "dry_run": self.dry_run.isChecked(),
                "concurrency_enabled": self.concurrency.isChecked(),
                "max_workers": max_workers,
                "chunk_size": chunk_size,
                "export_directory": self.export_directory.text().strip(),
                "bulk_user_upload": self.bulk_upload.isChecked(),
                "verbose": self.verbose.isChecked(),
            }
        )

    def validate(self, state: WizardState) -> tuple[bool, str]:
        if not self.export_directory.text().strip():
            return False, "Specify an export directory for migration artifacts."
        return True, ""
