"""Discovery tab - comprehensive environment overview matching Excel report layout."""

from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from ...theme_manager import get_theme_manager
from ..model import AnalysisModel
from ..utils import set_sticky
from ..widgets import CollapsibleSectionCard, SectionCard, StatCard
from .base import AnalysisTab


class DiscoveryTab(AnalysisTab):
    """Discovery Report tab with Excel-style comprehensive overview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = get_theme_manager()

        # Root layout
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        # Scrollable content area
        self.scroll = QScrollArea()
        root_layout.addWidget(self.scroll, 1)

        # Content widget with vertical stacking layout
        self.content = QWidget()
        padding = self._theme.get_spacing("md")
        self.main_layout = QVBoxLayout(self.content)
        self.main_layout.setContentsMargins(padding, padding, padding, padding)
        self.main_layout.setSpacing(self._theme.get_spacing("md"))

        # Build sections - all full-width, stacked vertically
        self._build_summary_section()
        self._build_applications_section()
        self._build_users_section()
        self._build_user_policies_section()
        self._build_app_policies_section()
        self._build_custom_attributes_section()
        self._build_groups_section()
        self._build_mfa_section()
        self._build_directories_section()

        self.main_layout.addStretch()

        # Configure scroll area
        set_sticky(self.scroll, self.content)

    def _build_summary_section(self) -> None:
        """Build Discovery Report Summary section (top-level counts)."""
        self.summary_section = SectionCard("Discovery Report Summary")
        self.summary_section.set_grid_columns(3)
        self.main_layout.addWidget(self.summary_section)

    def _build_applications_section(self) -> None:
        """Build Applications breakdown section (collapsible, starts collapsed)."""
        self.apps_section = CollapsibleSectionCard("Applications", collapsed=True)
        self.apps_section.set_grid_columns(3)
        self.main_layout.addWidget(self.apps_section)

    def _build_users_section(self) -> None:
        """Build Users section (collapsible, starts collapsed)."""
        self.users_section = CollapsibleSectionCard("Users", collapsed=True)
        self.users_section.set_grid_columns(3)
        self.main_layout.addWidget(self.users_section)

    def _build_user_policies_section(self) -> None:
        """Build User Security Policies section (collapsible, starts collapsed)."""
        self.user_policies_section = CollapsibleSectionCard(
            "User Security Policies", collapsed=True
        )
        self.user_policies_section.set_grid_columns(2)
        self.main_layout.addWidget(self.user_policies_section)

    def _build_app_policies_section(self) -> None:
        """Build App Security Policies section (collapsible, starts collapsed)."""
        self.app_policies_section = CollapsibleSectionCard("App Security Policies", collapsed=True)
        self.app_policies_section.set_grid_columns(2)
        self.main_layout.addWidget(self.app_policies_section)

    def _build_custom_attributes_section(self) -> None:
        """Build Custom Attributes section (collapsible, starts collapsed)."""
        self.custom_attrs_section = CollapsibleSectionCard("Custom Attributes", collapsed=True)
        self.custom_attrs_section.set_grid_columns(2)
        self.main_layout.addWidget(self.custom_attrs_section)

    def _build_groups_section(self) -> None:
        """Build Groups section (collapsible, starts collapsed)."""
        self.groups_section = CollapsibleSectionCard("Groups", collapsed=True)
        self.groups_section.set_grid_columns(2)
        self.main_layout.addWidget(self.groups_section)

    def _build_mfa_section(self) -> None:
        """Build Multi-Factor section (collapsible, starts collapsed)."""
        self.mfa_section = CollapsibleSectionCard("Multi-Factor", collapsed=True)
        self.mfa_section.set_grid_columns(2)
        self.main_layout.addWidget(self.mfa_section)

    def _build_directories_section(self) -> None:
        """Build Directories section (collapsible, starts collapsed)."""
        self.directories_section = CollapsibleSectionCard("Directories", collapsed=True)
        self.directories_section.set_grid_columns(2)
        self.main_layout.addWidget(self.directories_section)

    def bind(self, model: AnalysisModel) -> None:
        """Populate the discovery tab with data from the analysis model."""
        # Clear existing cards
        self.summary_section.clear_cards()
        self.apps_section.clear_cards()
        self.users_section.clear_cards()
        self.user_policies_section.clear_cards()
        self.app_policies_section.clear_cards()
        self.custom_attrs_section.clear_cards()
        self.groups_section.clear_cards()
        self.mfa_section.clear_cards()
        self.directories_section.clear_cards()

        # Summary section - matching Excel report order
        summary_cards = [
            ("App", model.discovery_totals.get("apps", 0)),
            ("User", model.discovery_totals.get("users", 0)),
            ("Admin", model.discovery_totals.get("admins", 0)),
            ("Custom Attribute", model.discovery_totals.get("custom_attributes", 0)),
            ("User Policy", model.discovery_totals.get("user_policies", 0)),
            ("App Policy", model.discovery_totals.get("app_policies", 0)),
            ("Group", model.discovery_totals.get("groups", 0)),
            ("MFA", model.discovery_totals.get("mfa", 0)),
            ("Directory", model.discovery_totals.get("directories", 0)),
        ]
        for label, value in summary_cards:
            self.summary_section.add_stat_card(StatCard(label, value, auto_pluralize=False))

        # Applications section
        apps_cards = [
            ("SAML", model.discovery_apps.get("saml", 0)),
            ("OIDC", model.discovery_apps.get("oidc", 0)),
            ("OAuth", model.discovery_apps.get("oauth", 0)),
            ("SWA", model.discovery_apps.get("swa", 0)),
            ("Other", model.discovery_apps.get("other", 0)),
            ("Provisioning", model.discovery_apps.get("provisioning", 0)),
            ("Active", model.discovery_apps.get("active", 0)),
            ("Inactive", model.discovery_apps.get("inactive", 0)),
        ]
        for label, value in apps_cards:
            self.apps_section.add_stat_card(StatCard(label, value, auto_pluralize=False))

        # Users section
        users_cards = [
            ("Active/Licensed", model.users_license.get("active", 0)),
            ("Deactivated/Unlicensed", model.users_license.get("inactive", 0)),
            ("90+ Days Last Login", model.users_license.get("stale", 0)),
            ("Nested", 0),  # Not available in current data model
            ("Locked", model.users_security.get("locked", 0)),
            ("Password Expired", model.users_security.get("password_expired", 0)),
            ("Admin", model.users_security.get("admins", 0)),
        ]
        for label, value in users_cards:
            self.users_section.add_stat_card(StatCard(label, value, auto_pluralize=False))

        # User Security Policies section
        user_policy_cards = [
            ("Assigned", model.discovery_user_policies.get("assigned", 0)),
            ("Unassigned", model.discovery_user_policies.get("unassigned", 0)),
        ]
        for label, value in user_policy_cards:
            self.user_policies_section.add_stat_card(StatCard(label, value, auto_pluralize=False))

        # App Security Policies section
        app_policy_cards = [
            ("Assigned", model.discovery_app_policies.get("assigned", 0)),
            ("Unassigned", model.discovery_app_policies.get("unassigned", 0)),
        ]
        for label, value in app_policy_cards:
            self.app_policies_section.add_stat_card(StatCard(label, value, auto_pluralize=False))

        # Custom Attributes section
        custom_attrs_cards = [
            ("Used", model.custom_attribute_summary.get("used", 0)),
            ("Unused", model.custom_attribute_summary.get("unused", 0)),
        ]
        for label, value in custom_attrs_cards:
            self.custom_attrs_section.add_stat_card(StatCard(label, value, auto_pluralize=False))

        # Groups section
        groups_cards = [
            ("Nested", model.groups.get("nested", 0)),
            ("Assigned", model.groups.get("assigned", 0)),
            ("Unassigned", model.groups.get("unassigned", 0)),
            ("Rules", model.groups.get("rules", 0)),
        ]
        for label, value in groups_cards:
            self.groups_section.add_stat_card(StatCard(label, value, auto_pluralize=False))

        # MFA section
        mfa_cards = [
            ("Assigned", model.discovery_mfa.get("assigned", 0)),
            ("Unassigned", model.discovery_mfa.get("unassigned", 0)),
        ]
        for label, value in mfa_cards:
            self.mfa_section.add_stat_card(StatCard(label, value, auto_pluralize=False))

        # Directories section
        directories_cards = [
            ("Active", model.discovery_directories.get("active", 0)),
            ("Inactive", model.discovery_directories.get("inactive", 0)),
        ]
        for label, value in directories_cards:
            self.directories_section.add_stat_card(StatCard(label, value, auto_pluralize=False))
