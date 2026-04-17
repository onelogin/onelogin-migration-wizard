"""Detailed Analysis Report Dialog.

Provides comprehensive, tabbed view of migration analysis with tables,
filtering, sorting, and export capabilities.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from onelogin_migration_core.db import get_database_manager
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...styles.button_styles import SECONDARY_BUTTON_STYLE, SUCCESS_BUTTON_STYLE
from ...theme_manager import get_theme_manager
from .app_migration_dialog import ApplicationMigrationDialog
from .export.export_manager import ExportManager
from .export.export_utils import TableExportData
from .tables.apps_table_manager import APP_INDEX_ROLE, ApplicationsTableManager
from .tables.attrs_table_manager import AttributesTableManager
from .tables.groups_table_manager import GroupsTableManager
from .tables.users_table_manager import UsersTableManager
from .utils.formatters import summarize_assigned_groups
from .utils.status_helpers import app_status_details, describe_group_type, determine_group_priority
from .utils.type_inference import detect_attribute_warning, infer_attribute_type
from .utils.validators import estimate_active_users

LOGGER = logging.getLogger(__name__)


class AnalysisDetailDialog(QDialog):
    """Detailed analysis report dialog with tabbed interface."""

    def __init__(
        self,
        analysis_data: dict[str, Any],
        mode: str = "migration",
        parent: QWidget | None = None,
    ):
        """Initialize the detailed analysis dialog.

        Args:
            analysis_data: Complete analysis results from the analysis page
            mode: The wizard mode ("discovery" or "migration")
            parent: Parent widget
        """
        super().__init__(parent)
        self.analysis_data = analysis_data
        self.mode = mode
        self.theme_manager = get_theme_manager()
        self.setWindowTitle("Detailed Migration Analysis Report")
        self.resize(1200, 800)
        self.setModal(False)  # Non-modal so users can reference both windows

        # Pagination settings
        self.page_size = 100  # Show 100 items per page
        self.users_current_page = 0
        self.groups_current_page = 0
        self.apps_current_page = 0
        self.attrs_current_page = 0

        # Store full data lists for pagination
        raw_export = self.analysis_data.get("raw_export", {})
        self.all_users = raw_export.get("users", [])
        self.all_groups = raw_export.get("groups", [])
        self.all_apps = raw_export.get("applications", [])
        memberships = raw_export.get("memberships", [])

        users_data = self.analysis_data.get("users", {})
        self.all_custom_attrs = users_data.get("custom_attributes", [])

        # Build membership count map for groups
        self.group_member_counts: dict[str, int] = {}
        self.group_members_lookup: dict[str, list[str]] = {}
        for membership in memberships:
            group_id = membership.get("group_id") or membership.get("groupId")
            user_id = membership.get("user_id") or membership.get("userId")
            if not group_id:
                continue
            key = str(group_id)
            self.group_member_counts[key] = self.group_member_counts.get(key, 0) + 1
            if user_id:
                user_key = str(user_id)
                members_list = self.group_members_lookup.setdefault(key, [])
                if user_key not in members_list:
                    members_list.append(user_key)

        self.user_lookup: dict[str, dict[str, Any]] = {}
        for user in self.all_users:
            user_id = user.get("id")
            if user_id:
                self.user_lookup[str(user_id)] = user

        self.group_lookup: dict[str, dict[str, Any]] = {}
        for group in self.all_groups:
            group_id = group.get("id")
            if group_id:
                self.group_lookup[str(group_id)] = group

        self.user_groups_lookup: dict[str, list[str]] = {}
        for group_id, member_ids in self.group_members_lookup.items():
            group_record = self.group_lookup.get(group_id) or {}
            profile = group_record.get("profile") or {}
            group_name = profile.get("name") or group_record.get("label") or f"Group {group_id}"
            for member_id in member_ids:
                entries = self.user_groups_lookup.setdefault(member_id, [])
                if group_name not in entries:
                    entries.append(group_name)
        for memberships in self.user_groups_lookup.values():
            memberships.sort(key=str.lower)

        self.total_user_count = len(self.all_users)
        self.app_migration_choices: dict[str, dict[str, Any]] = {}

        # Managers
        self.export_manager = ExportManager(self)

        # Set window icon if available
        try:
            # Try to use the same icon as the main window
            if parent and hasattr(parent, "windowIcon"):
                self.setWindowIcon(parent.windowIcon())
        except Exception:
            pass

        self._init_ui()

    def _init_ui(self):
        """Initialize the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top section - Summary bar (fixed, non-scrolling)
        summary_bar = self._create_summary_bar()
        layout.addWidget(summary_bar)

        # Main content - Tabbed interface
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(
            """
            QTabWidget::pane {
                border: 1px solid #424242;
                background-color: #2b2b2b;
                border-top: 2px solid #424242;
            }
            QTabBar::tab {
                background-color: #1e1e1e;
                color: #b0b0b0;
                border: 1px solid #424242;
                border-bottom: none;
                padding: 12px 30px;
                margin-right: 3px;
                font-weight: 600;
                font-size: 13px;
                min-width: 120px;
            }
            QTabBar::tab:selected {
                background-color: #2b2b2b;
                color: #0ea5e9;
                border-bottom: 2px solid #0ea5e9;
                font-weight: 700;
            }
            QTabBar::tab:hover:!selected {
                background-color: #363636;
                color: #e0e0e0;
            }
        """
        )

        # Create tabs
        self.users_tab = self._create_users_tab()
        self.groups_tab = self._create_groups_tab()
        self.apps_tab = self._create_applications_tab()
        self.custom_attrs_tab = self._create_custom_attributes_tab()

        self.tab_widget.addTab(self.users_tab, "Users")
        self.tab_widget.addTab(self.groups_tab, "Groups")
        self.tab_widget.addTab(self.apps_tab, "Applications")
        self.tab_widget.addTab(self.custom_attrs_tab, "Custom Attributes")

        layout.addWidget(self.tab_widget, 1)

        # Bottom section - Action bar
        action_bar = self._create_action_bar()
        layout.addWidget(action_bar)

    def _create_summary_bar(self) -> QWidget:
        """Create fixed summary bar at top with professional styling."""
        container = QFrame()
        container.setStyleSheet(
            """
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1976d2, stop:1 #1565c0);
            }
        """
        )
        container.setFixedHeight(170)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(30, 18, 30, 16)
        layout.setSpacing(14)

        # Title row with timestamp
        title_layout = QHBoxLayout()
        title_label = QLabel("Detailed Migration Analysis Report")
        title_label.setStyleSheet(
            """
            color: white;
            font-size: 16px;
            font-weight: 700;
            letter-spacing: 0.3px;
        """
        )
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        # Timestamp in top-right
        timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
        time_label = QLabel(f"Generated: {timestamp}")
        time_label.setStyleSheet(
            """
            color: rgba(255, 255, 255, 0.85);
            font-size: 11px;
            font-weight: 500;
            padding-right: 5px;
        """
        )
        title_layout.addWidget(time_label)
        layout.addLayout(title_layout)

        # Statistics row
        stats_container = QWidget()
        stats_container.setStyleSheet("background: transparent;")
        stats_layout = QHBoxLayout(stats_container)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(16)
        stats_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        users = self.analysis_data.get("users", {})
        groups = self.analysis_data.get("groups", {})
        apps = self.analysis_data.get("applications", {})

        total_users = users.get("total", 0)
        total_groups = groups.get("total", 0)
        total_apps = apps.get("total", 0)

        metrics = [
            {"label": "Users", "value": f"{total_users:,}"},
            {"label": "Groups", "value": f"{total_groups:,}"},
            {"label": "Applications", "value": f"{total_apps:,}"},
        ]

        metrics_wrapper = QWidget()
        metrics_wrapper.setMinimumHeight(100)
        metrics_wrapper.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        metrics_layout = QHBoxLayout(metrics_wrapper)
        metrics_layout.setContentsMargins(10, 0, 10, 0)
        metrics_layout.setSpacing(36)
        metrics_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        for idx, metric in enumerate(metrics):
            metric_widget = self._create_metric_widget(
                label=metric["label"],
                value=metric["value"],
            )
            metric_widget.setMinimumSize(170, 90)
            metrics_layout.addWidget(metric_widget, 0, Qt.AlignmentFlag.AlignTop)

            if idx < len(metrics) - 1:
                separator = QFrame()
                separator.setFrameShape(QFrame.Shape.VLine)
                separator.setFixedWidth(1)
                separator.setFixedHeight(60)
                separator.setStyleSheet("background: rgba(255, 255, 255, 0.25);")
                metrics_layout.addWidget(separator, 0, Qt.AlignmentFlag.AlignTop)

        metrics_layout.addStretch()
        stats_layout.addWidget(metrics_wrapper, 1, Qt.AlignmentFlag.AlignTop)

        # Status badge with dynamic readiness
        badge_text = "✅ Ready to Migrate"
        badge_color = "#2e7d32"

        status_badge = QLabel(badge_text)
        status_badge.setStyleSheet(
            f"""
            background: {badge_color};
            color: white;
            padding: 8px 18px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 0.5px;
            margin-left: 10px;
        """
        )
        status_badge.setFixedHeight(36)
        status_badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        stats_layout.addWidget(status_badge, 0, Qt.AlignmentFlag.AlignTop)

        layout.addWidget(stats_container)

        return container

    def _create_metric_widget(
        self,
        label: str,
        value: str,
        icon: str | None = None,
        context: str | None = None,
    ) -> QWidget:
        """Create a single metric widget."""
        widget = QWidget()
        widget.setStyleSheet("background: transparent;")
        metric_layout = QVBoxLayout(widget)
        metric_layout.setContentsMargins(0, 0, 0, 0)
        metric_layout.setSpacing(6)
        metric_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        text_label = QLabel(label)
        text_label.setStyleSheet(
            """
            color: rgba(255, 255, 255, 0.85);
            font-size: 13px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.6px;
        """
        )
        text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        metric_layout.addWidget(text_label)

        value_label = QLabel(value)
        value_label.setStyleSheet(
            """
            color: white;
            font-size: 30px;
            font-weight: 700;
            letter-spacing: -0.5px;
        """
        )
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        metric_layout.addWidget(value_label)

        return widget

    def _create_users_tab(self) -> QWidget:
        """Create Users tab with sortable/filterable table."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Controls row
        controls_layout = QHBoxLayout()

        # Search box
        search_label = QLabel("Search:")
        controls_layout.addWidget(search_label)

        self.users_search = QLineEdit()
        self.users_search.setPlaceholderText("Search by name or email...")
        self.users_search.setFixedWidth(250)
        self.users_search.setClearButtonEnabled(True)
        self._apply_search_box_style(self.users_search)
        controls_layout.addWidget(self.users_search)

        controls_layout.addSpacing(20)

        # Status filter
        filter_label = QLabel("Status:")
        controls_layout.addWidget(filter_label)

        self.users_status_filter = QComboBox()
        self.users_status_filter.addItems(["All", "Active", "Suspended", "Deprovisioned"])
        self.users_status_filter.setFixedWidth(150)
        self._apply_combobox_style(self.users_status_filter)
        controls_layout.addWidget(self.users_status_filter)

        controls_layout.addStretch()

        # Export button
        controls_layout.addWidget(self.export_manager.create_export_button("users"))

        layout.addLayout(controls_layout)

        # Count and pagination info
        info_layout = QHBoxLayout()
        self.users_count_label = QLabel()
        self.users_count_label.setStyleSheet(
            "color: #a0a0a0; font-size: 12px; background-color: transparent;"
        )
        info_layout.addWidget(self.users_count_label)
        info_layout.addStretch()
        self.users_page_label = QLabel()
        self.users_page_label.setStyleSheet(
            "color: #a0a0a0; font-size: 12px; background-color: transparent;"
        )
        info_layout.addWidget(self.users_page_label)
        layout.addLayout(info_layout)

        # Table
        self.users_table = QTableWidget()
        self.users_table.setColumnCount(6)
        self.users_table.setHorizontalHeaderLabels(
            ["", "Name", "Email", "Status", "Custom Attrs", "Groups"]
        )
        self.users_table.setAlternatingRowColors(True)
        self.users_table.setSortingEnabled(True)
        self.users_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.users_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.users_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.users_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.users_table.setWordWrap(False)

        # Increase row height for better readability
        self.users_table.verticalHeader().setDefaultSectionSize(35)
        self.users_table.verticalHeader().setVisible(False)  # Hide row numbers

        # Set column widths
        header = self.users_table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionsMovable(True)
        header.setMinimumSectionSize(110)
        header.setHighlightSections(False)
        if hasattr(header, "setWordWrap"):
            header.setWordWrap(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # Selection
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Name
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Email
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)  # Status
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)  # Custom Attrs
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)  # Groups
        select_width = max(40, self.theme_manager.get_spacing("sm") * 2 + 18)
        header.resizeSection(0, select_width)
        header.resizeSection(1, 220)
        header.resizeSection(2, 280)
        header.resizeSection(3, 140)
        header.resizeSection(4, 140)
        header.resizeSection(5, 220)

        status_header = self.users_table.horizontalHeaderItem(3)
        if status_header:
            status_header.setToolTip("Okta user status")
        custom_header = self.users_table.horizontalHeaderItem(4)
        if custom_header:
            custom_header.setToolTip("Number of custom attributes populated for the user")
        groups_header = self.users_table.horizontalHeaderItem(5)
        if groups_header:
            groups_header.setToolTip("Group memberships summarized in Groups tab")

        self._apply_table_style(self.users_table)
        layout.addWidget(self.users_table, 1)

        # Pagination controls
        pagination_layout = QHBoxLayout()
        pagination_layout.addStretch()

        self.users_prev_btn = QPushButton("← Previous")
        self.users_prev_btn.clicked.connect(self._users_prev_page)
        self.users_prev_btn.setFixedWidth(100)
        self._apply_pagination_button_style(self.users_prev_btn)
        pagination_layout.addWidget(self.users_prev_btn)

        self.users_next_btn = QPushButton("Next →")
        self.users_next_btn.clicked.connect(self._users_next_page)
        self.users_next_btn.setFixedWidth(100)
        self._apply_pagination_button_style(self.users_next_btn)
        pagination_layout.addWidget(self.users_next_btn)

        layout.addLayout(pagination_layout)

        self.users_table_manager = UsersTableManager(
            self,
            self.users_table,
            self.users_count_label,
            self.users_page_label,
            self.users_prev_btn,
            self.users_next_btn,
            self.users_search,
            self.users_status_filter,
        )

        self.users_search.textChanged.connect(lambda _: self.users_table_manager.apply_filters())
        self.users_status_filter.currentTextChanged.connect(
            lambda _: self.users_table_manager.apply_filters()
        )

        # Populate table
        self.users_table_manager.populate()

        self.export_manager.register_table("users", self.users_table, self._build_users_export_data)
        self.export_manager.set_filter_provider(
            "users",
            lambda: {
                "Search": self.users_search.text(),
                "Status Filter": self.users_status_filter.currentText(),
            },
        )

        return widget

    def _create_groups_tab(self) -> QWidget:
        """Create Groups tab with expandable member lists."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Controls row
        controls_layout = QHBoxLayout()

        # Search box
        search_label = QLabel("Search:")
        controls_layout.addWidget(search_label)

        self.groups_search = QLineEdit()
        self.groups_search.setPlaceholderText("Search by group name...")
        self.groups_search.setFixedWidth(250)
        self.groups_search.setClearButtonEnabled(True)
        self._apply_search_box_style(self.groups_search)
        controls_layout.addWidget(self.groups_search)

        controls_layout.addStretch()

        # Export button
        controls_layout.addWidget(self.export_manager.create_export_button("groups"))

        layout.addLayout(controls_layout)

        # Count and pagination info
        info_layout = QHBoxLayout()
        self.groups_count_label = QLabel()
        self.groups_count_label.setStyleSheet(
            "color: #a0a0a0; font-size: 12px; background-color: transparent;"
        )
        info_layout.addWidget(self.groups_count_label)
        info_layout.addStretch()
        self.groups_page_label = QLabel()
        self.groups_page_label.setStyleSheet(
            "color: #a0a0a0; font-size: 12px; background-color: transparent;"
        )
        info_layout.addWidget(self.groups_page_label)
        layout.addLayout(info_layout)

        # Table
        self.groups_table = QTableWidget()
        self.groups_table.setColumnCount(7)
        self.groups_table.setHorizontalHeaderLabels(
            [
                "",
                "Group Name",
                "Member Count",
                "User Coverage",
                "Priority",
                "Group Type",
                "Will Become\n(Role)",
            ]
        )
        self.groups_table.setAlternatingRowColors(True)
        self.groups_table.setSortingEnabled(True)
        self.groups_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.groups_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.groups_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.groups_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.groups_table.setWordWrap(False)

        # Increase row height and hide row numbers
        self.groups_table.verticalHeader().setDefaultSectionSize(35)
        self.groups_table.verticalHeader().setVisible(False)

        # Set column widths
        header = self.groups_table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionsMovable(True)
        header.setMinimumSectionSize(110)
        header.setHighlightSections(False)
        if hasattr(header, "setWordWrap"):
            header.setWordWrap(True)
        select_width = max(40, self.theme_manager.get_spacing("sm") * 2 + 18)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # Selection
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Group Name
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Member Count
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # User Coverage
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Priority
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)  # Group Type
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)  # Will Become
        header.resizeSection(0, select_width)
        header.resizeSection(1, 260)
        header.resizeSection(5, 200)
        header.resizeSection(6, 220)

        # Header tooltips for clarity
        become_header = self.groups_table.horizontalHeaderItem(6)
        if become_header:
            become_header.setToolTip("Will Become (Role) in OneLogin")

        self._apply_table_style(self.groups_table)
        layout.addWidget(self.groups_table, 1)

        # Pagination controls
        pagination_layout = QHBoxLayout()
        pagination_layout.addStretch()

        self.groups_prev_btn = QPushButton("← Previous")
        self.groups_prev_btn.clicked.connect(self._groups_prev_page)
        self.groups_prev_btn.setFixedWidth(100)
        self._apply_pagination_button_style(self.groups_prev_btn)
        pagination_layout.addWidget(self.groups_prev_btn)

        self.groups_next_btn = QPushButton("Next →")
        self.groups_next_btn.clicked.connect(self._groups_next_page)
        self.groups_next_btn.setFixedWidth(100)
        self._apply_pagination_button_style(self.groups_next_btn)
        pagination_layout.addWidget(self.groups_next_btn)

        layout.addLayout(pagination_layout)

        # Populate table
        self.groups_table_manager = GroupsTableManager(
            self,
            self.groups_table,
            self.groups_count_label,
            self.groups_page_label,
            self.groups_prev_btn,
            self.groups_next_btn,
            self.groups_search,
        )

        self.groups_search.textChanged.connect(lambda _: self.groups_table_manager.apply_filters())
        self.groups_table.activated.connect(
            lambda index: self.groups_table_manager.handle_activation(index.row())
        )

        self.groups_table_manager.populate()

        self.export_manager.register_table(
            "groups", self.groups_table, self._build_groups_export_data
        )
        self.export_manager.set_filter_provider(
            "groups",
            lambda: {
                "Search": self.groups_search.text(),
            },
        )

        return widget

    def _create_applications_tab(self) -> QWidget:
        """Create Applications tab with collapsible sections."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Controls row
        controls_layout = QHBoxLayout()

        # Search box
        search_label = QLabel("Search:")
        controls_layout.addWidget(search_label)

        self.apps_search = QLineEdit()
        self.apps_search.setPlaceholderText("Search by app name...")
        self.apps_search.setFixedWidth(250)
        self.apps_search.setClearButtonEnabled(True)
        self._apply_search_box_style(self.apps_search)
        controls_layout.addWidget(self.apps_search)

        controls_layout.addSpacing(20)

        # Type filter
        filter_label = QLabel("Type:")
        controls_layout.addWidget(filter_label)

        self.apps_type_filter = QComboBox()
        self.apps_type_filter.addItems(["All", "SAML", "OIDC", "OAuth", "OpenID", "Custom"])
        self.apps_type_filter.setFixedWidth(150)
        self._apply_combobox_style(self.apps_type_filter)
        controls_layout.addWidget(self.apps_type_filter)

        controls_layout.addSpacing(20)

        status_filter_label = QLabel("Migration status:")
        controls_layout.addWidget(status_filter_label)

        self.apps_status_filter = QComboBox()
        self.apps_status_filter.addItems(
            [
                "All",
                "Can Auto-Migrate",
                "Connector Match",
                "Custom SAML/OIDC",
                "Needs Review",
                "Manual Migration",
                "Inactive",
            ]
        )
        self.apps_status_filter.setFixedWidth(200)
        self._apply_combobox_style(self.apps_status_filter)
        controls_layout.addWidget(self.apps_status_filter)

        controls_layout.addStretch()

        controls_layout.addWidget(self.export_manager.create_export_button("applications"))

        layout.addLayout(controls_layout)

        # Count and pagination info
        info_layout = QHBoxLayout()
        self.apps_count_label = QLabel()
        self.apps_count_label.setStyleSheet(
            "color: #a0a0a0; font-size: 12px; background-color: transparent;"
        )
        info_layout.addWidget(self.apps_count_label)
        info_layout.addStretch()
        self.apps_page_label = QLabel()
        self.apps_page_label.setStyleSheet(
            "color: #a0a0a0; font-size: 12px; background-color: transparent;"
        )
        info_layout.addWidget(self.apps_page_label)
        layout.addLayout(info_layout)

        # Table
        self.apps_table = QTableWidget()
        self.apps_table.setColumnCount(6)
        self.apps_table.setHorizontalHeaderLabels(
            [
                "",
                "Name",
                "Type",
                "Status",
                "Assigned Groups",
                "Active Users",
            ]
        )
        self.apps_table.setAlternatingRowColors(True)
        self.apps_table.setSortingEnabled(True)
        self.apps_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.apps_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.apps_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.apps_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.apps_table.setWordWrap(False)

        # Increase row height and hide row numbers
        self.apps_table.verticalHeader().setDefaultSectionSize(35)
        self.apps_table.verticalHeader().setVisible(False)

        # Set column widths
        header = self.apps_table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionsMovable(True)
        header.setMinimumSectionSize(110)
        header.setHighlightSections(False)
        if hasattr(header, "setWordWrap"):
            header.setWordWrap(True)
        select_width = max(40, self.theme_manager.get_spacing("sm") * 2 + 18)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # Selection
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # App Name
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Type
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Status
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)  # Assigned Groups
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Active Users
        header.resizeSection(0, select_width)
        header.resizeSection(1, 320)
        header.resizeSection(4, 220)
        header.resizeSection(3, 170)

        # Header tooltips
        status_header = self.apps_table.horizontalHeaderItem(3)
        if status_header:
            status_header.setToolTip("Migration readiness status")
        active_header = self.apps_table.horizontalHeaderItem(5)
        if active_header:
            active_header.setToolTip("Estimated active users based on assigned groups")

        self._apply_table_style(self.apps_table)
        layout.addWidget(self.apps_table, 1)

        self.apps_table.itemActivated.connect(
            lambda item: self._handle_app_row_activated(item.row(), item.column())
        )

        # Pagination controls
        pagination_layout = QHBoxLayout()
        pagination_layout.addStretch()

        self.apps_prev_btn = QPushButton("← Previous")
        self.apps_prev_btn.clicked.connect(self._apps_prev_page)
        self.apps_prev_btn.setFixedWidth(100)
        self._apply_pagination_button_style(self.apps_prev_btn)
        pagination_layout.addWidget(self.apps_prev_btn)

        self.apps_next_btn = QPushButton("Next →")
        self.apps_next_btn.clicked.connect(self._apps_next_page)
        self.apps_next_btn.setFixedWidth(100)
        self._apply_pagination_button_style(self.apps_next_btn)
        pagination_layout.addWidget(self.apps_next_btn)

        layout.addLayout(pagination_layout)

        self.apps_table_manager = ApplicationsTableManager(
            self,
            self.apps_table,
            self.apps_count_label,
            self.apps_page_label,
            self.apps_prev_btn,
            self.apps_next_btn,
            self.apps_search,
            self.apps_type_filter,
            self.apps_status_filter,
        )

        self.apps_search.textChanged.connect(lambda _: self.apps_table_manager.apply_filters())
        self.apps_type_filter.currentTextChanged.connect(
            lambda _: self.apps_table_manager.apply_filters()
        )
        self.apps_status_filter.currentTextChanged.connect(
            lambda _: self.apps_table_manager.apply_filters()
        )

        # Populate table
        self.apps_table_manager.populate()

        self.export_manager.register_table(
            "applications", self.apps_table, self._build_applications_export_data
        )
        self.export_manager.set_filter_provider(
            "applications",
            lambda: {
                "Search": self.apps_search.text(),
                "Type Filter": self.apps_type_filter.currentText(),
                "Status Filter": self.apps_status_filter.currentText(),
            },
        )

        return widget

    def _create_custom_attributes_tab(self) -> QWidget:
        """Create Custom Attributes tab with usage statistics."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Controls row
        controls_layout = QHBoxLayout()

        # Search box
        search_label = QLabel("Search:")
        controls_layout.addWidget(search_label)

        self.attrs_search = QLineEdit()
        self.attrs_search.setPlaceholderText("Search by attribute name...")
        self.attrs_search.setFixedWidth(250)
        self.attrs_search.setClearButtonEnabled(True)
        self._apply_search_box_style(self.attrs_search)
        controls_layout.addWidget(self.attrs_search)

        controls_layout.addStretch()

        # Export button
        controls_layout.addWidget(self.export_manager.create_export_button("custom_attributes"))

        layout.addLayout(controls_layout)

        # Count and pagination info
        info_layout = QHBoxLayout()
        self.attrs_count_label = QLabel()
        self.attrs_count_label.setStyleSheet(
            "color: #a0a0a0; font-size: 12px; background-color: transparent;"
        )
        info_layout.addWidget(self.attrs_count_label)
        info_layout.addStretch()
        self.attrs_page_label = QLabel()
        self.attrs_page_label.setStyleSheet(
            "color: #a0a0a0; font-size: 12px; background-color: transparent;"
        )
        info_layout.addWidget(self.attrs_page_label)
        layout.addLayout(info_layout)

        # Info banner
        info_label = QLabel(
            "<div style='background: #1a3d5c; border-left: 4px solid #0ea5e9; padding: 12px; "
            "border-radius: 3px;'>"
            "<b style='color: #90caf9;'>Custom Attributes:</b> <span style='color: #90caf9;'>These fields from Okta do not map to OneLogin's standard fields "
            "and will be created as custom attributes during migration.</span>"
            "</div>"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Table
        self.attrs_table = QTableWidget()
        self.attrs_table.setColumnCount(7)
        self.attrs_table.setHorizontalHeaderLabels(
            [
                "",
                "Attribute Name",
                "Data Type",
                "Usage",
                "Sample Values",
                "Required?",
                "Status in OneLogin",
            ]
        )
        self.attrs_table.setAlternatingRowColors(True)
        self.attrs_table.setSortingEnabled(True)
        self.attrs_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.attrs_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.attrs_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.attrs_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.attrs_table.setWordWrap(False)

        # Increase row height and hide row numbers
        self.attrs_table.verticalHeader().setDefaultSectionSize(35)
        self.attrs_table.verticalHeader().setVisible(False)

        # Set column widths
        header = self.attrs_table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionsMovable(True)
        header.setMinimumSectionSize(110)
        header.setHighlightSections(False)
        if hasattr(header, "setWordWrap"):
            header.setWordWrap(True)
        select_width = max(40, self.theme_manager.get_spacing("sm") * 2 + 18)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # Selection
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Attribute Name
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Data Type
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Usage
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)  # Sample Values
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Required?
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)  # Status
        header.resizeSection(0, select_width)
        header.resizeSection(1, 220)
        header.resizeSection(4, 280)
        header.resizeSection(6, 260)

        sample_header = self.attrs_table.horizontalHeaderItem(4)
        if sample_header:
            sample_header.setToolTip("Example values observed in Okta profiles")

        self._apply_table_style(self.attrs_table)
        layout.addWidget(self.attrs_table, 1)

        # Pagination controls
        pagination_layout = QHBoxLayout()
        pagination_layout.addStretch()

        self.attrs_prev_btn = QPushButton("← Previous")
        self.attrs_prev_btn.clicked.connect(self._attrs_prev_page)
        self.attrs_prev_btn.setFixedWidth(100)
        self._apply_pagination_button_style(self.attrs_prev_btn)
        pagination_layout.addWidget(self.attrs_prev_btn)

        self.attrs_next_btn = QPushButton("Next →")
        self.attrs_next_btn.clicked.connect(self._attrs_next_page)
        self.attrs_next_btn.setFixedWidth(100)
        self._apply_pagination_button_style(self.attrs_next_btn)
        pagination_layout.addWidget(self.attrs_next_btn)

        layout.addLayout(pagination_layout)

        self.attrs_table_manager = AttributesTableManager(
            self,
            self.attrs_table,
            self.attrs_count_label,
            self.attrs_page_label,
            self.attrs_prev_btn,
            self.attrs_next_btn,
            self.attrs_search,
        )

        self.attrs_search.textChanged.connect(lambda _: self.attrs_table_manager.apply_filters())

        # Populate table
        self.attrs_table_manager.populate()

        self.export_manager.register_table(
            "custom_attributes",
            self.attrs_table,
            self._build_custom_attributes_export_data,
        )
        self.export_manager.set_filter_provider(
            "custom_attributes",
            lambda: {
                "Search": self.attrs_search.text(),
            },
        )

        return widget

    # ------------------------------------------------------------------ Export builders
    def _build_users_export_data(self) -> TableExportData:
        """Return all user rows for export."""
        headers = ["Name", "Email", "Status", "Custom Attrs", "Groups"]
        users_data = self.analysis_data.get("users", {}) or {}
        custom_attrs = users_data.get("custom_attributes", []) or []
        rows: list[list[str]] = []

        for user in self.all_users:
            profile = user.get("profile") or {}
            first_name = profile.get("firstName") or ""
            last_name = profile.get("lastName") or ""
            display_name = " ".join(part for part in [first_name, last_name] if part).strip()
            if not display_name:
                display_name = profile.get("displayName") or profile.get("login") or "N/A"

            email = profile.get("email") or profile.get("login") or "N/A"
            status = user.get("status") or "UNKNOWN"

            attr_count = sum(1 for attr in custom_attrs if profile.get(attr))
            attr_display = (
                f"{attr_count} attr{'s' if attr_count != 1 else ''}" if attr_count else "-"
            )

            user_id = str(user.get("id") or "")
            group_names = self.user_groups_lookup.get(user_id, [])
            groups_text = "; ".join(group_names) if group_names else "No group memberships"

            rows.append([display_name, email, status, attr_display, groups_text])

        return TableExportData(
            sheet_name="Users",
            headers=headers,
            rows=rows,
            export_mode="Full dataset (all users)",
        )

    def _build_groups_export_data(self) -> TableExportData:
        """Return all group rows for export."""
        headers = [
            "Group Name",
            "Member Count",
            "User Coverage",
            "Priority",
            "Group Type",
            "Will Become (Role)",
        ]
        rows: list[list[str]] = []

        for group in self.all_groups:
            profile = group.get("profile") or {}
            group_id = group.get("id")
            name = profile.get("name") or "(No Name)"

            member_count = self.group_member_counts.get(str(group_id), 0)
            if self.total_user_count:
                coverage_pct = (member_count / self.total_user_count) * 100
                coverage_text = f"{coverage_pct:.1f}% of users"
            else:
                coverage_text = "N/A"

            priority_text, _ = determine_group_priority(member_count)
            group_type_text = describe_group_type(group)
            role_name = profile.get("name") or group.get("label") or "OneLogin Role"

            rows.append(
                [
                    name,
                    f"{member_count:,}",
                    coverage_text,
                    priority_text,
                    group_type_text,
                    role_name,
                ]
            )

        return TableExportData(
            sheet_name="Groups",
            headers=headers,
            rows=rows,
            export_mode="Full dataset (all groups)",
        )

    def _build_applications_export_data(self) -> TableExportData:
        """Return all application rows for export."""
        headers = [
            "Name",
            "Type",
            "Status",
            "Assigned Groups",
            "Active Users (Est.)",
        ]
        rows: list[list[str]] = []

        for app in self.all_apps:
            name = app.get("label") or app.get("name") or "(No Name)"

            sign_on_mode = (app.get("signOnMode") or "").upper()
            # Check for specific protocols - order matters for OIDC vs legacy OpenID
            if "SAML" in sign_on_mode:
                app_type = "SAML"
            elif "OPENID_CONNECT" in sign_on_mode:
                app_type = "OIDC"  # Modern OpenID Connect
            elif "OPENID" in sign_on_mode:
                app_type = "OpenID"  # Legacy OpenID
            elif "OAUTH" in sign_on_mode:
                app_type = "OAuth"
            else:
                app_type = "Custom"

            status_details = app_status_details(app)
            status_text = status_details.get("label", "Unknown")

            assigned_groups, _ = summarize_assigned_groups(app, self.group_lookup)
            estimated_users = estimate_active_users(app, self.group_members_lookup)
            users_text = f"{estimated_users:,}" if estimated_users is not None else "—"

            rows.append([name, app_type, status_text, assigned_groups, users_text])

        return TableExportData(
            sheet_name="Applications",
            headers=headers,
            rows=rows,
            export_mode="Full dataset (all applications)",
        )

    def _build_custom_attributes_export_data(self) -> TableExportData:
        """Return all custom attribute rows for export."""
        headers = [
            "Attribute Name",
            "Detected Type",
            "Usage",
            "Sample Values",
            "Required",
            "Status",
        ]
        rows: list[list[str]] = []

        for attr in self.all_custom_attrs:
            usage_count = 0
            observed_values: list[Any] = []
            sample_values: list[str] = []

            for user in self.all_users:
                profile = user.get("profile") or {}
                value = profile.get(attr)
                if value in (None, ""):
                    continue
                usage_count += 1
                observed_values.append(value)
                if len(sample_values) < 3:
                    sample_values.append(str(value)[:50])

            data_type = infer_attribute_type(observed_values)
            if usage_count and self.total_user_count:
                usage_pct = (usage_count / self.total_user_count) * 100
                usage_text = f"{usage_count:,} users ({usage_pct:.1f}%)"
            elif usage_count:
                usage_text = f"{usage_count:,} users"
            else:
                usage_text = "No usage detected"

            samples = ", ".join(sample_values) if sample_values else "(No values)"
            required = usage_count == self.total_user_count and self.total_user_count > 0
            required_text = "Yes" if required else "No"

            warning = detect_attribute_warning(attr, observed_values, data_type)
            if warning:
                status_text = f"⚠ Review mapping – {warning}"
            else:
                status_text = "Will be created automatically"

            rows.append(
                [
                    attr,
                    data_type,
                    usage_text,
                    samples,
                    required_text,
                    status_text,
                ]
            )

        return TableExportData(
            sheet_name="Custom Attributes",
            headers=headers,
            rows=rows,
            export_mode="Full dataset (all custom attributes)",
        )

    def _create_action_bar(self) -> QWidget:
        """Create bottom action bar with Export/Print/Close buttons."""
        container = QFrame()
        container.setStyleSheet(
            """
            QFrame {
                background: #1e1e1e;
                border-top: 1px solid #424242;
            }
        """
        )
        container.setFixedHeight(70)

        layout = QHBoxLayout(container)
        layout.setContentsMargins(25, 15, 25, 15)
        layout.setSpacing(10)

        # Export All button
        export_all_btn = QPushButton("Export All Data")
        export_all_btn.clicked.connect(
            lambda: self.export_manager.export_all(
                ["users", "groups", "applications", "custom_attributes"]
            )
        )
        export_all_btn.setStyleSheet(SUCCESS_BUTTON_STYLE())
        layout.addWidget(export_all_btn)

        layout.addStretch()

        # Close button - text depends on mode
        button_text = "Close" if self.mode == "discovery" else "Save"
        close_btn = QPushButton(button_text)
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet(SECONDARY_BUTTON_STYLE())
        layout.addWidget(close_btn)

        return container

    # ------------------------------------------------------------------ App dialog helpers
    def _handle_app_row_activated(self, row: int, _column: int) -> None:
        app = self._get_app_for_row(row)
        if not app:
            return
        self.open_app_migration_dialog(app, table_row=row)

    def open_app_migration_dialog(self, app: dict[str, Any], table_row: int | None = None) -> None:
        dialog = ApplicationMigrationDialog(app, self)
        if dialog.exec() != QDialog.Accepted or not dialog.selected_option:
            return

        selection = dialog.selected_option
        app_meta = app.setdefault("_migration", {})
        app_meta["selection"] = selection
        # Mark as user-reviewed so status display shows "Ready (Reviewed)"
        app_meta["user_reviewed"] = True

        key = str(app.get("id") or app.get("label"))
        self.app_migration_choices[key] = selection
        selections = self.analysis_data.setdefault("migration_choices", {}).setdefault(
            "applications", {}
        )
        selections[key] = selection

        # CRITICAL FIX: Save user decision to database so migration runtime can use it
        self._save_user_connector_override(app, selection)

        self._update_app_row_display(app, table_row)

    def _get_app_for_row(self, row: int) -> dict[str, Any] | None:
        item = self.apps_table.item(row, 1)
        if item is None:
            return None
        app_index = item.data(APP_INDEX_ROLE)
        if app_index is None:
            return None
        try:
            index = int(app_index)
        except (TypeError, ValueError):
            return None
        if 0 <= index < len(self.all_apps):
            return self.all_apps[index]
        return None

    def _find_row_for_app(self, app: dict[str, Any]) -> int | None:
        target_index = app.get("_migration", {}).get("app_index")
        if target_index is None:
            try:
                target_index = self.all_apps.index(app)
            except ValueError:
                return None
        for row in range(self.apps_table.rowCount()):
            item = self.apps_table.item(row, 1)
            if not item:
                continue
            app_index = item.data(APP_INDEX_ROLE)
            if app_index is None:
                continue
            try:
                if int(app_index) == int(target_index):
                    return row
            except (TypeError, ValueError):
                continue
        return None

    def _update_app_row_display(self, app: dict[str, Any], table_row: int | None) -> None:
        if table_row is None:
            table_row = self._find_row_for_app(app)
        if table_row is None:
            return

        status_details = app_status_details(app)
        status_item = self.apps_table.item(table_row, 3)
        if status_item:
            status_item.setText(status_details["label"])
            status_item.setForeground(QColor(status_details["color"]))
            status_item.setToolTip(status_details["tooltip"])
            status_item.setData(Qt.ItemDataRole.UserRole, status_details["sort_value"])
            status_item.setData(Qt.ItemDataRole.UserRole + 1, status_details.get("category_key"))

    def _save_user_connector_override(self, app: dict[str, Any], selection: dict[str, Any]) -> None:
        """Save user's connector selection to database for use during migration.

        This is the critical fix that ensures user-reviewed applications actually migrate
        instead of being skipped.

        Args:
            app: The Okta application
            selection: The user's connector selection (from ApplicationMigrationDialog)
        """
        try:
            # Only save connector selections (not custom SAML/OIDC which don't need overrides)
            if selection.get("type") != "connector":
                LOGGER.debug(
                    "Skipping database save for non-connector selection type: %s",
                    selection.get("type"),
                )
                return

            connector_id = selection.get("id")
            connector_name = selection.get("name", "Unknown")

            if not connector_id:
                LOGGER.warning("Connector selection missing ID, cannot save to database")
                return

            # Get app label and normalize it (same logic as migration runtime)
            app_label = app.get("label") or app.get("name")
            if not app_label:
                LOGGER.warning("Application missing label/name, cannot save override")
                return

            # Normalize label to match migration lookup logic
            from onelogin_migration_core.manager import MigrationManager

            normalized_label = MigrationManager._normalize_app_label(app_label)

            if not normalized_label:
                LOGGER.warning("Normalized label is empty for app: %s", app_label)
                return

            # Save to database
            db = get_database_manager()
            confidence = app.get("_migration", {}).get("confidence_score", 0.0)
            notes = f"User-selected connector: {connector_name} (confidence: {confidence:.1f}%)"

            db.save_user_override(
                okta_internal_name=normalized_label,
                onelogin_id=connector_id,
                notes=notes,
            )

            LOGGER.info(
                "Saved user override to database: '%s' -> connector %d (%s)",
                app_label,
                connector_id,
                connector_name,
            )

        except Exception as e:
            # Don't let database errors block the UI workflow
            LOGGER.error(
                "Failed to save user connector override for '%s' (non-fatal): %s",
                app.get("label", "Unknown"),
                e,
            )

    def _apply_table_style(self, table: QTableWidget):
        """Apply consistent professional styling to tables."""
        table.setStyleSheet(
            """
            QTableWidget {
                background-color: #2b2b2b;
                alternate-background-color: #242424;
                color: #e0e0e0;
                gridline-color: #424242;
                border: 1px solid #424242;
                selection-background-color: #0d47a1;
                selection-color: #ffffff;
                font-size: 13px;
            }
            QTableWidget::item {
                padding: 10px 8px;
                border-right: 1px solid #333333;
                border-bottom: 1px solid #333333;
                color: #e0e0e0;
            }
            QTableWidget::item:alternate {
                background-color: #242424;
                color: #e0e0e0;
            }
            QTableWidget::item:hover {
                background-color: #363636;
                color: #ffffff;
            }
            QTableWidget::item:selected {
                background-color: #0d47a1;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #1e1e1e;
                color: #e0e0e0;
                padding: 12px 10px;
                border: none;
                border-bottom: 2px solid #0ea5e9;
                border-right: 1px solid #333333;
                font-weight: 600;
                font-size: 13px;
                line-height: 1.3;
            }
            QHeaderView::section:hover {
                background-color: #242424;
                color: #ffffff;
            }
            QHeaderView::section:pressed {
                background-color: #363636;
            }
            QScrollBar:vertical {
                background: #1e1e1e;
                width: 14px;
                border-radius: 7px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #424242;
                border-radius: 7px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #525252;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                background: #1e1e1e;
                height: 14px;
                border-radius: 7px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #424242;
                border-radius: 7px;
                min-width: 30px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #525252;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """
        )

    def _apply_search_box_style(self, search_box: QLineEdit):
        """Apply consistent dark mode styling to search boxes."""
        search_box.setStyleSheet(
            """
            QLineEdit {
                background-color: #1e1e1e;
                color: #e0e0e0;
                border: 1px solid #424242;
                border-radius: 4px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #0ea5e9;
                background-color: #242424;
            }
            QLineEdit::placeholder {
                color: #666666;
            }
        """
        )

    def _apply_combobox_style(self, combobox: QComboBox):
        """Apply consistent dark mode styling to comboboxes."""
        combobox.setStyleSheet(
            """
            QComboBox {
                background-color: #1e1e1e;
                color: #e0e0e0;
                border: 1px solid #424242;
                border-radius: 4px;
                padding: 8px 12px;
                min-width: 120px;
                font-size: 13px;
            }
            QComboBox:hover {
                border: 1px solid #525252;
                background-color: #242424;
            }
            QComboBox:focus {
                border: 1px solid #0ea5e9;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox::down-arrow {
                width: 12px;
                height: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: #2b2b2b;
                color: #e0e0e0;
                selection-background-color: #0d47a1;
                selection-color: #ffffff;
                border: 1px solid #424242;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                padding: 8px 12px;
                min-height: 30px;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #363636;
            }
        """
        )

    def _apply_pagination_button_style(self, button: QPushButton):
        """Apply consistent dark mode styling to pagination buttons."""
        button.setStyleSheet(
            """
            QPushButton {
                background-color: #363636;
                color: #a0a0a0;
                border: 1px solid #424242;
                border-radius: 4px;
                padding: 8px 20px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover:!disabled {
                background-color: #424242;
                color: #e0e0e0;
                border: 1px solid #525252;
            }
            QPushButton:pressed {
                background-color: #2b2b2b;
            }
            QPushButton:disabled {
                background-color: #242424;
                color: #555555;
                border: 1px solid #333333;
            }
        """
        )

    def _populate_users_table(self):
        """Compatibility wrapper for legacy calls."""
        if hasattr(self, "users_table_manager"):
            self.users_table_manager.populate()

    def _populate_groups_table(self):
        """Compatibility wrapper for legacy calls."""
        if hasattr(self, "groups_table_manager"):
            self.groups_table_manager.populate()

    def _show_group_members(self, group_id: str, group_name: str):
        if hasattr(self, "groups_table_manager"):
            self.groups_table_manager.show_group_members(group_id, group_name)

    def _on_group_item_double_clicked(self, item: QTableWidgetItem) -> None:
        if hasattr(self, "groups_table_manager"):
            self.groups_table_manager.on_item_double_clicked(item)

    def _on_group_item_activated(self, item: QTableWidgetItem) -> None:
        if hasattr(self, "groups_table_manager"):
            self.groups_table_manager.on_item_activated(item)

    def _open_group_members_from_row(self, row: int) -> None:
        if hasattr(self, "groups_table_manager"):
            self.groups_table_manager.open_members_for_row(row)

    def _populate_apps_table(self):
        """Compatibility wrapper for legacy calls."""
        if hasattr(self, "apps_table_manager"):
            self.apps_table_manager.populate()

    def _populate_attrs_table(self):
        """Compatibility wrapper for legacy calls."""
        if hasattr(self, "attrs_table_manager"):
            self.attrs_table_manager.populate()

    def _filter_users_table(self):
        if hasattr(self, "users_table_manager"):
            self.users_table_manager.apply_filters()

    def _filter_groups_table(self):
        if hasattr(self, "groups_table_manager"):
            self.groups_table_manager.apply_filters()

    def _filter_apps_table(self):
        if hasattr(self, "apps_table_manager"):
            self.apps_table_manager.apply_filters()

    def _filter_attrs_table(self):
        if hasattr(self, "attrs_table_manager"):
            self.attrs_table_manager.apply_filters()

    def _update_users_count(self):
        if hasattr(self, "users_table_manager"):
            self.users_table_manager.update_count()

    def _update_users_pagination_controls(self):
        if hasattr(self, "users_table_manager"):
            self.users_table_manager.update_pagination()

    def _users_prev_page(self):
        """Go to previous page of users."""
        if self.users_current_page > 0:
            self.users_current_page -= 1
            self._populate_users_table()

    def _users_next_page(self):
        """Go to next page of users."""
        total_users = len(self.all_users)
        total_pages = (total_users + self.page_size - 1) // self.page_size
        if self.users_current_page < total_pages - 1:
            self.users_current_page += 1
            self._populate_users_table()

    def _update_groups_count(self):
        if hasattr(self, "groups_table_manager"):
            self.groups_table_manager.update_count()

    def _update_groups_pagination_controls(self):
        if hasattr(self, "groups_table_manager"):
            self.groups_table_manager.update_pagination()

    def _groups_prev_page(self):
        """Go to previous page of groups."""
        if self.groups_current_page > 0:
            self.groups_current_page -= 1
            self._populate_groups_table()

    def _groups_next_page(self):
        """Go to next page of groups."""
        total_groups = len(self.all_groups)
        total_pages = (total_groups + self.page_size - 1) // self.page_size
        if self.groups_current_page < total_pages - 1:
            self.groups_current_page += 1
            self._populate_groups_table()

    def _update_apps_count(self):
        if hasattr(self, "apps_table_manager"):
            self.apps_table_manager.update_count()

    def _update_apps_pagination_controls(self):
        if hasattr(self, "apps_table_manager"):
            self.apps_table_manager.update_pagination()

    def _apps_prev_page(self):
        """Go to previous page of apps."""
        if self.apps_current_page > 0:
            self.apps_current_page -= 1
            self._populate_apps_table()

    def _apps_next_page(self):
        """Go to next page of apps."""
        total_apps = len(self.all_apps)
        total_pages = (total_apps + self.page_size - 1) // self.page_size
        if self.apps_current_page < total_pages - 1:
            self.apps_current_page += 1
            self._populate_apps_table()

    def _update_attrs_count(self):
        if hasattr(self, "attrs_table_manager"):
            self.attrs_table_manager.update_count()

    def _update_attrs_pagination_controls(self):
        if hasattr(self, "attrs_table_manager"):
            self.attrs_table_manager.update_pagination()

    def _attrs_prev_page(self):
        """Go to previous page of custom attributes."""
        if self.attrs_current_page > 0:
            self.attrs_current_page -= 1
            self._populate_attrs_table()

    def _attrs_next_page(self):
        """Go to next page of custom attributes."""
        total_attrs = len(self.all_custom_attrs)
        total_pages = (total_attrs + self.page_size - 1) // self.page_size
        if self.attrs_current_page < total_pages - 1:
            self.attrs_current_page += 1
            self._populate_attrs_table()

    def get_selections(self) -> dict[str, dict[str, Any]]:
        """Collect all selected items from all table managers using inverse selection.

        For scalability with 100k+ entities, uses whichever representation is smaller:
        - If most items are selected: store excluded IDs (inverse=True)
        - If most items are unselected: store selected IDs (inverse=False)

        Returns:
            dict with keys: 'users', 'groups', 'applications', 'custom_attributes'
            Each value is a dict with: {'ids': set[str], 'inverse': bool}
            - inverse=True: 'ids' are EXCLUDED (all others included)
            - inverse=False: 'ids' are INCLUDED (all others excluded)
            - Empty 'ids' with inverse=True means "all selected"
            - Empty 'ids' with inverse=False means "none selected"
        """
        selections = {}

        # Users
        if hasattr(self, "users_table_manager"):
            selected_users = self.users_table_manager.get_all_selected_keys()
            all_user_ids = {str(u.get("id")) for u in self.all_users if u.get("id")}

            # Choose smaller representation
            num_selected = len(selected_users)
            num_total = len(all_user_ids)
            if num_selected >= num_total / 2:
                # Most are selected → store excluded IDs
                excluded = all_user_ids - selected_users
                selections["users"] = {"ids": excluded, "inverse": True}
                LOGGER.info(
                    f"Users: {num_selected}/{num_total} selected, storing {len(excluded)} excluded IDs"
                )
            else:
                # Most are unselected → store selected IDs
                selections["users"] = {"ids": selected_users, "inverse": False}
                LOGGER.info(
                    f"Users: {num_selected}/{num_total} selected, storing {num_selected} selected IDs"
                )
        else:
            selections["users"] = {"ids": set(), "inverse": True}

        # Groups
        if hasattr(self, "groups_table_manager"):
            selected_groups = self.groups_table_manager.get_all_selected_keys()
            all_group_ids = {str(g.get("id")) for g in self.all_groups if g.get("id")}

            num_selected = len(selected_groups)
            num_total = len(all_group_ids)
            if num_selected >= num_total / 2:
                excluded = all_group_ids - selected_groups
                selections["groups"] = {"ids": excluded, "inverse": True}
                LOGGER.info(
                    f"Groups: {num_selected}/{num_total} selected, storing {len(excluded)} excluded IDs"
                )
            else:
                selections["groups"] = {"ids": selected_groups, "inverse": False}
                LOGGER.info(
                    f"Groups: {num_selected}/{num_total} selected, storing {num_selected} selected IDs"
                )
        else:
            selections["groups"] = {"ids": set(), "inverse": True}

        # Applications
        if hasattr(self, "apps_table_manager"):
            selected_apps = self.apps_table_manager.get_all_selected_keys()
            all_app_ids = {str(a.get("id")) for a in self.all_apps if a.get("id")}

            num_selected = len(selected_apps)
            num_total = len(all_app_ids)
            if num_selected >= num_total / 2:
                excluded = all_app_ids - selected_apps
                selections["applications"] = {"ids": excluded, "inverse": True}
                LOGGER.info(
                    f"Apps: {num_selected}/{num_total} selected, storing {len(excluded)} excluded IDs"
                )
            else:
                selections["applications"] = {"ids": selected_apps, "inverse": False}
                LOGGER.info(
                    f"Apps: {num_selected}/{num_total} selected, storing {num_selected} selected IDs"
                )
        else:
            selections["applications"] = {"ids": set(), "inverse": True}

        # Custom Attributes
        if hasattr(self, "attrs_table_manager"):
            selected_attrs = self.attrs_table_manager.get_all_selected_keys()
            all_attr_names = set(self.all_custom_attrs)

            num_selected = len(selected_attrs)
            num_total = len(all_attr_names)
            if num_selected >= num_total / 2:
                excluded = all_attr_names - selected_attrs
                selections["custom_attributes"] = {"ids": excluded, "inverse": True}
                LOGGER.info(
                    f"Attrs: {num_selected}/{num_total} selected, storing {len(excluded)} excluded names"
                )
            else:
                selections["custom_attributes"] = {
                    "ids": selected_attrs,
                    "inverse": False,
                }
                LOGGER.info(
                    f"Attrs: {num_selected}/{num_total} selected, storing {num_selected} selected names"
                )
        else:
            selections["custom_attributes"] = {"ids": set(), "inverse": True}

        return selections

    def closeEvent(self, event):
        """Handle dialog close - cleanup all table managers to free memory."""
        # Cleanup all table managers to explicitly delete checkboxes
        # This prevents memory leaks from accumulated widgets
        for manager_attr in [
            "users_table_manager",
            "groups_table_manager",
            "apps_table_manager",
            "attrs_table_manager",
        ]:
            manager = getattr(self, manager_attr, None)
            if manager and hasattr(manager, "_reset_selection_state"):
                try:
                    # This will disconnect and delete all checkboxes
                    manager._reset_selection_state()
                except Exception as e:
                    LOGGER.warning(f"Error cleaning up {manager_attr}: {e}")

        super().closeEvent(event)
