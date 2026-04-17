"""Modern analysis wizard page that hosts the modular analysis UI."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from onelogin_migration_core.clients import OneLoginClient, build_source_client
from onelogin_migration_core.config import OneLoginApiSettings
from onelogin_migration_core.db import get_database_manager
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..analysis import AnalysisModel, AnalysisView
from ..dialogs import AnalysisDetailDialog
from ..dialogs.analysis_detail.export.export_utils import TableExportData
from ..dialogs.analysis_detail.export.xlsx_exporter import XLSXExporter
from ..theme_manager import ThemeMode
from .analysis_old import AnalysisWorker
from .base import BasePage

if TYPE_CHECKING:
    from .. import WizardState

LOGGER = logging.getLogger(__name__)

_AnalysisState = Literal["placeholder", "loading", "results", "error"]


class AnalysisPage(BasePage):
    """Wizard page that kicks off environment analysis and binds data to the new UI."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Step 5 – Environment Analysis")
        self.analysis_results: dict[str, Any] | None = None
        self.worker: AnalysisWorker | None = None
        self.auto_analyze = True
        self._detailed_dialog: AnalysisDetailDialog | None = None

        self._current_state: _AnalysisState = "placeholder"
        self._last_error: str | None = None

        self.stack = QStackedWidget()
        self.body_layout.addWidget(self.stack, 1)

        self.placeholder_widget = self._build_placeholder()
        self.loading_widget = self._build_loading_panel()
        self.error_widget = self._build_error_panel()
        self.analysis_view = AnalysisView()
        self.analysis_view.enable_report_actions(False)

        self.stack.addWidget(self.placeholder_widget)
        self.stack.addWidget(self.loading_widget)
        self.stack.addWidget(self.analysis_view)
        self.stack.addWidget(self.error_widget)

        self.analysis_view.refresh_requested.connect(self.run_analysis)
        self.analysis_view.view_report_requested.connect(self.open_detailed_report)
        self.analysis_view.download_report_requested.connect(self._handle_download_request)
        self.analysis_view.filter_apps_requested.connect(self._handle_filter_request)

        self._set_state("placeholder")
        self._apply_theme()

    # ------------------------------------------------------------------ UI builders
    def _build_placeholder(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(60, 60, 60, 60)
        layout.setSpacing(20)

        self.placeholder_title = QLabel("Analyze your source environment")
        self.placeholder_title.setWordWrap(True)
        layout.addWidget(self.placeholder_title)

        self.placeholder_desc = QLabel(
            "Run the automated analysis to understand users, groups, applications, and "
            "policies before migrating to OneLogin."
        )
        self.placeholder_desc.setWordWrap(True)
        layout.addWidget(self.placeholder_desc)

        layout.addStretch(1)

        self.placeholder_button = QPushButton("Start Analysis")
        self.placeholder_button.clicked.connect(self.run_analysis)
        layout.addWidget(self.placeholder_button)

        layout.addStretch(3)
        return widget

    def _build_loading_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(80, 80, 80, 80)
        layout.setSpacing(20)

        self.status_label = QLabel("Preparing to analyse…")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setMinimumHeight(16)
        layout.addWidget(self.progress_bar)

        layout.addStretch(1)
        return widget

    def _build_error_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(60, 60, 60, 60)
        layout.setSpacing(20)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        layout.addStretch(1)

        self.retry_button = QPushButton("Retry Analysis")
        self.retry_button.clicked.connect(self.run_analysis)
        layout.addWidget(self.retry_button)

        layout.addStretch(2)
        return widget

    # ---------------------------------------------------------------- theme support
    def _apply_theme(self) -> None:
        super()._apply_theme()
        self._apply_placeholder_styles()
        self._apply_loading_styles()
        self._apply_error_styles()

    def _apply_placeholder_styles(self) -> None:
        if not hasattr(self, "placeholder_widget"):
            return
        heading_color = self.theme_manager.get_color("text_primary")
        text_color = self.theme_manager.get_color("text_secondary")
        background = self.theme_manager.get_color("background")
        self.placeholder_widget.setStyleSheet(f"background-color: {background};")
        self.placeholder_title.setStyleSheet(
            f"font-size: 22px; font-weight: 600; color: {heading_color};"
        )
        self.placeholder_desc.setStyleSheet(f"font-size: 14px; color: {text_color};")
        self.placeholder_button.setStyleSheet(self.theme_manager.get_button_style("primary"))

    def _apply_loading_styles(self) -> None:
        if not hasattr(self, "loading_widget"):
            return
        primary = self.theme_manager.get_color("primary")
        text_primary = self.theme_manager.get_color("text_primary")
        surface = self.theme_manager.get_color("surface_elevated")
        self.status_label.setStyleSheet(
            f"color: {primary}; font-size: 16px; font-weight: 600; background-color: transparent;"
        )
        self.loading_widget.setStyleSheet(f"background-color: {surface}; border-radius: 12px;")
        self.progress_bar.setStyleSheet(
            f"""
            QProgressBar {{
                border: 1px solid {primary};
                border-radius: 6px;
                text-align: center;
                color: {text_primary};
            }}
            QProgressBar::chunk {{
                background-color: {primary};
                border-radius: 4px;
            }}
        """
        )

    def _apply_error_styles(self) -> None:
        if not hasattr(self, "error_widget"):
            return
        error_bg = self.theme_manager.get_color("error_light")
        error_text = self.theme_manager.get_color("error")
        surface = self.theme_manager.get_color("surface")
        self.error_widget.setStyleSheet(f"background-color: {surface}; border-radius: 12px;")
        self.error_label.setStyleSheet(
            f"""
            color: {error_text};
            background-color: {error_bg};
            border-left: 4px solid {error_text};
            padding: {self.theme_manager.get_spacing('md')}px;
            font-size: 14px;
            font-weight: 600;
        """
        )
        self.retry_button.setStyleSheet(self.theme_manager.get_button_style("secondary"))

    def _on_theme_changed(self, mode: ThemeMode) -> None:
        super()._on_theme_changed(mode)
        # AnalysisView manages its own theme bindings internally.

    # ---------------------------------------------------------------- state helpers
    def _set_state(self, state: _AnalysisState) -> None:
        self._current_state = state
        if state == "placeholder":
            self.stack.setCurrentWidget(self.placeholder_widget)
            self.analysis_view.enable_report_actions(False)
            self.analysis_view.set_completion_message(None)
        elif state == "loading":
            self.stack.setCurrentWidget(self.loading_widget)
            self.analysis_view.enable_report_actions(False)
            self.analysis_view.set_completion_message(None)
        elif state == "results":
            self.stack.setCurrentWidget(self.analysis_view)
        elif state == "error":
            self.stack.setCurrentWidget(self.error_widget)
            self.analysis_view.enable_report_actions(False)
            self.analysis_view.set_completion_message(None)

    # ----------------------------------------------------------------- Qt lifecycle
    def on_enter(self, state: WizardState) -> None:
        super().on_enter(state)

        source_name = state.source_provider if state else "Source"
        self.placeholder_title.setText(f"Analyze your {source_name} environment")
        self.placeholder_desc.setText(
            f"Run the automated analysis to understand users, groups, applications, and policies "
            f"before migrating from {source_name} to OneLogin."
        )

        if self.analysis_results:
            self._set_state("results")
        elif self.auto_analyze:
            QTimer.singleShot(100, self.run_analysis)

    # ------------------------------------------------------------------ navigation
    def can_proceed(self, state: WizardState) -> bool:
        result = self.analysis_results is not None
        LOGGER.info("AnalysisPage.can_proceed -> %s", result)
        return result

    def validate(self, state: WizardState) -> tuple[bool, str]:
        if self.analysis_results is not None:
            return True, ""
        return False, "Please wait for the environment analysis to complete."

    def collect(self, state: WizardState) -> None:
        super().collect(state)
        if state is not None and self.analysis_results:
            state.raw_export = self.analysis_results.get("raw_export")

            # Collect selections from the detailed dialog if it was opened
            if self._detailed_dialog:
                selections = self._detailed_dialog.get_selections()

                # Store selections in WizardState using inverse selection format
                # Each selection is {'ids': set, 'inverse': bool}
                for category in [
                    "users",
                    "groups",
                    "applications",
                    "custom_attributes",
                ]:
                    selection_data = selections.get(category, {"ids": set(), "inverse": True})
                    ids = selection_data.get("ids", set())
                    is_inverse = selection_data.get("inverse", True)

                    # Store in appropriate field based on inverse flag
                    if category == "users":
                        if is_inverse:
                            state.excluded_users = ids if ids else None
                            state.selected_users = None
                        else:
                            state.selected_users = ids if ids else None
                            state.excluded_users = None
                    elif category == "groups":
                        if is_inverse:
                            state.excluded_groups = ids if ids else None
                            state.selected_groups = None
                        else:
                            state.selected_groups = ids if ids else None
                            state.excluded_groups = None
                    elif category == "applications":
                        if is_inverse:
                            state.excluded_applications = ids if ids else None
                            state.selected_applications = None
                        else:
                            state.selected_applications = ids if ids else None
                            state.excluded_applications = None
                    elif category == "custom_attributes":
                        if is_inverse:
                            state.excluded_custom_attributes = ids if ids else None
                            state.selected_custom_attributes = None
                        else:
                            state.selected_custom_attributes = ids if ids else None
                            state.excluded_custom_attributes = None

                LOGGER.info(
                    f"Saved selections to state - "
                    f"Users: {len(state.selected_users or state.excluded_users or set())} IDs, "
                    f"Groups: {len(state.selected_groups or state.excluded_groups or set())} IDs, "
                    f"Apps: {len(state.selected_applications or state.excluded_applications or set())} IDs, "
                    f"Attrs: {len(state.selected_custom_attributes or state.excluded_custom_attributes or set())} IDs"
                )

    # ---------------------------------------------------------------- worker wiring
    def run_analysis(self) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.information(
                self,
                "Analysis in progress",
                "An environment analysis is already running. Please wait for it to finish.",
            )
            return

        if not self._state:
            QMessageBox.warning(self, "Configuration Missing", "Wizard state not initialized.")
            return

        source_settings = self._state.source_settings
        if not source_settings:
            QMessageBox.warning(
                self,
                "Configuration Missing",
                f"Please configure {self._state.source_provider} settings first.",
            )
            return

        provider = self._state.source_provider if self._state else "Source"
        domain = source_settings.get("domain", "").strip()
        token = source_settings.get("token", "").strip()

        if not domain or not token:
            QMessageBox.warning(
                self,
                "Configuration Missing",
                f"{provider} domain and API token are required.",
            )
            return

        onelogin_client: OneLoginClient | None = None
        target_settings = self._state.target_settings if self._state else {}
        if target_settings:
            try:
                client_id = (target_settings.get("client_id") or "").strip()
                client_secret = (target_settings.get("client_secret") or "").strip()
                region = (target_settings.get("region") or "us").strip() or "us"
                subdomain_target = (target_settings.get("subdomain") or "").strip()
                rate_limit_per_hour = int(target_settings.get("rate_limit_per_hour", 5000) or 5000)

                if client_id and client_secret and subdomain_target:
                    onelogin_settings = OneLoginApiSettings(
                        client_id=client_id,
                        client_secret=client_secret,
                        region=region,
                        subdomain=subdomain_target,
                        rate_limit_per_hour=rate_limit_per_hour,
                    )
                    onelogin_client = OneLoginClient(onelogin_settings)
                else:
                    LOGGER.info(
                        "OneLogin credentials incomplete; skipping connector catalog lookup."
                    )
            except (ValueError, TypeError) as exc:
                LOGGER.warning(
                    "Skipping OneLogin connector lookup due to configuration error: %s",
                    exc,
                )

        self._set_state("loading")
        self.status_label.setText(f"Connecting to {self._state.source_provider}…")
        self._last_error = None

        source_client = build_source_client(self._state.to_migration_settings())
        self.worker = AnalysisWorker(source_client, onelogin_client)
        self.worker.progress_update.connect(self.on_progress_update)
        self.worker.analysis_complete.connect(self.on_analysis_complete)
        self.worker.analysis_error.connect(self.on_analysis_error)
        self.worker.start()

    def on_progress_update(self, message: str) -> None:
        self.status_label.setText(message)

    def on_analysis_complete(self, results: dict[str, Any]) -> None:
        self.analysis_results = results
        if self._state:
            self._state.raw_export = results.get("raw_export")

        model = AnalysisModel.from_results(results)
        self.analysis_view.bind(model)

        self._set_state("results")

        # Auto-save 100% connector matches to database
        self._auto_save_perfect_matches(results)

        LOGGER.info("Analysis complete. Results captured: %s", self.analysis_results is not None)
        self.completeChanged.emit()

    def on_analysis_error(self, error_message: str) -> None:
        LOGGER.error("Analysis failed: %s", error_message)
        self._last_error = error_message
        self.error_label.setText(
            f"⚠️ Analysis failed\n\n{error_message}\n\nVerify the source credentials and network "
            "connectivity, then try again."
        )
        self._set_state("error")
        self.completeChanged.emit()

    def _auto_save_perfect_matches(self, results: dict[str, Any]) -> None:
        """Auto-save 100% connector matches to user_connector_overrides database.

        This ensures apps with perfect matches (≥99.5% confidence) are automatically
        approved and will migrate successfully without requiring manual review.
        """
        try:
            db = get_database_manager()

            # Get all applications from results
            raw_export = results.get("raw_export", {})
            applications = raw_export.get("applications", [])

            if not applications:
                LOGGER.debug("No applications found in analysis results for auto-save")
                return

            # Collect all 100% matches
            perfect_matches = []
            for app in applications:
                migration_meta = app.get("_migration", {})
                category = migration_meta.get("category")

                # Only auto-save connector matches
                if category != "connector":
                    continue

                confidence = float(migration_meta.get("confidence_score", 0.0))

                # Check for 100% match (≥99.5%)
                if confidence >= 99.5:
                    connector = migration_meta.get("connector", {})
                    connector_id = connector.get("id")
                    connector_name = connector.get("name", "Unknown")

                    # Get app label for the override key
                    app_label = app.get("label") or app.get("name")
                    if not app_label or not connector_id:
                        continue

                    # Normalize label to match migration lookup logic
                    from onelogin_migration_core.manager import MigrationManager

                    normalized_label = MigrationManager._normalize_app_label(app_label)

                    if normalized_label:
                        perfect_matches.append(
                            {
                                "okta_internal_name": normalized_label,
                                "onelogin_id": connector_id,
                                "notes": f"Auto-saved 100% match: {connector_name} (confidence: {confidence:.1f}%)",
                            }
                        )

                        # Mark as user_reviewed in metadata so status shows "Ready (100% match)"
                        # Note: This is optional since we're already at 99.5%+ confidence
                        migration_meta["auto_saved"] = True

                        LOGGER.debug(
                            "Queued auto-save for '%s' -> connector %d (%s, %.1f%% confidence)",
                            app_label,
                            connector_id,
                            connector_name,
                            confidence,
                        )

            # Batch save all perfect matches
            if perfect_matches:
                db.save_user_override_batch(perfect_matches)
                LOGGER.info(
                    "Auto-saved %d perfect connector matches (≥99.5%% confidence) to database",
                    len(perfect_matches),
                )
            else:
                LOGGER.debug("No perfect matches (≥99.5%% confidence) found for auto-save")

        except Exception as e:
            # Don't let auto-save failures break the analysis flow
            LOGGER.warning("Failed to auto-save perfect matches (non-fatal): %s", e)

    # ------------------------------------------------------------------ report ops
    def open_detailed_report(self) -> None:
        if not self.analysis_results:
            QMessageBox.warning(
                self,
                "No Analysis Data",
                "Please run the analysis first before viewing the detailed report.",
            )
            return

        # Create and show the detailed dialog
        # Store reference so we can get selections later
        self._detailed_dialog = AnalysisDetailDialog(self.analysis_results, self._state.mode, self)
        self._detailed_dialog.exec()

        # Log the current selection state
        if self._detailed_dialog:
            selections = self._detailed_dialog.get_selections()
            LOGGER.info(
                f"Dialog closed with selections - Users: {len(selections.get('users', set()))}, "
                f"Groups: {len(selections.get('groups', set()))}, "
                f"Apps: {len(selections.get('applications', set()))}, "
                f"Attrs: {len(selections.get('custom_attributes', set()))}"
            )

    def _handle_download_request(self, action_id: str) -> None:
        if not self.analysis_results:
            QMessageBox.information(self, "Analysis", "Run the analysis before downloading data.")
            return

        if action_id == "download_discovery":
            self._export_discovery_report()
        elif action_id == "download_json":
            self._export_analysis_json()
        elif action_id == "download_excel":
            self._export_analysis_tables()
        elif action_id == "print_pdf":
            QMessageBox.information(
                self,
                "Print Report",
                "PDF export is not available in this preview build.",
            )
        else:
            LOGGER.warning("Unknown analysis download action: %s", action_id)

    def _export_analysis_json(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Migration Data",
            "migration_data.json",
            "JSON Files (*.json);;All Files (*)",
        )
        if not file_path:
            return

        raw_export = self.analysis_results.get("raw_export") if self.analysis_results else None
        if raw_export is None:
            QMessageBox.information(
                self,
                "Export Unavailable",
                "Raw migration data is not available for export.",
            )
            return

        path = Path(file_path)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")

        try:
            with path.open("w", encoding="utf-8") as handle:
                json.dump(raw_export, handle, indent=2)
            QMessageBox.information(
                self,
                "Export Successful",
                f"Migration data saved to:\n{path}",
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Failed to export analysis JSON: %s", exc)
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to write migration data:\n{exc}",
            )

    def _export_analysis_tables(self) -> None:
        dialog = AnalysisDetailDialog(self.analysis_results or {}, self._state.mode, self)
        try:
            dialog.export_manager.export_all(
                ["users", "groups", "applications", "custom_attributes"]
            )
        finally:
            dialog.deleteLater()

    def _export_discovery_report(self) -> None:
        date_today = date.today().strftime("%Y-%m-%d")
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Discovery Report",
            f"Discovery_Report_{date_today}.xlsx",
            "Excel Workbook (*.xlsx)",
        )
        if not file_path:
            return

        try:
            model = AnalysisModel.from_results(self.analysis_results or {})
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Failed to build discovery model: %s", exc)
            QMessageBox.critical(
                self,
                "Export Failed",
                "Unable to prepare the discovery summary for export.",
            )
            return

        path = Path(file_path)
        if path.suffix.lower() != ".xlsx":
            path = path.with_suffix(".xlsx")

        try:
            summary_sheet = self._build_discovery_summary_sheet(model)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Failed to build discovery summary sheet: %s", exc)
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to build discovery summary:\n{exc}",
            )
            return

        detail_dialog = AnalysisDetailDialog(self.analysis_results or {}, self._state.mode, self)
        try:
            detail_sheets = detail_dialog.export_manager.collect_tables(
                ["users", "groups", "applications", "custom_attributes"]
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Failed to gather detailed export sheets: %s", exc)
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to prepare detailed data for export:\n{exc}",
            )
            return
        finally:
            detail_dialog.deleteLater()

        sheets: list[TableExportData] = [summary_sheet]
        if detail_sheets:
            sheets.extend(detail_sheets)
        else:
            LOGGER.info("No detailed sheets available; exporting summary only.")

        exporter = XLSXExporter()
        try:
            exporter.write_workbook(path, sheets)
            QMessageBox.information(
                self,
                "Export Successful",
                f"Discovery report saved to:\n{path}",
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Failed to export discovery report: %s", exc)
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to write discovery report:\n{exc}",
            )

    def _build_discovery_summary_sheet(self, model: AnalysisModel) -> TableExportData:
        """Create the discovery summary sheet matching the UI layout."""
        discovery = (self.analysis_results or {}).get("discovery") or {}
        discovery_users = discovery.get("users") or {}

        def fmt(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, bool):
                return "1" if value else "0"
            if isinstance(value, (int, float)):
                try:
                    if isinstance(value, float) and not value.is_integer():
                        text = f"{value:,.2f}"
                        return text.rstrip("0").rstrip(".")
                    return f"{int(value):,}"
                except (TypeError, ValueError):
                    return str(value)
            return str(value)

        col_count = 10

        def pad(values: list[str]) -> list[str]:
            if len(values) > col_count:
                return values[:col_count]
            return values + [""] * (col_count - len(values))

        blank = [""] * col_count

        discovery_totals = model.discovery_totals
        apps_total = discovery_totals.get("apps", 0)
        users_total = discovery_totals.get("users", 0)
        admins_total = discovery_totals.get("admins", 0)
        custom_attrs_total = discovery_totals.get("custom_attributes", 0)
        user_policies_total = discovery_totals.get("user_policies", 0)
        app_policies_total = discovery_totals.get("app_policies", 0)
        groups_total = discovery_totals.get("groups", 0)
        mfa_total = model.discovery_mfa.get("total", discovery_totals.get("mfa", 0))
        directories_total = model.discovery_directories.get(
            "total", discovery_totals.get("directories", 0)
        )

        discovery_apps = model.discovery_apps
        users_active = model.users_license.get("active", 0)
        users_inactive = model.users_license.get("inactive", 0)
        users_stale = model.users_license.get("stale", 0)
        users_nested = (
            discovery_users.get("nested")
            or discovery_users.get("nested_groups")
            or discovery_users.get("nestedUsers")
            or 0
        )
        users_locked = model.users_security.get("locked", 0)
        users_password_expired = model.users_security.get("password_expired", 0)

        user_policies_assigned = model.discovery_user_policies.get("assigned", 0)
        user_policies_unassigned = model.discovery_user_policies.get("unassigned", 0)

        app_policies_assigned = model.discovery_app_policies.get("assigned", 0)
        app_policies_unassigned = model.discovery_app_policies.get("unassigned", 0)

        custom_attrs_used = model.custom_attribute_summary.get("used", 0)
        custom_attrs_unused = model.custom_attribute_summary.get("unused", 0)

        groups_nested = model.groups.get("nested", 0)
        groups_assigned = model.groups.get("assigned", 0)
        groups_unassigned = model.groups.get("unassigned", 0)
        groups_rules = model.groups.get("rules", 0)

        mfa_assigned = model.discovery_mfa.get("assigned", 0)
        mfa_unassigned = model.discovery_mfa.get("unassigned", 0)

        directories_active = model.discovery_directories.get("active", 0)
        directories_inactive = model.discovery_directories.get("inactive", 0)

        headers = pad(["Discovery Report"])
        rows: list[list[str]] = [
            blank,
            pad(
                [
                    "Apps",
                    "Users/Admins",
                    "Custom Attributes",
                    "User Policies",
                    "App Policies",
                    "Groups",
                    "MFA",
                    "Directories",
                ]
            ),
            pad(
                [
                    fmt(apps_total),
                    f"{fmt(users_total)} / {fmt(admins_total)}",
                    fmt(custom_attrs_total),
                    fmt(user_policies_total),
                    fmt(app_policies_total),
                    fmt(groups_total),
                    fmt(mfa_total),
                    fmt(directories_total),
                ]
            ),
            blank,
            pad(["Break Down"]),
            blank,
            pad(["Applications"]),
            pad(
                [
                    "Qty",
                    "SAML",
                    "OIDC",
                    "OAuth",
                    "SWA",
                    "Other",
                    "Provisioning",
                    "Active",
                    "Inactive",
                ]
            ),
            pad(
                [
                    fmt(apps_total),
                    fmt(discovery_apps.get("saml", 0)),
                    fmt(discovery_apps.get("oidc", 0)),
                    fmt(discovery_apps.get("oauth", 0)),
                    fmt(discovery_apps.get("swa", 0)),
                    fmt(discovery_apps.get("other", 0)),
                    fmt(discovery_apps.get("provisioning", 0)),
                    fmt(discovery_apps.get("active", 0)),
                    fmt(discovery_apps.get("inactive", 0)),
                ]
            ),
            blank,
            pad(["Users"]),
            pad(
                [
                    "Qty",
                    "Active/Licensed",
                    "Deactivated/Unlicensed",
                    "90+ Days Last Login",
                    "Nested",
                    "Locked",
                    "Password Expired",
                ]
            ),
            pad(
                [
                    fmt(users_total),
                    fmt(users_active),
                    fmt(users_inactive),
                    fmt(users_stale),
                    fmt(users_nested),
                    fmt(users_locked),
                    fmt(users_password_expired),
                ]
            ),
            pad(["Admins"]),
            pad(["Qty", fmt(admins_total)]),
            blank,
            pad(["User Security Policies"]),
            pad(["Qty", "Assigned", "Unassigned"]),
            pad(
                [
                    fmt(user_policies_total),
                    fmt(user_policies_assigned),
                    fmt(user_policies_unassigned),
                ]
            ),
            blank,
            pad(["App Security Policies"]),
            pad(["Qty", "Assigned", "Unassigned"]),
            pad(
                [
                    fmt(app_policies_total),
                    fmt(app_policies_assigned),
                    fmt(app_policies_unassigned),
                ]
            ),
            blank,
            pad(["Custom Attributes"]),
            pad(["Qty", "Used", "Unused"]),
            pad(
                [
                    fmt(custom_attrs_total),
                    fmt(custom_attrs_used),
                    fmt(custom_attrs_unused),
                ]
            ),
            blank,
            pad(["Groups"]),
            pad(["Qty", "Nested", "Assigned", "Unassigned", "Rules"]),
            pad(
                [
                    fmt(groups_total),
                    fmt(groups_nested),
                    fmt(groups_assigned),
                    fmt(groups_unassigned),
                    fmt(groups_rules),
                ]
            ),
            blank,
            pad(["Qty", "Active", "Inactive"]),
            blank,
            pad(["Multi-Factor"]),
            pad(["Qty", "Assigned", "Unassigned"]),
            pad(
                [
                    fmt(mfa_total),
                    fmt(mfa_assigned),
                    fmt(mfa_unassigned),
                ]
            ),
            blank,
            pad(["Directories"]),
            pad(["Qty", "Active", "Inactive"]),
            pad(
                [
                    fmt(directories_total),
                    fmt(directories_active),
                    fmt(directories_inactive),
                ]
            ),
        ]

        return TableExportData(
            sheet_name="Discovery Summary",
            headers=headers,
            rows=rows,
            export_mode="Discovery overview",
            include_metadata=False,
        )

    def _handle_filter_request(self, category: str) -> None:
        if not self.analysis_results:
            QMessageBox.information(
                self,
                "Detailed Report",
                "Run the analysis before drilling into application details.",
            )
            return

        # Map categories to filter values
        status_map = {
            "can_migrate": "Can Auto-Migrate",  # Shows both connector matches and custom SAML/OIDC
            "need_review": "Needs Review",
            "cannot_migrate": "Manual Migration",
        }

        dialog = AnalysisDetailDialog(self.analysis_results, self._state.mode, self)
        try:
            # Always switch to the Applications tab (index 2)
            dialog.tab_widget.setCurrentIndex(2)

            # Apply the appropriate filter
            status_text = status_map.get(category)
            if status_text and hasattr(dialog, "apps_status_filter"):
                dialog.apps_status_filter.setCurrentText(status_text)
                if hasattr(dialog, "apps_table_manager"):
                    dialog.apps_table_manager.apply_filters()

            dialog.exec()
        finally:
            dialog.deleteLater()
