"""Applications tab content."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ...theme_manager import get_theme_manager
from ..model import AnalysisModel
from ..utils import format_int, set_sticky
from ..widgets import Banner, CollapsibleSectionCard, SectionCard, StatCard, StatusPill
from .base import AnalysisTab


class AppsTab(AnalysisTab):
    """Application breakdown."""

    request_filter = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = get_theme_manager()

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.connectors_banner = Banner("warning", "", parent=self)
        self.connectors_banner.setVisible(False)
        root_layout.addWidget(self.connectors_banner)

        self.scroll = QScrollArea()
        root_layout.addWidget(self.scroll, 1)

        # Content widget with vertical stacking layout
        padding = self._theme.get_spacing("md")
        self.content = QWidget()
        self.main_layout = QVBoxLayout(self.content)
        self.main_layout.setContentsMargins(padding, padding, padding, padding)
        self.main_layout.setSpacing(self._theme.get_spacing("md"))

        set_sticky(self.scroll, self.content)

        # Migration Summary - always visible
        self.summary_card = SectionCard("Migration Summary")
        self.summary_card.set_grid_columns(3)
        self.main_layout.addWidget(self.summary_card)

        # Migration status pills (clickable)
        self.pill_container = QWidget()
        pill_layout = QHBoxLayout(self.pill_container)
        pill_layout.setContentsMargins(0, 0, 0, 0)
        pill_layout.setSpacing(self._theme.get_spacing("md"))
        pill_layout.addStretch()

        self.can_migrate_pill = StatusPill("success", "0 can auto-migrate", clickable=True)
        self.can_migrate_pill.clicked.connect(lambda: self.request_filter.emit("can_migrate"))
        pill_layout.addWidget(self.can_migrate_pill)

        self.need_review_pill = StatusPill("warning", "0 need manual review", clickable=True)
        self.need_review_pill.clicked.connect(lambda: self.request_filter.emit("need_review"))
        pill_layout.addWidget(self.need_review_pill)

        self.cannot_migrate_pill = StatusPill("danger", "0 cannot auto-migrate", clickable=True)
        self.cannot_migrate_pill.clicked.connect(lambda: self.request_filter.emit("cannot_migrate"))
        pill_layout.addWidget(self.cannot_migrate_pill)

        pill_layout.addStretch()

        self.main_layout.addWidget(self.pill_container)

        # Connector Coverage - collapsible, starts expanded (critical for migration planning)
        self.breakdown_card = CollapsibleSectionCard("Connector Coverage", collapsed=True)
        self.breakdown_card.set_grid_columns(3)
        self.main_layout.addWidget(self.breakdown_card)

        # Sign-on methods - collapsible, starts collapsed (technical detail)
        self.methods_card = CollapsibleSectionCard("Sign-on Methods", collapsed=True)
        self.methods_card.set_grid_columns(3)
        self.main_layout.addWidget(self.methods_card)

        # Connector Mapping Quality - collapsible, starts collapsed (detailed analysis)
        self.mapping_card = CollapsibleSectionCard("Connector Mapping Quality", collapsed=True)
        self.mapping_card.set_grid_columns(3)
        self.main_layout.addWidget(self.mapping_card)

        # Note label
        self.note_label = QLabel()
        self.note_label.setWordWrap(True)
        self.note_label.setVisible(False)
        self.main_layout.addWidget(self.note_label)
        self._theme.theme_changed.connect(self._apply_note_style)
        self._apply_note_style()

        self.main_layout.addStretch()

    def bind(self, model: AnalysisModel) -> None:
        """Populate app methods and migration status."""
        # Connector catalog banner
        connector_error = model.connectors.error if model.connectors else None
        if connector_error:
            self.connectors_banner.set_text(connector_error)
            self.connectors_banner.setVisible(True)
        else:
            self.connectors_banner.setVisible(False)

        total = model.apps_total or sum(model.apps_status.values())

        # Migration summary card
        self.summary_card.clear_cards()
        summary_metrics = [
            ("Total Apps", total),
            ("Auto-Migrate", model.apps_status.get("can_migrate", 0)),
            ("Need Review", model.apps_status.get("need_review", 0)),
            ("Unsupported", model.apps_status.get("cannot_migrate", 0)),
        ]
        for label, value in summary_metrics:
            self.summary_card.add_stat_card(StatCard(label, value, auto_pluralize=False))

        # Clear and populate sign-on methods
        self.methods_card.clear_cards()
        for label, value in model.apps_methods.items():
            pretty = label.upper()
            # Don't pluralize protocol names like SAML, OIDC
            card = StatCard(pretty, value, auto_pluralize=False)
            self.methods_card.add_stat_card(card)

        # Update migration status pills
        counts = model.apps_status
        self.can_migrate_pill.set_text(
            f"✅ {format_int(counts.get('can_migrate', 0))} can auto-migrate"
        )
        self.need_review_pill.set_text(
            f"⚠️ {format_int(counts.get('need_review', 0))} need manual review"
        )
        self.cannot_migrate_pill.set_text(
            f"✖️ {format_int(counts.get('cannot_migrate', 0))} cannot auto-migrate"
        )

        # Connector coverage breakdown
        self.breakdown_card.clear_cards()
        breakdown_metrics = [
            (
                "Connector Match",
                model.apps_breakdown.get("connector_matches", 0),
                "Mapped to catalog",
            ),
            ("Custom SSO", model.apps_breakdown.get("custom_sso", 0), "Use custom SAML/OIDC"),
            ("Manual Review", model.apps_breakdown.get("needs_review", 0), "Verify configuration"),
            ("Unsupported", model.apps_breakdown.get("unsupported", 0), "Recreate manually"),
        ]
        for label, value, caption in breakdown_metrics:
            self.breakdown_card.add_stat_card(
                StatCard(label, value, caption=caption, auto_pluralize=False)
            )

        # Mapping quality metrics
        self.mapping_card.clear_cards()
        mapping_metrics = [
            ("Exact Match", model.apps_mapping_quality.get("exact_matches", 0)),
            ("Fuzzy Match", model.apps_mapping_quality.get("fuzzy_matches", 0)),
            ("No Match", model.apps_mapping_quality.get("no_matches", 0)),
        ]
        for label, value in mapping_metrics:
            self.mapping_card.add_stat_card(StatCard(label, value, auto_pluralize=False))

        # Manual configuration note
        needs_attention = counts.get("need_review", 0) or counts.get("cannot_migrate", 0)
        if needs_attention:
            self.note_label.setText(
                "Applications requiring review or that cannot be auto-migrated will need "
                "manual configuration in OneLogin after migration."
            )
            self.note_label.setVisible(True)
            self._apply_note_style()
        else:
            self.note_label.setVisible(False)

    def _apply_note_style(self) -> None:
        """Reapply note styling on theme changes."""
        if not self.note_label.isVisible():
            # Styling applied on-demand in bind to avoid stale colors for hidden note.
            return
        warning_color = self._theme.get_color("warning")
        surface = self._theme.get_color("surface_elevated")
        border_radius = self._theme.get_radius("sm")
        padding = self._theme.get_spacing("md")
        self.note_label.setStyleSheet(
            f"""
            QLabel {{
                color: {warning_color};
                background-color: {surface};
                border-left: 3px solid {warning_color};
                border-radius: {border_radius}px;
                padding: {padding}px;
                font-size: 13px;
                font-weight: 600;
            }}
        """
        )
