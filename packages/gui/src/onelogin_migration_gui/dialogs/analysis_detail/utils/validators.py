"""Validation and lookup helpers for analysis detail data."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["extract_group_ids", "estimate_active_users"]


def extract_group_ids(app: dict[str, Any]) -> list[str]:
    """Extract normalized group identifiers from an application embedding."""
    embedded = app.get("_embedded", {})
    raw_groups = embedded.get("group") or []
    if isinstance(raw_groups, dict):
        raw_groups = raw_groups.get("items", [])

    group_ids: list[str] = []
    if isinstance(raw_groups, list):
        for group in raw_groups:
            gid = None
            if isinstance(group, dict):
                gid = group.get("id")
            if gid is not None:
                group_ids.append(str(gid))
    return group_ids


def estimate_active_users(
    app: dict[str, Any],
    group_members_lookup: Mapping[str, Iterable[str]],
) -> int | None:
    """Estimate active users linked to an app via assigned groups."""
    group_ids = extract_group_ids(app)
    if not group_ids:
        return None

    unique_users: set[str] = set()
    for gid in group_ids:
        members = group_members_lookup.get(gid, [])
        for user_id in members:
            unique_users.add(str(user_id))

    return len(unique_users) if unique_users else 0
