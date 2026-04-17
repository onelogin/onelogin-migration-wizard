"""Field transformation and normalization utilities for migration."""

from __future__ import annotations

import re
from typing import Any

from .constants import KNOWN_STANDARD_FIELDS


class FieldTransformer:
    """Handles transformation of Okta data to OneLogin format."""

    @staticmethod
    def transform_user(user: dict[str, Any]) -> dict[str, Any] | None:
        """Transform an Okta user to OneLogin format.

        Args:
            user: Okta user object

        Returns:
            Transformed user payload for OneLogin API, or None if invalid
        """
        profile = user.get("profile") or {}
        credentials = user.get("credentials") or {}
        if not profile and not credentials:
            return None

        def first_value(*candidates: Any) -> Any | None:
            for candidate in candidates:
                if isinstance(candidate, str):
                    if candidate.strip():
                        return candidate
                elif candidate:
                    return candidate
            return None

        def email_from_credentials() -> str | None:
            emails = credentials.get("emails")
            if isinstance(emails, list):
                for item in emails:
                    value = item.get("value") if isinstance(item, dict) else None
                    if isinstance(value, str) and value.strip():
                        return value
            return None

        # Standard identity and contact information supported by OneLogin's API
        email = first_value(
            profile.get("email"),
            email_from_credentials(),
            profile.get("secondEmail"),
            profile.get("login"),
        )
        username = first_value(profile.get("login"), email)

        login_value = profile.get("login")
        samaccountname = first_value(
            profile.get("samAccountName"),
            profile.get("samaccountname"),
            (
                login_value.split("@")[0]
                if isinstance(login_value, str) and "@" in login_value
                else login_value
            ),
        )
        userprincipalname = first_value(
            profile.get("userPrincipalName"),
            profile.get("userprincipalname"),
            email,
            login_value,
        )

        transformed: dict[str, Any] = {
            "firstname": profile.get("firstName"),
            "lastname": profile.get("lastName"),
            "email": email,
            "username": username,
            "mobile_phone": first_value(profile.get("mobilePhone"), profile.get("mobile_phone")),
            "phone": first_value(
                profile.get("primaryPhone"),
                profile.get("phone"),
                profile.get("workPhone"),
            ),
            "company": first_value(profile.get("company"), profile.get("organization")),
            "department": profile.get("department"),
            "title": profile.get("title"),
            "comment": first_value(
                profile.get("comment"),
                profile.get("notes"),
                profile.get("description"),
            ),
            "preferred_locale_code": first_value(
                profile.get("locale"),
                profile.get("preferredLocale"),
                profile.get("preferredLanguage"),
            ),
            "samaccountname": samaccountname,
            "userprincipalname": userprincipalname,
            # Account state: 1 active, 0 inactive in OneLogin
            "state": 1 if (user.get("status") or "").upper() == "ACTIVE" else 0,
            "status": 1 if (user.get("status") or "").upper() == "ACTIVE" else 0,
            "external_id": str(user.get("id")) if user.get("id") is not None else None,
        }

        custom_attributes: dict[str, Any] = {}

        def add_custom_attribute(name: str, *profile_keys: str) -> None:
            value = first_value(*(profile.get(key) for key in profile_keys))
            if value is None:
                return
            if isinstance(value, str) and value.strip() == "":
                return
            custom_attributes[name] = value

        add_custom_attribute("second_email", "secondEmail", "second_email")
        add_custom_attribute(
            "street_address",
            "streetAddress",
            "address",
            "postalAddress",
        )
        add_custom_attribute("city", "city")
        add_custom_attribute("state", "state", "stateCode", "region")
        add_custom_attribute("zip_code", "zipCode", "postalCode", "zip")
        add_custom_attribute("country", "country")
        add_custom_attribute("country_code", "countryCode", "country_code")
        add_custom_attribute("display_name", "displayName", "display_name")
        add_custom_attribute("employee_number", "employeeNumber", "employee_number")

        dynamic_custom_attributes: dict[str, Any] = {}
        for key, raw_value in profile.items():
            if key in KNOWN_STANDARD_FIELDS:
                continue
            if raw_value is None:
                continue
            if isinstance(raw_value, (dict, list)):
                continue
            if isinstance(raw_value, str):
                if raw_value.strip() == "":
                    continue
                value = raw_value
            elif isinstance(raw_value, (int, float, bool)):
                value = str(raw_value)
            else:
                value = str(raw_value).strip()
                if not value:
                    continue
            normalized_name = FieldTransformer.normalize_custom_attribute_name(key)
            if not normalized_name:
                continue
            if normalized_name in transformed or normalized_name in custom_attributes:
                continue
            dynamic_custom_attributes[normalized_name] = value

        if dynamic_custom_attributes:
            custom_attributes.update(dynamic_custom_attributes)

        if custom_attributes:
            transformed["custom_attributes"] = custom_attributes

        return FieldTransformer.clean_payload(transformed)

    @staticmethod
    def transform_group(group: dict[str, Any]) -> dict[str, Any] | None:
        """Transform an Okta group to OneLogin role format.

        Args:
            group: Okta group object

        Returns:
            Transformed role payload for OneLogin API, or None if invalid
        """
        profile = group.get("profile") or {}
        name = profile.get("name") or group.get("label")
        if not name:
            return None
        return {"name": name}

    @staticmethod
    def transform_application(
        app: dict[str, Any],
        connector_lookup: dict[str, dict[str | None, int]],
    ) -> dict[str, Any] | None:
        """Transform an Okta application to OneLogin format.

        Args:
            app: Okta application object
            connector_lookup: Mapping of application labels to OneLogin connector IDs

        Returns:
            Transformed application payload for OneLogin API, or None if invalid
        """
        label = app.get("label") or app.get("name")
        if not label:
            return None
        settings = app.get("settings") or {}
        sign_on = app.get("signOnMode")
        connector_id = FieldTransformer._lookup_connector_id(app, connector_lookup)
        if connector_id is None:
            return None
        configuration = FieldTransformer._build_application_configuration(settings)
        visible = FieldTransformer._coerce_bool(settings.get("appVisible"), default=True)
        payload: dict[str, Any] = {
            "name": label,
            "connector_id": connector_id,
            "description": settings.get("appNotes"),
            "visible": visible,
            "configuration": configuration,
        }
        if sign_on:
            payload["signon_mode"] = sign_on
        if "parameters" in app:
            payload["parameters"] = app["parameters"]
        return FieldTransformer.clean_payload(payload)

    @staticmethod
    def _lookup_connector_id(
        app: dict[str, Any],
        connector_lookup: dict[str, dict[str | None, int]],
    ) -> int | None:
        """Look up OneLogin connector ID for an Okta application."""
        sign_on = FieldTransformer.normalize_signon_mode(app.get("signOnMode"))
        labels: list[str] = []
        for key in ("label", "name"):
            candidate = FieldTransformer.normalize_app_label(app.get(key))
            if candidate:
                labels.append(candidate)
        settings = app.get("settings")
        if isinstance(settings, dict):
            for key in ("appName", "displayName", "name"):
                candidate = FieldTransformer.normalize_app_label(settings.get(key))
                if candidate:
                    labels.append(candidate)

        for label in labels:
            connectors = connector_lookup.get(label)
            if not connectors:
                continue
            if sign_on in connectors:
                return connectors[sign_on]
            if None in connectors:
                return connectors[None]
        return None

    @staticmethod
    def _build_application_configuration(settings: dict[str, Any]) -> dict[str, Any]:
        """Extract and merge application configuration from settings."""
        configuration: dict[str, Any] = {}
        if not isinstance(settings, dict):
            return configuration
        for key in ("appSettingsJson", "settingsJson", "signOn"):
            value = settings.get(key)
            if isinstance(value, dict):
                configuration.update(value)
        url = settings.get("appUrl") or settings.get("url")
        if isinstance(url, str) and url.strip() and "url" not in configuration:
            configuration["url"] = url
        return configuration

    @staticmethod
    def _coerce_bool(value: Any, *, default: bool) -> bool:
        """Coerce a value to boolean."""
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y"}:
                return True
            if normalized in {"false", "0", "no", "n"}:
                return False
            return default
        return bool(value)

    @staticmethod
    def normalize_app_label(value: Any) -> str:
        """Normalize an application label for lookup."""
        if not isinstance(value, str):
            return ""
        normalized = re.sub(r"\s+", " ", value).strip().lower()
        return normalized

    @staticmethod
    def normalize_signon_mode(value: Any) -> str | None:
        """Normalize a sign-on mode value."""
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized or None
        normalized = str(value).strip().lower()
        return normalized or None

    @staticmethod
    def normalize_custom_attribute_name(source_key: str) -> str:
        """Normalize a custom attribute name to OneLogin format.

        Converts camelCase to snake_case, removes invalid characters,
        and ensures the name starts with a letter or underscore.

        Args:
            source_key: Original attribute name

        Returns:
            Normalized attribute name (max 64 characters)
        """
        if not isinstance(source_key, str):
            return ""
        name = source_key.strip()
        if not name:
            return ""
        # Convert camelCase to snake_case
        name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
        name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
        # Replace invalid characters with underscore
        name = re.sub(r"[^0-9A-Za-z]+", "_", name)
        name = name.strip("_").lower()
        if not name:
            return ""
        # Ensure it starts with a letter or underscore
        if name[0].isdigit():
            name = f"_{name}"
        return name[:64]

    @staticmethod
    def clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """Remove keys with None or empty-string values to avoid 422 validation errors."""
        cleaned: dict[str, Any] = {}
        for k, v in payload.items():
            if v is None:
                continue
            if isinstance(v, str) and v.strip() == "":
                continue
            cleaned[k] = v
        return cleaned


__all__ = ["FieldTransformer"]
