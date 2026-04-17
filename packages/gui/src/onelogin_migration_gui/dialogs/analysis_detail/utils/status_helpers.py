"""Helpers for deriving status labels and group metadata."""

from __future__ import annotations

from typing import Any

__all__ = ["app_status_details", "determine_group_priority", "describe_group_type"]


def app_status_details(app: dict[str, Any]) -> dict[str, Any]:
    """Return label, color, reason, tooltip, and sort key for an app entry."""
    migration_meta = app.get("_migration") or {}
    selection = migration_meta.get("selection") or {}
    selection_type = selection.get("type")

    # Helper function to add duplicate suffix to result
    def _mark_duplicate(result: dict[str, Any]) -> dict[str, Any]:
        if migration_meta.get("is_duplicate"):
            result["label"] = f"{result['label']} (Duplicate)"
        return result

    if selection_type == "custom_saml":
        return _mark_duplicate({
            "label": "⚠ Needs Review",
            "color": "#f57c00",
            "reason": "Selected custom SAML connector",
            "tooltip": "Use a custom SAML connector configured in OneLogin.",
            "sort_value": 1,
            "category_key": "custom_saml",
        })
    if selection_type == "custom_oidc":
        return _mark_duplicate({
            "label": "⚠ Needs Review",
            "color": "#f57c00",
            "reason": "Selected custom OpenID Connect migration",
            "tooltip": "Use a custom OpenID Connect connector configured in OneLogin.",
            "sort_value": 1,
            "category_key": "custom_saml",
        })
    if selection_type == "connector":
        connector_name = selection.get("name") or "OneLogin Connector"
        tooltip = f"Selected connector: {connector_name}."
        return _mark_duplicate({
            "label": "✅ Connector Selected",
            "color": "#2e7d32",
            "reason": f"Using connector {connector_name}",
            "tooltip": tooltip,
            "sort_value": 0,
            "category_key": "connector",
        })

    category = migration_meta.get("category")
    meta_reason = migration_meta.get("reason")

    if category == "connector":
        reason = meta_reason or "Native OneLogin connector available"
        connector = migration_meta.get("connector") or {}
        connector_name = connector.get("name")
        confidence = float(migration_meta.get("confidence_score") or 0.0)
        user_reviewed = migration_meta.get("user_reviewed", False)

        # Priority 1: User has reviewed and approved (overrides all automatic categorization)
        if user_reviewed:
            label = "✅ Ready (Reviewed)"
            color = "#2e7d32"  # Green
            tooltip = "User has reviewed and approved this connector mapping."
            if connector_name:
                tooltip += f" Connector: {connector_name}."
            sort_value = 0

        # Priority 2: 100% automatic match (99.5%+ confidence)
        elif confidence >= 99.5:
            label = "✅ Ready (100% match)"
            color = "#2e7d32"  # Green
            tooltip = "Exact connector match found and auto-approved."
            if connector_name:
                tooltip += f" Connector: {connector_name}."
            sort_value = 0

        # Priority 3: Partial match (90-99% confidence) - needs verification
        elif confidence >= 90.0:
            label = f"⚠ Partial Match ({int(confidence)}%)"
            color = "#f57c00"  # Orange/Yellow
            tooltip = "High-confidence match found but should be verified before migration."
            if connector_name:
                tooltip += f" Suggested connector: {connector_name}."
            tooltip += " Click to review and approve."
            sort_value = 1

        # Priority 4: Low confidence match (<90%) - requires manual review
        else:
            label = "❌ Needs Review"
            color = "#d32f2f"  # Red
            tooltip = "No high-confidence connector match found. Manual selection required."
            if connector_name and confidence > 0:
                tooltip += f" Low-confidence suggestion: {connector_name} ({int(confidence)}%)."
            tooltip += " Click to select a connector."
            sort_value = 2

        return _mark_duplicate({
            "label": label,
            "color": color,
            "reason": reason,
            "tooltip": tooltip,
            "sort_value": sort_value,
            "category_key": "connector",
        })

    if category == "custom_saml":
        reason = meta_reason or "Compatible with custom SAML/OIDC connector"
        return _mark_duplicate({
            "label": "⚠ Needs Review",
            "color": "#f57c00",
            "reason": reason,
            "tooltip": "Create a custom SAML/OIDC connector in OneLogin to complete migration.",
            "sort_value": 1,
            "category_key": "custom_saml",
        })

    if category == "unsupported":
        reason = meta_reason or "Manual migration required"
        return _mark_duplicate({
            "label": "❌ Manual Migration Required",
            "color": "#c62828",
            "reason": reason,
            "tooltip": "This application type is not supported by OneLogin automation.",
            "sort_value": 3,
            "category_key": "manual",
        })

    if category == "needs_review":
        reason = meta_reason or "Review configuration before migration"
        return _mark_duplicate({
            "label": "⚠ Needs Review",
            "color": "#f57c00",
            "reason": reason,
            "tooltip": "Evaluate this application manually to confirm migration path.",
            "sort_value": 2,
            "category_key": "review",
        })

    sign_on_mode = (app.get("signOnMode") or "").upper()
    status = app.get("status", "ACTIVE")
    settings = app.get("settings", {})
    embedded = app.get("_embedded", {})
    assigned_groups = embedded.get("group") or []
    assignment_count = len(assigned_groups)

    if sign_on_mode in {"SAML_2_0", "OPENID_CONNECT"}:
        app_settings = settings.get("appSettingsJson", {})
        has_complex_config = (
            isinstance(app_settings, dict) and len(app_settings) > 5
        ) or assignment_count > 10
        if has_complex_config:
            return _mark_duplicate({
                "label": "⚠ Needs Review",
                "color": "#f57c00",
                "reason": "Complex configuration or large group assignment detected",
                "tooltip": "Large number of settings or assignments may require manual validation.",
                "sort_value": 1,
                "category_key": "review",
            })
        return _mark_duplicate({
            "label": "✅ Ready to Auto-Migrate",
            "color": "#2e7d32",
            "reason": "Compatible SSO configuration detected",
            "tooltip": "SAML/OIDC configuration aligns with automated migration path.",
            "sort_value": 0,
            "category_key": "auto",
        })

    if sign_on_mode in {"SECURE_PASSWORD_STORE", "BOOKMARK"}:
        return _mark_duplicate({
            "label": "❌ Manual Migration Required",
            "color": "#c62828",
            "reason": "Password-store or bookmark apps must be recreated in OneLogin",
            "tooltip": "These app types cannot be migrated automatically.",
            "sort_value": 2,
            "category_key": "manual",
        })

    if sign_on_mode in {"AUTO_LOGIN", "BROWSER_PLUGIN"}:
        return _mark_duplicate({
            "label": "⚠ Needs Review",
            "color": "#f57c00",
            "reason": "Auto-login workflows require manual validation",
            "tooltip": "Confirm auto-login flows after migration.",
            "sort_value": 1,
            "category_key": "review",
        })

    if status.upper() == "INACTIVE":
        return _mark_duplicate({
            "label": "ℹ Inactive in Okta",
            "color": "#546e7a",
            "reason": "Application is inactive and can be migrated later",
            "tooltip": "Inactive apps are low priority for migration.",
            "sort_value": 3,
            "category_key": "inactive",
        })

    return _mark_duplicate({
        "label": "❌ Manual Migration Required",
        "color": "#c62828",
        "reason": f"Unsupported sign-on mode: {sign_on_mode or 'Unknown'}",
        "tooltip": "This application type is not supported by OneLogin automation.",
        "sort_value": 3,
        "category_key": "manual",
    })


def determine_group_priority(member_count: int) -> tuple[str, str]:
    """Return the impact label and color for a group based on member count."""
    if member_count >= 500:
        return "High Impact", "#c62828"
    if member_count >= 100:
        return "Moderate Impact", "#f57c00"
    if member_count > 0:
        return "Low Impact", "#2e7d32"
    return "Empty Group", "#546e7a"


def describe_group_type(group: dict[str, Any]) -> str:
    """Generate a readable description of the Okta group type."""
    group_type = (group.get("type") or "").upper()
    profile = group.get("profile") or {}
    expression = profile.get("expression")

    if expression:
        return "Dynamic Rule • Nested logic"

    type_map = {
        "OKTA_GROUP": "Okta Directory",
        "APP_GROUP": "Application-linked",
        "BUILT_IN": "System",
        "DYNAMIC": "Dynamic Rule",
    }
    label = type_map.get(group_type, group_type.title() if group_type else "Unknown")

    external_names = profile.get("externalNames")
    if external_names:
        label += " • External source"

    if group.get("_embedded", {}).get("groups"):
        label += " • Contains nested groups"

    return label
