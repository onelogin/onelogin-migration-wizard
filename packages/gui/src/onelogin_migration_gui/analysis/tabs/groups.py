"""Groups tab content - with DataTable for top groups."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from ...theme_manager import get_theme_manager
from ..model import AnalysisModel
from ..utils import set_sticky
from ..widgets import DataTable, SectionCard, StatCard
from .base import AnalysisTab


class GroupsTab(AnalysisTab):
    """Group breakdown and top groups table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = get_theme_manager()

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        root_layout.addWidget(self.scroll, 1)

        self.content = QWidget()
        padding = self._theme.get_spacing("md")
        main_layout = QVBoxLayout(self.content)
        main_layout.setContentsMargins(padding, padding, padding, padding)
        main_layout.setSpacing(self._theme.get_spacing("md"))

        # Group summary stats
        self.summary_section = SectionCard("Group Summary")
        self.summary_section.set_grid_columns(3)
        main_layout.addWidget(self.summary_section)

        # Top groups table label
        table_label = QLabel("Top Groups by Size")
        font_size = self._theme.get_typography("h3")["size"]
        text_color = self._theme.get_color("text_primary")
        table_label.setStyleSheet(
            f"font-size: {font_size}px; color: {text_color}; font-weight: 600; margin-top: 8px;"
        )
        self._theme.theme_changed.connect(lambda: self._update_table_label_style(table_label))
        main_layout.addWidget(table_label)

        # Top groups table (name left-aligned, members right-aligned)
        self.top_groups_table = DataTable(
            headers=["Group Name", "Members"], numeric_columns=[1]  # Members column is numeric
        )
        self.top_groups_table.setMinimumHeight(300)
        main_layout.addWidget(self.top_groups_table)

        main_layout.addStretch()

        set_sticky(self.scroll, self.content)

    def _update_table_label_style(self, label: QLabel) -> None:
        """Update table label styling on theme change."""
        font_size = self._theme.get_typography("h3")["size"]
        text_color = self._theme.get_color("text_primary")
        label.setStyleSheet(
            f"font-size: {font_size}px; color: {text_color}; font-weight: 600; margin-top: 8px;"
        )

    def bind(self, model: AnalysisModel) -> None:
        """Populate group metrics and top groups table."""
        # Clear and populate summary
        self.summary_section.clear_cards()
        metrics = [
            ("Total Groups", model.groups.get("total", 0)),
            ("Nested", model.groups.get("nested", 0)),
            ("Assigned", model.groups.get("assigned", 0)),
            ("Unassigned", model.groups.get("unassigned", 0)),
            ("Automation Rules", model.groups.get("rules", 0)),
        ]
        for label, value in metrics:
            self.summary_section.add_stat_card(StatCard(label, value, auto_pluralize=False))

        # Populate top groups table
        self.top_groups_table.clear_data()
        for group in model.top_groups:
            self.top_groups_table.add_row([group.name, group.members])
