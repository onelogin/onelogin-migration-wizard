"""Dialog for selecting migration options for an Okta application."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...components import ModernButton, ModernCard, ModernCheckbox
from ...theme_manager import get_theme_manager

LOGGER = logging.getLogger(__name__)

# OneLogin auth_method values (from API documentation)
AUTH_METHOD_LABELS = {
    0: "Password",
    1: "OpenID",
    2: "SAML",
    3: "API",
    4: "Google",
    6: "Forms",
    7: "WSFED",
    8: "OIDC",
}


class ApplicationMigrationDialog(QDialog):
    """Modal dialog that lets the user choose a migration approach for an app."""

    def __init__(self, app: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self.app = app
        self.meta: dict[str, Any] = app.get("_migration") or {}
        self.matches: list[dict[str, Any]] = list(self.meta.get("matches") or [])
        self.supports_custom = bool(self.meta.get("supports_custom_sso"))
        self.selected_option: dict[str, Any] | None = self.meta.get("selection")
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        self.option_map: dict[QAbstractButton, dict[str, Any]] = {}
        self.option_frames: dict[QAbstractButton, ModernCard] = {}
        self.option_accent_styles: dict[QAbstractButton, tuple[str, bool]] = {}
        self.theme_manager = get_theme_manager()
        self.selection_summary = QLabel()

        # Search functionality
        self.search_box: QLineEdit | None = None
        self.search_results_container: QWidget | None = None
        self.search_scroll_area: QScrollArea | None = None
        self.all_connectors: list[dict[str, Any]] = []

        # Pagination state for infinite scroll
        self.current_offset = 0
        self.page_size = 20
        self.has_more_results = True
        self.is_loading = False
        self.current_search_text = ""

        # Get connector database for search
        from onelogin_migration_core.db import get_default_connector_db

        self.connector_db = get_default_connector_db()

        # Debug logging
        app_label = app.get("label", "Unknown")
        LOGGER.info(
            f"AppMigrationDialog for '{app_label}': matches={len(self.matches)}, "
            f"supports_custom={self.supports_custom}, meta_keys={list(self.meta.keys())}"
        )
        if self.matches:
            LOGGER.info(f"  Matches: {[m.get('connector', {}).get('name') for m in self.matches]}")

        self.setWindowTitle("Select Migration Option")
        self.setModal(True)
        self.resize(650, 600)

        self._build_ui()
        self.theme_manager.theme_changed.connect(lambda *_: self._update_card_styles())

    # ------------------------------------------------------------------ Search
    def _build_search_section(self) -> QWidget:
        """Build the search box and results container."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(8)

        # Search box row
        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        search_label = QLabel("Search OneLogin connectors:")
        search_label.setStyleSheet(
            f"color: {self.theme_manager.get_color('text_secondary')}; font-size: 12px;"
        )
        search_row.addWidget(search_label)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Type to search available connectors...")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setFixedHeight(36)
        self._apply_search_box_style(self.search_box)
        self.search_box.textChanged.connect(self._on_search_text_changed)
        search_row.addWidget(self.search_box, 1)

        layout.addLayout(search_row)

        # Search results container (initially hidden)
        self.search_results_container = QWidget()
        self.search_results_layout = QVBoxLayout(self.search_results_container)
        self.search_results_layout.setContentsMargins(0, 0, 0, 0)
        self.search_results_layout.setSpacing(4)
        self.search_results_layout.addStretch(1)  # Push cards to top, prevent expansion
        self.search_results_container.setVisible(False)

        # Wrap in scroll area
        self.search_scroll_area = QScrollArea()
        self.search_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.search_scroll_area.setWidgetResizable(True)
        self.search_scroll_area.setWidget(self.search_results_container)
        self.search_scroll_area.setMaximumHeight(200)

        # Connect scroll bar to load more results
        scrollbar = self.search_scroll_area.verticalScrollBar()
        scrollbar.valueChanged.connect(self._on_scroll)

        layout.addWidget(self.search_scroll_area)

        # Load initial connectors when building UI
        self._load_initial_connectors()

        return container

    def _on_scroll(self, value: int) -> None:
        """Handle scroll events to implement infinite scroll."""
        if not self.search_scroll_area:
            return

        scrollbar = self.search_scroll_area.verticalScrollBar()
        # Check if we're near the bottom (within 20 pixels)
        if value >= scrollbar.maximum() - 20 and self.has_more_results and not self.is_loading:
            self._load_more_connectors()

    def _load_initial_connectors(self) -> None:
        """Load the first page of connectors when dialog opens."""
        self.current_offset = 0
        self.has_more_results = True
        self.current_search_text = ""
        self._load_more_connectors()

    def _load_more_connectors(self) -> None:
        """Load next batch of connectors (for pagination)."""
        if self.is_loading or not self.has_more_results:
            return

        self.is_loading = True

        try:
            # Search with pagination
            if self.current_search_text:
                search_pattern = f"%{self.current_search_text}%"
                results = self._search_connectors_paginated(
                    search_pattern, self.page_size, self.current_offset
                )
            else:
                # Get all connectors paginated
                results = self._get_all_connectors_paginated(self.page_size, self.current_offset)

            if not results:
                self.has_more_results = False
            else:
                # Add results to UI (insert before the stretch at the end)
                for connector in results:
                    # Insert before the last item (the stretch)
                    insert_pos = self.search_results_layout.count() - 1
                    self.search_results_layout.insertWidget(
                        insert_pos, self._create_simple_search_card(connector)
                    )

                # Update offset for next page
                self.current_offset += len(results)

                # Check if we got fewer results than page size (last page)
                if len(results) < self.page_size:
                    self.has_more_results = False

            # Show container if we have results
            if self.current_offset > 0:
                self.search_results_container.setVisible(True)

            # Apply card styles to newly added items
            self._update_card_styles()

        except Exception as e:
            LOGGER.error(f"Failed to load connectors: {e}")
        finally:
            self.is_loading = False

    def _search_connectors_paginated(
        self, pattern: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        """Search connectors with pagination."""
        # Get all matching results
        all_results = self.connector_db.search_onelogin_connectors(pattern)
        # Return only the requested page
        return all_results[offset : offset + limit]

    def _get_all_connectors_paginated(self, limit: int, offset: int) -> list[dict[str, Any]]:
        """Get all connectors with pagination."""
        # Get all connectors from database
        all_connectors = self.connector_db.get_all_onelogin_connectors()
        # Return only the requested page
        return all_connectors[offset : offset + limit]

    def _clear_search_results(self) -> None:
        """Clear search results and properly clean up widgets."""
        # Find all buttons that belong to search results (not original matches)
        buttons_to_remove = []
        for button in list(self.option_map.keys()):
            option = self.option_map[button]
            if option.get("match_reason") == "manual_search":
                buttons_to_remove.append(button)

        # Disconnect and remove from tracking
        for button in buttons_to_remove:
            try:
                # Disconnect signals to prevent errors
                button.toggled.disconnect()
            except (RuntimeError, TypeError):
                pass  # Already disconnected or deleted

            # Remove from button group
            self.button_group.removeButton(button)

            # Remove from tracking dictionaries
            self.option_map.pop(button, None)
            self.option_frames.pop(button, None)
            self.option_accent_styles.pop(button, None)

        # Clear widgets from layout (but preserve the stretch at the end)
        while self.search_results_layout.count() > 1:  # Keep the last item (stretch)
            item = self.search_results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Reset pagination state
        self.current_offset = 0
        self.has_more_results = True

    def _on_search_text_changed(self, text: str) -> None:
        """Handle search box text changes."""
        # Clear previous results
        self._clear_search_results()

        # Update current search text
        self.current_search_text = text.strip()

        # Load results (either all connectors or filtered)
        self._load_more_connectors()

    def _create_simple_search_card(self, connector: dict[str, Any]) -> QFrame:
        """Create a simplified search result card showing only connector name."""
        connector_id = connector.get("id")
        connector_name = connector.get("name") or "Unknown Connector"
        auth_method = connector.get("auth_method")

        # Wrap in match_info format and use standard connector card
        match_info = {
            "connector": {
                "id": connector_id,
                "name": connector_name,
                "auth_method": auth_method,
            },
            "match_reason": "manual_search",
            "confidence_score": 0,
        }

        return self._create_connector_card(match_info)

    def _apply_search_box_style(self, search_box: QLineEdit):
        """Apply consistent styling to search box (matching table search)."""
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
            QLineEdit:hover {
                background-color: #242424;
            }
        """
        )

    # ------------------------------------------------------------------ UI build
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(18)

        header = QLabel(self.app.get("label") or "Application")
        header.setWordWrap(True)
        header.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {self.theme_manager.get_color('text_primary')};"
        )
        layout.addWidget(header)

        subheader = QLabel(self._scenario_heading())
        subheader.setWordWrap(True)
        subheader.setStyleSheet(
            f"font-size: 12px; color: {self.theme_manager.get_color('text_secondary')};"
        )
        layout.addWidget(subheader)

        content = self._build_body()
        layout.addWidget(content, 1)

        self.selection_summary.setStyleSheet(
            f"color: {self.theme_manager.get_color('text_secondary')}; font-size: 12px; font-style: italic;"
        )
        layout.addWidget(self.selection_summary)
        self._update_selection_summary()

        buttons = self._build_buttons()
        layout.addWidget(buttons)

    def _build_body(self) -> QWidget:
        container = QWidget()
        body_layout = QVBoxLayout(container)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)

        if self.matches or self.supports_custom:
            body_layout.addWidget(self._build_options_section())
        else:
            body_layout.addWidget(self._build_no_path_section())

        return container

    def _build_options_section(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        descriptor = QLabel(self._options_intro_text())
        descriptor.setStyleSheet(
            f"color: {self.theme_manager.get_color('text_primary')}; font-size: 13px; font-weight: 600;"
        )
        descriptor.setWordWrap(True)
        layout.addWidget(descriptor)

        # Add search box for partial matches and needs review cases
        confidence = float(self.meta.get("confidence_score") or 0.0)
        if confidence < 99.5:  # Show search for anything not a 100% match
            layout.addWidget(self._build_search_section())

        option_container = QWidget()
        option_layout = QVBoxLayout(option_container)
        option_layout.setContentsMargins(0, 0, 0, 0)
        option_layout.setSpacing(self.theme_manager.get_spacing("xs"))

        for match in self.matches:
            option_layout.addWidget(self._create_connector_card(match))

        if self.supports_custom:
            option_layout.addWidget(self._create_custom_card("custom_saml"))
            option_layout.addWidget(self._create_custom_card("custom_oidc"))

        option_layout.addStretch()

        if len(self.matches) > 3:
            scroll = QScrollArea()
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidgetResizable(True)
            scroll.setWidget(option_container)
            layout.addWidget(scroll, 1)
        else:
            layout.addWidget(option_container)

        self._update_card_styles()
        return wrapper

    def _build_no_path_section(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        reason = (
            self.meta.get("reason") or "This application does not have an automated migration path."
        )
        reason_label = QLabel(reason)
        reason_label.setWordWrap(True)
        reason_label.setStyleSheet(
            f"background-color: {self.theme_manager.get_color('surface_elevated')};"
            f"border-left: 4px solid {self.theme_manager.get_color('error')};"
            f"padding: 12px; font-size: 13px; color: {self.theme_manager.get_color('text_primary')};"
        )
        layout.addWidget(reason_label)

        details: list[str] = []
        sign_on = (self.app.get("signOnMode") or "").upper()
        if sign_on:
            details.append(f"Sign-on mode: {sign_on}")
        assignment_count = len(self.app.get("_embedded", {}).get("group", []) or [])
        details.append(f"Assigned groups: {assignment_count}")

        if details:
            info_label = QLabel("\n".join(details))
            info_label.setWordWrap(True)
            info_label.setStyleSheet(
                f"color: {self.theme_manager.get_color('text_secondary')}; font-size: 12px;"
            )
            layout.addWidget(info_label)

        layout.addStretch()
        return wrapper

    # ---------------------------------------------------------------- option helpers
    def _create_connector_card(self, match_info: dict[str, Any]) -> QFrame:
        connector = match_info.get("connector") or {}
        connector_name = connector.get("name") or "OneLogin Connector"
        match_reason = match_info.get("match_reason")

        card = ModernCard(accent_color=None, elevated=False, padding="xs")
        card.setObjectName("OptionCard")
        card.setMinimumHeight(48)  # Minimum height for consistency
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        row_layout = QHBoxLayout()
        inset = self.theme_manager.get_spacing("sm")
        row_layout.setContentsMargins(
            inset, self.theme_manager.get_spacing("xs"), inset, self.theme_manager.get_spacing("xs")
        )
        row_layout.setSpacing(self.theme_manager.get_spacing("sm"))

        checkbox = ModernCheckbox()
        checkbox.setFixedSize(18, 18)
        row_layout.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignTop)

        # Show connector name with auth method if available
        auth_method = connector.get("auth_method")
        if auth_method is not None and auth_method in AUTH_METHOD_LABELS:
            auth_label = AUTH_METHOD_LABELS[auth_method]
            display_name = f"{connector_name} ({auth_label})"
        else:
            display_name = connector_name

        title = QLabel(display_name)
        title.setStyleSheet("font-weight: 600; font-size: 13px;")
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        row_layout.addWidget(title, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        card.add_layout(row_layout)

        # Choose accent color based on match reason
        if match_reason == "manual_search":
            accent = self.theme_manager.get_color("secondary")
        elif match_reason == "partial":
            accent = self.theme_manager.get_color("warning")
        else:
            accent = self.theme_manager.get_color("success")
        payload = {
            "type": "connector",
            "id": connector.get("id"),
            "name": connector_name,
            "match_reason": match_reason,
        }
        self._register_option(checkbox, payload, card, accent, dashed=False)

        if (
            self.selected_option
            and self.selected_option.get("type") == "connector"
            and (self.selected_option.get("id") == connector.get("id"))
        ):
            checkbox.setChecked(True)
        # Only auto-select if this is a match (not a manual search result)
        elif (
            match_reason != "manual_search"
            and not self.selected_option
            and not any(btn.isChecked() for btn in self.button_group.buttons())
        ):
            checkbox.setChecked(True)

        return card

    def _create_custom_card(self, option_type: str) -> QFrame:
        card = ModernCard(accent_color=None, elevated=False, padding="xs")
        card.setObjectName("OptionCard")
        card.setMinimumHeight(48)  # Minimum height for consistency
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QHBoxLayout()
        inset = self.theme_manager.get_spacing("sm")
        layout.setContentsMargins(
            inset, self.theme_manager.get_spacing("xs"), inset, self.theme_manager.get_spacing("xs")
        )
        layout.setSpacing(self.theme_manager.get_spacing("sm"))

        if option_type == "custom_saml":
            title_text = "Custom SAML connector"
            accent = self.theme_manager.get_color("warning")
        else:
            title_text = "Custom OIDC Connector"
            accent = self.theme_manager.get_color("info")

        checkbox = ModernCheckbox()
        checkbox.setFixedSize(18, 18)
        layout.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignTop)

        # Only show option name (simplified layout)
        title_label = QLabel(title_text)
        title_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        title_label.setWordWrap(True)
        title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.addWidget(title_label, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        card.add_layout(layout)

        payload = {"type": option_type}
        self._register_option(checkbox, payload, card, accent, dashed=True)

        if self.selected_option and self.selected_option.get("type") == option_type:
            checkbox.setChecked(True)
        elif not self.selected_option and not any(
            btn.isChecked() for btn in self.button_group.buttons()
        ):
            checkbox.setChecked(True)

        return card

    def _register_option(
        self,
        button: QAbstractButton,
        payload: dict[str, Any],
        card: ModernCard,
        accent: str,
        dashed: bool,
    ) -> None:
        self.button_group.addButton(button)
        self.option_map[button] = payload
        self.option_frames[button] = card
        self.option_accent_styles[button] = (accent, dashed)

        button.toggled.connect(lambda checked, btn=button: self._on_option_toggled(btn, checked))

        card.mousePressEvent = lambda event: button.setChecked(True)  # pragma: no cover

    # ---------------------------------------------------------------- scenario text
    def _scenario_heading(self) -> str:
        if not self.matches and not self.supports_custom:
            return "No automated migration path detected. Review limitations below."
        if len(self.matches) == 1:
            return "Connector match found. Choose how to migrate this application."
        if len(self.matches) > 1:
            return "Multiple connector matches found. Select the preferred option."
        return "No Direct Connector Matches Found"

    def _options_intro_text(self) -> str:
        if len(self.matches) > 1:
            return (
                "Review the suggested connectors and choose the best fit for your migration plan."
            )
        if len(self.matches) == 1:
            return "Review the connector details or switch to a custom SAML/OIDC configuration."
        return "Either Select the custom SAML/OIDC option or search for a connector."

    # ---------------------------------------------------------------- button handling
    def _build_buttons(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, self.theme_manager.get_spacing("sm"), 0, 0)
        layout.setSpacing(self.theme_manager.get_spacing("sm"))
        layout.addStretch(1)

        if self.matches or self.supports_custom:
            cancel_btn = ModernButton("Cancel", variant="ghost")
            save_btn = ModernButton("Save", variant="primary")
            cancel_btn.clicked.connect(self.reject)
            save_btn.clicked.connect(self._handle_save)
            layout.addWidget(cancel_btn, 0, Qt.AlignmentFlag.AlignRight)
            layout.addWidget(save_btn, 0, Qt.AlignmentFlag.AlignRight)
        else:
            close_btn = ModernButton("Close", variant="secondary")
            close_btn.clicked.connect(self.reject)
            layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)

        return container

    def _handle_save(self) -> None:
        checked = self.button_group.checkedButton()
        if checked is None:
            return
        selection = self.option_map.get(checked)
        if not selection:
            return
        self.selected_option = selection
        self.accept()

    # ---------------------------------------------------------------- selection state
    def _on_option_toggled(self, button: QAbstractButton, checked: bool) -> None:
        if checked:
            self.selected_option = self.option_map.get(button)
        self._update_selection_summary()
        self._update_card_styles()

    def _update_selection_summary(self) -> None:
        btn = self.button_group.checkedButton()
        if btn is None:
            self.selection_summary.setText("")
            return
        selection = self.option_map.get(btn)
        if not selection:
            self.selection_summary.setText("")
            return
        option_type = selection.get("type")
        if option_type == "connector":
            name = selection.get("name") or "Connector"
            reason = selection.get("match_reason")
            detail = " (name similarity)" if reason == "partial" else ""
            self.selection_summary.setText(f"Currently selected: {name}{detail}")
        elif option_type == "custom_saml":
            self.selection_summary.setText("Currently selected: Custom SAML connector")
        elif option_type == "custom_oidc":
            self.selection_summary.setText("Currently selected: Custom OIDC connector")
        else:
            self.selection_summary.setText("")

    def _update_card_styles(self) -> None:
        for button, frame in list(self.option_frames.items()):
            try:
                accent, dashed = self.option_accent_styles.get(
                    button, (self.theme_manager.get_color("primary"), False)
                )
                selected = button.isChecked()
                frame.setStyleSheet(self._card_style(accent, dashed, selected))
            except RuntimeError:
                # Widget was deleted, skip it
                pass

    def _card_style(self, accent: str, dashed: bool, selected: bool) -> str:
        border_color = self.theme_manager.get_color("border")
        background = self.theme_manager.get_color("surface_elevated" if selected else "surface")
        text_color = self.theme_manager.get_color("text_primary")
        line_style = "dashed" if dashed else "solid"
        return (
            f"QFrame#OptionCard {{"
            f" border: 1px {line_style} {border_color};"
            f" border-left: 6px solid {accent};"
            f" border-radius: 6px;"
            f" background-color: {background};"
            f" color: {text_color};"
            f"}}"
        )
