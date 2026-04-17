"""Source provider wizard pages."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QLineEdit

from .provider import ProviderSettingsPage

if TYPE_CHECKING:  # pragma: no cover
    from .. import WizardState

DEFAULT_RATE_LIMIT = "600"

SOURCE_PROVIDERS: dict[str, dict[str, Any]] = {
    "Okta": {
        "subdomain": {"label": "Subdomain"},
        "token": {"label": "API Token", "echo_mode": QLineEdit.Password},
        "rate_limit_per_minute": {"label": "Rate limit / minute"},
    }
}


class SourceSettingsPage(ProviderSettingsPage):
    def __init__(self, credential_manager=None) -> None:
        super().__init__(
            "Step 1 – Source Settings",
            "Source",
            SOURCE_PROVIDERS,
            credential_manager=credential_manager,
        )

    def _state_defaults(self, state: WizardState) -> tuple[str, dict[str, Any]]:
        settings = dict(state.source_settings)
        settings.setdefault("rate_limit_per_minute", DEFAULT_RATE_LIMIT)
        return state.source_provider, settings

    def _store_provider(self, state: WizardState, provider: str) -> None:
        state.source_provider = provider

    def _store_state(self, state: WizardState, data: dict[str, Any]) -> None:
        state.source_settings = data
