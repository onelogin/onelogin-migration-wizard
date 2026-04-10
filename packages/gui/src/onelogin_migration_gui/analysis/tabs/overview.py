"""Overview tab content - simplified to show only top-level KPIs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout

from ...theme_manager import get_theme_manager
from ..model import AnalysisModel
from ..widgets import SectionCard, StatCard
from .base import AnalysisTab


class OverviewTab(AnalysisTab):
    """Top-level overview showing only essential KPIs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = get_theme_manager()

        # Direct layout - no scroll area
        main_layout = QVBoxLayout(self)
        padding = self._theme.get_spacing("md")
        main_layout.setContentsMargins(padding, padding, padding, padding)
        main_layout.setSpacing(self._theme.get_spacing("lg"))

        # Source hostname label
        self.source_label = QLabel()
        self.source_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        font_size = self._theme.get_typography("h3")["size"]
        text_color = self._theme.get_color("text_secondary")
        self.source_label.setStyleSheet(
            f"font-size: {font_size}px; color: {text_color}; font-weight: 500;"
        )
        self._theme.theme_changed.connect(self._update_source_label_style)
        main_layout.addWidget(self.source_label, 0)

        # Single section card with top KPIs (2 rows × 3 columns)
        self.kpi_section = SectionCard("Key Performance Indicators")
        self.kpi_section.set_grid_columns(3)
        # Give the section a large stretch factor to fill remaining space
        main_layout.addWidget(self.kpi_section, 1)

    def _update_source_label_style(self) -> None:
        """Update source label styling on theme change."""
        font_size = self._theme.get_typography("h3")["size"]
        text_color = self._theme.get_color("text_secondary")
        self.source_label.setStyleSheet(
            f"font-size: {font_size}px; color: {text_color}; font-weight: 500;"
        )

    def bind(self, model: AnalysisModel) -> None:
        """Populate overview with top-level KPIs only."""
        self.source_label.setText(f"Source: {model.source}")

        self.kpi_section.clear_cards()

        # Show only the 6 essential KPIs in 2 rows × 3 columns
        top_kpis = [
            ("Users", model.overview.get("users", 0)),
            ("Apps", model.overview.get("apps", 0)),
            ("Groups", model.overview.get("groups", 0)),
            ("Policies", model.overview.get("policies", 0)),
            ("MFAs", model.overview.get("mfa", 0)),
            ("Directories", model.overview.get("directories", 0)),
        ]

        for label, value in top_kpis:
            self.kpi_section.add_stat_card(StatCard(label, value, auto_pluralize=False))
