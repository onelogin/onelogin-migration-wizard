"""Formatting helpers shared across analysis detail components."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .validators import extract_group_ids

__all__ = ["excel_column_letter", "summarize_user", "summarize_assigned_groups"]


def excel_column_letter(index: int) -> str:
    """Convert a 1-based column index to Excel column letters."""
    result = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result or "A"


def summarize_user(user: dict[str, Any], fallback_id: str) -> dict[str, str]:
    """Return display-friendly summaries for a user record."""
    profile = user.get("profile", {}) if isinstance(user, dict) else {}
    first = profile.get("firstName")
    last = profile.get("lastName")
    display_name = " ".join(part for part in [first, last] if part).strip()
    if not display_name:
        display_name = profile.get("displayName") or profile.get("login") or fallback_id

    email = profile.get("email") or profile.get("login") or "—"
    status = user.get("status", "UNKNOWN")

    return {"name": display_name, "email": email, "status": status}


def summarize_assigned_groups(
    app: dict[str, Any],
    group_lookup: Mapping[str, dict[str, Any]],
) -> tuple[str, str]:
    """Return text and tooltip summarizing groups assigned to an app."""
    group_ids = extract_group_ids(app)
    if not group_ids:
        return "(No groups assigned)", "No Okta groups are currently assigned to this application."

    group_names = []
    for gid in group_ids:
        group = group_lookup.get(gid)
        name = group.get("profile", {}).get("name") if group else None
        group_names.append(name or gid)

    visible = ", ".join(group_names[:3])
    if len(group_names) > 3:
        visible += f", +{len(group_names) - 3} more"

    tooltip = "\n".join(group_names)
    return visible, tooltip
