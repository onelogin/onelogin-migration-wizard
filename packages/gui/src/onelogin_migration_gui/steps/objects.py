"""Object selection page."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..components import ModernButton, ModernCard, ModernCheckbox
from ..dialogs.analysis_detail.dialog import AnalysisDetailDialog
from ..dialogs.analysis_detail.utils.status_helpers import app_status_details
from .base import BasePage

if TYPE_CHECKING:  # pragma: no cover
    from .. import WizardState

# Object metadata: (display_name, description, accent_color)
OBJECT_METADATA = {
    "users": (
        "Users",
        "Migrate user accounts, profiles, status (active/inactive), and custom attributes",
        "primary",
    ),
    "groups": (
        "Groups",
        "Migrate groups as OneLogin roles and group memberships (requires Users to be selected for memberships)",
        "secondary",
    ),
    "applications": (
        "Applications",
        "Migrate application configurations with connector mappings, SSO settings, visibility, and descriptions",
        "info",
    ),
    "custom_attributes": (
        "Custom Attributes",
        "Discover and create custom attribute definitions in OneLogin before migration (Included when migrating Users)",
        "warning",
    ),
}

OBJECT_KEYS = tuple(OBJECT_METADATA.keys())


class ObjectSelectionPage(BasePage):
    def __init__(self) -> None:
        super().__init__("Step 4 – Select Objects to Migrate")

        # Set compact spacing and margins
        self.body_layout.setSpacing(self.theme_manager.get_spacing("xs"))
        self.body_layout.setContentsMargins(
            self.theme_manager.get_spacing("lg"),  # left
            self.theme_manager.get_spacing("xs"),  # top - compact
            self.theme_manager.get_spacing("lg"),  # right
            self.theme_manager.get_spacing("xs"),  # bottom - compact
        )

        # Header - more compact
        subtitle = QLabel("Choose which data to include in your migration")

        def update_subtitle_style():
            subtitle.setStyleSheet(
                f"""
                QLabel {{
                    font-size: 13px;
                    color: {self.theme_manager.get_color('text_secondary')};
                    margin-bottom: {self.theme_manager.get_spacing('xs')}px;
                }}
            """
            )

        update_subtitle_style()
        self.theme_manager.theme_changed.connect(update_subtitle_style)
        subtitle.setWordWrap(True)
        self.body_layout.addWidget(subtitle)

        # Object checkboxes in individual cards
        self.checkboxes: dict[str, QCheckBox] = {}
        self.object_labels: dict[str, tuple] = (
            {}
        )  # Store (primary_label, desc_label) for theme updates
        self.count_labels: dict[str, QLabel] = {}  # Store count labels for updates
        self.app_configure_button: QPushButton | None = None  # Configure button for apps
        self._current_state: WizardState | None = None  # Store state for refresh
        for key in OBJECT_KEYS:
            display_name, description, accent_color = OBJECT_METADATA[key]

            # Create card for this object with compact padding
            card = ModernCard(accent_color=accent_color, elevated=True, padding="sm")

            # Create main vertical layout for card content
            card_main_layout = QVBoxLayout()
            card_main_layout.setSpacing(self.theme_manager.get_spacing("xs"))
            card_main_layout.setContentsMargins(0, 0, 0, 0)

            # Create horizontal layout for checkbox and labels
            option_layout = QHBoxLayout()
            option_layout.setSpacing(self.theme_manager.get_spacing("sm"))
            option_layout.setContentsMargins(0, 0, 0, 0)

            # Create modern checkbox
            checkbox = ModernCheckbox()
            checkbox.setFixedSize(20, 20)  # Smaller checkbox
            self.checkboxes[key] = checkbox

            # Create vertical layout for labels
            labels_layout = QVBoxLayout()
            labels_layout.setSpacing(2)  # Very tight spacing between title and description
            labels_layout.setContentsMargins(0, 0, 0, 0)

            # Primary label with count
            primary_layout = QHBoxLayout()
            primary_layout.setSpacing(self.theme_manager.get_spacing("sm"))
            primary_layout.setContentsMargins(0, 0, 0, 0)

            primary_label = QLabel(display_name)
            primary_layout.addWidget(primary_label)

            # Add count label (initially hidden, updated in on_enter)
            count_label = QLabel("")
            count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            count_label.setVisible(False)  # Hidden until we have data
            self.count_labels[key] = count_label
            primary_layout.addWidget(count_label, 1)  # Give stretch factor

            labels_layout.addLayout(primary_layout)

            # Secondary description label
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            labels_layout.addWidget(desc_label)

            # Store labels for theme updates
            self.object_labels[key] = (primary_label, desc_label)

            # Add checkbox and labels to horizontal layout
            option_layout.addWidget(checkbox, 0)  # Don't stretch checkbox
            option_layout.addLayout(labels_layout, 1)  # Give labels stretch factor

            # Add option layout to card main layout
            card_main_layout.addLayout(option_layout)

            # Special handling for Applications - add Configure button
            if key == "applications":
                config_button_layout = QHBoxLayout()
                config_button_layout.setContentsMargins(
                    0, self.theme_manager.get_spacing("xs"), 0, 0
                )
                config_button_layout.addStretch()

                self.app_configure_button = ModernButton("⚙️ Configure Applications")
                self.app_configure_button.setStyleSheet(
                    self.theme_manager.get_button_style("primary")
                )
                self.app_configure_button.clicked.connect(self._open_app_configuration)
                self.app_configure_button.setVisible(False)  # Hidden until needed

                config_button_layout.addWidget(self.app_configure_button)
                card_main_layout.addLayout(config_button_layout)

            # Add to card
            card.add_layout(card_main_layout)

            # Add card to main layout
            self.body_layout.addWidget(card)
            self.body_layout.addSpacing(self.theme_manager.get_spacing("xs"))

            # Connect signal for Users checkbox to handle Custom Attributes greying
            if key == "users":
                checkbox.stateChanged.connect(self._on_users_changed)

        # Add stretch at the end to push content to top
        self.body_layout.addStretch()

        # Connect theme changes to update all labels
        self.theme_manager.theme_changed.connect(self._update_label_styles)
        self._update_label_styles()

    def _update_label_styles(self) -> None:
        """Update all object label styles when theme changes."""
        for primary_label, desc_label in self.object_labels.values():
            primary_label.setStyleSheet(
                f"""
                QLabel {{
                    font-weight: 600;
                    font-size: 14px;
                    color: {self.theme_manager.get_color('text_primary')};
                    background: transparent;
                    border: none;
                    padding: 0px;
                    margin: 0px;
                }}
            """
            )
            desc_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self.theme_manager.get_color('text_secondary')};
                    font-size: 11px;
                    line-height: 1.3;
                    background: transparent;
                    border: none;
                    padding: 0px;
                    margin: 0px;
                }}
            """
            )

        # Update count label styles
        for count_label in self.count_labels.values():
            count_label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self.theme_manager.get_color('text_secondary')};
                    font-size: 12px;
                    font-weight: 500;
                    background: transparent;
                    border: none;
                    padding: 0px;
                    margin: 0px;
                }}
            """
            )

    def _open_app_configuration(self) -> None:
        """Open AnalysisDetailDialog to configure applications needing review."""
        if not self._current_state or not self._current_state.raw_export:
            return

        # Create analysis results structure expected by AnalysisDetailDialog
        # The dialog needs raw_export and metadata for displaying totals
        raw_export = self._current_state.raw_export

        analysis_results = {
            "raw_export": raw_export,
            # Calculate totals from raw_export for header display
            "users": {"total": len(raw_export.get("users", []))},
            "groups": {"total": len(raw_export.get("groups", []))},
            "applications": {"total": len(raw_export.get("applications", []))},
            # Custom attributes metadata from users_metadata
            "custom_attributes": raw_export.get("users_metadata", {}).get("custom_attributes", []),
        }

        # Get mode from state (migration or discovery)
        mode = self._current_state.mode if self._current_state else "migration"

        # Create and show the detailed dialog
        dialog = AnalysisDetailDialog(analysis_results, mode, self)

        # Switch to Applications tab (tab index 2: Users=0, Groups=1, Applications=2)
        if hasattr(dialog, "tab_widget"):
            dialog.tab_widget.setCurrentIndex(2)

        # Apply "Needs Review" filter to applications status filter
        if hasattr(dialog, "apps_status_filter"):
            # Find "Needs Review" in the combo box and set it
            for i in range(dialog.apps_status_filter.count()):
                if dialog.apps_status_filter.itemText(i) == "Needs Review":
                    dialog.apps_status_filter.setCurrentIndex(i)
                    break

        # Show dialog modally
        dialog.exec()

        # After dialog closes, recalculate counts in case user made selections
        if self._current_state:
            # Get updated selections from dialog
            selections = dialog.get_selections()

            # Update state with new selections (using inverse selection format)
            for category in ["users", "groups", "applications", "custom_attributes"]:
                selection_data = selections.get(category, {"ids": set(), "inverse": True})
                ids = selection_data.get("ids", set())
                is_inverse = selection_data.get("inverse", True)

                # Store in appropriate field based on inverse flag
                if category == "users":
                    if is_inverse:
                        self._current_state.excluded_users = ids if ids else None
                        self._current_state.selected_users = None
                    else:
                        self._current_state.selected_users = ids if ids else None
                        self._current_state.excluded_users = None
                elif category == "groups":
                    if is_inverse:
                        self._current_state.excluded_groups = ids if ids else None
                        self._current_state.selected_groups = None
                    else:
                        self._current_state.selected_groups = ids if ids else None
                        self._current_state.excluded_groups = None
                elif category == "applications":
                    if is_inverse:
                        self._current_state.excluded_applications = ids if ids else None
                        self._current_state.selected_applications = None
                    else:
                        self._current_state.selected_applications = ids if ids else None
                        self._current_state.excluded_applications = None
                elif category == "custom_attributes":
                    if is_inverse:
                        self._current_state.excluded_custom_attributes = ids if ids else None
                        self._current_state.selected_custom_attributes = None
                    else:
                        self._current_state.selected_custom_attributes = ids if ids else None
                        self._current_state.excluded_custom_attributes = None

            # Recalculate and update counts
            counts = self._calculate_object_counts(self._current_state)
            self._update_count_displays(counts)

    def _update_count_displays(self, counts: dict[str, Any]) -> None:
        """Update count labels and configure button based on calculated counts."""
        # Users
        user_count = counts["users"]["total"]
        user_selected = counts["users"]["selected"]
        if user_selected is not None:
            self.count_labels["users"].setText(f"[{user_selected:,} / {user_count:,}]")
            self.count_labels["users"].setVisible(True)
        elif user_count > 0:
            self.count_labels["users"].setText(f"[{user_count:,} total]")
            self.count_labels["users"].setVisible(True)
        else:
            self.count_labels["users"].setVisible(False)

        # Groups
        group_count = counts["groups"]["total"]
        group_selected = counts["groups"]["selected"]
        if group_selected is not None:
            self.count_labels["groups"].setText(f"[{group_selected:,} / {group_count:,}]")
            self.count_labels["groups"].setVisible(True)
        elif group_count > 0:
            self.count_labels["groups"].setText(f"[{group_count:,} total]")
            self.count_labels["groups"].setVisible(True)
        else:
            self.count_labels["groups"].setVisible(False)

        # Applications
        app_total = counts["applications"]["total"]
        app_ready = counts["applications"]["ready"]
        needs_config = counts["applications"]["needs_config"]
        if app_total > 0:
            self.count_labels["applications"].setText(f"[{app_ready:,} ready / {app_total:,}]")
            self.count_labels["applications"].setVisible(True)
        else:
            self.count_labels["applications"].setVisible(False)

        # Show/hide configure button based on needs_config count
        if self.app_configure_button:
            if needs_config > 0:
                self.app_configure_button.setText(f"⚙️ Configure {needs_config:,} Apps")
                self.app_configure_button.setVisible(True)
            else:
                self.app_configure_button.setVisible(False)

        # Custom Attributes
        attr_count = counts["custom_attributes"]["total"]
        if attr_count > 0:
            self.count_labels["custom_attributes"].setText(f"[{attr_count:,} attributes]")
            self.count_labels["custom_attributes"].setVisible(True)
        else:
            self.count_labels["custom_attributes"].setVisible(False)

    def _calculate_object_counts(self, state: WizardState) -> dict[str, Any]:
        """Calculate readiness counts for each object type.

        Returns dict with structure:
        {
            "users": {"total": int, "selected": int | None},
            "groups": {"total": int, "selected": int | None},
            "applications": {"total": int, "ready": int, "needs_config": int},
            "custom_attributes": {"total": int},
        }
        """
        counts: dict[str, Any] = {
            "users": {"total": 0, "selected": None},
            "groups": {"total": 0, "selected": None},
            "applications": {"total": 0, "ready": 0, "needs_config": 0},
            "custom_attributes": {"total": 0},
        }

        # Get raw export data
        raw_export = state.raw_export if state else None
        if not raw_export:
            return counts

        # Users count
        all_users = raw_export.get("users", [])
        counts["users"]["total"] = len(all_users)
        if state.selected_users is not None:
            counts["users"]["selected"] = len(state.selected_users)
        elif state.excluded_users is not None:
            counts["users"]["selected"] = counts["users"]["total"] - len(state.excluded_users)

        # Groups count
        all_groups = raw_export.get("groups", [])
        counts["groups"]["total"] = len(all_groups)
        if state.selected_groups is not None:
            counts["groups"]["selected"] = len(state.selected_groups)
        elif state.excluded_groups is not None:
            counts["groups"]["selected"] = counts["groups"]["total"] - len(state.excluded_groups)

        # Applications - categorize by readiness
        all_apps = raw_export.get("applications", [])
        ready_count = 0
        needs_config_count = 0
        total_active = 0  # Exclude inactive apps from total

        for app in all_apps:
            status_details = app_status_details(app)
            category_key = status_details.get("category_key")

            # Get migration metadata to check readiness
            migration_meta = app.get("_migration", {})
            selection = migration_meta.get("selection")
            user_reviewed = migration_meta.get("user_reviewed", False)
            confidence = float(migration_meta.get("confidence_score", 0.0))

            # Skip inactive, unsupported, and manual migration apps
            if category_key in ("inactive", "unsupported", "manual"):
                continue

            total_active += 1

            # Ready to migrate: has user selection OR user reviewed OR 100% match
            if selection or user_reviewed or confidence >= 99.5:
                ready_count += 1
            # Needs configuration: everything else that's technically migratable
            else:
                needs_config_count += 1

        counts["applications"]["total"] = total_active
        counts["applications"]["ready"] = ready_count
        counts["applications"]["needs_config"] = needs_config_count

        # Custom attributes count
        users_data = raw_export.get("users_metadata", {})
        custom_attrs = users_data.get("custom_attributes", [])
        counts["custom_attributes"]["total"] = len(custom_attrs)

        return counts

    def _on_users_changed(self) -> None:
        """Handle Users checkbox state change to grey out Custom Attributes."""
        users_checked = self.checkboxes["users"].isChecked()
        custom_attrs_checkbox = self.checkboxes["custom_attributes"]

        if users_checked:
            # Grey out Custom Attributes when Users is selected
            custom_attrs_checkbox.setEnabled(False)
            custom_attrs_checkbox.setChecked(False)
            custom_attrs_checkbox.setToolTip(
                "Custom Attributes are included in the Users migration"
            )
        else:
            # Re-enable Custom Attributes when Users is unchecked
            custom_attrs_checkbox.setEnabled(True)
            custom_attrs_checkbox.setToolTip("")

    def on_enter(self, state: WizardState) -> None:
        super().on_enter(state)
        self._current_state = state

        for key, checkbox in self.checkboxes.items():
            checkbox.setChecked(bool(state.objects.get(key, False)))

        # Update Custom Attributes state based on Users checkbox
        self._on_users_changed()

        # Calculate and display counts
        counts = self._calculate_object_counts(state)
        self._update_count_displays(counts)

    def collect(self, state: WizardState) -> None:
        super().collect(state)
        state.objects.update(
            {key: checkbox.isChecked() for key, checkbox in self.checkboxes.items()}
        )

    def validate(self, state: WizardState) -> tuple[bool, str]:
        if any(checkbox.isChecked() for checkbox in self.checkboxes.values()):
            return True, ""
        return False, "Select at least one object to migrate."
