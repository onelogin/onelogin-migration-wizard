"""Provider configuration pages."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..components import ModernButton, ModernCard, ModernLineEdit
from .base import BasePage

if TYPE_CHECKING:  # pragma: no cover
    from .. import WizardState


class ProviderSettingsPage(BasePage):
    """Generic provider configuration page with dynamic schemas."""

    connection_test_requested = Signal(dict)
    auto_advance_requested = Signal()

    def __init__(
        self,
        title: str,
        entity_label: str,
        providers: dict[str, dict[str, Any]],
        hide_provider_selector: bool = False,
        credential_manager: Any | None = None,
    ) -> None:
        super().__init__(title)
        if not providers:
            raise ValueError("providers mapping cannot be empty")

        self.entity_label = entity_label
        self.provider_schemas = providers
        self.default_provider = next(iter(providers))
        self.current_provider = self.default_provider
        self.current_schema = providers[self.default_provider]
        self.fields: dict[str, QLineEdit] = {}
        self._value_cache: dict[str, dict[str, str]] = {name: {} for name in providers}
        self._validation_tested = False
        self._validation_succeeded = False
        self.hide_provider_selector = hide_provider_selector
        self.credential_manager = credential_manager
        self._auto_save_timers: dict[str, QTimer] = {}
        self._auto_advance_timer: QTimer | None = None

        # Header with entity label
        self.heading = QLabel(entity_label)
        heading_typo = self.theme_manager.get_typography("h2")
        self.heading.setStyleSheet(
            f"""
            QLabel {{
                font-size: {heading_typo['size']}px;
                font-weight: {heading_typo['weight']};
                color: {self.theme_manager.get_color('text_primary')};
                margin-bottom: {self.theme_manager.get_spacing('md')}px;
            }}
        """
        )
        self.body_layout.addWidget(self.heading)

        # Main settings card with constrained width
        self.settings_card = ModernCard(
            title="Provider Configuration", accent_color="primary", elevated=True
        )
        self.settings_card.setMaximumWidth(600)  # Narrower than Welcome page license card
        self.settings_card.setMinimumWidth(550)
        # Set minimum height to accommodate all elements without squishing
        # Provider (70) + 3 fields (210) + button (60) + validation (64) + card padding/spacing (~80) = 484px
        self.settings_card.setMinimumHeight(484)
        self.settings_card.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding
        )

        # Provider selector or static label (modern vertical layout)
        # Wrap in container to prevent blue accent bar
        provider_container = QWidget()
        provider_container.setStyleSheet("QWidget { background: transparent; border: none; }")
        # Prevent container from being squished
        provider_container.setMinimumHeight(70)  # Label + spacing + dropdown + margin
        provider_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        provider_layout = QVBoxLayout(provider_container)
        provider_layout.setSpacing(4)
        provider_layout.setContentsMargins(0, 0, 0, 8)  # 8px bottom margin
        provider_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)

        if hide_provider_selector:
            # Show static text instead of dropdown
            selector_label = QLabel("Provider")
            selector_label.setMinimumHeight(20)
            selector_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

            def update_selector_label_style():
                selector_label.setStyleSheet(
                    f"""
                    QLabel {{
                        color: {self.theme_manager.get_color('text_primary')};
                        font-size: 14px;
                        font-weight: 600;
                        padding: 2px 0px;
                        margin: 0px;
                        background: transparent;
                        border: none;
                    }}
                """
                )

            update_selector_label_style()
            self.theme_manager.theme_changed.connect(update_selector_label_style)

            self.provider_label = QLabel(self.default_provider)
            self.provider_label.setMinimumHeight(40)
            self.provider_label.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )

            def update_provider_label_style():
                self.provider_label.setStyleSheet(
                    f"""
                    QLabel {{
                        font-weight: 500;
                        font-size: 13px;
                        color: {self.theme_manager.get_color('text_primary')};
                        padding: {self.theme_manager.get_spacing('sm')}px;
                        background-color: {self.theme_manager.get_color('surface')};
                        border: 1px solid {self.theme_manager.get_color('border')};
                        border-radius: {self.theme_manager.get_radius('md')}px;
                    }}
                """
                )

            update_provider_label_style()
            self.theme_manager.theme_changed.connect(update_provider_label_style)

            provider_layout.addWidget(selector_label)
            provider_layout.addWidget(self.provider_label)
            self.provider_combo = None
        else:
            # Show dropdown selector with label above
            selector_label = QLabel("Provider")
            selector_label.setMinimumHeight(20)
            selector_label.setVisible(True)
            selector_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

            def update_dropdown_selector_label_style():
                selector_label.setStyleSheet(
                    f"""
                    QLabel {{
                        color: {self.theme_manager.get_color('text_primary')};
                        font-size: 14px;
                        font-weight: 600;
                        padding: 2px 0px;
                        margin: 0px;
                        background: transparent;
                        border: none;
                    }}
                """
                )

            update_dropdown_selector_label_style()
            self.theme_manager.theme_changed.connect(update_dropdown_selector_label_style)

            self.provider_combo = QComboBox()
            self.provider_combo.setMinimumHeight(40)
            self.provider_combo.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self.provider_combo.addItems(providers.keys())
            self.provider_combo.setStyleSheet(self.theme_manager.get_input_style())
            provider_layout.addWidget(selector_label)
            provider_layout.addWidget(self.provider_combo)
            self.provider_label = None

        # Add the wrapped provider section to card
        self.settings_card.add_widget(provider_container)

        # Form layout container - now vertical with labels above inputs
        self.form_container = QVBoxLayout()
        self.form_container.setSpacing(
            0
        )  # No spacing - each field container has its own bottom margin
        self.form_container.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        self.settings_card.add_layout(self.form_container)

        # Test connection button - wrap in container with FIXED height
        button_container = QWidget()
        button_container.setStyleSheet("QWidget { background: transparent; border: none; }")
        button_container.setMinimumHeight(60)  # Fixed height for button section
        button_container.setMaximumHeight(60)  # Fixed height - prevents resizing
        button_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        button_layout = QVBoxLayout(button_container)
        button_layout.setSpacing(0)
        button_layout.setContentsMargins(
            0, 12, 0, 0
        )  # 12px top margin to separate from form fields

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.test_button = ModernButton("Test Connection", variant="primary")
        self.test_button.setMinimumHeight(40)
        self.test_button.setMaximumHeight(40)
        self.test_button.setMinimumWidth(180)
        self.test_button.setMaximumWidth(180)
        self.test_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button_row.addWidget(self.test_button)
        button_layout.addLayout(button_row)

        self.settings_card.add_widget(button_container)

        # Add validation status label with icon - wrap in container with FIXED height
        # This reserves space even when hidden to prevent window resizing
        validation_container = QWidget()
        validation_container.setStyleSheet("QWidget { background: transparent; border: none; }")
        validation_container.setMinimumHeight(64)  # Fixed space for validation message
        validation_container.setMaximumHeight(64)  # Fixed space - prevents resizing
        validation_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        validation_layout = QVBoxLayout(validation_container)
        validation_layout.setSpacing(0)
        validation_layout.setContentsMargins(0, 8, 0, 8)  # 8px top margin, 8px bottom margin

        self.validation_status_label = QLabel()
        self.validation_status_label.setWordWrap(True)
        self.validation_status_label.setMinimumHeight(50)
        self.validation_status_label.setMaximumHeight(50)
        # Set fixed width to match the form field width (card is 550-600px, minus padding ~50px per side)
        self.validation_status_label.setMinimumWidth(450)
        self.validation_status_label.setMaximumWidth(500)
        self.validation_status_label.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.validation_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.validation_status_label.setVisible(False)
        validation_layout.addWidget(self.validation_status_label, 0, Qt.AlignmentFlag.AlignCenter)

        self.settings_card.add_widget(validation_container)

        self.body_layout.addWidget(self.settings_card)

        # Only connect provider combo if it exists
        if self.provider_combo:
            self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        self.test_button.clicked.connect(self._emit_test_request)

        # Connect theme changes to update combo box styling
        self.theme_manager.theme_changed.connect(self._update_combo_theme)

        self._rebuild_form(self.current_provider, None)

    def _update_combo_theme(self) -> None:
        """Update combo box and heading styling when theme changes."""
        if self.provider_combo:
            self.provider_combo.setStyleSheet(self.theme_manager.get_input_style())

        # Update heading color
        heading_typo = self.theme_manager.get_typography("h2")
        self.heading.setStyleSheet(
            f"""
            QLabel {{
                font-size: {heading_typo['size']}px;
                font-weight: {heading_typo['weight']};
                color: {self.theme_manager.get_color('text_primary')};
                margin-bottom: {self.theme_manager.get_spacing('md')}px;
            }}
        """
        )

        # Update all field labels in the current form
        self._update_field_labels()

    def _update_field_labels(self) -> None:
        """Update all field labels with current theme colors."""
        # Iterate through all items in the form container
        for i in range(self.form_container.count()):
            item = self.form_container.itemAt(i)
            if item and item.widget():
                field_container = item.widget()
                # Find QLabel children in the field container
                for child in field_container.findChildren(QLabel):
                    # Update label styling
                    child.setStyleSheet(
                        f"""
                        QLabel {{
                            color: {self.theme_manager.get_color('text_primary')};
                            font-size: 14px;
                            font-weight: 600;
                            padding: 2px 0px;
                            margin: 0px;
                            background: transparent;
                            border: none;
                        }}
                    """
                    )

    def current_settings(self) -> dict[str, str]:
        return {key: widget.text().strip() for key, widget in self.fields.items()}

    def get_provider_name(self) -> str:
        """Get the current provider name for display."""
        return self.current_provider

    def set_values(self, values: dict[str, Any], provider: str | None = None) -> None:
        """Populate the form with ``values`` optionally switching provider."""

        target_provider = provider or self.current_provider or self.default_provider
        if target_provider not in self.provider_schemas:
            target_provider = self.default_provider

        if provider is not None and self.provider_combo:
            self.provider_combo.blockSignals(True)
            self.provider_combo.setCurrentText(target_provider)
            self.provider_combo.blockSignals(False)

        self._value_cache[target_provider] = {
            key: str(values.get(key, "")) for key in self.provider_schemas[target_provider]
        }
        self._rebuild_form(target_provider, values)

    def on_enter(self, state: WizardState) -> None:
        super().on_enter(state)
        provider, values = self._state_defaults(state)
        if provider not in self.provider_schemas:
            provider = self.default_provider
        if self.provider_combo:
            self.provider_combo.blockSignals(True)
            self.provider_combo.setCurrentText(provider)
            self.provider_combo.blockSignals(False)

        # Auto-prefill credentials from secure storage if available
        # Only retrieve fields marked as passwords (sensitive credentials)
        if self.credential_manager:
            service = self.entity_label.lower()  # "source" or "target"
            schema = self.provider_schemas[provider]
            for key, field_meta in schema.items():
                # Only retrieve if this field is marked as a password field (sensitive)
                is_sensitive = field_meta.get("echo_mode") == QLineEdit.EchoMode.Password
                if is_sensitive and (key not in values or not values[key]):
                    # Try to retrieve from credential manager
                    try:
                        stored_value = self.credential_manager.get_credential(service, key)
                        if stored_value:
                            values[key] = stored_value.reveal()
                    except Exception:
                        # Silently fail if credential retrieval fails
                        pass

        self._rebuild_form(provider, values)
        self._value_cache[provider] = {
            key: str(values.get(key, "")) for key in self.provider_schemas[provider]
        }

    def collect(self, state: WizardState) -> None:
        super().collect(state)
        provider = self.current_provider
        settings = self.current_settings()
        self._value_cache[provider] = settings
        self._store_provider(state, provider)
        self._store_state(state, settings)

    def can_proceed(self, state: WizardState) -> bool:
        """Override to allow proceeding when all fields are filled."""
        # Check if all required fields are filled
        schema = self.provider_schemas.get(self.current_provider, {})
        for key in schema.keys():
            field = self.fields.get(key)
            if field is None or not field.text().strip():
                return False
        # Allow proceeding (button will say "Verify" if not tested, "Next" if tested)
        return True

    def needs_verification(self) -> bool:
        """Check if the page needs credential verification."""
        return not self._validation_succeeded

    def validate(self, state: WizardState) -> tuple[bool, str]:
        schema = self.provider_schemas.get(self.current_provider, {})
        missing = []
        for key, meta in schema.items():
            field = self.fields.get(key)
            if field is None or not field.text().strip():
                missing.append(meta["label"])
        if missing:
            return False, "Please fill in: " + ", ".join(missing)

        if not self._validation_succeeded:
            if self._validation_tested:
                return False, "Connection test failed. Fix the errors and verify again."
            return False, "Please test the connection before proceeding."

        return True, ""

    def _emit_test_request(self) -> None:
        self.connection_test_requested.emit(self.current_settings())

    def show_validation_status(self, success: bool, message: str) -> None:
        """Display inline validation status with icon and message."""
        # Cancel any existing auto-advance timer
        self._cancel_auto_advance()

        if success:
            icon = "✓"
            color = self.theme_manager.get_color("success")
            bg_color = self.theme_manager.get_color("success_light")
            text_color = "white"
            # Update message to indicate auto-advance
            display_message = f"{message} Advancing in 3 seconds..."
        else:
            icon = "✗"
            color = self.theme_manager.get_color("error")
            bg_color = self.theme_manager.get_color("error_light")
            text_color = "white"
            display_message = message

        self.validation_status_label.setText(f"{icon}  {display_message}")
        self.validation_status_label.setStyleSheet(
            f"color: {text_color}; background-color: {color}; "
            f"border: 2px solid {color}; "
            f"padding: {self.theme_manager.get_spacing('sm')}px {self.theme_manager.get_spacing('md')}px; "
            f"border-radius: {self.theme_manager.get_radius('md')}px; "
            f"font-weight: 600; font-size: 11pt; "
            f"margin-top: {self.theme_manager.get_spacing('sm')}px;"
        )
        self.validation_status_label.setVisible(True)
        self._validation_tested = True
        self._validation_succeeded = success

        # Auto-save credentials on successful validation
        # Only save fields marked as passwords (sensitive credentials)
        if success and self.credential_manager:
            service = self.entity_label.lower()  # "source" or "target"
            schema = self.current_schema
            for key, field in self.fields.items():
                # Only save if this field is marked as a password field (sensitive)
                field_meta = schema.get(key, {})
                is_sensitive = field_meta.get("echo_mode") == QLineEdit.EchoMode.Password
                if is_sensitive:
                    value = field.text().strip()
                    if value:
                        try:
                            self.credential_manager.auto_save_credential(service, key, value)
                        except Exception:
                            # Silently fail if credential save fails
                            pass

        # Start auto-advance timer on success
        if success:
            self._auto_advance_timer = QTimer()
            self._auto_advance_timer.setSingleShot(True)
            self._auto_advance_timer.timeout.connect(self._emit_auto_advance)
            self._auto_advance_timer.start(3000)  # 3 seconds

        # Notify that the page state has changed
        self.completeChanged.emit()

    def _cancel_auto_advance(self) -> None:
        """Cancel any pending auto-advance timer."""
        if self._auto_advance_timer is not None:
            self._auto_advance_timer.stop()
            self._auto_advance_timer.deleteLater()
            self._auto_advance_timer = None

    def _emit_auto_advance(self) -> None:
        """Emit signal to trigger auto-advance to next step."""
        self.auto_advance_requested.emit()

    def clear_validation_status(self) -> None:
        """Hide the validation status label."""
        # Cancel any pending auto-advance
        self._cancel_auto_advance()
        self.validation_status_label.setVisible(False)
        self.validation_status_label.setText("")
        self._validation_tested = False
        self._validation_succeeded = False
        # Notify that the page state has changed
        self.completeChanged.emit()

    def has_valid_credentials(self) -> bool:
        """Check if credentials have been validated successfully."""
        return self._validation_succeeded and self.validation_status_label.isVisible()

    def _on_provider_changed(self, provider: str) -> None:
        if self.current_provider:
            self._value_cache[self.current_provider] = self.current_settings()
        self._rebuild_form(provider, self._value_cache.get(provider))
        self.clear_validation_status()
        self.completeChanged.emit()

    def _rebuild_form(self, provider: str, values: dict[str, Any] | None) -> None:
        if provider not in self.provider_schemas:
            provider = self.default_provider
        schema = self.provider_schemas[provider]
        self.current_provider = provider
        self.current_schema = schema

        values = values or self._value_cache.get(provider, {})

        # Clear validation status when rebuilding form
        self.clear_validation_status()

        # Clear existing form fields
        while self.form_container.count():
            item = self.form_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                # Clear nested layout
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
                item.layout().deleteLater()

        self.fields = {}

        # Build form fields with proper label visibility
        for key, meta in schema.items():
            # Create a plain container widget to prevent accent bar styling
            field_container = QWidget()
            field_container.setStyleSheet("QWidget { background: transparent; border: none; }")
            # Prevent container from being squished
            field_container.setMinimumHeight(70)  # Label + spacing + input + margin
            field_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

            # Create field group layout (label + input vertically)
            field_group = QVBoxLayout(field_container)
            field_group.setSpacing(4)
            field_group.setContentsMargins(
                0, 0, 0, 8
            )  # 8px bottom margin to separate from next field
            field_group.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)

            # Create label with explicit visibility settings
            label = QLabel(meta["label"])
            label.setMinimumHeight(20)
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            label.setVisible(True)
            # Apply initial styling
            label.setStyleSheet(
                f"""
                QLabel {{
                    color: {self.theme_manager.get_color('text_primary')};
                    font-size: 14px;
                    font-weight: 600;
                    padding: 2px 0px;
                    margin: 0px;
                    background: transparent;
                    border: none;
                }}
            """
            )
            field_group.addWidget(label)

            # Create input field with proper sizing
            line_edit = ModernLineEdit()
            line_edit.setMinimumHeight(40)
            line_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

            if meta.get("echo_mode"):
                line_edit.setEchoMode(meta["echo_mode"])
            if key in values:
                line_edit.setText(str(values[key]))

            # Clear validation status when field is modified
            line_edit.textChanged.connect(self.clear_validation_status)
            # Add debounced auto-save for credential fields
            line_edit.textChanged.connect(lambda _, k=key: self._schedule_auto_save(k))
            field_group.addWidget(line_edit)

            # Add the container widget (not the layout directly)
            self.form_container.addWidget(field_container)
            self.fields[key] = line_edit

    def _schedule_auto_save(self, key: str) -> None:
        """Schedule a debounced auto-save for a field."""
        if not self.credential_manager:
            return

        # Cancel existing timer for this field
        if key in self._auto_save_timers:
            self._auto_save_timers[key].stop()
            self._auto_save_timers[key].deleteLater()

        # Create new timer
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._do_auto_save(key))
        timer.start(2000)  # 2 second debounce
        self._auto_save_timers[key] = timer

    def _do_auto_save(self, key: str) -> None:
        """Perform the actual auto-save for a field."""
        if not self.credential_manager:
            return

        field = self.fields.get(key)
        if not field:
            return

        value = field.text().strip()
        if value:
            service = self.entity_label.lower()  # "source" or "target"
            try:
                self.credential_manager.auto_save_credential(service, key, value)
            except Exception:
                # Silently fail if credential save fails
                pass

        # Clean up timer
        if key in self._auto_save_timers:
            self._auto_save_timers[key].deleteLater()
            del self._auto_save_timers[key]

    def _state_defaults(self, state: WizardState) -> tuple[str, dict[str, Any]]:
        raise NotImplementedError

    def _store_provider(self, state: WizardState, provider: str) -> None:
        raise NotImplementedError

    def _store_state(self, state: WizardState, data: dict[str, Any]) -> None:
        raise NotImplementedError
