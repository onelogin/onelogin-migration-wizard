"""Users tab content - reorganized with theme integration."""

from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from ...theme_manager import get_theme_manager
from ..model import AnalysisModel
from ..utils import set_sticky
from ..widgets import SectionCard, StatCard
from .base import AnalysisTab


class UsersTab(AnalysisTab):
    """User activity and security metrics."""

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
        main_layout.setSpacing(self._theme.get_spacing("lg"))

        # Section 1: License & Activity
        self.license_section = SectionCard("License & Activity")
        self.license_section.set_grid_columns(3)
        main_layout.addWidget(self.license_section)

        # Section 2: Security State
        self.security_section = SectionCard("Security State")
        self.security_section.set_grid_columns(3)
        main_layout.addWidget(self.security_section)

        main_layout.addStretch()

        set_sticky(self.scroll, self.content)

    def bind(self, model: AnalysisModel) -> None:
        """Populate user metrics."""
        # Clear existing cards
        self.license_section.clear_cards()
        self.security_section.clear_cards()

        # License & Activity section
        license_metrics = [
            ("Active/Licensed", model.users_license.get("active", 0)),
            ("Inactive/Unlicensed", model.users_license.get("inactive", 0)),
            ("90+ Days Since Login", model.users_license.get("stale", 0)),
        ]
        for label, value in license_metrics:
            self.license_section.add_stat_card(StatCard(label, value, auto_pluralize=False))

        # Security State section
        security_metrics = [
            ("Locked", model.users_security.get("locked", 0)),
            ("Password Expired", model.users_security.get("password_expired", 0)),
            ("Suspended", model.users_security.get("suspended", 0)),
            ("Admins", model.users_security.get("admins", 0)),
        ]
        for label, value in security_metrics:
            self.security_section.add_stat_card(StatCard(label, value, auto_pluralize=False))
