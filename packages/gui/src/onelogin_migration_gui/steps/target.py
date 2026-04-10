"""Target provider wizard pages."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QLineEdit

from .provider import ProviderSettingsPage

if TYPE_CHECKING:  # pragma: no cover
    from .. import WizardState

DEFAULT_RATE_LIMIT = "5000"

TARGET_PROVIDERS: dict[str, dict[str, Any]] = {
    "OneLogin": {
        "client_id": {"label": "Client ID"},
        "client_secret": {"label": "Client Secret", "echo_mode": QLineEdit.Password},
        "subdomain": {"label": "Subdomain"},
        "rate_limit_per_hour": {"label": "Rate limit / hour"},
    }
}


class TargetSettingsPage(ProviderSettingsPage):
    def __init__(self, credential_manager=None) -> None:
        super().__init__(
            "Step 2 – Target Settings",
            "Target",
            TARGET_PROVIDERS,
            hide_provider_selector=True,
            credential_manager=credential_manager,
        )

    def _state_defaults(self, state: WizardState) -> tuple[str, dict[str, Any]]:
        settings = dict(state.target_settings)
        settings.setdefault("rate_limit_per_hour", DEFAULT_RATE_LIMIT)
        return state.target_provider, settings

    def _store_provider(self, state: WizardState, provider: str) -> None:
        state.target_provider = provider

    def _store_state(self, state: WizardState, data: dict[str, Any]) -> None:
        state.target_settings = data
