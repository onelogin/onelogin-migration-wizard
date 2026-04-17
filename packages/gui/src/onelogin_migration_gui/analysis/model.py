"""Data model for the analysis UI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _coerce_int(value: Any, default: int = 0) -> int:
    """Best-effort conversion of incoming metrics to integers."""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return int(float(text))
        except ValueError:
            return default
    return default


def _get_int(data: Mapping[str, Any] | None, key: str, default: int = 0) -> int:
    """Safely extract an integer metric from a mapping."""
    if not data:
        return default
    if key not in data:
        return default
    return _coerce_int(data.get(key), default)


@dataclass(slots=True)
class TopGroup:
    name: str
    members: int


@dataclass(slots=True)
class CustomAttributeRow:
    source: str
    target: str
    status: str


@dataclass(slots=True)
class ConnectorPreview:
    """Abbreviated view of a OneLogin connector entry."""

    id: str
    name: str
    auth_method: str | None = None


@dataclass(slots=True)
class ConnectorStats:
    """Source metadata about how the connector catalog was loaded."""

    total: int = 0
    from_db: int = 0
    from_api: int = 0
    error: str | None = None
    preview: list[ConnectorPreview] = field(default_factory=list)


@dataclass(slots=True)
class AnalysisModel:
    """Aggregated metrics for the analysis tabs."""

    source: str
    completed_at: datetime
    overview: dict[str, int]
    discovery_totals: dict[str, int]
    discovery_apps: dict[str, int]
    discovery_user_policies: dict[str, int]
    discovery_app_policies: dict[str, int]
    discovery_mfa: dict[str, int]
    discovery_directories: dict[str, int]
    users_license: dict[str, int]
    users_security: dict[str, int]
    groups: dict[str, int]
    top_groups: list[TopGroup]
    apps_total: int
    apps_methods: dict[str, int]
    apps_status: dict[str, int]
    apps_breakdown: dict[str, int]
    apps_mapping_quality: dict[str, int]
    connectors: ConnectorStats
    custom_attributes: list[CustomAttributeRow]
    custom_attribute_summary: dict[str, int]

    @classmethod
    def from_results(cls, results: dict[str, Any]) -> AnalysisModel:
        """Build model from analysis worker payload."""
        discovery = results.get("discovery") or {}
        summary = discovery.get("summary") or {}
        applications = discovery.get("applications") or {}
        discovery_users = discovery.get("users") or {}
        discovery_groups = discovery.get("groups") or {}
        user_policies = discovery.get("user_policies") or {}
        app_policies = discovery.get("app_policies") or {}
        mfa = discovery.get("mfa") or {}
        directories = discovery.get("directories") or {}

        users_analysis = results.get("users") or {}
        groups_analysis = results.get("groups") or {}
        apps_analysis = results.get("applications") or {}
        custom_attrs = discovery.get("custom_attributes") or {}
        connectors = results.get("connectors") or {}

        top_groups = [
            TopGroup(name=row.get("name", ""), members=_coerce_int(row.get("members"), 0))
            for row in groups_analysis.get("top_groups", [])
        ]

        custom_attribute_rows = [
            CustomAttributeRow(source=name, target=name, status="Can Create")
            for name in users_analysis.get("custom_attributes", [])
        ]

        completed_at = datetime.fromisoformat(results["timestamp"])

        apps_breakdown = apps_analysis.get("breakdown") or {}
        apps_mapping = apps_analysis.get("mapping_quality") or {}

        connector_stats = ConnectorStats(
            total=_coerce_int(connectors.get("total"), 0),
            from_db=_coerce_int(connectors.get("from_db"), 0),
            from_api=_coerce_int(connectors.get("from_api"), 0),
            error=connectors.get("error"),
            preview=[
                ConnectorPreview(
                    id=str(item.get("id", "")),
                    name=item.get("name", ""),
                    auth_method=item.get("auth_method"),
                )
                for item in connectors.get("preview", []) or []
            ],
        )

        summary_users = _get_int(summary, "users", _get_int(users_analysis, "total"))
        summary_admins = _get_int(summary, "admins", 0)
        summary_apps = _get_int(summary, "apps", _get_int(apps_analysis, "total"))
        summary_groups_total = _get_int(summary, "groups", _get_int(groups_analysis, "total"))
        summary_mfa = _get_int(summary, "mfa", _get_int(mfa, "total"))
        summary_directories = _get_int(summary, "directories", _get_int(directories, "total"))
        summary_custom_attrs = _get_int(summary, "custom_attributes", len(custom_attribute_rows))

        user_policy_totals = {
            "total": _get_int(user_policies, "total", 0),
            "assigned": _get_int(user_policies, "assigned", 0),
            "unassigned": _get_int(user_policies, "unassigned", 0),
        }
        app_policy_totals = {
            "total": _get_int(app_policies, "total", 0),
            "assigned": _get_int(app_policies, "assigned", 0),
            "unassigned": _get_int(app_policies, "unassigned", 0),
        }
        discovery_totals = {
            "users": summary_users,
            "admins": summary_admins,
            "apps": summary_apps,
            "groups": summary_groups_total,
            "user_policies": user_policy_totals["total"],
            "app_policies": app_policy_totals["total"],
            "mfa": summary_mfa,
            "directories": summary_directories,
            "custom_attributes": summary_custom_attrs,
        }

        discovery_apps_data = {
            "saml": _get_int(applications, "saml", 0),
            "oidc": _get_int(applications, "oidc", 0),
            "oauth": _get_int(applications, "oauth", 0),
            "swa": _get_int(applications, "swa", 0),
            "other": _get_int(applications, "other", 0),
            "provisioning": _get_int(applications, "provisioning", 0),
            "active": _get_int(applications, "active", 0),
            "inactive": _get_int(applications, "inactive", 0),
        }
        discovery_user_policy_data = dict(user_policy_totals)
        discovery_app_policy_data = dict(app_policy_totals)
        discovery_mfa_data = {
            "total": _get_int(mfa, "total", 0),
            "assigned": _get_int(mfa, "assigned", 0),
            "unassigned": _get_int(mfa, "unassigned", 0),
        }
        discovery_directory_data = {
            "total": _get_int(directories, "total", 0),
            "active": _get_int(directories, "active", 0),
            "inactive": _get_int(directories, "inactive", 0),
        }

        users_license_data = {
            "active": _get_int(discovery_users, "active", _get_int(users_analysis, "active", 0)),
            "inactive": _get_int(discovery_users, "inactive", 0),
            "stale": _get_int(discovery_users, "stale_90_days", 0),
        }
        users_security_data = {
            "locked": _get_int(discovery_users, "locked", 0),
            "password_expired": _get_int(discovery_users, "password_expired", 0),
            "suspended": _get_int(users_analysis, "suspended", 0),
            "admins": summary_admins,
        }

        groups_data = {
            "total": _get_int(discovery_groups, "total", summary_groups_total),
            "nested": _get_int(discovery_groups, "nested", 0),
            "assigned": _get_int(discovery_groups, "assigned", 0),
            "unassigned": _get_int(discovery_groups, "unassigned", 0),
            "rules": _get_int(discovery_groups, "rules", 0),
        }

        apps_total = _get_int(apps_analysis, "total", 0)
        apps_methods_data = {
            "saml": _get_int(applications, "saml", 0),
            "oidc": _get_int(applications, "oidc", 0),
            "oauth": _get_int(applications, "oauth", 0),
            "swa": _get_int(applications, "swa", 0),
            "other": _get_int(applications, "other", 0),
        }
        apps_breakdown_data = {
            "connector_matches": _get_int(apps_breakdown, "connector_matches", 0),
            "custom_sso": _get_int(apps_breakdown, "custom_sso", 0),
            "unsupported": _get_int(apps_breakdown, "unsupported", 0),
            "needs_review": _get_int(apps_breakdown, "needs_review", 0),
        }
        apps_mapping_quality_data = {
            "exact_matches": _get_int(apps_mapping, "exact_matches", 0),
            "fuzzy_matches": _get_int(apps_mapping, "fuzzy_matches", 0),
            "no_matches": _get_int(apps_mapping, "no_matches", 0),
        }

        custom_attribute_summary = {
            "total": _get_int(custom_attrs, "total", len(custom_attribute_rows)),
            "used": _get_int(custom_attrs, "used", 0),
            "unused": _get_int(custom_attrs, "unused", 0),
        }

        return cls(
            source=results.get("source", ""),
            completed_at=completed_at,
            overview={
                "users": summary_users,
                "apps": summary_apps,
                "groups": summary_groups_total,
                "policies": user_policy_totals["total"] + app_policy_totals["total"],
                "mfa": summary_mfa,
                "directories": summary_directories,
            },
            discovery_totals=discovery_totals,
            discovery_apps=discovery_apps_data,
            discovery_user_policies=discovery_user_policy_data,
            discovery_app_policies=discovery_app_policy_data,
            discovery_mfa=discovery_mfa_data,
            discovery_directories=discovery_directory_data,
            users_license=users_license_data,
            users_security=users_security_data,
            groups=groups_data,
            top_groups=top_groups,
            apps_total=apps_total,
            apps_methods=apps_methods_data,
            apps_status={
                "can_migrate": len(apps_analysis.get("can_migrate", [])),
                "need_review": len(apps_analysis.get("need_review", [])),
                "cannot_migrate": len(apps_analysis.get("cannot_migrate", [])),
            },
            apps_breakdown=apps_breakdown_data,
            apps_mapping_quality=apps_mapping_quality_data,
            connectors=connector_stats,
            custom_attributes=custom_attribute_rows,
            custom_attribute_summary=custom_attribute_summary,
        )
