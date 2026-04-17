"""Summary page."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel

from ..components import ModernCard
from .base import BasePage

if TYPE_CHECKING:  # pragma: no cover
    from .. import WizardState


class SummaryPage(BasePage):
    def __init__(self) -> None:
        super().__init__("Step 5 – Review and Start Migration")

        # Set very compact spacing for the body layout
        self.body_layout.setSpacing(self.theme_manager.get_spacing("xs"))
        self.body_layout.setContentsMargins(
            self.theme_manager.get_spacing("lg"),  # left
            self.theme_manager.get_spacing("xs"),  # top - very compact
            self.theme_manager.get_spacing("lg"),  # right
            self.theme_manager.get_spacing("xs"),  # bottom - very compact
        )

        # Header - more compact
        self.header = QLabel("Review your migration configuration before starting")
        self.header.setWordWrap(True)
        self.body_layout.addWidget(self.header)

        # Connect theme changes to update all labels
        self.theme_manager.theme_changed.connect(self._update_theme_styles)

        # Create cards for different sections with extra compact padding
        self.source_card = ModernCard(
            title="Source Provider", accent_color="primary", elevated=True, padding="xs"
        )
        self.target_card = ModernCard(
            title="Target Provider", accent_color="success", elevated=True, padding="xs"
        )
        self.options_card = ModernCard(
            title="Migration Options", accent_color="info", elevated=True, padding="xs"
        )
        self.objects_card = ModernCard(
            title="Objects to Migrate", accent_color="secondary", elevated=True, padding="xs"
        )

        self.body_layout.addWidget(self.source_card)
        self.body_layout.addSpacing(self.theme_manager.get_spacing("xs"))
        self.body_layout.addWidget(self.target_card)
        self.body_layout.addSpacing(self.theme_manager.get_spacing("xs"))
        self.body_layout.addWidget(self.options_card)
        self.body_layout.addSpacing(self.theme_manager.get_spacing("xs"))
        self.body_layout.addWidget(self.objects_card)
        self.body_layout.addStretch()

        # Apply initial theme styles
        self._update_theme_styles()

    def _update_theme_styles(self) -> None:
        """Update all theme-dependent styles."""
        # Update header
        self.header.setStyleSheet(
            f"""
            QLabel {{
                font-size: 13px;
                color: {self.theme_manager.get_color('text_secondary')};
                margin-bottom: {self.theme_manager.get_spacing('xs')}px;
            }}
        """
        )

        # Update all info row labels and values
        for card in [self.source_card, self.target_card, self.options_card, self.objects_card]:
            # Find all labels with our custom properties
            for label in card.findChildren(QLabel):
                if label.property("info_label"):
                    label.setStyleSheet(
                        f"""
                        QLabel {{
                            color: {self.theme_manager.get_color('text_secondary')};
                            font-weight: 600;
                            font-size: 12px;
                            background: transparent;
                            border: none;
                            padding: 0px;
                            margin: 0px;
                        }}
                    """
                    )
                elif label.property("info_value"):
                    label.setStyleSheet(
                        f"""
                        QLabel {{
                            color: {self.theme_manager.get_color('text_primary')};
                            font-size: 12px;
                            background: transparent;
                            border: none;
                            padding: 0px;
                            margin: 0px;
                        }}
                    """
                    )

    def _add_info_row(self, card: ModernCard, label: str, value: str) -> None:
        """Add an information row to a card."""
        row_layout = QGridLayout()
        row_layout.setColumnStretch(0, 0)  # Label column: fixed width
        row_layout.setColumnStretch(1, 1)  # Value column: stretch
        row_layout.setSpacing(self.theme_manager.get_spacing("sm"))
        row_layout.setContentsMargins(0, 0, 0, 0)  # No extra margins
        row_layout.setVerticalSpacing(2)  # Very tight vertical spacing

        label_widget = QLabel(label)
        label_widget.setProperty("info_label", True)  # Tag for theme updates
        label_widget.setStyleSheet(
            f"""
            QLabel {{
                color: {self.theme_manager.get_color('text_secondary')};
                font-weight: 600;
                font-size: 12px;
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }}
        """
        )

        value_widget = QLabel(value)
        value_widget.setProperty("info_value", True)  # Tag for theme updates
        value_widget.setStyleSheet(
            f"""
            QLabel {{
                color: {self.theme_manager.get_color('text_primary')};
                font-size: 12px;
                background: transparent;
                border: none;
                padding: 0px;
                margin: 0px;
            }}
        """
        )
        value_widget.setWordWrap(True)

        row_layout.addWidget(label_widget, 0, 0, Qt.AlignmentFlag.AlignTop)
        row_layout.addWidget(value_widget, 0, 1, Qt.AlignmentFlag.AlignTop)

        card.add_layout(row_layout)

    def on_enter(self, state: WizardState) -> None:
        super().on_enter(state)

        # Clear previous content
        for card in [self.source_card, self.target_card, self.options_card, self.objects_card]:
            # Remove all widgets from card except title
            while card.content_layout.count() > 0:
                item = card.content_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    while item.layout().count() > 0:
                        subitem = item.layout().takeAt(0)
                        if subitem.widget():
                            subitem.widget().deleteLater()

        # Source Provider
        self._add_info_row(self.source_card, "Provider:", state.source_provider)
        self._add_info_row(
            self.source_card, "Subdomain:", state.source_settings.get("subdomain", "")
        )

        # Target Provider
        self._add_info_row(self.target_card, "Provider:", state.target_provider)
        self._add_info_row(
            self.target_card, "Subdomain:", state.target_settings.get("subdomain", "")
        )

        # Migration Options
        self._add_info_row(
            self.options_card, "Dry run:", "Yes" if state.options.get("dry_run") else "No"
        )
        self._add_info_row(
            self.options_card,
            "Multithreading:",
            "Yes" if state.options.get("concurrency_enabled") else "No",
        )
        self._add_info_row(
            self.options_card, "Worker threads:", str(state.options.get("max_workers", 4))
        )
        self._add_info_row(
            self.options_card, "Chunk size:", str(state.options.get("chunk_size", 200))
        )
        self._add_info_row(
            self.options_card, "Export directory:", state.options.get("export_directory", "")
        )
        self._add_info_row(
            self.options_card,
            "Bulk user upload:",
            "Yes" if state.options.get("bulk_user_upload") else "No",
        )

        # Objects to Migrate
        for key, enabled in state.objects.items():
            status_icon = "✓" if enabled else "✗"
            status_color = self.theme_manager.get_color("success" if enabled else "text_disabled")
            value_label = QLabel(f"{status_icon} {key.replace('_', ' ').title()}")
            value_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {status_color};
                    font-weight: 500;
                    font-size: 12px;
                    background: transparent;
                    border: none;
                    padding: 0px;
                    margin: 0px;
                }}
            """
            )
            self.objects_card.add_widget(value_label)
