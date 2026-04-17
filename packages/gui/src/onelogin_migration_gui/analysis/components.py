"""Composite analysis view widget."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..theme_manager import get_theme_manager
from .model import AnalysisModel
from .styles import ANALYSIS_QSS
from .tabs.apps import AppsTab
from .tabs.custom_attrs import CustomAttributesTab
from .tabs.discovery import DiscoveryTab
from .tabs.groups import GroupsTab
from .tabs.overview import OverviewTab
from .tabs.users import UsersTab
from .widgets import SplitButton


class AnalysisView(QWidget):
    """Main view for the analysis step."""

    refresh_requested = Signal()
    view_report_requested = Signal()
    download_report_requested = Signal(str)
    filter_apps_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = get_theme_manager()
        self.setStyleSheet(ANALYSIS_QSS)

        # Ensure AnalysisView expands to fill available space
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = self._build_header()
        root.addWidget(self.header, 0)

        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.tab_widget, 1)

        self.overview_tab = OverviewTab()
        self.discovery_tab = DiscoveryTab()
        self.users_tab = UsersTab()
        self.groups_tab = GroupsTab()
        self.apps_tab = AppsTab()
        self.custom_tab = CustomAttributesTab()

        self.tab_widget.addTab(self.overview_tab, "Overview")
        self.tab_widget.addTab(self.discovery_tab, "Discovery")
        self.tab_widget.addTab(self.users_tab, "Users")
        self.tab_widget.addTab(self.groups_tab, "Groups")
        self.tab_widget.addTab(self.apps_tab, "Apps")
        self.tab_widget.addTab(self.custom_tab, "Custom Attributes")

        self.apps_tab.request_filter.connect(self.filter_apps_requested)

        self._install_shortcuts()

        self._model: AnalysisModel | None = None
        self._completion_message: str | None = None

    # --------------------------------------------------------------------- builders
    def _build_header(self) -> QWidget:
        """Build header with refresh action and report controls."""
        container = QFrame()
        container.setProperty("class", "analysisHeader")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(
            self._theme.get_spacing("md"),
            self._theme.get_spacing("md"),
            self._theme.get_spacing("md"),
            self._theme.get_spacing("md"),
        )
        layout.setSpacing(self._theme.get_spacing("md"))

        # Refresh
        self.refresh_button = QPushButton("↻ Refresh Analysis")
        self._theme.theme_changed.connect(self._update_refresh_button_style)
        self._update_refresh_button_style()
        self.refresh_button.clicked.connect(self.refresh_requested)
        layout.addWidget(self.refresh_button)

        layout.addStretch(1)

        menu_items = [
            ("download_discovery", "Discovery Report (.xlsx)"),
            ("download_json", "Migration Data (.json)"),
        ]
        self.report_button = SplitButton("Explore", menu_items, menu_label="Download")
        self.report_button.triggered.connect(self._handle_report_trigger)
        self.report_button.set_enabled(False)
        layout.addWidget(self.report_button, 0, Qt.AlignmentFlag.AlignRight)

        return container

    # --------------------------------------------------------------------- shortcuts
    def _install_shortcuts(self) -> None:
        """Install keyboard shortcuts for common actions."""
        shortcut_refresh = QShortcut(QKeySequence("Ctrl+R"), self)
        shortcut_refresh.activated.connect(self.refresh_requested)
        shortcut_refresh_mac = QShortcut(QKeySequence("Meta+R"), self)
        shortcut_refresh_mac.activated.connect(self.refresh_requested)

        # Shortcut for downloading discovery report
        shortcut_report = QShortcut(QKeySequence("Ctrl+D"), self)
        shortcut_report.activated.connect(
            lambda: self.download_report_requested.emit("download_discovery")
        )
        shortcut_report_mac = QShortcut(QKeySequence("Meta+D"), self)
        shortcut_report_mac.activated.connect(
            lambda: self.download_report_requested.emit("download_discovery")
        )
        # Shortcut for downloading Migration Data JSON
        shortcut_json = QShortcut(QKeySequence("Ctrl+J"), self)
        shortcut_json.activated.connect(
            lambda: self.download_report_requested.emit("download_json")
        )
        shortcut_json_mac = QShortcut(QKeySequence("Meta+J"), self)
        shortcut_json_mac.activated.connect(
            lambda: self.download_report_requested.emit("download_json")
        )

    # --------------------------------------------------------------------- theming
    def _update_refresh_button_style(self) -> None:
        """Update refresh button styling on theme change."""
        self.refresh_button.setStyleSheet(self._theme.get_button_style("primary"))

    # ---------------------------------------------------------------------- actions
    def _handle_report_trigger(self, action_id: str) -> None:
        """Handle report button actions."""
        if action_id == "primary":
            self.view_report_requested.emit()
            return
        self.download_report_requested.emit(action_id)

    def enable_report_actions(self, enabled: bool) -> None:
        """Enable or disable report download actions."""
        self.report_button.set_enabled(enabled)

    def set_completion_message(self, message: str | None) -> None:
        """Store the completion message; UI no longer displays it."""
        self._completion_message = message

    # ----------------------------------------------------------------------- binding
    def bind(self, model: AnalysisModel) -> None:
        """Bind analysis model to all tabs and update header message."""
        self._model = model
        self.overview_tab.bind(model)
        self.discovery_tab.bind(model)
        self.users_tab.bind(model)
        self.groups_tab.bind(model)
        self.apps_tab.bind(model)
        self.custom_tab.bind(model)

        formatted = model.completed_at.strftime("%b %d, %Y %I:%M %p")
        self.set_completion_message(f"Analysis completed on {formatted}")
        self.enable_report_actions(True)
